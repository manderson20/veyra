# SPDX-License-Identifier: AGPL-3.0-or-later
"""Packet captures, the database side (docs/CALL_FEATURES.md §2.2): rows,
resolving a target into a filter, starting and stopping the root unit
through polkit, recording what the runner reports, files and deletion."""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.models import Capture, Extension, Organization, SipTrunk
from veyra.core.models.base import utcnow
from veyra.diagnostics import filters
from veyra.telephony.adapter import Capability, EngineUnavailable, NotSupported, TelephonyAdapter
from veyra.telephony.settings import SipSettings

UNIT = "veyra-capture@{instance}.service"
MIN_SECONDS, DEFAULT_SECONDS, MAX_SECONDS = 10, 120, 30 * 60
MIN_MB, DEFAULT_MB, MAX_MB = 1, 50, 500
MAX_RUNNING = 2
STALE_GRACE = timedelta(minutes=3)
ACTIVE = ("starting", "running")
# Tests replace this with a recorder.
systemctl: Callable[[list[str]], Any] | None = None


class CaptureError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ------------------------------------------------------------------ targets


def sip_ports(sip: SipSettings) -> list[int]:
    ports = {sip.udp_port}
    if sip.tcp_enabled:
        ports.add(sip.tcp_port)
    if sip.tls_enabled:
        ports.add(sip.tls_port)
    return sorted(ports)


def registrations_by_endpoint(adapter: TelephonyAdapter | None) -> dict[str, list[str]]:
    """Endpoint -> the addresses its contacts register from (source, else contact)."""
    if adapter is None or Capability.REGISTRATIONS not in adapter.capabilities():
        return {}
    try:
        rows = adapter.registrations()
    except (EngineUnavailable, NotSupported):
        return {}
    out: dict[str, list[str]] = {}
    for r in rows:
        host = r.source_host or r.contact_host
        if host and host not in out.setdefault(r.endpoint, []):
            out[r.endpoint].append(host)
    return out


def targets(db: Session, adapter: TelephonyAdapter | None, sip: SipSettings) -> dict[str, Any]:
    """What the start form offers: SIP ports, the RTP range, extensions with
    the addresses they register from, trunks with their hosts."""
    regs = registrations_by_endpoint(adapter)
    orgs = {o.id: o.name for o in db.scalars(select(Organization))}
    exts = db.scalars(
        select(Extension).where(Extension.is_enabled.is_(True)).order_by(Extension.number)
    ).all()
    trunks = db.scalars(select(SipTrunk).order_by(SipTrunk.name)).all()
    return {
        "sip_ports": sip_ports(sip),
        "rtp_range": [sip.rtp_start, sip.rtp_end],
        "extensions": [
            {
                "id": str(e.id),
                "number": e.number,
                "display_name": e.display_name,
                "organization_name": orgs.get(e.organization_id),
                "hosts": regs.get(e.endpoint_name, []),
            }
            for e in exts
        ],
        "trunks": [
            {"id": str(t.id), "name": t.name, "host": t.host, "port": t.port} for t in trunks
        ],
    }


def resolve(
    db: Session,
    adapter: TelephonyAdapter | None,
    sip: SipSettings,
    *,
    target: str,
    extension_id: uuid.UUID | None = None,
    trunk_id: uuid.UUID | None = None,
    address: str | None = None,
    rtp: bool = False,
) -> tuple[dict[str, Any], str]:
    """A start request -> (normalised filter, label)."""
    ports = sip_ports(sip)
    spec: dict[str, Any] = {"hosts": [], "nets": [], "ports": ports, "portranges": [], "rtp": rtp}
    if rtp:
        spec["portranges"] = [[sip.rtp_start, sip.rtp_end]]
    if target == "all_sip":
        label = "All SIP" + (" and RTP" if rtp else "")
    elif target == "extension":
        ext = db.get(Extension, extension_id) if extension_id else None
        if ext is None:
            raise CaptureError(404, "not_found", "Extension was not found.")
        hosts = registrations_by_endpoint(adapter).get(ext.endpoint_name, [])
        if not hosts:
            raise CaptureError(
                409,
                "not_registered",
                "No phone is registered for this extension right now, so there is no address to "
                "capture. Capture all SIP instead, or by address.",
            )
        spec["hosts"] = hosts
        label = f"Extension {ext.number} {ext.display_name}".strip()
    elif target == "trunk":
        trunk = db.get(SipTrunk, trunk_id) if trunk_id else None
        if trunk is None:
            raise CaptureError(404, "not_found", "Trunk was not found.")
        spec["hosts"] = [trunk.host]
        spec["ports"] = sorted(set(ports) | {trunk.port})
        label = f"Trunk {trunk.name}"
    elif target == "address":
        text = (address or "").strip()
        if not text:
            raise CaptureError(400, "bad_filter", "An address or network is needed.")
        if "/" in text:
            spec["nets"] = [text]
        else:
            spec["hosts"] = [text]
        label = text
    else:
        raise CaptureError(400, "bad_filter", "Unknown capture target.")
    try:
        return filters.normalize(spec), label[:200]
    except filters.FilterError as e:
        raise CaptureError(400, "bad_filter", str(e)) from e


# ------------------------------------------------------------------ rows


def path_for(directory: Path, capture_id: uuid.UUID) -> Path:
    return directory / f"{capture_id}.pcap"


