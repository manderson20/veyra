# SPDX-License-Identifier: AGPL-3.0-or-later
"""The number inventory (docs/MULTI_TENANCY_MSP.md §4): which organization
each carrier number belongs to, and the rules for routing it.

A number is kept in canonical form: digits only, ten for a North American
number however it was entered. No number belongs to two organizations, and
a number is routed by its owner only.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.core import tenancy
from veyra.core.errors import ProblemError, conflict
from veyra.core.models import InboundRoute, Organization, OrganizationNumber, SipTrunk
from veyra.core.models.base import utcnow
from veyra.telephony import routing

if TYPE_CHECKING:
    from veyra.core.security.principal import Principal

MAX_RANGE = 10_000
_DIGITS = re.compile(r"^[0-9]{2,18}$")


def canonical(value: str) -> str:
    """Digits only, without the North American 1; ``ValueError`` when the
    value is not a number Veyra can route."""
    did = routing.normalize_did(value)
    if did == routing.DID_ANY:
        raise ValueError("'any' is not a number")
    digits = routing.canonical_did(did).lstrip("+")
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    if not _DIGITS.match(digits):
        raise ValueError("digits only, 2 to 18 of them")
    return digits


def maybe_canonical(value: str | None) -> str | None:
    try:
        return canonical(value or "")
    except ValueError:
        return None


def in_range(number: str, first: str, last: str) -> bool:
    return len(number) == len(first) and first <= number <= last


def owner_of(db: Session, number: str) -> OrganizationNumber | None:
    """The inventory row that holds ``number`` (canonical), if any."""
    return db.scalar(
        select(OrganizationNumber).where(
            func.length(OrganizationNumber.first) == len(number),
            OrganizationNumber.first <= number,
            OrganizationNumber.last >= number,
        )
    )


def _validation(field: str, message: str, code: str = "validation_failed") -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code=code,
        errors=[{"field": field, "message": message}],
    )


def is_platform(principal: Principal | None) -> bool:
    """Assigning numbers is the platform's: organizations.write is platform-only."""
    return principal is None or principal.has("organizations.write")


def _org_name(db: Session, org_id: uuid.UUID) -> str:
    org = db.get(Organization, org_id)
    return org.name if org is not None else "another organization"


def check_route(db: Session, principal: Principal | None, route: InboundRoute) -> None:
    """The rules for an inbound route (docs/MULTI_TENANCY_MSP.md §4.2), checked
    on every create and change; raises a problem, or assigns the number to the
    route's organization when nobody owns it yet and the user may."""
    trunk = db.get(SipTrunk, route.trunk_id) if route.trunk_id else None
    if trunk is not None and trunk.organization_id not in (None, route.organization_id):
        raise _validation(
            "trunk_id", f"the trunk {trunk.name} is dedicated to another organization"
        )
    multi = tenancy.enabled(db)
    if route.did == routing.DID_ANY:
        dedicated = trunk is not None and trunk.organization_id == route.organization_id
        if multi and not is_platform(principal) and not dedicated:
            raise _validation(
                "did",
                "only a platform administrator can route every number of a shared trunk "
                "('any'); choose a trunk dedicated to this organization",
                code="any_needs_dedicated_trunk",
            )
        return
    number = maybe_canonical(route.did)
    if number is None:
        raise _validation("did", "not a number Veyra can route")
    elsewhere = db.scalar(
        select(InboundRoute.id).where(
            InboundRoute.did_canonical == route.did_canonical,
            InboundRoute.organization_id != route.organization_id,
        )
    )
    if elsewhere is not None:
        raise conflict(
            f"{route.did} is already routed by another organization.", "did_in_use_elsewhere"
        )
    held = owner_of(db, number)
    if held is not None and held.organization_id != route.organization_id:
        raise conflict(
            f"{route.did} belongs to {_org_name(db, held.organization_id)}, not to this "
            "organization.",
            "number_not_owned",
        )
    if held is not None:
        if held.trunk_id is not None and route.trunk_id not in (None, held.trunk_id):
            raise _validation("trunk_id", f"{route.did} arrives only on its own trunk")
        return
    if multi and not is_platform(principal):
        raise _validation(
            "did",
            f"{route.did} is not one of this organization's numbers; a platform "
            "administrator assigns numbers under Organizations",
            code="number_not_assigned",
        )
    db.add(
        OrganizationNumber(
            id=uuid.uuid4(),
            organization_id=route.organization_id,
            first=number,
            last=number,
            source="auto",
            created_at=utcnow(),
            created_by=principal.label if principal is not None else "system",
        )
    )


