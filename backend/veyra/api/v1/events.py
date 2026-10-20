# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call-event stream for the Companion (docs/COMPANION.md §4): a one-time
ticket from an authenticated request, then a WebSocket that delivers the
caller's own call events."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.callevents import CallEventHub
from veyra.core.db import session_factory
from veyra.core.deps import current_principal
from veyra.core.errors import forbidden
from veyra.core.models import ApiToken, Extension, User, UserSession
from veyra.core.models.base import utcnow
from veyra.core.security.principal import Principal

router = APIRouter(prefix="/events", tags=["events"])

PING_SECONDS = 20
SILENCE_LIMIT_SECONDS = 60


class TicketOut(BaseModel):
    ticket: str
    expires_in: int
    url: str


def hub_of(app: Any) -> CallEventHub:
    hub = getattr(app.state, "callevents", None)
    if hub is None:
        hub = CallEventHub()
        app.state.callevents = hub
    return hub


@router.post("/ticket", response_model=TicketOut, summary="One-time ticket for the event stream")
def ticket(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> TicketOut:
    if not principal.has_scope("me"):
        raise forbidden()
    hub = hub_of(request.app)
    value, ttl = hub.issue_ticket(
        principal.user_id, token_id=principal.token_id, session_id=principal.session_id
    )
    return TicketOut(ticket=value, expires_in=ttl, url="/api/v1/events/calls")


def _still_valid(
    db: Session, user_id: uuid.UUID, token_id: uuid.UUID | None, session_id: uuid.UUID | None
) -> bool:
    now = utcnow()
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return False
    if token_id is not None:
        tok = db.get(ApiToken, token_id)
        return tok is not None and tok.revoked_at is None and tok.expires_at > now
    if session_id is not None:
        ses = db.get(UserSession, session_id)
        return ses is not None and ses.revoked_at is None and ses.expires_at > now
    return True


def _endpoints(db: Session, user_id: uuid.UUID) -> dict[str, tuple[uuid.UUID, str, str]]:
    rows = db.scalars(select(Extension).where(Extension.user_id == user_id)).all()
    return {e.endpoint_name: (e.id, e.number, e.display_name) for e in rows}


@router.websocket("/calls")
async def calls_stream(websocket: WebSocket) -> None:
    hub = hub_of(websocket.app)
    value = websocket.query_params.get("ticket", "")
    tkt = hub.redeem_ticket(value) if value else None
    if tkt is None:
        await websocket.close(code=4401, reason="ticket invalid or expired")
        return
    maker = session_factory()
    db = maker()
    try:
        if not _still_valid(db, tkt.user_id, tkt.token_id, tkt.session_id):
            await websocket.close(code=4401, reason="not signed in")
            return
        endpoints = _endpoints(db, tkt.user_id)
    finally:
        db.close()
    await websocket.accept()
    sub = hub.subscribe(tkt.user_id, {k: (v[0], v[1]) for k, v in endpoints.items()})
    await websocket.send_text(
        json.dumps(
            {
                "type": "hello",
                "extensions": [
                    {"id": str(v[0]), "number": v[1], "name": v[2]} for v in endpoints.values()
                ],
                "listener": hub.state,
                "server_time": utcnow().isoformat(timespec="seconds"),
            }
        )
    )
    last_heard = asyncio.get_running_loop().time()

    async def reader() -> None:
        nonlocal last_heard
        while True:
            await websocket.receive_text()
            last_heard = asyncio.get_running_loop().time()

    read_task = asyncio.create_task(reader())
    try:
        while True:
            try:
                event = await asyncio.wait_for(sub.queue.get(), timeout=PING_SECONDS)
            except TimeoutError:
                event = None
            if read_task.done():
                break
            if isinstance(event, dict):
                await websocket.send_text(json.dumps(event))
                continue
            if event is not None:
                ext_id, number = sub.endpoints[event.endpoint]
                await websocket.send_text(json.dumps(event.payload(ext_id, number)))
                continue
            loop = asyncio.get_running_loop()
            if loop.time() - last_heard > SILENCE_LIMIT_SECONDS:
                await websocket.close(code=4408, reason="no pong")
                break
            check_db = maker()
            try:
                ok = _still_valid(check_db, tkt.user_id, tkt.token_id, tkt.session_id)
            finally:
                check_db.close()
            if not ok:
                await websocket.close(code=4401, reason="signed out")
                break
            await websocket.send_text(json.dumps({"type": "ping", "listener": hub.state}))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(sub)
        read_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await read_task


@router.websocket("/staff")
async def staff_stream(websocket: WebSocket) -> None:
    """Live views for administrators (issue #111): a ``changed`` message
    whenever a call event touches an extension the caller may see with
    ``calls.read``; the Calls page then reloads instead of polling."""
    from veyra.api.v1.extensions import _visible
    from veyra.core.security.sessions import load_principal

    hub = hub_of(websocket.app)
    value = websocket.query_params.get("ticket", "")
    tkt = hub.redeem_ticket(value) if value else None
    if tkt is None:
        await websocket.close(code=4401, reason="ticket invalid or expired")
        return
    maker = session_factory()
    db = maker()
    try:
        user = db.get(User, tkt.user_id)
        if user is None or not _still_valid(db, tkt.user_id, tkt.token_id, tkt.session_id):
            await websocket.close(code=4401, reason="not signed in")
            return
        principal = load_principal(db, user, tkt.session_id)
        rows = db.scalars(_visible(principal, "calls.read")).all()
        endpoints = {e.endpoint_name: (e.id, e.number) for e in rows}
    finally:
        db.close()
    if not endpoints:
        await websocket.close(code=4403, reason="no calls to show")
        return
    await websocket.accept()
    sub = hub.subscribe(tkt.user_id, endpoints)
    await websocket.send_text(json.dumps({"type": "hello", "listener": hub.state}))
    try:
        while True:
            try:
                event = await asyncio.wait_for(sub.queue.get(), timeout=PING_SECONDS)
            except TimeoutError:
                event = None
            if event is None:
                check_db = maker()
                try:
                    ok = _still_valid(check_db, tkt.user_id, tkt.token_id, tkt.session_id)
                finally:
                    check_db.close()
                if not ok:
                    await websocket.close(code=4401, reason="signed out")
                    break
                await websocket.send_text(json.dumps({"type": "ping", "listener": hub.state}))
                continue
            # Several events of one call arrive together: one message is enough.
            while not sub.queue.empty():
                sub.queue.get_nowait()
            await websocket.send_text(json.dumps({"type": "changed"}))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(sub)
