# SPDX-License-Identifier: AGPL-3.0-or-later
"""Calls: what is up right now, and click-to-dial.

Click-to-dial asks the engine to ring one of the caller's phones first and,
when it is picked up, to place the call to the number entered, so the
number never has to be typed on the handset. Until trunks exist (Milestone
6) the dialplan only reaches internal extensions and feature codes.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1.extensions import _visible as visible_extensions
from veyra.api.v1.schemas import MessageOut
from veyra.core import audit, tenancy
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.models import Extension, Organization
from veyra.core.security.principal import Principal
from veyra.telephony.adapter import (
    ActiveCall,
    Capability,
    EngineUnavailable,
    NotSupported,
    TelephonyAdapter,
)

router = APIRouter(prefix="/calls", tags=["calls"])

_NUMBER_RE = re.compile(r"^\+?[0-9*#]{1,32}$")
ORIGINATE_TIMEOUT_SECONDS = 30


def _adapter(request: Request) -> TelephonyAdapter:
    return request.app.state.telephony


class ActiveCallOut(BaseModel):
    channel_id: str
    caller: str | None
    callee: str | None
    state: str
    duration_seconds: int
    endpoint: str | None
    extension_number: str | None = None
    extension_name: str | None = None


class ActiveCallsOut(BaseModel):
    calls: list[ActiveCallOut]
    available: bool
    message: str | None = None


class OriginateIn(BaseModel):
    extension_id: uuid.UUID
    number: str = Field(min_length=1, max_length=32)


class OriginateOut(BaseModel):
    channel_id: str
    extension_number: str
    number: str
    message: str


def _normalize_number(value: str) -> str:
    digits = re.sub(r"[\s().-]", "", value.strip())
    if not _NUMBER_RE.match(digits):
        raise ProblemError(
            422,
            "Validation failed",
            "Enter digits only (a leading + is allowed).",
            code="validation_failed",
            errors=[{"field": "number", "message": "digits only"}],
        )
    return digits


@router.get("", response_model=ActiveCallsOut, summary="Calls in progress")
def active_calls(
    request: Request,
    principal: Principal = Depends(require("calls.read")),
    db: Session = Depends(get_db),
) -> ActiveCallsOut:
    """Platform administrators see every channel; others see the channels
    that belong to extensions in their organizations."""
    adapter = _adapter(request)
    if Capability.ACTIVE_CALLS not in adapter.capabilities():
        return ActiveCallsOut(calls=[], available=False, message="The engine cannot report calls.")
    try:
        calls = adapter.active_calls()
    except (EngineUnavailable, NotSupported) as e:
        return ActiveCallsOut(calls=[], available=False, message=str(e))
    rows = db.scalars(visible_extensions(principal, "calls.read")).all()
    by_endpoint = {e.endpoint_name: e for e in rows}
    by_number = {e.number: e for e in rows}
    out: list[ActiveCallOut] = []
    for c in calls:
        ext = by_endpoint.get(c.endpoint or "") or by_number.get(c.caller or "")
        if ext is None and not principal.is_platform_admin:
            continue
        out.append(
            ActiveCallOut(
                channel_id=c.channel_id,
                caller=c.caller,
                callee=c.callee,
                state=c.state,
                duration_seconds=c.duration_seconds,
                endpoint=c.endpoint,
                extension_number=ext.number if ext else None,
                extension_name=ext.display_name if ext else None,
            )
        )
    return ActiveCallsOut(calls=out, available=True)


@router.post(
    "/originate",
    response_model=OriginateOut,
    status_code=202,
    summary="Click-to-dial: ring one of your phones, then place the call",
)
def originate(
    body: OriginateIn,
    request: Request,
    principal: Principal = Depends(require("calls.originate")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> OriginateOut:
    adapter = _adapter(request)
    if Capability.CLICK_TO_DIAL not in adapter.capabilities():
        raise conflict("The configured telephony engine cannot place calls.", "not_available")
    ext = db.scalar(select(Extension).where(Extension.id == body.extension_id))
    if ext is None:
        raise not_found("Extension")
    # Your own phone, or any phone you administer.
    own = ext.user_id == principal.user_id
    if not own and not principal.has("extensions.write", ext.organization_id):
        raise forbidden("You can only dial from your own extensions.")
    if not ext.is_enabled:
        raise conflict("This extension is disabled.", "extension_disabled")
    number = _normalize_number(body.number)
    if number == ext.number:
        raise conflict("That is the number of the phone itself.", "same_number")
    health = adapter.health()
    if health.state != "running":
        raise conflict(
            f"The telephony engine is not running ({health.state}).", "engine_not_running"
        )
    try:
        channel_id = adapter.originate(
            ext.endpoint_name,
            number,
            caller_id=f"{number} <{number}>",
            context=tenancy.names_of(db, ext.organization_id).internal,
            timeout=ORIGINATE_TIMEOUT_SECONDS,
        )
    except EngineUnavailable as e:
        audit.record(
            db,
            action="call.originate",
            outcome="failure",
            actor_user_id=principal.user_id,
            actor_label=principal.label,
            organization_id=ext.organization_id,
            target_type="extension",
            target_id=ext.id,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"from": ext.number, "to": number, "error": str(e)},
        )
        db.commit()
        raise conflict(f"The engine refused the call: {e}", "originate_failed") from e
    audit.record(
        db,
        action="call.originate",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=ext.organization_id,
        target_type="extension",
        target_id=ext.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"from": ext.number, "to": number, "own_extension": own, "channel": channel_id},
    )
    db.commit()
    return OriginateOut(
        channel_id=channel_id,
        extension_number=ext.number,
        number=number,
        message=f"Extension {ext.number} is ringing; pick it up to call {number}.",
    )


_CHANNEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


@router.delete(
    "/{channel_id}",
    response_model=MessageOut,
    summary="Hang up a call in progress",
)
def hangup(
    channel_id: str,
    request: Request,
    principal: Principal = Depends(require("calls.hangup")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    """Ends the channel; the other side of the call is cleared by the engine.
    Platform administrators may end any channel, others the channels of
    extensions in organizations where they hold ``calls.hangup``."""
    adapter = _adapter(request)
    if Capability.ACTIVE_CALLS not in adapter.capabilities() or not _CHANNEL_RE.match(channel_id):
        raise not_found("Call")
    try:
        calls = adapter.active_calls()
    except (EngineUnavailable, NotSupported) as e:
        raise conflict(f"The engine cannot report calls: {e}", "not_available") from e
    call = next((c for c in calls if c.channel_id == channel_id), None)
    if call is None:
        raise not_found("Call")
    rows = db.scalars(visible_extensions(principal, "calls.hangup")).all()
    ext = next(
        (e for e in rows if e.endpoint_name == call.endpoint),
        next((e for e in rows if e.number == call.caller), None),
    )
    if ext is None and not principal.is_platform_admin:
        raise not_found("Call")
    details = {
        "channel": channel_id,
        "from": call.caller,
        "to": call.callee,
        "duration_seconds": call.duration_seconds,
    }
    try:
        adapter.hangup(channel_id)
    except (EngineUnavailable, NotSupported) as e:
        audit.record(
            db,
            action="call.hangup",
            outcome="failure",
            actor_user_id=principal.user_id,
            actor_label=principal.label,
            organization_id=ext.organization_id if ext else None,
            target_type="extension" if ext else None,
            target_id=ext.id if ext else None,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={**details, "error": str(e)},
        )
        db.commit()
        raise conflict(f"The engine did not hang up the call: {e}", "hangup_failed") from e
    audit.record(
        db,
        action="call.hangup",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=ext.organization_id if ext else None,
        target_type="extension" if ext else None,
        target_id=ext.id if ext else None,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=details,
    )
    db.commit()
    who = ext.number if ext else (call.endpoint or channel_id)
    return MessageOut(message=f"The call on {who} was hung up.")


def calls_for(calls: list[ActiveCall], endpoint: str) -> list[ActiveCall]:
    return [c for c in calls if c.endpoint == endpoint]


class RecordIn(BaseModel):
    action: str = Field(pattern="^(start|stop)$")


@router.post(
    "/{channel_id}/record",
    response_model=MessageOut,
    summary="Start or stop recording a call in progress",
)
def record(
    channel_id: str,
    body: RecordIn,
    request: Request,
    principal: Principal = Depends(require("calls.record")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    """The web's "record this call" (issue #135): like the phone's on-demand
    code, the recording is filed with the call record. Platform
    administrators may record any call, others the calls of extensions in
    organizations where they hold ``calls.record``."""
    adapter = _adapter(request)
    if Capability.ACTIVE_CALLS not in adapter.capabilities() or not _CHANNEL_RE.match(channel_id):
        raise not_found("Call")
    try:
        calls = adapter.active_calls()
    except (EngineUnavailable, NotSupported) as e:
        raise conflict(f"The engine cannot report calls: {e}", "not_available") from e
    call = next((c for c in calls if c.channel_id == channel_id), None)
    if call is None:
        raise not_found("Call")
    rows = db.scalars(visible_extensions(principal, "calls.record")).all()
    ext = next(
        (e for e in rows if e.endpoint_name == call.endpoint),
        next((e for e in rows if e.number == call.caller), None),
    )
    if ext is None and not principal.is_platform_admin:
        raise not_found("Call")
    try:
        adapter.record_call(channel_id, body.action == "start")
    except ValueError as e:
        raise conflict(str(e), "record_refused") from e
    except (EngineUnavailable, NotSupported) as e:
        raise conflict(
            f"The engine did not {body.action} the recording: {e}", "record_failed"
        ) from e
    audit.record(
        db,
        action=f"call.record_{body.action}",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=ext.organization_id if ext else None,
        target_type="extension" if ext else None,
        target_id=ext.id if ext else None,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"channel": channel_id, "from": call.caller, "to": call.callee},
    )
    db.commit()
    return MessageOut(
        message="Recording started." if body.action == "start" else "Recording stopped."
    )


class MonitorIn(BaseModel):
    mode: str = Field(pattern="^(listen|whisper|barge)$")
    # The supervisor's phone; empty: the first of your own extensions.
    extension_id: uuid.UUID | None = None


@router.post(
    "/{channel_id}/monitor",
    response_model=MessageOut,
    status_code=202,
    summary="Listen to, whisper on or join a call in progress (supervisor)",
)
def monitor(
    channel_id: str,
    body: MonitorIn,
    request: Request,
    principal: Principal = Depends(require("calls.monitor")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    """Issue #167: rings the supervisor's phone; once answered it hears the
    call (listen), talks to the extension's user only (whisper) or to both
    sides (barge). Every session is audited. A class of service may protect
    its phones from being monitored."""
    from veyra.core.models import ClassOfService

    adapter = _adapter(request)
    if Capability.ACTIVE_CALLS not in adapter.capabilities() or not _CHANNEL_RE.match(channel_id):
        raise not_found("Call")
    try:
        calls = adapter.active_calls()
    except (EngineUnavailable, NotSupported) as e:
        raise conflict(f"The engine cannot report calls: {e}", "not_available") from e
    call = next((c for c in calls if c.channel_id == channel_id), None)
    if call is None:
        raise not_found("Call")
    rows = db.scalars(visible_extensions(principal, "calls.monitor")).all()
    target = next((e for e in rows if e.endpoint_name == call.endpoint), None)
    if target is None:
        raise not_found("Call")
    if target.class_of_service_id is not None:
        cos = db.get(ClassOfService, target.class_of_service_id)
        if cos is not None and cos.monitor_protected:
            raise conflict(
                f"Extension {target.number}'s class of service does not allow monitoring.",
                "monitor_protected",
            )
    if body.extension_id is not None:
        phone = db.get(Extension, body.extension_id)
        if phone is None:
            raise not_found("Extension")
        if phone.user_id != principal.user_id and not principal.has(
            "extensions.write", phone.organization_id
        ):
            raise forbidden("You can only use your own phone to monitor a call.")
    else:
        phone = db.scalar(
            select(Extension)
            .where(Extension.user_id == principal.user_id, Extension.is_enabled.is_(True))
            .order_by(Extension.number)
        )
        if phone is None:
            raise conflict("You have no phone to listen on; choose one.", "no_phone")
    if phone.organization_id != target.organization_id and not principal.is_platform_admin:
        raise forbidden("The phone and the call are in different organizations.")
    if phone.id == target.id:
        raise conflict("That is the call on your own phone.", "same_number")
    details = {
        "channel": channel_id,
        "mode": body.mode,
        "target": target.number,
        "supervisor_phone": phone.number,
        "from": call.caller,
        "to": call.callee,
    }
    try:
        spy = adapter.monitor_call(
            channel_id,
            phone.endpoint_name,
            body.mode,
            context=tenancy.names_of(db, phone.organization_id).spy,
            caller_id=f"Monitor {target.number} <{target.number}>",
            beep=bool(getattr(db.get(Organization, target.organization_id), "monitor_beep", False)),
        )
    except ValueError as e:
        raise conflict(str(e), "monitor_refused") from e
    except (EngineUnavailable, NotSupported) as e:
        raise conflict(f"The engine did not start monitoring: {e}", "monitor_failed") from e
    audit.record(
        db,
        action="call.monitor",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=target.organization_id,
        target_type="extension",
        target_id=target.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={**details, "supervisor_channel": spy},
    )
    db.commit()
    verb = {"listen": "listen to", "whisper": "whisper on", "barge": "join"}[body.mode]
    return MessageOut(message=f"Extension {phone.number} is ringing; answer it to {verb} the call.")
