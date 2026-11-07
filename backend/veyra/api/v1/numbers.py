# SPDX-License-Identifier: AGPL-3.0-or-later
"""The number inventory (docs/MULTI_TENANCY_MSP.md §4): the numbers and
blocks assigned to each organization. Platform administrators assign them;
an organization's administrators read their own."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.configmgmt import service as configmgmt
from veyra.core import audit, numbers
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, not_found
from veyra.core.models import InboundRoute, Organization, OrganizationNumber, SipTrunk
from veyra.core.models.base import utcnow
from veyra.core.security.principal import Principal
from veyra.telephony import routing

router = APIRouter(tags=["numbers"])


class NumberIn(BaseModel):
    first: str = Field(min_length=2, max_length=24)
    # The last number of a block; empty: just ``first``.
    last: str | None = Field(None, max_length=24)
    trunk_id: uuid.UUID | None = None
    label: str | None = Field(None, max_length=100)

    @field_validator("first", "last")
    @classmethod
    def _number(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return numbers.canonical(v)


class NumberOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    first: str
    last: str
    count: int
    trunk_id: uuid.UUID | None
    trunk_name: str | None = None
    label: str | None
    source: str
    routed: int = 0
    created_at: datetime
    created_by: str


class ConflictOut(BaseModel):
    route_id: uuid.UUID
    did: str
    route_organization_id: uuid.UUID
    route_organization_name: str
    owner_organization_id: uuid.UUID
    owner_organization_name: str


def _validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


def _outs(db: Session, rows: list[OrganizationNumber]) -> list[NumberOut]:
    trunk_names = {t.id: t.name for t in db.scalars(select(SipTrunk))}
    routes = [
        (r.organization_id, n)
        for r in db.scalars(select(InboundRoute).where(InboundRoute.did != routing.DID_ANY))
        if (n := numbers.maybe_canonical(r.did)) is not None
    ]
    return [
        NumberOut(
            id=row.id,
            organization_id=row.organization_id,
            first=row.first,
            last=row.last,
            count=int(row.last) - int(row.first) + 1,
            trunk_id=row.trunk_id,
            trunk_name=trunk_names.get(row.trunk_id) if row.trunk_id else None,
            label=row.label,
            source=row.source,
            routed=sum(
                1
                for org, n in routes
                if org == row.organization_id and numbers.in_range(n, row.first, row.last)
            ),
            created_at=row.created_at,
            created_by=row.created_by,
        )
        for row in rows
    ]


def _org(db: Session, organization_id: uuid.UUID) -> Organization:
    org = db.get(Organization, organization_id)
    if org is None:
        raise not_found("Organization")
    return org


@router.get(
    "/organizations/{organization_id}/numbers",
    response_model=list[NumberOut],
    summary="The organization's numbers",
)
def list_numbers(
    organization_id: uuid.UUID,
    principal: Principal = Depends(require("routing.read")),
    db: Session = Depends(get_db),
) -> list[NumberOut]:
    if not principal.has("routing.read", organization_id):
        raise not_found("Organization")
    _org(db, organization_id)
    rows = db.scalars(
        select(OrganizationNumber)
        .where(OrganizationNumber.organization_id == organization_id)
        .order_by(OrganizationNumber.first)
    ).all()
    return _outs(db, list(rows))


@router.post(
    "/organizations/{organization_id}/numbers",
    response_model=NumberOut,
    status_code=201,
    summary="Assign a number or a block of numbers",
)
def add_number(
    organization_id: uuid.UUID,
    body: NumberIn,
    principal: Principal = Depends(require("organizations.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> NumberOut:
    org = _org(db, organization_id)
    first, last = body.first, body.last or body.first
    if len(first) != len(last) or last < first:
        raise _validation("last", "the last number must have as many digits and come after")
    if int(last) - int(first) + 1 > numbers.MAX_RANGE:
        raise _validation("last", f"at most {numbers.MAX_RANGE} numbers in one block")
    trunk = db.get(SipTrunk, body.trunk_id) if body.trunk_id else None
    if body.trunk_id and trunk is None:
        raise _validation("trunk_id", "trunk not found")
    if trunk is not None and trunk.organization_id not in (None, org.id):
        raise _validation("trunk_id", f"the trunk {trunk.name} is another organization's")
    for n in (first, last):
        held = numbers.owner_of(db, n)
        if held is not None:
            whose = db.get(Organization, held.organization_id)
            raise conflict(
                f"{n} is already assigned to {whose.name if whose else 'an organization'}.",
                "number_assigned",
            )
    row = OrganizationNumber(
        id=uuid.uuid4(),
        organization_id=org.id,
        first=first,
        last=last,
        trunk_id=body.trunk_id,
        label=(body.label or "").strip() or None,
        source="manual",
        created_at=utcnow(),
        created_by=principal.label,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as e:  # a block that covers another
        db.rollback()
        raise conflict(
            "Part of that block is already assigned to an organization.", "number_assigned"
        ) from e
    audit.record(
        db,
        action="organization.number_add",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=org.id,
        target_type="organization_number",
        target_id=row.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"first": first, "last": last, "trunk_id": str(body.trunk_id or "") or None},
    )
    # Routes skipped as conflicts may now route.
    configmgmt.mark_changed(db, by=principal.label, what=f"numbers of {org.slug}")
    db.commit()
    return _outs(db, [row])[0]


@router.delete(
    "/organizations/{organization_id}/numbers/{number_id}",
    status_code=204,
    summary="Withdraw a number or block",
)
def remove_number(
    organization_id: uuid.UUID,
    number_id: uuid.UUID,
    principal: Principal = Depends(require("organizations.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> None:
    row = db.get(OrganizationNumber, number_id)
    if row is None or row.organization_id != organization_id:
        raise not_found("Number")
    used = [
        r.did
        for r in db.scalars(
            select(InboundRoute).where(
                InboundRoute.organization_id == organization_id,
                InboundRoute.did != routing.DID_ANY,
            )
        )
        if (n := numbers.maybe_canonical(r.did)) and numbers.in_range(n, row.first, row.last)
    ]
    if used:
        raise conflict(
            "Inbound routes still use " + ", ".join(sorted(used)[:10]) + ". Remove them first.",
            "number_in_use",
        )
    db.delete(row)
    audit.record(
        db,
        action="organization.number_remove",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=organization_id,
        target_type="organization_number",
        target_id=number_id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"first": row.first, "last": row.last},
    )
    db.commit()


@router.get(
    "/numbers/conflicts",
    response_model=list[ConflictOut],
    summary="Routes for a number another organization owns",
)
def list_conflicts(
    principal: Principal = Depends(require("organizations.write")),
    db: Session = Depends(get_db),
) -> list[ConflictOut]:
    names = {o.id: o.name for o in db.scalars(select(Organization))}
    return [
        ConflictOut(
            route_id=c.route_id,
            did=c.did,
            route_organization_id=c.route_organization_id,
            route_organization_name=names.get(c.route_organization_id, ""),
            owner_organization_id=c.owner_organization_id,
            owner_organization_name=names.get(c.owner_organization_id, ""),
        )
        for c in numbers.conflicts(db)
    ]
