# SPDX-License-Identifier: AGPL-3.0-or-later
"""The database side of backups (docs/PRODUCTION_HARDENING.md §2): settings,
the rows the runner records, scheduling from the worker, starting the root
unit through polkit, and the status file for the page."""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.backups import destinations as dests
from veyra.backups import policy, recording_archive
from veyra.core import audit
from veyra.core.models import Backup, SystemSetting
from veyra.core.models.base import utcnow
from veyra.core.security.crypto import InstallationKey

UNIT = "veyra-backup@{instance}.service"
STALE_RUNNING_HOURS = 8  # longer than TimeoutStartSec of the unit (6 h)
STATUS_PATH = Path("/var/lib/veyra-backup/status.json")
STALE_AFTER = timedelta(days=2)
# Tests replace this with a recorder.
systemctl: Callable[[list[str]], Any] | None = None


class BackupError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ------------------------------------------------------------------ settings


def settings(db: Session) -> dict[str, Any]:
    row = db.get(SystemSetting, policy.SETTINGS_KEY)
    return policy.settings_doc(row.value if row is not None and isinstance(row.value, dict) else {})


def save_settings(db: Session, body: dict[str, Any], by: uuid.UUID | None) -> dict[str, Any]:
    try:
        value = policy.settings_doc(body)
    except ValueError as e:
        raise BackupError(400, "bad_settings", str(e)) from e
    bad = [r for r in value["recipients"] if not policy.valid_recipient(r)]
    if bad:
        raise BackupError(
            400,
            "bad_recipient",
            "Recipients are age public keys (age1…) or SSH public keys (ssh-ed25519 …).",
        )
    row = db.get(SystemSetting, policy.SETTINGS_KEY)
    if row is None:
        db.add(SystemSetting(key=policy.SETTINGS_KEY, value=value, updated_by=by))
    else:
        row.value = value
        row.updated_by = by
    db.flush()
    return value


def public_settings(db: Session) -> dict[str, Any]:
    """The settings for the interface: destinations without secrets, with
    the outcome of their last copy."""
    value = settings(db)
    last = _last_copies(db)
    return {
        **{k: v for k, v in value.items() if k != "ssh_private_ciphertext"},
        "destinations": [dests.public(d, last.get(d["id"])) for d in value["destinations"]],
    }


def _last_copies(db: Session) -> dict[str, dict[str, Any]]:
    """Each destination's most recent copy result, from the newest backups."""
    out: dict[str, dict[str, Any]] = {}
    for b in rows(db, 20):
        for dest_id, result in (b.copies or {}).items():
            if isinstance(result, dict) and dest_id not in out:
                out[dest_id] = result
    return out


def runner_settings(db: Session, key: InstallationKey) -> dict[str, Any]:
    """The settings for the root runner, with the secrets decrypted."""
    value = settings(db)
    out = dict(value)
    out.pop("ssh_private_ciphertext", None)
    if value["ssh_private_ciphertext"]:
        out["ssh_private_key"] = key.decrypt(value["ssh_private_ciphertext"], dests.SSH_KEY_PURPOSE)
    out["destinations"] = []
    for d in value["destinations"]:
        d = dict(d)
        cipher = d.pop("secret_ciphertext", None)
        if cipher:
            d["secret"] = key.decrypt(cipher, dests.secret_purpose(d["id"]))
        out["destinations"].append(d)
    return out


def ssh_public_key(db: Session, key: InstallationKey, by: uuid.UUID | None) -> str:
    """Veyra's SSH key for SFTP destinations, created the first time."""
    value = settings(db)
    if value["ssh_public"] and value["ssh_private_ciphertext"]:
        return str(value["ssh_public"])
    private, public_line = dests.generate_ssh_key("veyra-backup")
    value["ssh_private_ciphertext"] = key.encrypt(private, dests.SSH_KEY_PURPOSE)
    value["ssh_public"] = public_line
    _store(db, value, by)
    return public_line


def _store(db: Session, value: dict[str, Any], by: uuid.UUID | None) -> None:
    row = db.get(SystemSetting, policy.SETTINGS_KEY)
    if row is None:
        db.add(SystemSetting(key=policy.SETTINGS_KEY, value=value, updated_by=by))
    else:
        row.value = value
        row.updated_by = by
    db.flush()


