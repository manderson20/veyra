# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outside line access, known elsewhere as DISA (issue #392): a caller from
outside enters a PIN and dials out with a chosen class of service and caller
ID. It carries toll-fraud risk, so a PIN is required, weak ones are refused,
and it takes the routing permission."""

from __future__ import annotations

import itertools
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import destinations
from veyra.api.v1 import group_helpers as helpers
from veyra.api.v1.extensions import installation_key
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import conflict, not_found
from veyra.core.models import ClassOfService, DisaLine
from veyra.core.security.principal import Principal
from veyra.telephony import routing
from veyra.telephony.snapshot import disa_pin_purpose

router = APIRouter(prefix="/disa", tags=["disa"])

READ = "routing.read"
WRITE = "routing.write"
_PIN_RE = re.compile(r"^[0-9]{6,10}$")
_NUMBER_RE = re.compile(r"^\+?[0-9]{3,20}$")


def _check_pin(pin: str) -> str:
    """Six or more digits, not one digit repeated or a run up or down."""
    pin = pin.strip()
    if not _PIN_RE.match(pin):
        raise ValueError("6 to 10 digits")
    steps = {int(b) - int(a) for a, b in itertools.pairwise(pin)}
    if steps <= {0} or steps <= {1} or steps <= {-1}:
        raise ValueError("too easy to guess; don't use a repeated digit or a run of digits")
    return pin


def _check_number(number: str) -> str:
    number = number.strip()
    if not _NUMBER_RE.match(number):
        raise ValueError("enter a phone number")
    return number


class DisaIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    pin: str
    class_of_service_id: uuid.UUID
    caller_id_number: str
    is_enabled: bool = True

    @field_validator("pin")
    @classmethod
    def _pin(cls, v: str) -> str:
        return _check_pin(v)

    @field_validator("caller_id_number")
    @classmethod
    def _number(cls, v: str) -> str:
        return _check_number(v)


class DisaPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    pin: str | None = None
    class_of_service_id: uuid.UUID | None = None
    caller_id_number: str | None = None
    is_enabled: bool | None = None

    @field_validator("pin")
    @classmethod
    def _pin(cls, v: str | None) -> str | None:
        return _check_pin(v) if v is not None else None

    @field_validator("caller_id_number")
    @classmethod
    def _number(cls, v: str | None) -> str | None:
        return _check_number(v) if v is not None else None


class DisaOut(BaseModel):
    """The PIN is never returned."""

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    class_of_service_id: uuid.UUID
    class_of_service_name: str
    caller_id_number: str
    is_enabled: bool
    in_use_by: list[str]
    created_at: datetime
    updated_at: datetime


def _out(db: Session, row: DisaLine) -> DisaOut:
    cos = db.get(ClassOfService, row.class_of_service_id)
    return DisaOut(
        id=row.id,
        organization_id=row.organization_id,
        name=row.name,
        slug=row.slug,
        class_of_service_id=row.class_of_service_id,
        class_of_service_name=cos.name if cos else "",
        caller_id_number=row.caller_id_number,
        is_enabled=row.is_enabled,
        in_use_by=destinations.describe_uses(db, "disa", row.slug),  # type: ignore[arg-type]
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _get(db: Session, principal: Principal, line_id: uuid.UUID, perm: str) -> DisaLine:
    row = db.scalar(
        helpers.org_filter(select(DisaLine), DisaLine.organization_id, principal, perm).where(
            DisaLine.id == line_id
        )
    )
    if row is None:
        raise not_found("Outside line access")
    return row


def _check_class(db: Session, org_id: uuid.UUID, cos_id: uuid.UUID) -> None:
    cos = db.get(ClassOfService, cos_id)
    if cos is None or cos.organization_id != org_id:
        raise destinations.validation(
            "class_of_service_id", "class of service not found in this organization"
        )


@router.get("", response_model=list[DisaOut], summary="List outside line access")
def list_lines(
    organization_id: uuid.UUID | None = Query(None),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> list[DisaOut]:
    stmt = helpers.org_filter(select(DisaLine), DisaLine.organization_id, principal, READ)
    if organization_id:
        stmt = stmt.where(DisaLine.organization_id == organization_id)
    return [_out(db, r) for r in db.scalars(stmt.order_by(DisaLine.name))]


@router.post("", response_model=DisaOut, status_code=201, summary="Add outside line access")
def create_line(
    body: DisaIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> DisaOut:
    org = helpers.org_for_write(db, principal, body.organization_id)
    _check_class(db, org.id, body.class_of_service_id)
    routing.slugify(body.name)
    line_id = uuid.uuid4()
    row = DisaLine(
        id=line_id,
        organization_id=org.id,
        name=body.name.strip(),
        slug=helpers.unique_slug(db, DisaLine, body.name),
        pin_ciphertext=installation_key(request).encrypt(body.pin, disa_pin_purpose(line_id)),
        class_of_service_id=body.class_of_service_id,
        caller_id_number=body.caller_id_number,
        is_enabled=body.is_enabled,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as e:
        raise conflict("That name is already in use.", "disa_name_in_use") from e
    helpers.record(
        db,
        ctx,
        principal,
        "disa.create",
        target_type="disa",
        target=row,
        details={"caller_id_number": row.caller_id_number},
    )
    db.commit()
    return _out(db, row)


@router.patch("/{line_id}", response_model=DisaOut, summary="Change outside line access")
def update_line(
    line_id: uuid.UUID,
    body: DisaPatch,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> DisaOut:
    row = _get(db, principal, line_id, WRITE)
    details: dict[str, str] = {}
    if body.class_of_service_id is not None:
        _check_class(db, row.organization_id, body.class_of_service_id)
        row.class_of_service_id = body.class_of_service_id
        details["class_of_service_id"] = str(body.class_of_service_id)
    if body.name is not None:
        row.name = body.name.strip()
        details["name"] = row.name
    if body.caller_id_number is not None:
        row.caller_id_number = body.caller_id_number
        details["caller_id_number"] = row.caller_id_number
    if body.is_enabled is not None:
        if not body.is_enabled:
            uses = destinations.describe_uses(db, "disa", row.slug)  # type: ignore[arg-type]
            if uses:
                raise conflict(f"In use by {', '.join(uses)}.", "disa_in_use")
        row.is_enabled = body.is_enabled
        details["is_enabled"] = str(body.is_enabled)
    if body.pin is not None:
        row.pin_ciphertext = installation_key(request).encrypt(body.pin, disa_pin_purpose(row.id))
        details["pin"] = "changed"
    try:
        db.flush()
    except IntegrityError as e:
        raise conflict("That name is already in use.", "disa_name_in_use") from e
    helpers.record(
        db, ctx, principal, "disa.update", target_type="disa", target=row, details=details
    )
    db.commit()
    return _out(db, row)


@router.delete("/{line_id}", status_code=204, summary="Delete outside line access")
def delete_line(
    line_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    row = _get(db, principal, line_id, WRITE)
    uses = destinations.describe_uses(db, "disa", row.slug)  # type: ignore[arg-type]
    if uses:
        raise conflict(f"In use by {', '.join(uses)}.", "disa_in_use")
    helpers.record(db, ctx, principal, "disa.delete", target_type="disa", target=row, details={})
    db.delete(row)
    db.commit()
    return Response(status_code=204)
