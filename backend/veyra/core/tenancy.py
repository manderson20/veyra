# SPDX-License-Identifier: AGPL-3.0-or-later
"""Multi-tenancy rules (docs/MULTI_TENANCY.md §2, §6): engine namespaces of new
organizations and the switch that allows more than one active organization."""

from __future__ import annotations

import re
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


_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# Fields that name an organization by slug.
_ORG_FIELDS = ("organization", "organization_slug")
# Fields that hold a carrier number, which must stay unique on the server.
_NUMBER_FIELDS = ("did", "routes", "emergency_caller_id_number")
TWIN_NUMBER_PREFIX = "00"


def _owner(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    slug = item.get("organization_slug", item.get("organization"))
    return str(slug) if slug else None


def _twin_number(number: str) -> str:
    """A number no real route uses: the isolation check's DIDs and ELINs."""
    return TWIN_NUMBER_PREFIX + number.lstrip("+")[-18:]


def _collect(value: Any, key: str, ids: set[str], numbers: set[str]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _collect(v, k, ids, numbers)
    elif isinstance(value, list):
        for v in value:
            _collect(v, key, ids, numbers)
    elif isinstance(value, str):
        if _UUID_RE.match(value):
            ids.add(value)
        elif key in _NUMBER_FIELDS and value != "any":
            numbers.add(value)


def _rewrite(value: Any, key: str, src: str, twin: str, swap: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _rewrite(v, k, src, twin, swap) for k, v in value.items()}
    if isinstance(value, list):
        return [_rewrite(v, key, src, twin, swap) for v in value]
    if isinstance(value, str):
        if key in _ORG_FIELDS and value == src:
            return twin
        return swap.get(value, value)
    return value


def _with_twin(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The snapshot plus a synthetic organization that copies everything the
    first organization owns (docs/MULTI_TENANCY_MSP.md §3.1), with the same
    numbers, slugs and names, in its own namespace. Every key listed in
    ``snapshot.ORG_LISTS`` and ``ORG_NESTED`` is copied, so a new feature is
    in the proof as soon as its key is listed (and a key listed nowhere fails
    the tests).

    In the copies, the organization's slug becomes the twin's, endpoint names
    and ids are swapped consistently (so references stay inside the twin),
    and DIDs and ELINs get a prefix, because carrier numbers stay unique on
    the server. An ``any`` catch-all is not copied: there is one per trunk."""
    import copy
    import uuid as _uuid

    from veyra.telephony.snapshot import ORG_LISTS, ORG_NESTED

    snap = copy.deepcopy(snapshot)
    orgs = list(snap.get("organizations") or [])
    first = next((o for o in orgs if o.get("is_active", True)), None)
    if first is None:
        return snap
    src, twin = str(first["slug"]), CHECK_NAMESPACE
    orgs.append({**first, "slug": twin, "name": "Isolation check", "namespace": twin})
    snap["organizations"] = orgs
    snap["installation"] = {**dict(snap.get("installation") or {}), "multi_tenancy_enabled": True}

    def owned(items: Any) -> list[dict[str, Any]]:
        return [
            i
            for i in (items or [])
            if _owner(i) == src and not (isinstance(i, dict) and i.get("did") == "any")
        ]

    sources: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
    for key in ORG_LISTS:
        sources[(key, None)] = owned(snap.get(key))
    for key, members in ORG_NESTED.items():
        nested = snap.get(key) or {}
        for name in members:
            sources[(key, name)] = owned(nested.get(name))

    ids: set[str] = set()
    numbers: set[str] = set()
    for items in sources.values():
        _collect(items, "", ids, numbers)
    swap = {i: str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"veyra-twin:{i}")) for i in ids}
    swap |= {n: _twin_number(n) for n in numbers}
    for e in sources[("extensions", None)]:
        name = str(e.get("endpoint_name") or "")
        if name:
            swap[name] = f"{twin}-{name.split('-')[-1]}"

    for (key, member), items in sources.items():
        copies = [_rewrite(i, "", src, twin, swap) for i in items]
        if key == "outbound_routes":
            # Route contexts are shared names (veyra-out-<slug>).
            for c in copies:
                c["slug"] = f"{twin}-{c['slug']}"
        if member is None:
            snap[key] = list(snap.get(key) or []) + copies
            continue
        nested = dict(snap.get(key) or {})
        existing = list(nested.get(member) or [])
        if key == "paging" and member == "zones":
            # The sender listens on one port per zone, across the server.
            used = [int(z.get("port") or 0) for z in existing]
            for i, c in enumerate(copies):
                c["port"] = max(used, default=40000) + 1 + i
        nested[member] = existing + copies
        snap[key] = nested
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
        twin = _with_twin(snap)
        files = generator.generate(twin)
        problems = isolation.verify(
            files,
            strict=True,
            organizations={
                str(o.get("slug") or ""): str(o.get("namespace") or "")
                for o in twin.get("organizations") or []
            },
        )
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