def save_destination(
    db: Session,
    body: dict[str, Any],
    key: InstallationKey,
    by: uuid.UUID | None,
    dest_id: str | None = None,
) -> dict[str, Any]:
    """Add (``dest_id`` None) or change a destination. A secret in the body
    replaces the stored one; leaving it out keeps it."""
    value = settings(db)
    current = value["destinations"]
    existing = next((d for d in current if d["id"] == dest_id), None) if dest_id else None
    if dest_id and existing is None:
        raise BackupError(404, "not_found", "No such destination.")
    if existing is None and len(current) >= dests.MAX_DESTINATIONS:
        raise BackupError(
            400, "too_many", f"At most {dests.MAX_DESTINATIONS} destinations can be set up."
        )
    try:
        dest = dests.normalize(body, existing=existing)
    except (ValueError, TypeError) as e:
        raise BackupError(400, "bad_destination", str(e)) from e
    secret = str(body.get("secret_access_key") or "").strip()
    if dest["kind"] == "s3":
        if secret:
            dest["secret_ciphertext"] = key.encrypt(secret, dests.secret_purpose(dest["id"]))
        elif not dest.get("secret_ciphertext"):
            raise BackupError(400, "bad_destination", "Enter the secret access key.")
    if dest["kind"] == "gdrive":
        key_json = str(body.get("service_account_json") or "").strip()
        if key_json:
            from veyra.backups import gdrive

            try:
                parsed = gdrive.parse_key(key_json)
            except ValueError as e:
                raise BackupError(400, "bad_destination", str(e)) from e
            dest["client_email"] = parsed["client_email"]
            dest["secret_ciphertext"] = key.encrypt(key_json, dests.secret_purpose(dest["id"]))
        elif not dest.get("secret_ciphertext"):
            raise BackupError(400, "bad_destination", "Paste the service account's key file.")
    others = [d for d in current if d["id"] != dest["id"]]
    if any(dests.describe(d) == dests.describe(dest) for d in others):
        raise BackupError(400, "duplicate", "Another destination already goes there.")
    value["destinations"] = (
        [dest if d["id"] == dest["id"] else d for d in current] if existing else [*current, dest]
    )
    _store(db, value, by)
    return dest


def destination(db: Session, dest_id: str) -> dict[str, Any] | None:
    return next((d for d in settings(db)["destinations"] if d["id"] == dest_id), None)


def delete_destination(db: Session, dest_id: str, by: uuid.UUID | None) -> dict[str, Any]:
    value = settings(db)
    dest = next((d for d in value["destinations"] if d["id"] == dest_id), None)
    if dest is None:
        raise BackupError(404, "not_found", "No such destination.")
    copies = recording_archive.uses_destination(db, dest_id)
    if value["recording_archive"]["destination_id"] == dest_id or copies:
        raise BackupError(
            409,
            "destination_in_use",
            "Call recordings are archived here, and Veyra must be able to delete those copies "
            f"when the recordings are deleted ({copies} copies). Choose another archive "
            "destination first, and keep this one until its copies are gone.",
        )
    value["destinations"] = [d for d in value["destinations"] if d["id"] != dest_id]
    _store(db, value, by)
    return dest


def pin_host_key(db: Session, dest_id: str, host_key: str, by: uuid.UUID | None) -> None:
    value = settings(db)
    for d in value["destinations"]:
        if d["id"] == dest_id and d["kind"] == "sftp":
            d["host_key"] = host_key
            _store(db, value, by)
            return
    raise BackupError(404, "not_found", "No such SFTP destination.")


# ------------------------------------------------------------------ rows


