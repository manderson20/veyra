# SPDX-License-Identifier: AGPL-3.0-or-later
"""Voicemail boxes (docs/VOICEMAIL_IVR.md §3): one per extension, PIN
encrypted with the installation key, delivery options. Every write raises
the Deploy changes flag; PINs are returned once (creation and reset) and
never logged."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import group_helpers as helpers
from veyra.api.v1.destinations import count_uses
from veyra.api.v1.extensions import installation_key
from veyra.api.v1.group_helpers import MemberOut
from veyra.configmgmt import service as configmgmt
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.events import Event, bus
from veyra.core.mail import load_smtp_settings
from veyra.core.models import (
    Extension,
    Organization,
    User,
    VoicemailBox,
    VoicemailBoxMember,
)
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.crypto import InstallationKey
from veyra.core.security.principal import Principal
from veyra.telephony import routing
from veyra.telephony.snapshot import pin_purpose

router = APIRouter(prefix="/voicemail", tags=["voicemail"])

PIN_LENGTH = 6
RING_MIN, RING_MAX, RING_DEFAULT = 5, 120, 20


def _validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


def new_pin() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(PIN_LENGTH))


def set_pin(box: VoicemailBox, pin: str, key: InstallationKey) -> None:
    box.pin_ciphertext = key.encrypt(pin, pin_purpose(box.id))


def _pin_value(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    try:
        return routing.check_pin(v)
    except ValueError as e:
        raise ValueError(str(e)) from e


def _email_value(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    return routing.check_email(v)


# ----------------------------------------------------------------- schemas


class VoicemailBoxIn(BaseModel):
    # An extension's box, or (no extension) a shared inbox with its own
    # number and name (docs/PAGING_RECORDINGS.md §5).
    extension_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    number: str | None = Field(None, max_length=32)
    name: str | None = Field(None, max_length=100)
    members: list[uuid.UUID] = Field(default_factory=list, max_length=64)
    # Omitted: a random PIN is generated and returned once.
    pin: str | None = Field(None, max_length=10)
    # Omitted: the extension user's email; null or empty: no email.
    email: str | None = Field(None, max_length=254)
    attach_audio: bool = True
    delete_after_email: bool = False
    ring_seconds: int = Field(RING_DEFAULT, ge=RING_MIN, le=RING_MAX)
    is_enabled: bool = True

    @field_validator("pin")
    @classmethod
    def _pin(cls, v: str | None) -> str | None:
        return _pin_value(v)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return _email_value(v)


class VoicemailBoxPatch(BaseModel):
    number: str | None = Field(None, max_length=32)
    name: str | None = Field(None, max_length=100)
    members: list[uuid.UUID] | None = Field(None, max_length=64)
    pin: str | None = Field(None, max_length=10)
    email: str | None = Field(None, max_length=254)
    attach_audio: bool | None = None
    delete_after_email: bool | None = None
    ring_seconds: int | None = Field(None, ge=RING_MIN, le=RING_MAX)
    is_enabled: bool | None = None

    @field_validator("pin")
    @classmethod
    def _pin(cls, v: str | None) -> str | None:
        return _pin_value(v)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return _email_value(v)


class VoicemailBoxOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    # Shared inboxes have no extension: ``number`` and ``name`` are their own.
    shared: bool
    extension_id: uuid.UUID | None
    extension_number: str
    extension_name: str
    extension_enabled: bool
    number: str
    name: str
    members: list[MemberOut]
    user_display_name: str | None
    email: str | None
    attach_audio: bool
    delete_after_email: bool
    ring_seconds: int
    is_enabled: bool
    # Email delivery (Settings → Email delivery) is on; without it messages
    # stay in the box and are never deleted after an email.
    email_delivery_enabled: bool
    # Inbound routes and IVR keys that point at this box.
    in_use_by: int
    created_at: datetime
    updated_at: datetime


class VoicemailBoxCreated(VoicemailBoxOut):
    pin: str


class PinOut(BaseModel):
    pin: str


# ----------------------------------------------------------------- helpers


def _org_filter(stmt: Select[Any], column: Any, principal: Principal, perm: str) -> Select[Any]:
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(column.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _uses(db: Session, extension_ids: set[uuid.UUID]) -> dict[Any, int]:
    """Routes, IVR targets, ring groups and queues pointing at the voicemail
    of these extensions."""
    return count_uses(db, "voicemail", extension_ids)


def _members(db: Session, box_ids: set[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    out: dict[uuid.UUID, list[uuid.UUID]] = {b: [] for b in box_ids}
    if box_ids:
        for m in db.scalars(
            select(VoicemailBoxMember).where(VoicemailBoxMember.box_id.in_(box_ids))
        ):
            out[m.box_id].append(m.extension_id)
    return out


def _set_members(db: Session, box: VoicemailBox, extension_ids: list[uuid.UUID]) -> None:
    for old in db.scalars(select(VoicemailBoxMember).where(VoicemailBoxMember.box_id == box.id)):
        db.delete(old)
    db.flush()
    for ext_id in extension_ids:
        db.add(VoicemailBoxMember(box_id=box.id, extension_id=ext_id))
    db.flush()


def _outs(db: Session, rows: list[VoicemailBox]) -> list[VoicemailBoxOut]:
    if not rows:
        return []
    members = _members(db, {r.id for r in rows})
    ext_ids = {r.extension_id for r in rows if r.extension_id} | {
        e for ms in members.values() for e in ms
    }
    exts = (
        {e.id: e for e in db.scalars(select(Extension).where(Extension.id.in_(ext_ids)))}
        if ext_ids
        else {}
    )
    shared_uses = count_uses(db, "voicemail_box", {r.id for r in rows if not r.extension_id})
    org_ids = {r.organization_id for r in rows}
    orgs = {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids)))}
    user_ids = {e.user_id for e in exts.values() if e.user_id}
    users = (
        {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}
    )
    uses = _uses(db, ext_ids)
    delivery = load_smtp_settings(db).enabled
    out = []
    for r in rows:
        ext = exts.get(r.extension_id) if r.extension_id else None
        org = orgs.get(r.organization_id)
        user = users.get(ext.user_id) if ext and ext.user_id else None
        shared = r.extension_id is None
        out.append(
            VoicemailBoxOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=org.name if org else "",
                shared=shared,
                extension_id=r.extension_id,
                extension_number=ext.number if ext else "",
                extension_name=ext.display_name if ext else "",
                extension_enabled=bool(ext and ext.is_enabled) if not shared else True,
                number=(r.number if shared else ext.number if ext else "") or "",
                name=(r.name if shared else ext.display_name if ext else "") or "",
                members=sorted(
                    (
                        MemberOut(
                            extension_id=e.id,
                            number=e.number,
                            display_name=e.display_name,
                            is_enabled=e.is_enabled,
                        )
                        for e in (exts.get(i) for i in members[r.id])
                        if e is not None
                    ),
                    key=lambda m: m.number,
                ),
                user_display_name=user.display_name if user else None,
                email=r.email,
                attach_audio=r.attach_audio,
                delete_after_email=r.delete_after_email,
                ring_seconds=r.ring_seconds,
                is_enabled=r.is_enabled,
                email_delivery_enabled=delivery,
                in_use_by=shared_uses.get(r.id, 0) if shared else uses.get(r.extension_id, 0),
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _get(db: Session, principal: Principal, box_id: uuid.UUID, perm: str) -> VoicemailBox:
    stmt = _org_filter(select(VoicemailBox), VoicemailBox.organization_id, principal, perm)
    box = db.scalar(stmt.where(VoicemailBox.id == box_id))
    if box is None:
        raise not_found("Voicemail box")
    return box


def _audit(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    box: VoicemailBox,
    number: str,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=box.organization_id,
        target_type="voicemail_box",
        target_id=box.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"extension": number, **details},
    )
    configmgmt.mark_changed(db, by=principal.label, what=f"{action} {number}")


# ----------------------------------------------------------------- routes


@router.get("", response_model=Page[VoicemailBoxOut], summary="List voicemail boxes")
def list_boxes(
    organization_id: uuid.UUID | None = None,
    extension_id: uuid.UUID | None = None,
    shared: bool | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require("voicemail.read")),
    db: Session = Depends(get_db),
) -> Page[VoicemailBoxOut]:
    stmt = (
        _org_filter(select(VoicemailBox), VoicemailBox.organization_id, principal, "voicemail.read")
        .outerjoin(Extension, Extension.id == VoicemailBox.extension_id)
        .order_by(func.coalesce(Extension.number, VoicemailBox.number))
    )
    if organization_id:
        stmt = stmt.where(VoicemailBox.organization_id == organization_id)
    if extension_id:
        stmt = stmt.where(VoicemailBox.extension_id == extension_id)
    if shared is not None:
        stmt = stmt.where(
            VoicemailBox.extension_id.is_(None)
            if shared
            else VoicemailBox.extension_id.is_not(None)
        )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Extension.number.ilike(like),
                Extension.display_name.ilike(like),
                VoicemailBox.number.ilike(like),
                VoicemailBox.name.ilike(like),
                VoicemailBox.email.ilike(like),
            )
        )
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post(
    "", response_model=VoicemailBoxCreated, status_code=201, summary="Create a voicemail box"
)
def create_box(
    body: VoicemailBoxIn,
    request: Request,
    principal: Principal = Depends(require("voicemail.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> VoicemailBoxCreated:
    if body.extension_id is None:
        # A shared inbox: its own number and name (docs/PAGING_RECORDINGS.md §5).
        if body.organization_id is None:
            raise _validation("organization_id", "choose the organization")
        if not principal.has("voicemail.write", body.organization_id):
            raise forbidden()
        org = db.get(Organization, body.organization_id)
        if org is None or not org.is_active:
            raise conflict("This organization is inactive.", "organization_inactive")
        if not (body.name or "").strip():
            raise _validation("name", "enter a name")
        if not (body.number or "").strip():
            raise _validation("number", "enter a number from the numbering plan")
        helpers.check_number(db, (body.number or "").strip(), "shared inbox", None)
        helpers.load_members(db, org.id, body.members, "members")
        key = installation_key(request)
        if body.delete_after_email and not body.email:
            raise _validation("delete_after_email", "needs an email address to deliver to")
        pin = body.pin or new_pin()
        box = VoicemailBox(
            id=uuid.uuid4(),
            organization_id=org.id,
            extension_id=None,
            number=(body.number or "").strip(),
            name=(body.name or "").strip(),
            pin_ciphertext="",
            email=body.email,
            attach_audio=body.attach_audio,
            delete_after_email=body.delete_after_email,
            ring_seconds=body.ring_seconds,
            is_enabled=body.is_enabled,
        )
        set_pin(box, pin, key)
        db.add(box)
        try:
            db.flush()
        except IntegrityError as e:
            db.rollback()
            raise conflict(f"Number {box.number} is already used.", "number_in_use") from e
        _set_members(db, box, body.members)
        _audit(
            db,
            ctx,
            principal,
            "voicemail.create",
            box,
            box.number or "",
            {
                "shared": True,
                "name": box.name,
                "members": len(body.members),
                "generated": body.pin is None,
            },
        )
        db.commit()
        bus.publish(Event("voicemail.created", {"id": str(box.id), "number": box.number}))
        out = _outs(db, [box])[0]
        return VoicemailBoxCreated(**out.model_dump(), pin=pin)
    ext = db.get(Extension, body.extension_id)
    if ext is None or not principal.has("voicemail.write", ext.organization_id):
        raise not_found("Extension") if ext is None else forbidden()
    org = db.get(Organization, ext.organization_id)
    if org is None or not org.is_active:
        raise conflict("This organization is inactive.", "organization_inactive")
    if db.scalar(select(VoicemailBox.id).where(VoicemailBox.extension_id == ext.id)) is not None:
        raise conflict(f"Extension {ext.number} already has a voicemail box.", "box_exists")
    key = installation_key(request)
    email = body.email
    if "email" not in body.model_fields_set and ext.user_id:
        user = db.get(User, ext.user_id)
        email = user.email if user else None
    if body.delete_after_email and not email:
        raise _validation("delete_after_email", "needs an email address to deliver to")
    pin = body.pin or new_pin()
    box = VoicemailBox(
        id=uuid.uuid4(),
        organization_id=ext.organization_id,
        extension_id=ext.id,
        pin_ciphertext="",
        email=email,
        attach_audio=body.attach_audio,
        delete_after_email=body.delete_after_email,
        ring_seconds=body.ring_seconds,
        is_enabled=body.is_enabled,
    )
    set_pin(box, pin, key)
    db.add(box)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(f"Extension {ext.number} already has a voicemail box.", "box_exists") from e
    _audit(
        db,
        ctx,
        principal,
        "voicemail.create",
        box,
        ext.number,
        {"email": email, "ring_seconds": box.ring_seconds, "generated": body.pin is None},
    )
    db.commit()
    bus.publish(Event("voicemail.created", {"id": str(box.id), "extension": ext.number}))
    out = _outs(db, [box])[0]
    return VoicemailBoxCreated(**out.model_dump(), pin=pin)


@router.get("/{box_id}", response_model=VoicemailBoxOut)
def get_box(
    box_id: uuid.UUID,
    principal: Principal = Depends(require("voicemail.read")),
    db: Session = Depends(get_db),
) -> VoicemailBoxOut:
    return _outs(db, [_get(db, principal, box_id, "voicemail.read")])[0]


@router.patch("/{box_id}", response_model=VoicemailBoxOut)
def update_box(
    box_id: uuid.UUID,
    body: VoicemailBoxPatch,
    request: Request,
    principal: Principal = Depends(require("voicemail.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> VoicemailBoxOut:
    box = _get(db, principal, box_id, "voicemail.write")
    ext = db.get(Extension, box.extension_id) if box.extension_id else None
    number = ext.number if ext else (box.number or "?")
    changes = body.model_dump(exclude_unset=True)
    details: dict[str, Any] = {}
    if box.extension_id is None:
        if changes.get("number") and changes["number"].strip() != box.number:
            helpers.check_number(db, changes["number"].strip(), "shared inbox", box.id)
            details["number"] = {"from": box.number, "to": changes["number"].strip()}
            box.number = changes["number"].strip()
        if changes.get("name") and changes["name"].strip() != box.name:
            details["name"] = changes["name"].strip()
            box.name = changes["name"].strip()
        if changes.get("members") is not None:
            wanted = list(changes["members"])
            helpers.load_members(db, box.organization_id, wanted, "members")
            if sorted(map(str, wanted)) != sorted(map(str, _members(db, {box.id})[box.id])):
                _set_members(db, box, wanted)
                details["members"] = len(wanted)
    if "pin" in changes:
        if not body.pin:
            raise _validation("pin", "4 to 10 digits")
        set_pin(box, body.pin, installation_key(request))
        details["code_changed"] = True
    if "email" in changes and body.email != box.email:
        box.email = body.email
        details["email"] = body.email
    for field in ("attach_audio", "delete_after_email", "ring_seconds", "is_enabled"):
        value = changes.get(field)
        if value is not None and value != getattr(box, field):
            setattr(box, field, value)
            details[field] = value
    if box.delete_after_email and not box.email:
        raise _validation("delete_after_email", "needs an email address to deliver to")
    if not details:
        return _outs(db, [box])[0]
    db.flush()
    _audit(db, ctx, principal, "voicemail.update", box, number, details)
    db.commit()
    bus.publish(Event("voicemail.updated", {"id": str(box.id)}))
    return _outs(db, [box])[0]


@router.post("/{box_id}/reset-pin", response_model=PinOut, summary="Set a new random PIN")
def reset_pin(
    box_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("voicemail.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PinOut:
    box = _get(db, principal, box_id, "voicemail.write")
    ext = db.get(Extension, box.extension_id)
    pin = new_pin()
    set_pin(box, pin, installation_key(request))
    db.flush()
    _audit(db, ctx, principal, "voicemail.pin_reset", box, ext.number if ext else "?", {})
    db.commit()
    return PinOut(pin=pin)


@router.delete("/{box_id}", status_code=204)
def delete_box(
    box_id: uuid.UUID,
    principal: Principal = Depends(require("voicemail.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    box = _get(db, principal, box_id, "voicemail.write")
    ext = db.get(Extension, box.extension_id) if box.extension_id else None
    number = ext.number if ext else (box.number or "?")
    uses = (
        _uses(db, {box.extension_id}).get(box.extension_id, 0)
        if box.extension_id
        else count_uses(db, "voicemail_box", {box.id}).get(box.id, 0)
    )
    if uses:
        raise ProblemError(
            409,
            "Voicemail box in use",
            f"{uses} inbound route(s), IVR key(s), ring group(s) or queue(s) send calls to the "
            f"voicemail of {number}. "
            "Change them first.",
            code="voicemail_in_use",
        )
    _audit(db, ctx, principal, "voicemail.delete", box, number, {})
    db.delete(box)
    db.commit()
    bus.publish(Event("voicemail.deleted", {"id": str(box_id), "extension": number}))
    return Response(status_code=204)
