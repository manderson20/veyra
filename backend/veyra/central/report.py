# SPDX-License-Identifier: AGPL-3.0-or-later
"""The report an instance sends with every check-in
(docs/CENTRAL_MANAGEMENT.md §3). Counts and states only: no secrets, no
names of people, no call records."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.core.models import (
    Alert,
    AuditEvent,
    AvailableUpdate,
    Extension,
    FirewallBan,
    Installation,
    InstalledModule,
    Organization,
    SipTrunk,
    UpdateCheck,
)
from veyra.core.models.base import utcnow
from veyra.version import __version__


def _count(db: Session, stmt: Any) -> int:
    return int(db.scalar(stmt) or 0)


def build(db: Session, adapter: Any | None) -> dict[str, Any]:
    now = utcnow()
    inst = db.scalar(select(Installation))
    engine: dict[str, Any] = {"state": "none"}
    registered = active_calls = None
    if adapter is not None:
        try:
            h = adapter.health()
            engine = {"state": h.state, "version": h.version, "message": h.message}
            if h.state == "running":
                registered = sum(1 for e in adapter.endpoint_statuses() if e.registered)
                active_calls = len(adapter.active_calls())
        except Exception as e:  # the report goes out even when the engine does not answer
            engine = {"state": "unknown", "message": f"{type(e).__name__}"}
    alerts = [
        {
            "rule": a.rule,
            "subject": a.subject,
            "message": a.message,
            "since": (a.raised_at or a.first_seen_at).isoformat(),
        }
        for a in db.scalars(select(Alert).where(Alert.state == "raised").order_by(Alert.raised_at))
    ]
    status = "ok"
    if engine["state"] not in ("running", "none") or any(
        a["rule"] in ("engine_down", "service_down") for a in alerts
    ):
        status = "failed"
    elif alerts:
        status = "degraded"
    last_check = db.scalar(select(UpdateCheck).order_by(UpdateCheck.checked_at.desc()).limit(1))
    updates = [
        {
            "version": u.version,
            "category": u.category,
            "state": u.state,
            "error": (u.error or None) and u.error[:300],
        }
        for u in db.scalars(
            select(AvailableUpdate)
            .where(AvailableUpdate.component == "veyra_core")
            .where(AvailableUpdate.state.notin_(("installed", "dismissed")))
            .order_by(AvailableUpdate.created_at.desc())
            .limit(5)
        )
    ]
    from veyra.firewall.settings import load_settings

    return {
        "identity": {
            "name": inst.name if inst else "Veyra",
            "version": __version__,
            "deployment_mode": inst.deployment_mode if inst else "standalone",
            "multi_tenancy": bool(inst and inst.multi_tenancy_enabled),
        },
        "health": {"status": status, "engine": engine},
        "telephony": {
            "organizations": _count(
                db,
                select(func.count())
                .select_from(Organization)
                .where(Organization.is_active.is_(True)),
            ),
            "extensions": _count(
                db,
                select(func.count()).select_from(Extension).where(Extension.is_enabled.is_(True)),
            ),
            "trunks": _count(
                db, select(func.count()).select_from(SipTrunk).where(SipTrunk.is_enabled.is_(True))
            ),
            "registered": registered,
            "active_calls": active_calls,
        },
        "alerts": alerts,
        "updates": {
            "installed": __version__,
            "available": updates,
            "last_check": last_check.checked_at.isoformat() if last_check else None,
            "last_outcome": last_check.outcome if last_check else None,
        },
        "security": {
            "firewall": bool(load_settings(db).enabled),
            "active_bans": _count(
                db,
                select(func.count())
                .select_from(FirewallBan)
                .where(FirewallBan.lifted_at.is_(None), FirewallBan.expires_at > now),
            ),
            "failed_sign_ins_1h": _count(
                db,
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.action == "auth.login",
                    AuditEvent.outcome == "failure",
                    AuditEvent.occurred_at > now - timedelta(hours=1),
                ),
            ),
        },
        "modules": [
            {"id": m.module_id, "version": m.version, "state": m.state}
            for m in db.scalars(select(InstalledModule).order_by(InstalledModule.module_id))
        ],
    }
