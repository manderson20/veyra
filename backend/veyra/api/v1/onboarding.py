# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organization onboarding (docs/MULTI_TENANCY_MSP.md §10): what is done and
what is left for one organization, step by step, and the final check."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.core import limits, tenancy
from veyra.core.db import get_db
from veyra.core.deps import require
from veyra.core.errors import not_found
from veyra.core.models import (
    Organization,
    OrganizationNumber,
    OutboundRoute,
    Role,
    RoleAssignment,
    SipTrunk,
    Site,
    User,
)
from veyra.core.security.principal import Principal
from veyra.emergency import service as emergency

router = APIRouter(tags=["organizations"])

ADMIN_ROLE = "org_admin"


def _org(db: Session, principal: Principal, organization_id: uuid.UUID) -> Organization:
    org = db.get(Organization, organization_id)
    if org is None or not principal.has("organizations.read", organization_id):
        raise not_found("Organization")
    return org


def _step(key: str, title: str, done: bool, detail: str, optional: bool = False) -> dict[str, Any]:
    return {"key": key, "title": title, "done": done, "optional": optional, "detail": detail}


def steps(db: Session, org: Organization) -> list[dict[str, Any]]:
    """Steps 1 to 6 of §10; step 7 (the check) runs on request."""
    count = db.scalar(
        select(func.count())
        .select_from(OrganizationNumber)
        .where(OrganizationNumber.organization_id == org.id)
    )
    missing = [
        what
        for what, ok in (
            ("its numbers", bool(count)),
            ("a main number", bool(org.main_number)),
            ("an emergency number", bool(org.emergency_caller_id_number)),
        )
        if not ok
    ]
    out = [
        _step(
            "organization",
            "Organization and numbers",
            not missing,
            f"{count} number block(s); main number {org.main_number}, emergency number "
            f"{org.emergency_caller_id_number}. Namespace {org.engine_namespace or '(first)'}."
            if not missing
            else "Still needs " + ", ".join(missing) + ".",
        )
    ]

    dedicated = [
        t.name for t in db.scalars(select(SipTrunk).where(SipTrunk.organization_id == org.id))
    ]
    routes = list(
        db.scalars(
            select(OutboundRoute).where(
                OutboundRoute.is_enabled.is_(True),
                OutboundRoute.is_emergency.is_(False),
                (OutboundRoute.organization_id == org.id) | OutboundRoute.organization_id.is_(None),
            )
        )
    )
    own = sum(1 for r in routes if r.organization_id == org.id)
    shared = len(routes) - own
    trunk_bits = []
    if dedicated:
        trunk_bits.append("dedicated trunk(s): " + ", ".join(sorted(dedicated)))
    if own:
        trunk_bits.append(f"{own} outbound route(s) of its own")
    if shared:
        trunk_bits.append(f"{shared} shared outbound route(s)")
    out.append(
        _step(
            "trunk",
            "Trunk",
            bool(dedicated or routes),
            "; ".join(trunk_bits).capitalize() + "."
            if trunk_bits
            else "No outbound route reaches this organization yet: add a dedicated trunk "
            "or a shared route.",
            optional=True,
        )
    )

    admins = list(
        db.scalars(
            select(User.email)
            .join(RoleAssignment, RoleAssignment.user_id == User.id)
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(
                Role.key == ADMIN_ROLE,
                RoleAssignment.scope_type == "organization",
                RoleAssignment.organization_id == org.id,
            )
            .order_by(User.email)
        )
    )
    out.append(
        _step(
            "administrator",
            "First administrator",
            bool(admins),
            "Organization administrators: " + ", ".join(admins) + "."
            if admins
            else "Nobody is an organization administrator here yet.",
        )
    )

    has_cred = org.provisioning_secret_ciphertext is not None
    out.append(
        _step(
            "phones",
            "Phones",
            has_cred,
            f"Phones enroll as {org.provisioning_user}."
            if has_cred
            else "Create the provisioning credential its phones use for their first fetch.",
        )
    )

    sites = list(db.scalars(select(Site).where(Site.organization_id == org.id).order_by(Site.name)))
    ready = [s.name for s in sites if emergency.readiness(db, s)["ready"]]
    out.append(
        _step(
            "emergency",
            "Emergency",
            bool(ready),
            f"{len(ready)} of {len(sites)} site(s) ready for 911: " + ", ".join(ready) + "."
            if ready
            else (
                f"None of its {len(sites)} site(s) is ready for 911 yet."
                if sites
                else "Add a site with its civic address and an ELIN (one of its numbers)."
            ),
        )
    )

    row = limits.of(db, org.id)
    set_ = (
        [
            f"{label} {value}"
            for label, value in (
                ("outside calls at once", row.max_outside_calls),
                ("extensions", row.max_extensions),
                ("devices", row.max_devices),
            )
            if value
        ]
        if row
        else []
    )
    out.append(
        _step(
            "limits",
            "Limits",
            bool(set_),
            "At most " + ", ".join(set_) + "." if set_ else "No limits: it may use what it needs.",
            optional=True,
        )
    )
    return out


@router.get(
    "/organizations/{organization_id}/onboarding",
    summary="What is done and left to set up an organization",
)
def get_onboarding(
    organization_id: uuid.UUID,
    principal: Principal = Depends(require("organizations.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org = _org(db, principal, organization_id)
    s = steps(db, org)
    return {
        "organization_id": str(org.id),
        "multi_tenancy": tenancy.enabled(db),
        "steps": s,
        "left": [x["title"] for x in s if not x["done"] and not x["optional"]],
    }


@router.post(
    "/organizations/{organization_id}/onboarding/check",
    summary="Run the isolation and caller ID checks with this organization included",
)
def run_check(
    organization_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("system.settings.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from veyra.core.security.crypto import try_load_installation_key

    org = _org(db, principal, organization_id)
    checks = tenancy.run_checks(db, try_load_installation_key(request.app.state.settings))
    s = steps(db, org)
    left = [x["title"] for x in s if not x["done"] and not x["optional"]]
    left += [str(c["detail"]) for c in checks if not c["ok"]]
    return {
        "organization_id": str(org.id),
        "checks": checks,
        "emergency": emergency.organizations_overview(db, [org.id]),
        "left": left,
        "ok": not left,
    }
