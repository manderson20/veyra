# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recording archive (docs/RECORDING_ARCHIVE.md): a copy of each call recording
on a backup destination, in a ``recordings`` folder of its own. Owner decision
2026-10-30: a copy lives exactly as long as its recording, so deleting a
recording, by hand or at its retention date, deletes the copy too.

The database side runs as the service account; ``run`` is the root job
(``veyra-backup@recordings``), which has no database role and asks through
``veyra backup archive-work`` and ``archive-report``. Files go up as stored:
encrypted recordings stay encrypted, with the wrapped key in their manifest."""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.backups import destinations
from veyra.core.models import CallRecording, SystemSetting
from veyra.core.models.base import utcnow

STATUS_KEY = "backup.recording_archive_status"
BATCH = 500
RUN_EVERY = timedelta(hours=1)
FOLDER = "recordings"


def name_of(rec_id: Any) -> str:
    return f"veyra-recording-{uuid.UUID(str(rec_id))}"


# ----------------------------------------------------------- service account


def _to_copy() -> Any:
    return select(CallRecording).where(
        CallRecording.deleted_at.is_(None), CallRecording.archived_at.is_(None)
    )


def _to_remove() -> Any:
    return select(CallRecording).where(
        CallRecording.deleted_at.is_not(None),
        CallRecording.archived_at.is_not(None),
        CallRecording.archive_removed_at.is_(None),
    )


def work(db: Session, destination_id: str, limit: int = BATCH) -> dict[str, Any]:
    """What the root job should do now."""
    copy = (
        db.scalars(_to_copy().order_by(CallRecording.created_at).limit(limit)).all()
        if destination_id
        else []
    )
    remove = db.scalars(_to_remove().limit(limit)).all()
    return {
        "copy": [
            {
                "id": str(r.id),
                "ref": r.ref,
                "path": r.path,
                "format": r.format,
                "created_at": r.created_at.isoformat(),
                "organization_id": str(r.organization_id) if r.organization_id else None,
                "wrapped_key": r.key_ciphertext,
            }
            for r in copy
        ],
        "remove": [{"id": str(r.id), "destination": r.archive_destination} for r in remove],
    }


def has_work(db: Session, destination_id: str) -> bool:
    if destination_id and db.execute(_to_copy().limit(1)).first():
        return True
    return db.execute(_to_remove().limit(1)).first() is not None


def report(db: Session, result: dict[str, Any], now: datetime | None = None) -> None:
    """Record what the root job did."""
    now = now or utcnow()
    for item in result.get("copied") or []:
        rec = db.get(CallRecording, uuid.UUID(item["id"]))
        if rec is not None:
            rec.archive_destination = item["destination"]
            rec.archived_at = now
    for rec_id in result.get("removed") or []:
        rec = db.get(CallRecording, uuid.UUID(rec_id))
        if rec is not None:
            rec.archive_removed_at = now
    row = db.get(SystemSetting, STATUS_KEY)
    value = {
        "started_at": (row.value or {}).get("started_at") if row is not None else now.isoformat(),
        "at": now.isoformat(),
        "copied": len(result.get("copied") or []),
        "removed": len(result.get("removed") or []),
        "errors": [str(e)[:300] for e in (result.get("errors") or [])][:10],
    }
    if row is None:
        db.add(SystemSetting(key=STATUS_KEY, value=value))
    else:
        row.value = value
    db.flush()


def uses_destination(db: Session, destination_id: str) -> int:
    """Copies on a destination that Veyra still has to be able to remove."""
    return (
        db.scalar(
            select(func.count())
            .select_from(CallRecording)
            .where(
                CallRecording.archive_destination == destination_id,
                CallRecording.archived_at.is_not(None),
                CallRecording.archive_removed_at.is_(None),
            )
        )
        or 0
    )


def status(db: Session, destination_id: str) -> dict[str, Any]:
    row = db.get(SystemSetting, STATUS_KEY)
    last = row.value if row is not None and isinstance(row.value, dict) else None

    def count(stmt: Any) -> int:
        return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    return {
        "destination_id": destination_id,
        "last_run": last,
        "waiting": count(_to_copy()) if destination_id else 0,
        "to_remove": count(_to_remove()),
        "archived": db.scalar(
            select(func.count())
            .select_from(CallRecording)
            .where(
                CallRecording.archived_at.is_not(None), CallRecording.archive_removed_at.is_(None)
            )
        )
        or 0,
    }


def last_errors(db: Session) -> list[str]:
    row = db.get(SystemSetting, STATUS_KEY)
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    return [str(e) for e in value.get("errors") or []]


def due(db: Session, now: datetime) -> bool:
    row = db.get(SystemSetting, STATUS_KEY)
    at = (row.value or {}).get("started_at") if row is not None else None
    if not at:
        return True
    try:
        return now - datetime.fromisoformat(at) >= RUN_EVERY
    except ValueError:
        return True


def note_started(db: Session, now: datetime) -> None:
    """Before the job starts, so one that dies is not restarted every minute."""
    row = db.get(SystemSetting, STATUS_KEY)
    if row is None:
        db.add(SystemSetting(key=STATUS_KEY, value={"started_at": now.isoformat()}))
    else:
        row.value = {**(row.value or {}), "started_at": now.isoformat()}
    db.flush()


# ------------------------------------------------------------------ root job


def run(
    settings: dict[str, Any],
    todo: dict[str, Any],
    recordings_dir: Path,
    make_remote: Callable[[dict[str, Any]], destinations.Remote] | None = None,
) -> dict[str, Any]:
    """Copy and remove; one failed item never stops the others on a working
    destination, and whatever failed is simply still there for the next run."""
    by_id = {str(d["id"]): d for d in settings.get("destinations") or []}
    connect = make_remote or (
        lambda d: destinations.archive_remote(
            d, secret=d.get("secret"), ssh_private_key=settings.get("ssh_private_key")
        )
    )
    remotes: dict[str, destinations.Remote] = {}
    errors: list[str] = []
    copied: list[dict[str, str]] = []
    removed: list[str] = []

    def remote_for(dest_id: str) -> destinations.Remote | None:
        if dest_id in remotes:
            return remotes[dest_id]
        dest = by_id.get(dest_id)
        if dest is None:
            errors.append(f"destination {dest_id} no longer exists")
            return None
        try:
            remotes[dest_id] = connect(dest)
        except (destinations.DestinationError, OSError) as e:
            errors.append(f"{dest.get('name') or dest_id}: {e}")
            return None
        return remotes[dest_id]

    # Removals first: they are what the retention period promises.
    for item in todo.get("remove") or []:
        rem = remote_for(str(item["destination"]))
        if rem is None:
            continue
        name = name_of(item["id"])
        try:
            rem.delete(name)
            if rem.exists(name):
                raise destinations.DestinationError("it is still there after deleting")
            removed.append(item["id"])
        except (destinations.DestinationError, OSError) as e:
            errors.append(f"removing {name}: {e}")

    dest_id = str((settings.get("recording_archive") or {}).get("destination_id") or "")
    root = recordings_dir.resolve()
    for item in todo.get("copy") or []:
        rem = remote_for(dest_id)
        if rem is None:
            break
        name = name_of(item["id"])
        source = (root / item["path"]).resolve()
        if root not in source.parents or not source.is_file():
            errors.append(f"{name}: the recording's file is not on this server")
            continue
        try:
            with tempfile.TemporaryDirectory() as tmp:
                artifact = Path(tmp) / name
                artifact.mkdir()
                shutil.copy2(source, artifact / source.name)
                (artifact / destinations.MANIFEST).write_text(json.dumps(item, indent=1))
                rem.upload(artifact)
            copied.append({"id": item["id"], "destination": dest_id})
        except (destinations.DestinationError, OSError) as e:
            errors.append(f"{name}: {e}")
            break  # the next ones would fail the same way; the next run retries
    return {"copied": copied, "removed": removed, "errors": errors}