def record(db: Session, p: dict[str, Any]) -> Backup:
    """``veyra backup record``: the runner's payload becomes a row (or updates
    the row of a backup already recorded as running)."""
    name = str(p["name"])
    row = db.scalar(select(Backup).where(Backup.manifest["name"].astext == name))
    if row is None:
        row = db.scalar(select(Backup).where(Backup.path.like(f"%/{name}%")))
    if row is None and p.get("kind") == "scheduled":
        # tick() recorded the run before starting the unit, with the name of
        # its own clock; the runner stamps its own a moment later. The pending
        # row is adopted rather than left "running" forever.
        row = db.scalar(
            select(Backup)
            .where(Backup.kind == "scheduled", Backup.state == "running", Backup.path == "")
            .order_by(Backup.started_at.desc())
            .limit(1)
        )
        if row is not None:
            row.manifest = {**(row.manifest or {}), "name": name}
    if row is None:
        row = Backup(
            id=uuid.uuid4(), kind=str(p.get("kind") or "manual"), path=str(p.get("path") or "")
        )
        db.add(row)
    if p.get("started_at"):
        row.started_at = datetime.fromisoformat(str(p["started_at"]))
    elif row.started_at is None:
        row.started_at = utcnow()  # a later record (a deletion) keeps the start
    if p.get("finished_at"):
        row.finished_at = datetime.fromisoformat(str(p["finished_at"]))
    row.state = str(p.get("state") or "failed")
    row.path = str(p.get("path") or row.path)
    # A later record for the same backup (a deletion) carries only what changed.
    if "encrypted" in p:
        row.encrypted = bool(p.get("encrypted"))
    if p.get("recipients") is not None:
        row.recipients = list(p.get("recipients") or [])
    if p.get("bytes") is not None:
        row.bytes = int(p.get("bytes") or 0)
    if p.get("parts"):
        row.parts = list(p["parts"])
    if p.get("copies"):
        row.copies = dict(p["copies"])
    if p.get("verify"):
        row.verify = dict(p["verify"])
    if p.get("manifest"):
        row.manifest = dict(p["manifest"])
    elif not row.manifest:
        row.manifest = {"name": name}
    if "error" in p:
        row.error = str(p["error"])[:1000] if p.get("error") else None
    row.created_by = str(p.get("created_by") or row.created_by or "scheduler")
    for removed in p.get("removed") or []:
        old = db.scalar(select(Backup).where(Backup.manifest["name"].astext == str(removed)))
        if old is not None:
            old.state = "deleted"
    db.flush()
    audit.record(
        db,
        action="backups.run",
        outcome="success" if row.state == "verified" else "failure",
        actor_type="system",
        actor_label=row.created_by,
        target_type="backup",
        target_id=row.id,
        details={
            "kind": row.kind,
            "bytes": row.bytes,
            "error": row.error,
            "removed": p.get("removed"),
        },
    )
    return row


def mark_deleted(db: Session, backup_id: uuid.UUID) -> Backup | None:
    row = db.get(Backup, backup_id)
    if row is not None:
        row.state = "deleted"
        db.flush()
    return row


def rows(db: Session, limit: int = 50) -> list[Backup]:
    return list(db.scalars(select(Backup).order_by(Backup.started_at.desc()).limit(limit)))


def row_out(b: Backup) -> dict[str, Any]:
    return {
        "id": str(b.id),
        "name": b.manifest.get("name") or Path(b.path).name.split(".")[0],
        "kind": b.kind,
        "started_at": b.started_at.isoformat(),
        "finished_at": b.finished_at.isoformat() if b.finished_at else None,
        "state": b.state,
        "path": b.path,
        "encrypted": b.encrypted,
        "recipients": b.recipients,
        "bytes": b.bytes,
        "parts": b.parts,
        "copies": b.copies,
        "verify": {k: v for k, v in b.verify.items() if k != "counts"} | {"ok": b.verify.get("ok")},
        "version": b.manifest.get("version"),
        "schema": b.manifest.get("schema"),
        "error": b.error,
        "created_by": b.created_by,
    }


def last_good(db: Session) -> Backup | None:
    return db.scalar(
        select(Backup)
        .where(Backup.state == "verified")
        .order_by(Backup.finished_at.desc())
        .limit(1)
    )


def last_any(db: Session) -> Backup | None:
    return db.scalar(select(Backup).order_by(Backup.started_at.desc()).limit(1))


def summary(db: Session) -> dict[str, Any]:
    good, last = last_good(db), last_any(db)
    s = settings(db)
    stale = s["enabled"] and (
        good is None or utcnow() - (good.finished_at or good.started_at) > STALE_AFTER
    )
    return {
        "enabled": s["enabled"],
        "last_good_at": (good.finished_at or good.started_at).isoformat() if good else None,
        "last_state": last.state if last else None,
        "last_error": last.error if last else None,
        "stale": stale,
        "encrypted": bool(s["recipients"]),
        "copies_failed": _failed_copies(s, last)
        + [("Recording archive", e) for e in recording_archive.last_errors(db)],
        "count": db.scalar(
            select(func.count()).select_from(Backup).where(Backup.state == "verified")
        ),
    }


