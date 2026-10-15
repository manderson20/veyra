# SPDX-License-Identifier: AGPL-3.0-or-later
"""Multi-tenancy rules (docs/MULTI_TENANCY.md §2, §6): engine namespaces of new
organizations and the switch that allows more than one active organization."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.core.errors import ProblemError
from veyra.core.models import Installation, Organization
from veyra.telephony.asterisk.names import LEGACY, Names, namespace_for


def enabled(db: Session) -> bool:
    inst = db.scalar(select(Installation))
    return bool(inst and inst.multi_tenancy_enabled)


def active_count(db: Session, *, exclude: uuid.UUID | None = None) -> int:
    stmt = select(func.count()).select_from(Organization).where(Organization.is_active.is_(True))
    if exclude is not None:
        stmt = stmt.where(Organization.id != exclude)
    return int(db.scalar(stmt) or 0)


def check_may_activate(db: Session, *, exclude: uuid.UUID | None = None) -> None:
    """Refuse a second active organization while multi-tenancy is off."""
    if active_count(db, exclude=exclude) >= 1 and not enabled(db):
        raise ProblemError(
            409,
            "Multi-tenancy is off",
            "A second active organization needs multi-tenancy, so that its phones cannot "
            "reach the other organization's. Turn it on under System → Settings first.",
            code="multi_tenancy_disabled",
        )


def new_namespace(db: Session, slug: str) -> str:
    """Today's names for the first organization; a derived namespace for the
    others. The empty namespace is handed out only while no organization holds it."""
    taken = set(db.scalars(select(Organization.engine_namespace)).all())
    if LEGACY not in taken:
        return LEGACY
    return namespace_for(slug, taken)


def names_of(db: Session, organization_id: uuid.UUID | None) -> Names:
    """The engine names of an organization (today's names when unknown)."""
    org = db.get(Organization, organization_id) if organization_id else None
    return Names(org.engine_namespace if org is not None else LEGACY)


def namespaces(db: Session) -> dict[uuid.UUID, str]:
    """Engine namespace of every organization, by id."""
    return {
        org_id: ns
        for org_id, ns in db.execute(select(Organization.id, Organization.engine_namespace))
    }


# --------------------------------------------------------------------- the switch

CHECK_NAMESPACE = "zzcheck"
SHARED = [
    "SIP trunks (managed by platform administrators)",
    "Outbound routes marked 'All organizations'",
    "The numbering plan (length and range); numbers themselves are per organization",
    "DIDs: each one routes to exactly one organization",
    "SMTP server, firewall, updates, modules and sign-in providers",
]


def status(db: Session) -> dict[str, object]:
    orgs = db.scalars(select(Organization).order_by(Organization.name)).all()
    return {
        "enabled": enabled(db),
        "active_organizations": sum(1 for o in orgs if o.is_active),
        "organizations": [
            {
                "id": str(o.id),
                "name": o.name,
                "slug": o.slug,
                "namespace": o.engine_namespace,
                "is_active": o.is_active,
            }
            for o in orgs
        ],
        "shared": SHARED,
    }


def _with_twin(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The snapshot plus a synthetic organization that copies the first
    organization's numbers, slugs and names in its own namespace, so the
    proof does not depend on how many organizations exist yet."""
    import copy

    snap = copy.deepcopy(snapshot)
    orgs = list(snap.get("organizations") or [])
    first = next((o for o in orgs if o.get("is_active", True)), None)
    if first is None:
        return snap
    src, twin = str(first["slug"]), CHECK_NAMESPACE
    orgs.append({**first, "slug": twin, "name": "Isolation check", "namespace": twin})
    snap["organizations"] = orgs
    snap["installation"] = {**dict(snap.get("installation") or {}), "multi_tenancy_enabled": True}

    def endpoint(name: str) -> str:
        return f"{twin}-{name.split('-')[-1]}"

    for key in ("extensions", "voicemail_boxes", "ring_groups", "queues", "ivr_menus"):
        items = list(snap.get(key) or [])
        copies = []
        for item in items:
            if item.get("organization") != src:
                continue
            c = copy.deepcopy(item)
            c["organization"] = twin
            if "endpoint_name" in c:
                c["endpoint_name"] = endpoint(str(c["endpoint_name"]))
            for m in c.get("members") or []:
                if isinstance(m, dict) and "endpoint_name" in m:
                    m["endpoint_name"] = endpoint(str(m["endpoint_name"]))
            copies.append(c)
        snap[key] = items + copies
    return snap


def run_checks(db: Session, key: Any) -> list[dict[str, object]]:
    from veyra.telephony.asterisk import generator, isolation
    from veyra.telephony.snapshot import SnapshotError, build_snapshot

    checks: list[dict[str, object]] = []
    nss = [o.engine_namespace for o in db.scalars(select(Organization))]
    checks.append(
        {
            "name": "namespaces",
            "ok": len(nss) == len(set(nss)),
            "detail": "Every organization has its own engine namespace.",
        }
    )
    try:
        snap = build_snapshot(db, key)
        files = generator.generate(_with_twin(snap))
        problems = isolation.verify(files, strict=True)
        checks.append(
            {
                "name": "isolation",
                "ok": not problems,
                "detail": "No organization can reach another's phones, contexts, "
                "voicemail or queues."
                if not problems
                else "; ".join(problems[:10]),
            }
        )
    except (SnapshotError, generator.GenerationError) as e:
        checks.append({"name": "isolation", "ok": False, "detail": str(e)})
    return checks


def switch(db: Session, on: bool, key: Any) -> list[dict[str, object]]:
    inst = db.scalar(select(Installation))
    if inst is None:  # pragma: no cover (setup creates it)
        raise ProblemError(409, "Not set up", "Complete the setup first.", code="setup_required")
    if not on:
        if active_count(db) > 1:
            raise ProblemError(
                409,
                "Several organizations are active",
                "Deactivate all organizations but one before turning multi-tenancy off.",
                code="organizations_active",
            )
        inst.multi_tenancy_enabled = False
        return []
    checks = run_checks(db, key)
    if not all(c["ok"] for c in checks):
        raise ProblemError(
            409,
            "Isolation checks failed",
            "Multi-tenancy stays off: "
            + "; ".join(str(c["detail"]) for c in checks if not c["ok"]),
            code="isolation_check_failed",
        )
    inst.multi_tenancy_enabled = True
    return checks
