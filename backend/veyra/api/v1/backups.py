# SPDX-License-Identifier: AGPL-3.0-or-later
"""Backups (docs/PRODUCTION_HARDENING.md §2): settings, the list, run,
verify-again (a new backup), delete, and the runner's status."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from veyra.api.v1.extensions import installation_key
from veyra.backups import destinations as dests
from veyra.backups import policy, recording_archive, service
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, not_found
from veyra.core.models import Backup
from veyra.core.security.principal import Principal

router = APIRouter(prefix="/backups", tags=["backups"])
READ = "backups.read"
MANAGE = "backups.manage"


def _problem(e: service.BackupError) -> ProblemError:
    return ProblemError(e.status, "Backups", e.message, code=e.code)


def _audit(
    db: Session, principal: Principal, ctx: RequestContext, action: str, **details: Any
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="backup",
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=details,
    )


class KeepIn(BaseModel):
    daily_days: int = Field(14, ge=0, le=3650)
    weekly_weeks: int = Field(8, ge=0, le=520)
    upgrades: int = Field(3, ge=0, le=100)


class SettingsIn(BaseModel):
    """Fields left out keep their current value (a change to the copy
    directory must not drop the recipients)."""

    enabled: bool | None = None
    time: str | None = Field(None, max_length=5)
    keep: KeepIn | None = None
    recordings: bool | None = None
    recipients: list[str] | None = Field(None, max_length=10)


@router.get("/settings", summary="Backup schedule, keep policy, encryption and destinations")
def get_settings(
    principal: Principal = Depends(require(READ)), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return service.public_settings(db)


@router.put("/settings", summary="Change the backup settings")
def put_settings(
    body: SettingsIn,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    try:
        merged = {**service.settings(db), **body.model_dump(exclude_none=True)}
        value = service.save_settings(db, merged, principal.user_id)
    except service.BackupError as e:
        raise _problem(e) from e
    _audit(
        db,
        principal,
        ctx,
        "backups.settings_update",
        **{
            k: v
            for k, v in value.items()
            if k not in ("recipients", "destinations", "ssh_private_ciphertext")
        },
        recipients=len(value["recipients"]),
    )
    db.commit()
    return service.public_settings(db)


# ------------------------------------------------------------- destinations


class DestinationIn(BaseModel):
    """A folder, an SFTP server or an S3-compatible bucket (§2.7). The
    secret access key is write-only: left out, the stored one stays."""

    kind: Literal["directory", "sftp", "s3"]
    name: str = Field("", max_length=80)
    enabled: bool = True
    keep: KeepIn | None = None
    path: str | None = Field(None, max_length=1024)
    host: str | None = Field(None, max_length=253)
    port: int | None = Field(None, ge=1, le=65535)
    username: str | None = Field(None, max_length=64)
    endpoint: str | None = Field(None, max_length=300)
    bucket: str | None = Field(None, max_length=63)
    region: str | None = Field(None, max_length=40)
    prefix: str | None = Field(None, max_length=300)
    access_key_id: str | None = Field(None, max_length=128)
    secret_access_key: str | None = Field(None, max_length=200)
    addressing: Literal["path", "virtual"] | None = None


class HostKeyIn(BaseModel):
    host_key: str = Field(min_length=20, max_length=2000)


def _dest_audit(dest: dict[str, Any]) -> dict[str, Any]:
    return {"id": dest["id"], "kind": dest["kind"], "target": dests.describe(dest)}


@router.get("/ssh-key", summary="Veyra's SSH public key for SFTP destinations")
def ssh_key(
    request: Request,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    public_key = service.ssh_public_key(db, installation_key(request), principal.user_id)
    db.commit()
    return {"public_key": public_key}


@router.post("/destinations", status_code=201, summary="Add a backup destination")
def add_destination(
    body: DestinationIn,
    request: Request,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    try:
        dest = service.save_destination(
            db, body.model_dump(exclude_none=True), installation_key(request), principal.user_id
        )
    except service.BackupError as e:
        raise _problem(e) from e
    _audit(db, principal, ctx, "backups.destination_add", **_dest_audit(dest))
    db.commit()
    return dests.public(dest)


@router.put("/destinations/{dest_id}", summary="Change a backup destination")
def change_destination(
    dest_id: str,
    body: DestinationIn,
    request: Request,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    try:
        dest = service.save_destination(
            db,
            body.model_dump(exclude_none=True),
            installation_key(request),
            principal.user_id,
            dest_id=dest_id,
        )
    except service.BackupError as e:
        raise _problem(e) from e
    _audit(db, principal, ctx, "backups.destination_update", **_dest_audit(dest))
    db.commit()
    return dests.public(dest)


@router.delete("/destinations/{dest_id}", status_code=204, summary="Remove a backup destination")
def delete_destination(
    dest_id: str,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> None:
    """Veyra stops copying there; the copies already made stay."""
    try:
        dest = service.delete_destination(db, dest_id, principal.user_id)
    except service.BackupError as e:
        raise _problem(e) from e
    _audit(db, principal, ctx, "backups.destination_delete", **_dest_audit(dest))
    db.commit()


class ArchiveIn(BaseModel):
    destination_id: str = Field("", max_length=40)


@router.get("/recording-archive", summary="The recording archive's destination and progress")
def get_recording_archive(
    principal: Principal = Depends(require(MANAGE)), db: Session = Depends(get_db)
) -> dict[str, Any]:
    dest_id = service.settings(db)["recording_archive"]["destination_id"]
    return recording_archive.status(db, dest_id)


@router.put("/recording-archive", summary="Choose where call recordings are archived")
def put_recording_archive(
    body: ArchiveIn,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    """Copies already made stay where they are, and are deleted from there when
    their recordings are."""
    try:
        service.set_archive_destination(db, body.destination_id, principal.user_id)
    except service.BackupError as e:
        raise _problem(e) from e
    _audit(db, principal, ctx, "backups.recording_archive_set", destination_id=body.destination_id)
    db.commit()
    return recording_archive.status(db, body.destination_id)


@router.post("/destinations/{dest_id}/test", summary="Check that Veyra can write there")
def test_destination(
    dest_id: str,
    request: Request,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Writes, checks and removes a small file. An SFTP server whose host
    key is not confirmed yet answers with the key to confirm instead."""
    dest = service.destination(db, dest_id)
    if dest is None:
        raise not_found("Destination")
    try:
        if dest["kind"] == "directory":
            # The copies run as root; the service can only see the folder.
            path = Path(dest["path"])
            if not path.is_dir():
                raise dests.DestinationError(f"{path} is not a folder (is the share mounted?)")
            return {
                "state": "ok",
                "message": f"{path} exists"
                + (" and is a mounted share." if path.is_mount() else ".")
                + " The copies are written by the backup service.",
            }
        if dest["kind"] == "sftp" and not dest.get("host_key"):
            line = dests.scan_host_key(dest["host"], int(dest["port"]))
            return {
                "state": "host_key",
                "host_key": line,
                "fingerprint": dests.host_key_fingerprint(line),
                "message": "Confirm that this is the server's host key.",
            }
        settings = service.runner_settings(db, installation_key(request))
        full = next(d for d in settings["destinations"] if d["id"] == dest_id)
        dests.remote(
            full, secret=full.get("secret"), ssh_private_key=settings.get("ssh_private_key")
        ).test()
    except dests.DestinationError as e:
        return {"state": "failed", "message": str(e)}
    return {"state": "ok", "message": "Veyra wrote, checked and removed a test file."}


