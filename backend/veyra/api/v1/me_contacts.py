# SPDX-License-Identifier: AGPL-3.0-or-later
"""Personal contacts and speed dials of the signed-in user
(docs/USER_PORTAL.md §6): the ``me`` scope, own rows only, audited."""

from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import String, func, or_, select
from sqlalchemy.orm import Session

from veyra.api.v1.me import require_me
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context
from veyra.core.errors import ProblemError, not_found
from veyra.core.models import UserContact
from veyra.core.security.principal import Principal

router = APIRouter(prefix="/me/contacts", tags=["me"])

MAX_CONTACTS = 500
MAX_NUMBERS = 5
MAX_IMPORT_LINES = 1000
LABELS = ("work", "mobile", "home", "other")
_NUMBER_RE = re.compile(r"^\+?[0-9*#]{2,32}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_number(value: str) -> str:
    text = re.sub(r"[\s().-]", "", str(value or ""))
    if not _NUMBER_RE.match(text):
        raise ValueError("digits (and a leading +) only, 2 to 32 characters")
    return text


class ContactNumber(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["work", "mobile", "home", "other"] = "work"
    number: str = Field(min_length=1, max_length=40)

    @field_validator("number")
    @classmethod
    def _number(cls, v: str) -> str:
        return clean_number(v)


class ContactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    company: str | None = Field(None, max_length=100)
    numbers: list[ContactNumber] = Field(default_factory=list, max_length=MAX_NUMBERS)
    email: str | None = Field(None, max_length=254)
    favourite: bool = False
    speed_dial: int | None = Field(None, ge=1, le=99)
    notes: str | None = Field(None, max_length=2000)

    @field_validator("name", "company", "email", "notes")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str:
        if not v:
            raise ValueError("a name is required")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        if v and not _EMAIL_RE.match(v):
            raise ValueError("not a valid email address")
        return v.lower() if v else None

    @model_validator(mode="after")
    def _at_least_one_way(self) -> ContactIn:
        if not self.numbers and not self.email:
            raise ValueError("a contact needs a number or an email address")
        return self


class ContactPatch(BaseModel):
    """Any subset of a contact's fields; a missing field is left as it is."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=100)
    company: str | None = Field(None, max_length=100)
    numbers: list[ContactNumber] | None = Field(None, max_length=MAX_NUMBERS)
    email: str | None = Field(None, max_length=254)
    favourite: bool | None = None
    speed_dial: int | None = Field(None, ge=1, le=99)
    notes: str | None = Field(None, max_length=2000)

    @field_validator("company", "email", "notes")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("a name is required")
        return v.strip() if v else v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        if v and not _EMAIL_RE.match(v):
            raise ValueError("not a valid email address")
        return v.lower() if v else None


class ContactOut(BaseModel):
    id: uuid.UUID
    name: str
    company: str | None
    numbers: list[ContactNumber]
    email: str | None
    favourite: bool
    speed_dial: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ImportIn(BaseModel):
    # CSV: name, company, number[, number2, number3], email, speed_dial — or
    # one "name, number" per line.
    text: str = Field(min_length=1, max_length=200_000)
    replace: bool = False


class ImportOut(BaseModel):
    added: int
    updated: int
    skipped: list[str]


def _out(row: UserContact) -> ContactOut:
    return ContactOut(
        id=row.id,
        name=row.name,
        company=row.company,
        numbers=[ContactNumber(**n) for n in (row.numbers or [])],
        email=row.email,
        favourite=bool(row.favourite),
        speed_dial=row.speed_dial,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _own(db: Session, principal: Principal, contact_id: uuid.UUID) -> UserContact:
    row = db.get(UserContact, contact_id)
    if row is None or row.user_id != principal.user_id:
        raise not_found("Contact")
    return row


def _audit(
    db: Session, ctx: RequestContext, principal: Principal, action: str, details: dict[str, Any]
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=None,
        target_type="user",
        target_id=principal.user_id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"self_service": True, **details},
    )


def _check_speed_dial(
    db: Session, principal: Principal, slot: int | None, exclude: uuid.UUID | None
) -> None:
    if slot is None:
        return
    stmt = select(UserContact.id).where(
        UserContact.user_id == principal.user_id, UserContact.speed_dial == slot
    )
    if exclude is not None:
        stmt = stmt.where(UserContact.id != exclude)
    if db.scalar(stmt) is not None:
        raise ProblemError(
            409,
            "Speed dial in use",
            f"Speed dial {slot} is already assigned to another contact.",
            code="speed_dial_in_use",
            errors=[{"field": "speed_dial", "message": "already used"}],
        )


def _count(db: Session, principal: Principal) -> int:
    stmt = select(func.count()).select_from(UserContact)
    return int(db.scalar(stmt.where(UserContact.user_id == principal.user_id)) or 0)


@router.get("", response_model=list[ContactOut], summary="Your contacts")
def list_contacts(
    q: str | None = Query(None, max_length=100),
    favourite: bool | None = None,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> list[ContactOut]:
    stmt = select(UserContact).where(UserContact.user_id == principal.user_id)
    if q:
        like = f"%{q.strip()}%"
        digits = re.sub(r"[\s().-]", "", q)
        clauses = [
            UserContact.name.ilike(like),
            UserContact.company.ilike(like),
            UserContact.email.ilike(like),
        ]
        if digits:
            clauses.append(UserContact.numbers.cast(String).ilike(f"%{digits}%"))
        stmt = stmt.where(or_(*clauses))
    if favourite is not None:
        stmt = stmt.where(UserContact.favourite.is_(favourite))
    rows = db.scalars(
        stmt.order_by(UserContact.favourite.desc(), func.lower(UserContact.name))
    ).all()
    return [_out(r) for r in rows]


@router.post("", response_model=ContactOut, status_code=201, summary="Add a contact")
def create_contact(
    body: ContactIn,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ContactOut:
    if _count(db, principal) >= MAX_CONTACTS:
        raise ProblemError(
            409, "Too many contacts", f"At most {MAX_CONTACTS} contacts.", code="too_many_contacts"
        )
    _check_speed_dial(db, principal, body.speed_dial, None)
    row = UserContact(
        user_id=principal.user_id,
        name=body.name,
        company=body.company,
        numbers=[n.model_dump() for n in body.numbers],
        email=body.email,
        favourite=body.favourite,
        speed_dial=body.speed_dial,
        notes=body.notes,
    )
    db.add(row)
    db.flush()
    _audit(db, ctx, principal, "contact.create", {"contact_id": str(row.id), "name": row.name})
    db.commit()
    db.refresh(row)
    return _out(row)


@router.get("/export.csv", summary="Your contacts as CSV")
def export_contacts(
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> Response:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["name", "company", "numbers", "email", "favourite", "speed_dial", "notes"])
    for row in db.scalars(
        select(UserContact)
        .where(UserContact.user_id == principal.user_id)
        .order_by(func.lower(UserContact.name))
    ):
        writer.writerow(
            [
                row.name,
                row.company or "",
                " ".join(f"{n.get('label')}:{n.get('number')}" for n in (row.numbers or [])),
                row.email or "",
                "yes" if row.favourite else "",
                row.speed_dial or "",
                row.notes or "",
            ]
        )
    return Response(
        out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="contacts.csv"'},
    )


@router.post("/import", response_model=ImportOut, summary="Import contacts from CSV")
def import_contacts(
    body: ImportIn,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ImportOut:
    rows = list(csv.reader(io.StringIO(body.text)))
    if len(rows) > MAX_IMPORT_LINES:
        raise ProblemError(
            422, "Too many lines", f"At most {MAX_IMPORT_LINES} lines.", code="too_many_lines"
        )
    if body.replace:
        for old in db.scalars(
            select(UserContact).where(UserContact.user_id == principal.user_id)
        ).all():
            db.delete(old)
        db.flush()
    existing = {
        r.name.lower(): r
        for r in db.scalars(select(UserContact).where(UserContact.user_id == principal.user_id))
    }
    added = updated = 0
    skipped: list[str] = []
    header_seen = False
    for i, cells in enumerate(rows, start=1):
        cells = [c.strip() for c in cells]
        if not any(cells):
            continue
        if not header_seen and cells[0].lower() == "name":
            header_seen = True
            continue
        name = cells[0] if cells else ""
        if not name:
            skipped.append(f"line {i}: no name")
            continue
        company = cells[1] if len(cells) > 1 else ""
        number_cells = cells[2:3] if len(cells) > 2 else []
        email = ""
        speed = ""
        notes = ""
        if len(cells) > 3:
            # Either "numbers email favourite speed_dial notes" (our export) or
            # a plain "name, company, number, number, number".
            rest = cells[3:]
            if _EMAIL_RE.match(rest[0]) or rest[0] == "":
                email = rest[0]
                speed = rest[2] if len(rest) > 2 else ""
                notes = rest[3] if len(rest) > 3 else ""
            else:
                number_cells += rest[:2]
        numbers: list[dict[str, str]] = []
        bad = False
        for cell in number_cells:
            for piece in cell.split():
                label, _, num = piece.rpartition(":")
                label = label if label in LABELS else "work"
                try:
                    numbers.append({"label": label, "number": clean_number(num)})
                except ValueError:
                    bad = True
        if bad or (not numbers and not email):
            skipped.append(f"line {i}: no usable number or email")
            continue
        if len(numbers) > MAX_NUMBERS:
            numbers = numbers[:MAX_NUMBERS]
        slot: int | None = None
        if speed.isdigit() and 1 <= int(speed) <= 99:
            slot = int(speed)
        row: UserContact | None = existing.get(name.lower())
        if row is None:
            if len(existing) + added >= MAX_CONTACTS:
                skipped.append(f"line {i}: contact limit reached")
                continue
            row = UserContact(user_id=principal.user_id, name=name, numbers=[], favourite=False)
            db.add(row)
            existing[name.lower()] = row
            added += 1
        else:
            updated += 1
        row.company = company or None
        row.numbers = numbers
        row.email = email.lower() or None
        if slot is not None:
            try:
                _check_speed_dial(db, principal, slot, row.id if row.id else None)
                row.speed_dial = slot
            except ProblemError:
                skipped.append(f"line {i}: speed dial {slot} already used")
        row.notes = notes or None
        db.flush()
    _audit(
        db,
        ctx,
        principal,
        "contact.import",
        {"added": added, "updated": updated, "skipped": len(skipped), "replace": body.replace},
    )
    db.commit()
    return ImportOut(added=added, updated=updated, skipped=skipped[:50])


@router.get("/{contact_id}", response_model=ContactOut, summary="One of your contacts")
def get_contact(
    contact_id: uuid.UUID,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> ContactOut:
    return _out(_own(db, principal, contact_id))


@router.patch("/{contact_id}", response_model=ContactOut, summary="Change a contact")
def patch_contact(
    contact_id: uuid.UUID,
    body: ContactPatch,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ContactOut:
    row = _own(db, principal, contact_id)
    fields = body.model_dump(exclude_unset=True)
    if "speed_dial" in fields:
        _check_speed_dial(db, principal, body.speed_dial, row.id)
    for key, value in fields.items():
        if key == "numbers":
            value = [n.model_dump() for n in body.numbers or []]
        setattr(row, key, value)
    if not row.numbers and not row.email:
        raise ProblemError(
            422,
            "Nothing to reach",
            "A contact needs a number or an email address.",
            code="validation_error",
            errors=[{"field": "numbers", "message": "a number or an email address is required"}],
        )
    _audit(
        db,
        ctx,
        principal,
        "contact.update",
        {"contact_id": str(row.id), "fields": sorted(fields)},
    )
    db.commit()
    db.refresh(row)
    return _out(row)


@router.delete("/{contact_id}", status_code=204, summary="Delete a contact")
def delete_contact(
    contact_id: uuid.UUID,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    row = _own(db, principal, contact_id)
    _audit(db, ctx, principal, "contact.delete", {"contact_id": str(row.id), "name": row.name})
    db.delete(row)
    db.commit()
    return Response(status_code=204)