@dataclass(frozen=True)
class Conflict:
    route_id: uuid.UUID
    did: str
    route_organization_id: uuid.UUID
    owner_organization_id: uuid.UUID


def conflicts(db: Session) -> list[Conflict]:
    """Inbound routes for a number another organization owns. The engine
    skips them (the owner's route works); a platform administrator decides."""
    rows = db.scalars(select(OrganizationNumber)).all()
    out = []
    for r in db.scalars(select(InboundRoute).where(InboundRoute.did != routing.DID_ANY)):
        number = maybe_canonical(r.did)
        if number is None:
            continue
        owner = next((n for n in rows if in_range(number, n.first, n.last)), None)
        if owner is not None and owner.organization_id != r.organization_id:
            out.append(Conflict(r.id, r.did, r.organization_id, owner.organization_id))
    return out


# ------------------------------------------------------------------ caller ID


def _cid_error(field: str, message: str) -> ProblemError:
    return _validation(field, message, code="caller_id_not_allowed")


def _allow_list(org: Organization | None) -> set[str]:
    return {
        n
        for raw in (org.caller_id_allow_list if org else None) or []
        if (n := maybe_canonical(str(raw)))
    }


def owns(db: Session, organization_id: uuid.UUID, number: str | None) -> bool:
    """``number`` (any form) is one of the organization's inventory numbers."""
    n = maybe_canonical(number)
    held = owner_of(db, n) if n else None
    return held is not None and held.organization_id == organization_id


def check_caller_id(
    db: Session,
    principal: Principal | None,
    organization_id: uuid.UUID,
    number: str | None,
    *,
    field: str = "outbound_caller_id_number",
    emergency: bool = False,
) -> None:
    """A caller ID an extension presents (docs/MULTI_TENANCY_MSP.md §5.1).

    With multi-tenancy on: one of the organization's numbers, or for an
    outbound caller ID also its allow list; only platform administrators may
    set any number. An emergency caller ID must be an inventory number, so
    the 911 centre's callback rings here. With it off: today's rule
    (docs/CALL_FEATURES.md §3.5)."""
    if not number:
        return
    org = db.get(Organization, organization_id)
    if not tenancy.enabled(db):
        if emergency or principal is None or principal.has("routing.write", organization_id):
            return
        wanted = routing.canonical_did(number)
        dids = {
            d
            for d in db.scalars(
                select(InboundRoute.did_canonical).where(
                    InboundRoute.organization_id == organization_id
                )
            )
            if d != routing.DID_ANY
        }
        allowed = set()
        for raw in (org.caller_id_allow_list if org else None) or []:
            try:
                allowed.add(routing.canonical_did(str(raw)))
            except ValueError:
                continue
        if wanted in dids or wanted in allowed:
            return
        raise _cid_error(
            field,
            "The number is not one of the organization's numbers (inbound routes) and is not "
            "on its caller ID allow list.",
        )
    if is_platform(principal) or owns(db, organization_id, number):
        return
    if not emergency and maybe_canonical(number) in _allow_list(org):
        return
    raise _cid_error(
        field,
        "The number is not one of this organization's numbers"
        + ("." if emergency else " and is not on its caller ID allow list.")
        + " A platform administrator assigns numbers under Organizations.",
    )


def check_owned(db: Session, organization_id: uuid.UUID, number: str | None, field: str) -> None:
    """Numbers that must be the organization's own while multi-tenancy is on,
    whoever sets them: a site's ELIN, an organization's main number."""
    if number and tenancy.enabled(db) and not owns(db, organization_id, number):
        raise _cid_error(field, "The number is not one of this organization's numbers.")


def check_route_caller_id(
    db: Session, organization_id: uuid.UUID | None, number: str | None
) -> None:
    """An outbound route's caller ID while multi-tenancy is on: a route for
    one organization presents one of its numbers; a route for every
    organization presents none, or it would send one customer's number on
    every customer's calls (docs/MULTI_TENANCY_MSP.md §5.2)."""
    if not number or not tenancy.enabled(db):
        return
    if organization_id is None:
        raise _cid_error(
            "caller_id_number",
            "A route for every organization cannot set a caller ID while several "
            "organizations share the server; each call presents its own organization's number.",
        )
    org = db.get(Organization, organization_id)
    if owns(db, organization_id, number) or maybe_canonical(number) in _allow_list(org):
        return
    raise _cid_error("caller_id_number", "The number is not one of this organization's numbers.")


def main_number_rows(db: Session) -> dict[uuid.UUID, str]:
    return {
        o.id: o.main_number
        for o in db.scalars(select(Organization).where(Organization.main_number.is_not(None)))
        if o.main_number
    }