@router.post("/destinations/{dest_id}/host-key", summary="Confirm an SFTP server's host key")
def confirm_host_key(
    dest_id: str,
    body: HostKeyIn,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    fingerprint = dests.host_key_fingerprint(body.host_key)
    if fingerprint is None or len(body.host_key.split()) != 3:
        raise ProblemError(400, "Backups", "That is not a host key.", code="bad_host_key")
    try:
        service.pin_host_key(db, dest_id, body.host_key.strip(), principal.user_id)
    except service.BackupError as e:
        raise _problem(e) from e
    _audit(db, principal, ctx, "backups.destination_host_key", id=dest_id, fingerprint=fingerprint)
    db.commit()
    return {"fingerprint": fingerprint}


@router.get("", summary="Backups, newest first")
def list_backups(
    principal: Principal = Depends(require(READ)), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return {
        "summary": service.summary(db),
        "backups": [service.row_out(b) for b in service.rows(db)],
    }


@router.get("/status", summary="Progress of the running or last backup")
def status(principal: Principal = Depends(require(READ))) -> dict[str, Any]:
    return service.status() or {"state": "idle"}


@router.post("/run", status_code=202, summary="Take a backup now")
def run_now(
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    if service.running():
        raise ProblemError(409, "Backup running", "A backup is already running.", code="running")
    try:
        service.start("run-manual")
    except service.BackupError as e:
        raise _problem(e) from e
    _audit(db, principal, ctx, "backups.run_now")
    db.commit()
    return {"started": True}


@router.get("/{backup_id}", summary="One backup with its verification")
def get_backup(
    backup_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    row = db.get(Backup, backup_id)
    if row is None:
        raise not_found("Backup")
    out = service.row_out(row)
    out["verify"] = row.verify
    out["manifest"] = row.manifest
    return out


@router.delete("/{backup_id}", status_code=202, summary="Delete a backup's files")
def delete_backup(
    backup_id: uuid.UUID,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    row = db.get(Backup, backup_id)
    if row is None:
        raise not_found("Backup")
    if row.state == "running":
        raise ProblemError(409, "Backup running", "Wait for the backup to finish.", code="running")
    try:
        service.start(f"delete-{backup_id}")
    except service.BackupError as e:
        raise _problem(e) from e
    _audit(db, principal, ctx, "backups.delete", id=str(backup_id), name=row.manifest.get("name"))
    db.commit()
    return {"deleting": True}


__all__ = ["policy", "router"]