def start(
    db: Session,
    *,
    spec: dict[str, Any],
    label: str,
    directory: Path,
    duration_seconds: int = DEFAULT_SECONDS,
    size_limit_mb: int = DEFAULT_MB,
    created_by: str = "console",
    created_by_user_id: uuid.UUID | None = None,
) -> Capture:
    """Record the capture, then start its unit. The row exists first so the
    runner finds it, and is marked failed when the unit cannot start."""
    try:
        normalized = filters.normalize(spec)
        expression = filters.expression(normalized)
    except filters.FilterError as e:
        raise CaptureError(400, "bad_filter", str(e)) from e
    if not MIN_SECONDS <= duration_seconds <= MAX_SECONDS:
        raise CaptureError(
            400, "bad_duration", f"Duration is {MIN_SECONDS} to {MAX_SECONDS} seconds."
        )
    if not MIN_MB <= size_limit_mb <= MAX_MB:
        raise CaptureError(400, "bad_size", f"The size limit is {MIN_MB} to {MAX_MB} MB.")
    mark_stale(db)
    if running_count(db) >= MAX_RUNNING:
        raise CaptureError(
            409, "too_many", f"At most {MAX_RUNNING} captures run at a time; stop one first."
        )
    row = Capture(
        id=uuid.uuid4(),
        state="starting",
        label=label[:200],
        filter=normalized,
        expression=expression,
        duration_seconds=duration_seconds,
        size_limit_mb=size_limit_mb,
        created_by=created_by[:320],
        created_by_user_id=created_by_user_id,
    )
    row.path = str(path_for(directory, row.id))
    db.add(row)
    db.commit()
    try:
        _systemctl(["start", "--no-block", UNIT.format(instance=row.id)])
    except CaptureError as e:
        row.state, row.error, row.finished_at = "failed", e.message, utcnow()
        db.commit()
        raise
    return row


def stop(db: Session, row: Capture) -> None:
    if row.state not in ACTIVE:
        raise CaptureError(409, "not_running", "This capture is not running.")
    _systemctl(["stop", "--no-block", UNIT.format(instance=row.id)])


def record(db: Session, p: dict[str, Any]) -> Capture:
    """``veyra capture record``: the runner reports running, then the outcome."""
    row = db.get(Capture, uuid.UUID(str(p["id"])))
    if row is None:
        raise CaptureError(404, "not_found", "Capture was not found.")
    state = str(p.get("state") or "failed")
    if state not in ("running", "finished", "stopped", "failed"):
        raise CaptureError(400, "bad_state", f"unknown state {state!r}")
    if row.state == "deleted":
        return row  # deleted while running: the file is gone, keep it that way
    row.state = state
    if p.get("bytes") is not None:
        row.bytes = int(p["bytes"])
    if p.get("packets") is not None:
        row.packets = int(p["packets"])
    if p.get("path"):
        row.path = str(p["path"])
    if "error" in p:
        row.error = (str(p["error"])[:1000] or None) if p.get("error") else None
    if p.get("finished_at"):
        row.finished_at = datetime.fromisoformat(str(p["finished_at"]))
    elif state != "running":
        row.finished_at = utcnow()
    db.flush()
    if state != "running":
        audit.record(
            db,
            action="capture.run",
            outcome="success" if state != "failed" else "failure",
            actor_type="system",
            actor_label="capture unit",
            target_type="capture",
            target_id=row.id,
            details={
                "label": row.label,
                "state": state,
                "bytes": row.bytes,
                "packets": row.packets,
                "error": row.error,
                "created_by": row.created_by,
            },
        )
    return row


def running_count(db: Session) -> int:
    return len(db.scalars(select(Capture.id).where(Capture.state.in_(ACTIVE))).all())


def mark_stale(db: Session, now: datetime | None = None) -> int:
    """A capture whose unit never reported back (it failed to start, or the
    host went down) is marked failed once its duration plus a grace period
    has passed."""
    now = now or utcnow()
    n = 0
    for row in db.scalars(select(Capture).where(Capture.state.in_(ACTIVE))):
        deadline = row.started_at + timedelta(seconds=row.duration_seconds) + STALE_GRACE
        if deadline < now:
            row.state, row.finished_at = "failed", now
            row.error = "the capture unit did not report back"
            n += 1
    if n:
        db.flush()
    return n


def rows(db: Session, limit: int = 100) -> list[Capture]:
    mark_stale(db)
    return list(db.scalars(select(Capture).order_by(Capture.started_at.desc()).limit(limit)))


def file_of(row: Capture) -> Path | None:
    if not row.path or row.state in ("starting", "running", "deleted"):
        return None
    path = Path(row.path)
    return path if path.is_file() else None


def row_out(c: Capture) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "label": c.label,
        "state": c.state,
        "started_at": c.started_at.isoformat(),
        "finished_at": c.finished_at.isoformat() if c.finished_at else None,
        "duration_seconds": c.duration_seconds,
        "size_limit_mb": c.size_limit_mb,
        "filter": c.filter,
        "expression": c.expression,
        "rtp": bool(c.filter.get("rtp")),
        "bytes": c.bytes,
        "packets": c.packets,
        "error": c.error,
        "created_by": c.created_by,
        "downloadable": file_of(c) is not None,
    }


def delete(db: Session, row: Capture) -> None:
    """Remove the file and mark the row; a running capture is stopped first
    by the caller."""
    if row.state in ACTIVE:
        raise CaptureError(409, "running", "Stop the capture before deleting it.")
    remove_file(row)
    row.state = "deleted"
    db.flush()


def remove_file(row: Capture) -> bool:
    if not row.path:
        return False
    try:
        os.unlink(row.path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


# ------------------------------------------------------------------ the unit


def _systemctl(args: list[str]) -> None:
    cmd = ["systemctl", *args]
    res = (
        systemctl(cmd)
        if systemctl
        else subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)  # noqa: S603
    )
    if getattr(res, "returncode", 1) != 0:
        raise CaptureError(
            503,
            "unit_failed",
            "The capture unit could not be controlled: "
            + ((getattr(res, "stderr", "") or "systemctl failed").strip()[:300]),
        )
