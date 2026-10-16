# SPDX-License-Identifier: AGPL-3.0-or-later
"""Backups (docs/PRODUCTION_HARDENING.md §2): settings, the list, run,
verify-again (a new backup), delete, and the runner's status."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from veyra.backups import policy, service
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
    enabled: bool = True
    time: str = Field("02:30", max_length=5)
    keep: KeepIn = Field(default_factory=KeepIn)
    recordings: bool = False
    recipients: list[str] = Field(default_factory=list, max_length=10)
    copy_dir: str = Field("", max_length=1024)


@router.get("/settings", summary="Backup schedule, keep policy, encryption and destinations")
def get_settings(
    principal: Principal = Depends(require(READ)), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return service.settings(db)


@router.put("/settings", summary="Change the backup settings")
def put_settings(
    body: SettingsIn,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    try:
        value = service.save_settings(db, body.model_dump(), principal.user_id)
    except service.BackupError as e:
        raise _problem(e) from e
    _audit(
        db,
        principal,
        ctx,
        "backups.settings_update",
        **{k: v for k, v in value.items() if k != "recipients"},
        recipients=len(value["recipients"]),
    )
    db.commit()
    return value


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
