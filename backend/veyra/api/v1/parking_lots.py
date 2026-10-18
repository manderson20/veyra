# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parking lots (docs/CALL_FEATURES.md §4.7): a park extension, a range of
slots with BLF hints, a timeout that returns the call to the parker and then
a destination. One organization per lot; the numbers live in its number space."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import destinations
from veyra.api.v1 import group_helpers as helpers
from veyra.api.v1.destinations import DestinationIn, DestinationOut, Resolver, check_destination
from veyra.api.v1.group_helpers import READ, WRITE
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, not_found
from veyra.core.events import Event, bus
from veyra.core.models import ParkingLot
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import routing
from veyra.telephony.numbering import number_owner

router = APIRouter(prefix="/parking-lots", tags=["parking-lots"])

MAX_SLOTS = 50


def _validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


# ----------------------------------------------------------------- schemas


class ParkingLotIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    park_exten: str = Field(min_length=1, max_length=32)
    slot_first: int = Field(ge=1, le=99999999)
    slot_last: int = Field(ge=1, le=99999999)
    timeout_seconds: int = Field(45, ge=10, le=1800)
    return_ring_seconds: int = Field(20, ge=5, le=120)
    courtesy_tone: bool = True
    timeout: DestinationIn = Field(default_factory=lambda: DestinationIn(type="hangup"))
    is_enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        routing.slugify(v)
        return v

    @field_validator("park_exten")
    @classmethod
    def _park(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[0-9]{1,32}", v):
            raise ValueError("digits only")
        return v

    @model_validator(mode="after")
    def _range(self) -> ParkingLotIn:
        if self.slot_last < self.slot_first:
            raise ValueError("the last slot must not be below the first")
        if self.slot_last - self.slot_first + 1 > MAX_SLOTS:
            raise ValueError(f"at most {MAX_SLOTS} slots")
        if self.slot_first <= int(self.park_exten) <= self.slot_last:
            raise ValueError("the park extension must lie outside the slots")
        return self


class ParkingLotPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    park_exten: str | None = Field(None, min_length=1, max_length=32)
    slot_first: int | None = Field(None, ge=1, le=99999999)
    slot_last: int | None = Field(None, ge=1, le=99999999)
    timeout_seconds: int | None = Field(None, ge=10, le=1800)
    return_ring_seconds: int | None = Field(None, ge=5, le=120)
    courtesy_tone: bool | None = None
    timeout: DestinationIn | None = None
    is_enabled: bool | None = None


class ParkingLotOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    slug: str
    context: str
    description: str | None
    park_exten: str
    slot_first: int
    slot_last: int
    slots: list[str]
    timeout_seconds: int
    return_ring_seconds: int
    courtesy_tone: bool
    timeout: DestinationOut
    is_enabled: bool
    problems: list[str]
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------- helpers


def _outs(db: Session, rows: list[ParkingLot]) -> list[ParkingLotOut]:
    if not rows:
        return []
    orgs = helpers.org_names(db, {r.organization_id for r in rows})
    resolver = Resolver(db)
    resolver.load([destinations.ref_of(r, "timeout") for r in rows])
    out = []
    for r in rows:
        timeout = resolver.out_ref(destinations.ref_of(r, "timeout"))
        problems = []
        if timeout.missing:
            problems.append("The timeout destination no longer exists.")
        out.append(
            ParkingLotOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=orgs.get(r.organization_id, ""),
                name=r.name,
                slug=r.slug,
                context=f"veyra-park-{r.slug}",
                description=r.description,
                park_exten=r.park_exten,
                slot_first=r.slot_first,
                slot_last=r.slot_last,
                slots=[str(n) for n in range(r.slot_first, r.slot_last + 1)],
                timeout_seconds=r.timeout_seconds,
                return_ring_seconds=r.return_ring_seconds,
                courtesy_tone=r.courtesy_tone,
                timeout=timeout,
                is_enabled=r.is_enabled,
                problems=problems,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _get(db: Session, principal: Principal, lot_id: uuid.UUID, perm: str) -> ParkingLot:
    stmt = helpers.org_filter(select(ParkingLot), ParkingLot.organization_id, principal, perm)
    row = db.scalar(stmt.where(ParkingLot.id == lot_id))
    if row is None:
        raise not_found("Parking lot")
    return row


def _check(
    db: Session, org_id: uuid.UUID, body: ParkingLotIn, self_id: uuid.UUID | None = None
) -> None:
    """Every number of the lot must be free in the organization. Parking numbers
    are short by convention (70, 71-79) and need not fit the extension length
    of the numbering plan."""
    numbers = [body.park_exten] + [str(n) for n in range(body.slot_first, body.slot_last + 1)]
    for number in numbers:
        field = "park_exten" if number == body.park_exten else "slot_first"
        owner = number_owner(
            db,
            number,
            organization_id=org_id,
            exclude=("parking lot", self_id) if self_id else None,
        )
        if owner is not None:
            raise ProblemError(
                409,
                "Number in use",
                f"{owner.capitalize()} {number} already exists.",
                code="number_in_use",
                errors=[{"field": field, "message": f"{number} is already used by a {owner}"}],
            )
    check_destination(db, org_id, body.timeout, field="timeout", allow_hangup=True)


def _name_conflict() -> Exception:
    return conflict("A parking lot with that name exists in this organization.", "name_in_use")


# ----------------------------------------------------------------- routes


@router.get("", response_model=Page[ParkingLotOut], summary="List parking lots")
def list_lots(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[ParkingLotOut]:
    stmt = helpers.org_filter(
        select(ParkingLot), ParkingLot.organization_id, principal, READ
    ).order_by(ParkingLot.park_exten)
    if organization_id:
        stmt = stmt.where(ParkingLot.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                ParkingLot.name.ilike(like),
                ParkingLot.park_exten.ilike(like),
                ParkingLot.description.ilike(like),
            )
        )
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post("", response_model=ParkingLotOut, status_code=201, summary="Create a parking lot")
def create_lot(
    body: ParkingLotIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ParkingLotOut:
    org = helpers.org_for_write(db, principal, body.organization_id)
    _check(db, org.id, body)
    lot = ParkingLot(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=body.name,
        slug=helpers.unique_slug(db, ParkingLot, body.name),
        description=(body.description or "").strip() or None,
        park_exten=body.park_exten,
        slot_first=body.slot_first,
        slot_last=body.slot_last,
        timeout_seconds=body.timeout_seconds,
        return_ring_seconds=body.return_ring_seconds,
        courtesy_tone=body.courtesy_tone,
        is_enabled=body.is_enabled,
    )
    destinations.apply(lot, "timeout", body.timeout)
    db.add(lot)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise _name_conflict() from e
    helpers.record(
        db,
        ctx,
        principal,
        "parking_lot.create",
        target_type="parking_lot",
        target=lot,
        details={
            "slug": lot.slug,
            "park_exten": lot.park_exten,
            "slots": f"{lot.slot_first}-{lot.slot_last}",
        },
    )
    db.commit()
    bus.publish(Event("parking_lot.created", {"id": str(lot.id), "name": lot.name}))
    return _outs(db, [lot])[0]


@router.get("/{lot_id}", response_model=ParkingLotOut)
def get_lot(
    lot_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> ParkingLotOut:
    return _outs(db, [_get(db, principal, lot_id, READ)])[0]


@router.patch("/{lot_id}", response_model=ParkingLotOut)
def update_lot(
    lot_id: uuid.UUID,
    body: ParkingLotPatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ParkingLotOut:
    lot = _get(db, principal, lot_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    current = {
        "organization_id": lot.organization_id,
        "name": lot.name,
        "description": lot.description,
        "park_exten": lot.park_exten,
        "slot_first": lot.slot_first,
        "slot_last": lot.slot_last,
        "timeout_seconds": lot.timeout_seconds,
        "return_ring_seconds": lot.return_ring_seconds,
        "courtesy_tone": lot.courtesy_tone,
        "timeout": destinations.as_input(destinations.ref_of(lot, "timeout")),
        "is_enabled": lot.is_enabled,
    }
    try:
        validated = ParkingLotIn.model_validate({**current, **changes})
    except ValueError as e:
        raise _validation("parking_lot", str(e).splitlines()[0]) from e
    _check(db, lot.organization_id, validated, self_id=lot.id)
    details: dict[str, Any] = {}
    if validated.name != lot.name:
        details["name"] = {"from": lot.name, "to": validated.name}
        lot.name = validated.name
    desc = (validated.description or "").strip() or None
    if desc != lot.description:
        lot.description = desc
        details["description"] = True
    for field in (
        "park_exten",
        "slot_first",
        "slot_last",
        "timeout_seconds",
        "return_ring_seconds",
        "courtesy_tone",
        "is_enabled",
    ):
        value = getattr(validated, field)
        if value != getattr(lot, field):
            setattr(lot, field, value)
            details[field] = str(value)
    if destinations.ref_of(lot, "timeout") != validated.timeout.as_ref():
        destinations.apply(lot, "timeout", validated.timeout)
        details["timeout"] = validated.timeout.model_dump(mode="json")
    if not details:
        return _outs(db, [lot])[0]
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise _name_conflict() from e
    helpers.record(
        db,
        ctx,
        principal,
        "parking_lot.update",
        target_type="parking_lot",
        target=lot,
        details=details,
    )
    db.commit()
    bus.publish(Event("parking_lot.updated", {"id": str(lot.id)}))
    return _outs(db, [lot])[0]


@router.delete("/{lot_id}", status_code=204)
def delete_lot(
    lot_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    lot = _get(db, principal, lot_id, WRITE)
    helpers.record(
        db,
        ctx,
        principal,
        "parking_lot.delete",
        target_type="parking_lot",
        target=lot,
        details={"slug": lot.slug, "park_exten": lot.park_exten},
    )
    db.delete(lot)
    db.commit()
    bus.publish(Event("parking_lot.deleted", {"id": str(lot_id)}))
    return Response(status_code=204)
