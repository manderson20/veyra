# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conference rooms (docs/CALL_FEATURES.md §4.3): dialled by number or reached
as a destination, with optional user and administrator PINs (encrypted with
the installation key), a participant limit, recording and the key menu."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import destinations, hold_music
from veyra.api.v1 import group_helpers as helpers
from veyra.api.v1.extensions import installation_key
from veyra.api.v1.group_helpers import READ, WRITE, validation
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import conflict, not_found
from veyra.core.events import Event, bus
from veyra.core.models import ConferenceRoom
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import routing
from veyra.telephony.snapshot import conference_pin_purpose

router = APIRouter(prefix="/conferences", tags=["conferences"])

_PIN_RE = re.compile(r"^[0-9]{4,10}$")
MAX_PARTICIPANTS = 500


def _pin(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    if not _PIN_RE.match(v.strip()):
        raise ValueError("4 to 10 digits")
    return v.strip()


# ----------------------------------------------------------------- schemas


class ConferenceIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    number: str = Field(min_length=1, max_length=32)
    description: str | None = Field(None, max_length=2000)
    # Write-only; empty or missing: no PIN of that kind.
    user_pin: str | None = Field(None, max_length=10)
    admin_pin: str | None = Field(None, max_length=10)
    max_participants: int = Field(0, ge=0, le=MAX_PARTICIPANTS)
    record: bool = False
    announce_join_leave: bool = True
    music_on_hold_alone: bool = True
    wait_for_admin: bool = False
    moh_class_id: uuid.UUID | None = None
    is_enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        routing.slugify(v)
        return v

    @field_validator("number")
    @classmethod
    def _number(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[0-9]{2,32}", v):
            raise ValueError("digits only")
        return v

    @field_validator("user_pin", "admin_pin")
    @classmethod
    def _pins(cls, v: str | None) -> str | None:
        return _pin(v)


class ConferencePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    number: str | None = Field(None, min_length=1, max_length=32)
    description: str | None = Field(None, max_length=2000)
    user_pin: str | None = Field(None, max_length=10)
    admin_pin: str | None = Field(None, max_length=10)
    max_participants: int | None = Field(None, ge=0, le=MAX_PARTICIPANTS)
    record: bool | None = None
    announce_join_leave: bool | None = None
    music_on_hold_alone: bool | None = None
    wait_for_admin: bool | None = None
    moh_class_id: uuid.UUID | None = None
    is_enabled: bool | None = None


class ConferenceOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    slug: str
    number: str
    context: str
    description: str | None
    has_user_pin: bool
    has_admin_pin: bool
    max_participants: int
    record: bool
    announce_join_leave: bool
    music_on_hold_alone: bool
    wait_for_admin: bool
    moh_class_id: uuid.UUID | None
    moh_class_name: str | None
    is_enabled: bool
    problems: list[str]
    # Routes, menus, groups and announcements that point at the room.
    in_use_by: int
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------- helpers


def _outs(db: Session, rows: list[ConferenceRoom]) -> list[ConferenceOut]:
    if not rows:
        return []
    orgs = helpers.org_names(db, {r.organization_id for r in rows})
    moh_names = hold_music.set_names(db, {r.moh_class_id for r in rows if r.moh_class_id})
    uses = destinations.count_uses(db, "conference", {r.id for r in rows})
    out = []
    for r in rows:
        problems = []
        if r.wait_for_admin and not r.admin_pin_ciphertext:
            problems.append(
                "Participants wait for an administrator, but the room has no administrator PIN."
            )
        out.append(
            ConferenceOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=orgs.get(r.organization_id, ""),
                name=r.name,
                slug=r.slug,
                number=r.number,
                context=f"veyra-conf-{r.slug}",
                description=r.description,
                has_user_pin=bool(r.user_pin_ciphertext),
                has_admin_pin=bool(r.admin_pin_ciphertext),
                max_participants=r.max_participants,
                record=r.record,
                announce_join_leave=r.announce_join_leave,
                music_on_hold_alone=r.music_on_hold_alone,
                wait_for_admin=r.wait_for_admin,
                moh_class_id=r.moh_class_id,
                moh_class_name=moh_names.get(r.moh_class_id) if r.moh_class_id else None,
                is_enabled=r.is_enabled,
                problems=problems,
                in_use_by=uses.get(r.id, 0),
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _get(db: Session, principal: Principal, room_id: uuid.UUID, perm: str) -> ConferenceRoom:
    stmt = helpers.org_filter(
        select(ConferenceRoom), ConferenceRoom.organization_id, principal, perm
    )
    row = db.scalar(stmt.where(ConferenceRoom.id == room_id))
    if row is None:
        raise not_found("Conference room")
    return row


def _check(
    db: Session, org_id: uuid.UUID, body: ConferenceIn, self_id: uuid.UUID | None = None
) -> None:
    helpers.check_number(db, body.number, "conference room", self_id, org_id)
    hold_music.check_set(db, org_id, body.moh_class_id, "moh_class_id")
    if body.user_pin and body.admin_pin and body.user_pin == body.admin_pin:
        raise validation("admin_pin", "the administrator PIN must differ from the user PIN")


def _set_pins(
    room: ConferenceRoom, request: Request, user_pin: str | None, admin_pin: str | None
) -> None:
    key = installation_key(request)
    room.user_pin_ciphertext = (
        key.encrypt(user_pin, conference_pin_purpose(room.id, "user")) if user_pin else None
    )
    room.admin_pin_ciphertext = (
        key.encrypt(admin_pin, conference_pin_purpose(room.id, "admin")) if admin_pin else None
    )


def _stored_pin(room: ConferenceRoom, which: str, key: Any) -> str | None:
    ciphertext = getattr(room, f"{which}_pin_ciphertext")
    if not ciphertext:
        return None
    return str(key.decrypt(ciphertext, conference_pin_purpose(room.id, which)))


def _name_conflict() -> Exception:
    return conflict("A conference room with that name exists in this organization.", "name_in_use")


# ----------------------------------------------------------------- routes


@router.get("", response_model=Page[ConferenceOut], summary="List conference rooms")
def list_rooms(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[ConferenceOut]:
    stmt = helpers.org_filter(
        select(ConferenceRoom), ConferenceRoom.organization_id, principal, READ
    ).order_by(ConferenceRoom.number)
    if organization_id:
        stmt = stmt.where(ConferenceRoom.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                ConferenceRoom.name.ilike(like),
                ConferenceRoom.number.ilike(like),
                ConferenceRoom.description.ilike(like),
            )
        )
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post("", response_model=ConferenceOut, status_code=201, summary="Create a conference room")
def create_room(
    body: ConferenceIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ConferenceOut:
    org = helpers.org_for_write(db, principal, body.organization_id)
    _check(db, org.id, body)
    room = ConferenceRoom(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=body.name,
        slug=helpers.unique_slug(db, ConferenceRoom, body.name),
        number=body.number,
        description=(body.description or "").strip() or None,
        max_participants=body.max_participants,
        record=body.record,
        announce_join_leave=body.announce_join_leave,
        music_on_hold_alone=body.music_on_hold_alone,
        wait_for_admin=body.wait_for_admin,
        moh_class_id=body.moh_class_id,
        is_enabled=body.is_enabled,
    )
    _set_pins(room, request, body.user_pin, body.admin_pin)
    db.add(room)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise _name_conflict() from e
    helpers.record(
        db,
        ctx,
        principal,
        "conference.create",
        target_type="conference_room",
        target=room,
        details={"slug": room.slug, "number": room.number},
    )
    db.commit()
    bus.publish(Event("conference.created", {"id": str(room.id), "name": room.name}))
    return _outs(db, [room])[0]


@router.get("/{room_id}", response_model=ConferenceOut)
def get_room(
    room_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> ConferenceOut:
    return _outs(db, [_get(db, principal, room_id, READ)])[0]


@router.patch("/{room_id}", response_model=ConferenceOut)
def update_room(
    room_id: uuid.UUID,
    body: ConferencePatch,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ConferenceOut:
    room = _get(db, principal, room_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    # PINs are write-only: a missing field keeps the stored PIN, null or an
    # empty string removes it. The merged document carries placeholders for
    # the kept ones so the validator does not see them as absent.
    current = {
        "organization_id": room.organization_id,
        "name": room.name,
        "number": room.number,
        "description": room.description,
        "user_pin": "0000" if room.user_pin_ciphertext else None,
        "admin_pin": "0000" if room.admin_pin_ciphertext else None,
        "max_participants": room.max_participants,
        "record": room.record,
        "announce_join_leave": room.announce_join_leave,
        "music_on_hold_alone": room.music_on_hold_alone,
        "wait_for_admin": room.wait_for_admin,
        "moh_class_id": room.moh_class_id,
        "is_enabled": room.is_enabled,
    }
    try:
        validated = ConferenceIn.model_validate({**current, **changes})
    except ValueError as e:
        raise validation("conference", str(e).splitlines()[0]) from e
    if "user_pin" in changes or "admin_pin" in changes:
        # Compare against the PIN that stays when only one of them changes.
        key = installation_key(request)
        user_pin = validated.user_pin if "user_pin" in changes else _stored_pin(room, "user", key)
        admin_pin = (
            validated.admin_pin if "admin_pin" in changes else _stored_pin(room, "admin", key)
        )
        if user_pin and admin_pin and user_pin == admin_pin:
            raise validation("admin_pin", "the administrator PIN must differ from the user PIN")
    helpers.check_number(db, validated.number, "conference room", room.id, room.organization_id)
    hold_music.check_set(db, room.organization_id, validated.moh_class_id, "moh_class_id")
    details: dict[str, Any] = {}
    if validated.name != room.name:
        details["name"] = {"from": room.name, "to": validated.name}
        room.name = validated.name
    if validated.number != room.number:
        details["number"] = {"from": room.number, "to": validated.number}
        room.number = validated.number
    desc = (validated.description or "").strip() or None
    if desc != room.description:
        room.description = desc
        details["description"] = True
    for field in (
        "max_participants",
        "record",
        "announce_join_leave",
        "music_on_hold_alone",
        "wait_for_admin",
        "moh_class_id",
        "is_enabled",
    ):
        value = getattr(validated, field)
        if value != getattr(room, field):
            setattr(room, field, value)
            details[field] = str(value) if value is not None else None
    if "user_pin" in changes or "admin_pin" in changes:
        key = installation_key(request)
        if "user_pin" in changes:
            pin = validated.user_pin
            room.user_pin_ciphertext = (
                key.encrypt(pin, conference_pin_purpose(room.id, "user")) if pin else None
            )
            details["user_pin"] = "set" if pin else "removed"
        if "admin_pin" in changes:
            pin = validated.admin_pin
            room.admin_pin_ciphertext = (
                key.encrypt(pin, conference_pin_purpose(room.id, "admin")) if pin else None
            )
            details["admin_pin"] = "set" if pin else "removed"
    if not details:
        return _outs(db, [room])[0]
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise _name_conflict() from e
    helpers.record(
        db,
        ctx,
        principal,
        "conference.update",
        target_type="conference_room",
        target=room,
        details=details,
    )
    db.commit()
    bus.publish(Event("conference.updated", {"id": str(room.id)}))
    return _outs(db, [room])[0]


@router.delete("/{room_id}", status_code=204)
def delete_room(
    room_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    room = _get(db, principal, room_id, WRITE)
    what = destinations.describe_uses(db, "conference", room.id)
    if what:
        raise destinations.in_use_error("Conference room in use", "conference_in_use", what)
    helpers.record(
        db,
        ctx,
        principal,
        "conference.delete",
        target_type="conference_room",
        target=room,
        details={"slug": room.slug, "number": room.number},
    )
    db.delete(room)
    db.commit()
    bus.publish(Event("conference.deleted", {"id": str(room_id)}))
    return Response(status_code=204)


# ------------------------------------------------- live control (issue #96)


class LiveParticipantOut(BaseModel):
    channel: str
    caller_id: str
    admin: bool
    marked: bool
    muted: bool


class LiveOut(BaseModel):
    running: bool
    locked: bool = False
    participants: list[LiveParticipantOut] = Field(default_factory=list)


class LiveActionIn(BaseModel):
    action: str = Field(pattern="^(mute|unmute|kick|mute_all|unmute_all|lock|unlock|end)$")
    channel: str | None = Field(None, max_length=160)


def _engine_room(db: Session, room: ConferenceRoom) -> str:
    from veyra.core import tenancy

    return tenancy.names_of(db, room.organization_id).conference(room.slug)


def _live(request: Request, db: Session, room: ConferenceRoom) -> LiveOut:
    from veyra.core.errors import ProblemError
    from veyra.telephony.adapter import EngineUnavailable, NotSupported

    try:
        live = request.app.state.telephony.conference_live(_engine_room(db, room))
    except NotSupported as e:
        raise ProblemError(409, "Not available", str(e), code="not_available") from e
    except EngineUnavailable as e:
        raise ProblemError(503, "Engine unavailable", str(e), code="engine_unavailable") from e
    if live is None:
        return LiveOut(running=False)
    return LiveOut(running=True, **live)


@router.get("/{room_id}/live", response_model=LiveOut, summary="Who is in the room now")
def live_room(
    room_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> LiveOut:
    return _live(request, db, _get(db, principal, room_id, READ))


@router.post("/{room_id}/live", response_model=LiveOut, summary="Mute, kick, lock or end")
def live_action(
    room_id: uuid.UUID,
    body: LiveActionIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> LiveOut:
    from veyra.core.errors import ProblemError
    from veyra.telephony.adapter import EngineUnavailable, NotSupported

    room = _get(db, principal, room_id, WRITE)
    if body.action in ("mute", "unmute", "kick"):
        current = _live(request, db, room)
        if body.channel not in {p.channel for p in current.participants}:
            raise not_found("Participant")
    try:
        request.app.state.telephony.conference_action(
            _engine_room(db, room), body.action, body.channel
        )
    except NotSupported as e:
        raise ProblemError(409, "Not available", str(e), code="not_available") from e
    except (EngineUnavailable, ValueError) as e:
        raise ProblemError(409, "Not done", str(e), code="conference_action_failed") from e
    helpers.record(
        db,
        ctx,
        principal,
        f"conference.live_{body.action}",
        target_type="conference_room",
        target=room,
        details={"channel": body.channel} if body.channel else {},
    )
    db.commit()
    return _live(request, db, room)
