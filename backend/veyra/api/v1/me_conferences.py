# SPDX-License-Identifier: AGPL-3.0-or-later
"""The conference rooms a user owns, on My Phone (issue #96): the same live
view and control as the room page, for the rooms their extension owns."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1 import conferences
from veyra.api.v1.me import require_me
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context
from veyra.core.errors import not_found
from veyra.core.models import ConferenceRoom, ConferenceRoomOwner, Extension
from veyra.core.security.principal import Principal

router = APIRouter(prefix="/me/conferences", tags=["me"])


class MyConferenceOut(BaseModel):
    id: uuid.UUID
    name: str
    number: str


def _owned(db: Session, principal: Principal) -> list[tuple[ConferenceRoom, Extension]]:
    rows = db.execute(
        select(ConferenceRoom, Extension)
        .join(ConferenceRoomOwner, ConferenceRoomOwner.room_id == ConferenceRoom.id)
        .join(Extension, Extension.id == ConferenceRoomOwner.extension_id)
        .where(Extension.user_id == principal.user_id, Extension.is_enabled.is_(True))
        .order_by(ConferenceRoom.number, Extension.number)
    ).all()
    return [(room, ext) for room, ext in rows]


def _own_room(
    db: Session, principal: Principal, room_id: uuid.UUID
) -> tuple[ConferenceRoom, Extension]:
    for room, ext in _owned(db, principal):
        if room.id == room_id:
            return room, ext
    raise not_found("Conference room")


@router.get("", response_model=list[MyConferenceOut], summary="The rooms you own")
def my_rooms(
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> list[MyConferenceOut]:
    seen: dict[uuid.UUID, MyConferenceOut] = {}
    for room, _ext in _owned(db, principal):
        seen.setdefault(room.id, MyConferenceOut(id=room.id, name=room.name, number=room.number))
    return list(seen.values())


@router.get("/{room_id}/live", response_model=conferences.LiveOut, summary="Who is in your room")
def my_live(
    room_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> conferences.LiveOut:
    room, _ext = _own_room(db, principal, room_id)
    return conferences.live_state(request, db, room)


@router.post("/{room_id}/live", response_model=conferences.LiveOut, summary="Control your room")
def my_live_action(
    room_id: uuid.UUID,
    body: conferences.LiveActionIn,
    request: Request,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> conferences.LiveOut:
    room, ext = _own_room(db, principal, room_id)
    return conferences.perform_action(request, db, room, body, principal, ctx, ext)