def _failed_copies(s: dict[str, Any], last: Backup | None) -> list[tuple[str, str]]:
    """(destination name, error) for each enabled destination whose copy
    failed in the latest finished backup."""
    if last is None or last.state == "running":
        return []
    names = {d["id"]: d.get("name") or d["id"] for d in s["destinations"] if d.get("enabled")}
    return [
        (names[k], str(v.get("error") or "unknown error"))
        for k, v in (last.copies or {}).items()
        if k in names and isinstance(v, dict) and v.get("state") == "failed"
    ]


# ---------------------------------------------------------- recording archive


def set_archive_destination(db: Session, dest_id: str, by: uuid.UUID | None) -> None:
    value = settings(db)
    if dest_id and not any(d["id"] == dest_id for d in value["destinations"]):
        raise BackupError(404, "not_found", "No such destination.")
    value["recording_archive"] = {"destination_id": dest_id}
    _store(db, value, by)


def archive_tick(db: Session, now: datetime | None = None) -> bool:
    """The worker: start the archive job when there is work, at most hourly."""
    now = now or utcnow()
    dest_id = settings(db)["recording_archive"]["destination_id"]
    if running() or not recording_archive.due(db, now):
        return False
    if not recording_archive.has_work(db, dest_id):
        return False
    recording_archive.note_started(db, now)
    db.commit()
    start("recordings")
    return True


# ------------------------------------------------------------------ the unit


_INSTANCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def start(instance: str) -> None:
    """``systemctl start --no-block veyra-backup@<instance>`` through polkit.
    The instance names the unit's job (``run-manual``, ``delete-<id>``)."""
    if not _INSTANCE_RE.match(instance):
        raise BackupError(400, "bad_instance", "The backup job name is not valid.")
    cmd = ["systemctl", "start", "--no-block", UNIT.format(instance=instance)]
    res = (
        systemctl(cmd)
        if systemctl
        else subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)  # noqa: S603
    )
    if getattr(res, "returncode", 1) != 0:
        raise BackupError(
            503,
            "unit_failed",
            "The backup could not be started: "
            + ((getattr(res, "stderr", "") or "systemctl failed").strip()[:300]),
        )


def status(path: Path = STATUS_PATH) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def running(path: Path = STATUS_PATH) -> bool:
    st = status(path)
    return bool(st and st.get("state") == "running")


def tick(db: Session, now: datetime | None = None, tz: ZoneInfo | None = None) -> bool:
    """The worker: start the scheduled backup when due. True when started."""
    now = now or utcnow()
    # A pending row the unit never reported on (the unit failed to start, or
    # the host went down) would otherwise show as running forever.
    for stale in db.scalars(
        select(Backup).where(
            Backup.kind == "scheduled",
            Backup.state == "running",
            Backup.path == "",
            Backup.started_at < now - timedelta(hours=STALE_RUNNING_HOURS),
        )
    ):
        stale.state = "failed"
        stale.finished_at = now
        stale.error = "the backup unit did not report back"
    s = settings(db)
    if not s["enabled"] or running():
        return False
    last = db.scalar(
        select(Backup.started_at)
        .where(Backup.kind == "scheduled")
        .order_by(Backup.started_at.desc())
        .limit(1)
    )
    if not policy.next_due(last, s["time"], now, tz or _local_zone()):
        return False
    # The row exists before the unit starts, so a second tick does not start another.
    db.add(
        Backup(
            id=uuid.uuid4(),
            kind="scheduled",
            started_at=now,
            state="running",
            path="",
            manifest={"name": policy.stamp(now)},
        )
    )
    db.commit()
    start("run")
    return True


def _local_zone() -> ZoneInfo:
    try:
        name = Path("/etc/timezone").read_text().strip()
        return ZoneInfo(name or "UTC")
    except (OSError, KeyError, ValueError):
        return ZoneInfo("UTC")
