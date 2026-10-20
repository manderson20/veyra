# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dial-by-name directory's own entries and operator (docs/CALL_FEATURES.md
§4.2; issue #135). People with a voicemail box are listed by themselves;
these entries add names such as "Front office" for a ring group or "Nurse"
for an extension, and the operator is where 0 goes."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.configmgmt import service as configmgmt
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.models import DirectoryEntry, DirectorySettings, Organization
from veyra.core.security.principal import Principal
from veyra.telephony.numbering import number_owner

router = APIRouter(prefix="/name-directory", tags=["call flow"])

READ = "ivr.read"
WRITE = "ivr.write"
MAX_ENTRIES = 500
# The name the caller spells; letters, digits and simple punctuation.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .'&()/-]{0,99}$")


def _validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


def _number(db: Session, org_id: uuid.UUID, value: str | None, field: str) -> str | None:
    """A number of the organization (extension, group, queue, room…), or none."""
    v = (value or "").strip()
    if not v:
        return None
    if not v.isdigit() or len(v) > 32:
        raise _validation(field, "an internal number (digits)")
    if number_owner(db, v, organization_id=org_id) is None:
        raise _validation(field, f"{v} is not a number of this organization")
    return v


class EntryIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    number: str = Field(min_length=1, max_length=32)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not _NAME_RE.match(v):
            raise ValueError("letters, digits, spaces and . ' & ( ) / -")
        return v


class EntryPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    number: str | None = Field(None, min_length=1, max_length=32)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return EntryIn._name(v) if v is not None else None


class EntryOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    number: str
    created_at: datetime
    updated_at: datetime


class DirectoryOut(BaseModel):
    organization_id: uuid.UUID
    operator_number: str | None
    entries: list[EntryOut]


class OperatorIn(BaseModel):
    organization_id: uuid.UUID
    operator_number: str | None = Field(None, max_length=32)


def _org(db: Session, principal: Principal, org_id: uuid.UUID, perm: str) -> Organization:
    org = db.get(Organization, org_id)
    if org is None or not principal.has(READ, org.id):
        raise not_found("Organization")
    if not principal.has(perm, org.id):
        raise forbidden()
    return org


def _out(e: DirectoryEntry) -> EntryOut:
    return EntryOut(
        id=e.id,
        organization_id=e.organization_id,
        name=e.name,
        number=e.number,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


def _changed(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    org: Organization,
    action: str,
    details: dict[str, object],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=org.id,
        target_type="organization",
        target_id=org.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=details,
    )
    configmgmt.mark_changed(db, by=principal.label, what=f"{action} {org.slug}")


@router.get("", response_model=DirectoryOut, summary="The directory's entries and operator")
def get_directory(
    organization_id: uuid.UUID = Query(...),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> DirectoryOut:
    org = _org(db, principal, organization_id, READ)
    settings = db.get(DirectorySettings, org.id)
    rows = db.scalars(
        select(DirectoryEntry)
        .where(DirectoryEntry.organization_id == org.id)
        .order_by(func.lower(DirectoryEntry.name))
    ).all()
    return DirectoryOut(
        organization_id=org.id,
        operator_number=settings.operator_number if settings else None,
        entries=[_out(e) for e in rows],
    )


@router.put("/operator", response_model=DirectoryOut, summary="Where 0 goes in the directory")
def set_operator(
    body: OperatorIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> DirectoryOut:
    org = _org(db, principal, body.organization_id, WRITE)
    number = _number(db, org.id, body.operator_number, "operator_number")
    row = db.get(DirectorySettings, org.id)
    if row is None:
        row = DirectorySettings(organization_id=org.id, operator_number=number)
        db.add(row)
    elif row.operator_number != number:
        row.operator_number = number
    _changed(db, ctx, principal, org, "directory.operator", {"operator_number": number})
    db.commit()
    return get_directory(org.id, principal, db)


@router.post("/entries", response_model=EntryOut, status_code=201, summary="Add a directory name")
def create_entry(
    body: EntryIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> EntryOut:
    org = _org(db, principal, body.organization_id, WRITE)
    number = _number(db, org.id, body.number, "number")
    assert number is not None
    count = db.scalar(
        select(func.count())
        .select_from(DirectoryEntry)
        .where(DirectoryEntry.organization_id == org.id)
    )
    if (count or 0) >= MAX_ENTRIES:
        raise conflict(f"At most {MAX_ENTRIES} directory names.", "too_many_entries")
    row = DirectoryEntry(id=uuid.uuid4(), organization_id=org.id, name=body.name, number=number)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(f"The directory already has {body.name}.", "name_in_use") from e
    _changed(
        db, ctx, principal, org, "directory.entry_create", {"name": row.name, "number": number}
    )
    db.commit()
    return _out(row)


def _entry(
    db: Session, principal: Principal, entry_id: uuid.UUID
) -> tuple[DirectoryEntry, Organization]:
    row = db.get(DirectoryEntry, entry_id)
    if row is None:
        raise not_found("Directory name")
    return row, _org(db, principal, row.organization_id, WRITE)


@router.patch("/entries/{entry_id}", response_model=EntryOut)
def update_entry(
    entry_id: uuid.UUID,
    body: EntryPatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> EntryOut:
    row, org = _entry(db, principal, entry_id)
    if body.name is not None:
        row.name = body.name
    if body.number is not None:
        row.number = _number(db, org.id, body.number, "number") or row.number
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(f"The directory already has {body.name}.", "name_in_use") from e
    _changed(
        db, ctx, principal, org, "directory.entry_update", {"name": row.name, "number": row.number}
    )
    db.commit()
    return _out(row)


@router.delete("/entries/{entry_id}", status_code=204)
def delete_entry(
    entry_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    row, org = _entry(db, principal, entry_id)
    _changed(db, ctx, principal, org, "directory.entry_delete", {"name": row.name})
    db.delete(row)
    db.commit()
    return Response(status_code=204)
