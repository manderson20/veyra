# SPDX-License-Identifier: AGPL-3.0-or-later
"""Retention (docs/PRODUCTION_HARDENING.md §4): one settings document with
a row per data class, one daily job that applies it and audits what it
removed, and the inventory that shows what the database and the disk hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.models import (
    Alert,
    AuditEvent,
    Backup,
    CallRecord,
    CallRecording,
    CallSample,
    Capture,
    CentralSample,
    ClusterEvent,
    FirewallBan,
    FirewallEvent,
    PageLog,
    ProvisioningRequest,
    SystemSetting,
    UpdateHistory,
    UserSession,
)
from veyra.core.models.base import utcnow

SETTINGS_KEY = "retention"
LAST_RUN_KEY = "retention.last_run"
CALLS_KEY = "calls.retention_days"  # the Milestone 10 setting the call history reads
RUN_EVERY = timedelta(hours=24)


@dataclass(frozen=True)
class Rule:
    key: str
    label: str
    default_days: int
    minimum_days: int
    description: str
    model: Any
    time_column: Any
    editable: bool = True


RULES: list[Rule] = [
    Rule(
        "audit_log",
        "Audit log",
        730,
        365,
        "Who did what; append-only. Platform administrators only; never below a year.",
        AuditEvent,
        AuditEvent.occurred_at,
    ),
    Rule(
        "calls",
        "Call history",
        400,
        30,
        "Calls, their legs and queue events (reports read them).",
        CallRecord,
        CallRecord.started_at,
    ),
    Rule(
        "alerts",
        "Alert history",
        365,
        30,
        "Cleared alerts; open alerts are never removed.",
        Alert,
        Alert.cleared_at,
    ),
    Rule(
        "update_history",
        "Update history",
        730,
        90,
        "Installed releases and their logs.",
        UpdateHistory,
        UpdateHistory.started_at,
    ),
    Rule(
        "cluster_events",
        "Cluster events",
        730,
        90,
        "HA switchovers, failovers and role changes.",
        ClusterEvent,
        ClusterEvent.occurred_at,
    ),
    Rule(
        "firewall",
        "Firewall events and expired bans",
        90,
        7,
        "Detections and bans that expired or were lifted; active bans stay.",
        FirewallEvent,
        FirewallEvent.at,
    ),
    Rule(
        "provisioning_requests",
        "Provisioning request log",
        30,
        7,
        "Every phone configuration request.",
        ProvisioningRequest,
        ProvisioningRequest.at,
    ),
    Rule("page_log", "Page log", 90, 7, "Pages sent.", PageLog, PageLog.at),
    Rule(
        "captures",
        "Packet captures",
        7,
        1,
        "Capture files and their records (docs/CALL_FEATURES.md §2.2); a running capture stays.",
        Capture,
        Capture.started_at,
    ),
    Rule(
        "metrics",
        "Engine metrics samples",
        14,
        2,
        "Dashboard graph samples (one per worker pass).",
        CallSample,
        CallSample.at,
    ),
    Rule(
        "central_samples",
        "Central console samples",
        30,
        7,
        "Per-instance counts behind the console's graphs.",
        CentralSample,
        CentralSample.at,
    ),
]
BY_KEY = {r.key: r for r in RULES}


def settings(db: Session) -> dict[str, int]:
    row = db.get(SystemSetting, SETTINGS_KEY)
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    out = {r.key: r.default_days for r in RULES}
    for k, v in value.items():
        if k in BY_KEY and v is not None:
            out[k] = max(BY_KEY[k].minimum_days, int(v))
    # The call history setting of Milestone 10 stays the source for calls.
    calls = db.get(SystemSetting, CALLS_KEY)
    if calls is not None and isinstance(calls.value, dict) and calls.value.get("days"):
        out["calls"] = max(BY_KEY["calls"].minimum_days, int(calls.value["days"]))
    return out


def save_settings(db: Session, body: dict[str, Any], by: Any) -> dict[str, int]:
    value: dict[str, int] = {}
    for k, v in body.items():
        if k not in BY_KEY:
            raise ValueError(f"unknown data class {k!r}")
        days = int(v)
        if days < BY_KEY[k].minimum_days:
            raise ValueError(f"{BY_KEY[k].label}: at least {BY_KEY[k].minimum_days} days")
        value[k] = days
    row = db.get(SystemSetting, SETTINGS_KEY)
    if row is None:
        db.add(SystemSetting(key=SETTINGS_KEY, value=value, updated_by=by))
    else:
        row.value = {**(row.value if isinstance(row.value, dict) else {}), **value}
        row.updated_by = by
    if "calls" in value:
        calls = db.get(SystemSetting, CALLS_KEY)
        if calls is None:
            db.add(SystemSetting(key=CALLS_KEY, value={"days": value["calls"]}, updated_by=by))
        else:
            calls.value = {
                **(calls.value if isinstance(calls.value, dict) else {}),
                "days": value["calls"],
            }
    db.flush()
    return settings(db)


def rules_out(db: Session) -> list[dict[str, Any]]:
    current = settings(db)
    return [
        {
            "key": r.key,
            "label": r.label,
            "description": r.description,
            "days": current[r.key],
            "default_days": r.default_days,
            "minimum_days": r.minimum_days,
        }
        for r in RULES
    ]


# ------------------------------------------------------------------ the job


def _count(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


def _prune(db: Session, rule: Rule, cutoff: datetime) -> int:
    if rule.key == "audit_log":
        db.execute(text("SET LOCAL veyra.audit_retention = 'on'"))
        return _count(db.execute(delete(AuditEvent).where(AuditEvent.occurred_at < cutoff)))
    if rule.key == "calls":
        from veyra.reporting import cdr, queues

        return cdr.prune(db) + queues.prune(db)
    if rule.key == "alerts":
        return _count(
            db.execute(
                delete(Alert).where(Alert.cleared_at.is_not(None), Alert.cleared_at < cutoff)
            )
        )
    if rule.key == "firewall":
        n = _count(db.execute(delete(FirewallEvent).where(FirewallEvent.at < cutoff)))
        n += _count(
            db.execute(
                delete(FirewallBan).where(
                    FirewallBan.expires_at < cutoff,
                )
            )
        )
        return n
    if rule.key == "captures":
        from veyra.diagnostics import captures

        n = 0
        for row in db.scalars(
            select(Capture).where(
                Capture.started_at < cutoff, Capture.state.not_in(list(captures.ACTIVE))
            )
        ).all():
            captures.remove_file(row)
            db.delete(row)
            n += 1
        return n
    return _count(db.execute(delete(rule.model).where(rule.time_column < cutoff)))


def run(db: Session, now: datetime | None = None, *, actor: str = "worker") -> dict[str, int]:
    """Apply every rule; one audit entry per class that lost rows, and one
    summary. The caller commits."""
    now = now or utcnow()
    current = settings(db)
    removed: dict[str, int] = {}
    for rule in RULES:
        cutoff = now - timedelta(days=current[rule.key])
        n = _prune(db, rule, cutoff)
        removed[rule.key] = n
        if n:
            audit.record(
                db,
                action="retention.pruned",
                actor_type="system",
                actor_label=actor,
                target_type="data_class",
                target_id=rule.key,
                details={"removed": n, "days": current[rule.key], "cutoff": cutoff.isoformat()},
            )
    row = db.get(SystemSetting, LAST_RUN_KEY)
    value = {"at": now.isoformat(), "removed": removed}
    if row is None:
        db.add(SystemSetting(key=LAST_RUN_KEY, value=value))
    else:
        row.value = value
    db.flush()
    return removed


def due(db: Session, now: datetime | None = None) -> bool:
    now = now or utcnow()
    row = db.get(SystemSetting, LAST_RUN_KEY)
    if row is None or not isinstance(row.value, dict) or not row.value.get("at"):
        return True
    return now - datetime.fromisoformat(str(row.value["at"])) >= RUN_EVERY


def last_run(db: Session) -> dict[str, Any] | None:
    row = db.get(SystemSetting, LAST_RUN_KEY)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else None


# ------------------------------------------------------------------ inventory


def _dir_bytes(path: Path) -> int | None:
    try:
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    except OSError:
        return None


def inventory(db: Session, settings_obj: Any | None = None) -> list[dict[str, Any]]:
    """Rows, bytes and the oldest record per class, plus the file-backed classes."""
    current = settings(db)
    out: list[dict[str, Any]] = []
    for rule in RULES:
        table = rule.model.__tablename__
        rows = db.scalar(select(func.count()).select_from(rule.model)) or 0
        oldest = db.scalar(select(func.min(rule.time_column)))
        size = db.scalar(text(f"SELECT pg_total_relation_size('{table}')"))
        if rule.key == "captures":  # the files, not the table
            size = db.scalar(select(func.sum(Capture.bytes)).where(Capture.state != "deleted"))
        out.append(
            {
                "key": rule.key,
                "label": rule.label,
                "rows": int(rows),
                "bytes": int(size or 0),
                "oldest": oldest.isoformat() if oldest else None,
                "days": current[rule.key],
            }
        )
    rec_rows = db.scalar(
        select(func.count()).select_from(CallRecording).where(CallRecording.deleted_at.is_(None))
    )
    rec_bytes = (
        db.scalar(select(func.sum(CallRecording.size_bytes)))
        if hasattr(CallRecording, "size_bytes")
        else None
    )
    held = db.scalar(
        select(func.count()).select_from(CallRecording).where(CallRecording.held.is_(True))
    )
    out.append(
        {
            "key": "recordings",
            "label": "Call recordings",
            "rows": int(rec_rows or 0),
            "bytes": int(rec_bytes or 0),
            "oldest": None,
            "days": None,
            "note": f"per recording policy; {int(held or 0)} on legal hold",
        }
    )
    sessions = db.scalar(select(func.count()).select_from(UserSession)) or 0
    out.append(
        {
            "key": "sessions",
            "label": "Sessions and reset tokens",
            "rows": int(sessions),
            "bytes": 0,
            "oldest": None,
            "days": None,
            "note": "30 days after expiry (configuration)",
        }
    )
    backups = (
        db.scalar(select(func.count()).select_from(Backup).where(Backup.state == "verified")) or 0
    )
    backup_bytes = db.scalar(select(func.sum(Backup.bytes)).where(Backup.state == "verified")) or 0
    out.append(
        {
            "key": "backups",
            "label": "Backups",
            "rows": int(backups),
            "bytes": int(backup_bytes),
            "oldest": None,
            "days": None,
            "note": "keep policy on the Backups page",
        }
    )
    if settings_obj is not None:
        vm = _dir_bytes(Path("/var/spool/asterisk/voicemail"))
        out.append(
            {
                "key": "voicemail",
                "label": "Voicemail messages",
                "rows": 0,
                "bytes": int(vm or 0),
                "oldest": None,
                "days": None,
                "note": (
                    "Asterisk's maxmsg per mailbox; messages are deleted from the phone "
                    "or the Voicemail page"
                ),
            }
        )
        prompts = (
            _dir_bytes(settings_obj.prompts_dir) if hasattr(settings_obj, "prompts_dir") else None
        )
        if prompts is not None:
            out.append(
                {
                    "key": "prompts",
                    "label": "Prompts and hold music",
                    "rows": 0,
                    "bytes": int(prompts),
                    "oldest": None,
                    "days": None,
                    "note": "kept",
                }
            )
    return out
