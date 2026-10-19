# SPDX-License-Identifier: AGPL-3.0-or-later
"""The caller's own account data for clients such as the Companion
(docs/COMPANION.md §4): own extensions with registration state and the
preferences document. Available to sessions and to bearer tokens carrying
the ``me`` scope."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1.extensions import (
    FollowMeIn,
    RegistrationOut,
    _follow_me_out,
    _registrations,
    installation_key,
    save_follow_me,
)
from veyra.api.v1.voicemail import set_pin
from veyra.configmgmt import service as configmgmt
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, current_principal, request_context
from veyra.core.errors import ProblemError, forbidden, not_found
from veyra.core.models import (
    Extension,
    FollowMe,
    Organization,
    UserPreference,
    VoicemailBox,
    VoicemailBoxMember,
)
from veyra.core.security.principal import Principal
from veyra.telephony import extension_state, features, routing
from veyra.voicemail import service as vmsvc

router = APIRouter(prefix="/me", tags=["me"])

_NUMBER_RE = re.compile(r"^\+?[0-9*#]{1,32}$")


def require_me(principal: Principal = Depends(current_principal)) -> Principal:
    if not principal.has_scope("me"):
        raise forbidden()
    return principal


# ----------------------------------------------------------------- extensions


class MyExtensionOut(BaseModel):
    id: uuid.UUID
    number: str
    display_name: str
    organization_id: uuid.UUID
    organization_name: str
    is_enabled: bool
    registration: RegistrationOut | None


@router.get("/extensions", response_model=list[MyExtensionOut], summary="Your own extensions")
def my_extensions(
    request: Request,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> list[MyExtensionOut]:
    rows = db.scalars(
        select(Extension).where(Extension.user_id == principal.user_id).order_by(Extension.number)
    ).all()
    org_ids = {r.organization_id for r in rows}
    orgs = (
        {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids)))}
        if org_ids
        else {}
    )
    live = _registrations(request)
    return [
        MyExtensionOut(
            id=r.id,
            number=r.number,
            display_name=r.display_name,
            organization_id=r.organization_id,
            organization_name=orgs[r.organization_id].name if r.organization_id in orgs else "",
            is_enabled=r.is_enabled,
            registration=(
                live.get(r.endpoint_name, RegistrationOut(registered=False))
                if live is not None
                else None
            ),
        )
        for r in rows
    ]


# ------------------------------------------------ own phone (docs/CALL_FEATURES.md §3.9)


def _own_extension(db: Session, principal: Principal, extension_id: uuid.UUID) -> Extension:
    ext = db.scalar(
        select(Extension).where(
            Extension.id == extension_id, Extension.user_id == principal.user_id
        )
    )
    if ext is None:
        raise not_found("Extension")
    return ext


def _own_audit(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    ext: Extension,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=ext.organization_id,
        target_type="extension",
        target_id=ext.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"number": ext.number, "self_service": True, **details},
    )


class MyStateIn(BaseModel):
    """What a user may change on their own phone; the ring time stays with
    the administrator (it is in the dialplan)."""

    dnd: bool | None = None
    fmfm_enabled: bool | None = None
    cf_always: str | None = Field(None, max_length=32)
    cf_busy: str | None = Field(None, max_length=32)
    cf_no_answer: str | None = Field(None, max_length=32)


@router.get("/extensions/{extension_id}/state", summary="Your phone's Do Not Disturb and forwards")
def my_state(
    extension_id: uuid.UUID,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ext = _own_extension(db, principal, extension_id)
    return extension_state.out(extension_state.get(db, ext.id))


@router.put(
    "/extensions/{extension_id}/state", summary="Change your phone's Do Not Disturb or forwards"
)
def put_my_state(
    extension_id: uuid.UUID,
    body: MyStateIn,
    request: Request,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    ext = _own_extension(db, principal, extension_id)
    try:
        details = extension_state.apply(
            db,
            ext,
            body.model_dump(exclude_unset=True),
            by="user",
            adapter=getattr(request.app.state, "telephony", None),
        )
    except extension_state.StateError as e:
        raise ProblemError(
            422,
            "Validation failed",
            e.message,
            code="validation_failed",
            errors=[{"field": e.field, "message": e.message}],
        ) from e
    if details:
        _own_audit(db, ctx, principal, "extension.state_update", ext, details)
    db.commit()
    return extension_state.out(extension_state.get(db, ext.id))


@router.get("/extensions/{extension_id}/follow-me", summary="Your phone's find me / follow me")
def my_follow_me(
    extension_id: uuid.UUID,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ext = _own_extension(db, principal, extension_id)
    return _follow_me_out(db.get(FollowMe, ext.id), extension_state.get(db, ext.id))


@router.put(
    "/extensions/{extension_id}/follow-me", summary="Change your phone's find me / follow me"
)
def put_my_follow_me(
    extension_id: uuid.UUID,
    body: FollowMeIn,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    """Like the administrator's endpoint, the legs wait for a deployment; the
    change is recorded and shows as pending to administrators."""
    ext = _own_extension(db, principal, extension_id)
    row, details = save_follow_me(db, ext, body, by=principal.label)
    _own_audit(db, ctx, principal, "extension.follow_me_update", ext, details)
    configmgmt.mark_changed(db, by=principal.label, what=f"follow-me of {ext.number}")
    db.commit()
    return _follow_me_out(row, extension_state.get(db, ext.id))


@router.get("/feature-codes", summary="The feature codes you can dial")
def my_feature_codes(
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return {
        "codes": [
            {k: c[k] for k in ("key", "label", "description", "code", "takes_number")}
            for c in features.load(db)
            if c["enabled"]
        ],
        "fixed": dict(features.FIXED_CODES),
    }


# ----------------------------------------------------------------- preferences


class SpeedDial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=40)
    number: str = Field(min_length=1, max_length=32)

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a label")
        return v

    @field_validator("number")
    @classmethod
    def _number(cls, v: str) -> str:
        v = re.sub(r"[\s().-]", "", v.strip())
        if not _NUMBER_RE.match(v):
            raise ValueError("digits only (a leading + is allowed)")
        return v


class CompanionPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speed_dials: list[SpeedDial] = Field(default_factory=list, max_length=50)
    dial_prefix: str = Field("", max_length=8, pattern=r"^[0-9]*$")
    default_extension_id: uuid.UUID | None = None
    notify_incoming: bool = True
    notify_missed: bool = True
    handle_tel_links: bool = False


class PreferencesDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    companion: CompanionPreferences = Field(default_factory=CompanionPreferences)


class PreferencesOut(BaseModel):
    companion: CompanionPreferences
    updated_at: datetime | None


def _load(db: Session, user_id: uuid.UUID) -> UserPreference | None:
    return db.get(UserPreference, user_id)


def _out(row: UserPreference | None) -> PreferencesOut:
    doc = PreferencesDoc.model_validate(row.data if row and row.data else {})
    return PreferencesOut(companion=doc.companion, updated_at=row.updated_at if row else None)


@router.get("/preferences", response_model=PreferencesOut, summary="Your preferences")
def get_preferences(
    principal: Principal = Depends(require_me), db: Session = Depends(get_db)
) -> PreferencesOut:
    return _out(_load(db, principal.user_id))


@router.put("/preferences", response_model=PreferencesOut, summary="Replace your preferences")
def put_preferences(
    body: PreferencesDoc,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PreferencesOut:
    if body.companion.default_extension_id is not None:
        ext = db.get(Extension, body.companion.default_extension_id)
        if ext is None or ext.user_id != principal.user_id:
            body.companion.default_extension_id = None
    data: dict[str, Any] = body.model_dump(mode="json")
    row = _load(db, principal.user_id)
    if row is None:
        row = UserPreference(user_id=principal.user_id, data=data)
        db.add(row)
    else:
        row.data = data
    audit.record(
        db,
        action="user.preferences_update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="user",
        target_id=principal.user_id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"speed_dials": len(body.companion.speed_dials)},
    )
    db.commit()
    db.refresh(row)
    return _out(row)


# ----------------------------------------------------------------- voicemail


class MyVoicemailOut(BaseModel):
    id: uuid.UUID
    # A shared inbox (docs/VOICEMAIL_IVR.md §3.4) has no extension of its own;
    # it is listed when one of the caller's extensions is a member.
    shared: bool = False
    extension_id: uuid.UUID | None
    extension_number: str
    extension_name: str
    number: str
    name: str
    email: str | None
    ring_seconds: int
    is_enabled: bool


class PinIn(BaseModel):
    pin: str = Field(min_length=4, max_length=10)

    @field_validator("pin")
    @classmethod
    def _pin(cls, v: str) -> str:
        return routing.check_pin(v)


@router.get("/voicemail", response_model=list[MyVoicemailOut], summary="Your voicemail boxes")
def my_voicemail(
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> list[MyVoicemailOut]:
    return [_my_box_out(box, ext) for box, ext in _own_boxes(db, principal)]


def _own_boxes(db: Session, principal: Principal) -> list[tuple[VoicemailBox, Extension | None]]:
    """The caller's boxes: those of their extensions, then the shared inboxes
    one of their extensions is a member of."""
    rows = db.execute(
        select(VoicemailBox, Extension)
        .join(Extension, Extension.id == VoicemailBox.extension_id)
        .where(Extension.user_id == principal.user_id)
        .order_by(Extension.number)
    ).all()
    out: list[tuple[VoicemailBox, Extension | None]] = [(b, e) for b, e in rows]
    shared = db.scalars(
        select(VoicemailBox)
        .join(VoicemailBoxMember, VoicemailBoxMember.box_id == VoicemailBox.id)
        .join(Extension, Extension.id == VoicemailBoxMember.extension_id)
        .where(Extension.user_id == principal.user_id, VoicemailBox.extension_id.is_(None))
        .distinct()
        .order_by(VoicemailBox.number)
    ).all()
    out.extend((b, None) for b in shared)
    return out


def _my_box_out(box: VoicemailBox, ext: Extension | None) -> MyVoicemailOut:
    return MyVoicemailOut(
        id=box.id,
        shared=ext is None,
        extension_id=ext.id if ext else None,
        extension_number=ext.number if ext else (box.number or ""),
        extension_name=ext.display_name if ext else (box.name or "Shared inbox"),
        number=ext.number if ext else (box.number or ""),
        name=ext.display_name if ext else (box.name or "Shared inbox"),
        email=box.email,
        ring_seconds=box.ring_seconds,
        is_enabled=box.is_enabled,
    )


def _own_box(db: Session, principal: Principal, box_id: uuid.UUID) -> VoicemailBox:
    for box, _ in _own_boxes(db, principal):
        if box.id == box_id:
            return box
    raise not_found("Voicemail box")


def _box_audit(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    box: VoicemailBox,
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
        details={"self_service": True, **details},
    )


@router.post("/voicemail/{box_id}/pin", status_code=204, summary="Change your voicemail PIN")
def my_voicemail_pin(
    box_id: uuid.UUID,
    body: PinIn,
    request: Request,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    row = db.execute(
        select(VoicemailBox, Extension)
        .join(Extension, Extension.id == VoicemailBox.extension_id)
        .where(VoicemailBox.id == box_id, Extension.user_id == principal.user_id)
    ).first()
    if row is None:
        raise not_found("Voicemail box")
    box, ext = row
    set_pin(box, body.pin, installation_key(request))
    db.flush()
    audit.record(
        db,
        action="voicemail.pin_change",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=box.organization_id,
        target_type="voicemail_box",
        target_id=box.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"extension": ext.number},
    )
    # The PIN lives in voicemail.conf: the change reaches the phone system at
    # the next deployment.
    configmgmt.mark_changed(db, by=principal.label, what=f"voicemail.pin_change {ext.number}")
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------- voicemail messages (§2)


@router.get(
    "/voicemail/{box_id}/messages",
    response_model=vmsvc.MessagesOut,
    summary="Messages of one of your voicemail boxes",
)
def my_messages(
    box_id: uuid.UUID,
    request: Request,
    folder: str = "INBOX",
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> vmsvc.MessagesOut:
    box = _own_box(db, principal, box_id)
    return vmsvc.list_messages(db, request.app.state.settings, box, folder)


@router.get(
    "/voicemail/{box_id}/messages/{number}/audio",
    summary="Listen to one of your messages (audited)",
)
def my_message_audio(
    box_id: uuid.UUID,
    number: int,
    request: Request,
    folder: str = "INBOX",
    download: bool = False,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    box = _own_box(db, principal, box_id)
    media, data = vmsvc.audio(db, request.app.state.settings, box, folder, number)
    _box_audit(
        db,
        ctx,
        principal,
        "voicemail.message_download" if download else "voicemail.message_play",
        box,
        {"folder": folder, "number": number},
    )
    db.commit()
    headers = {"Cache-Control": "private, no-store"}
    if download:
        headers["Content-Disposition"] = (
            f'attachment; filename="voicemail-{folder.lower()}-{number:04d}.wav"'
        )
    return Response(content=data, media_type=media, headers=headers)


@router.post(
    "/voicemail/{box_id}/messages/{number}/move",
    summary="Move one of your messages to another folder",
)
def my_message_move(
    box_id: uuid.UUID,
    number: int,
    body: vmsvc.MoveIn,
    request: Request,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    box = _own_box(db, principal, box_id)
    out = vmsvc.move(db, request.app.state.settings, box, number, body)
    _box_audit(
        db,
        ctx,
        principal,
        "voicemail.message_move",
        box,
        {"folder": body.folder, "number": number, "to": body.to},
    )
    db.commit()
    return out


@router.post(
    "/voicemail/{box_id}/messages/{number}/forward",
    summary="Forward one of your messages to another box you can see",
)
def my_message_forward(
    box_id: uuid.UUID,
    number: int,
    body: vmsvc.ForwardIn,
    request: Request,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    box = _own_box(db, principal, box_id)
    # A user forwards within what they may see: their own boxes, or any box
    # of their organization by extension (a colleague's mailbox).
    target = db.get(VoicemailBox, body.box_id)
    if target is None or target.organization_id != box.organization_id:
        raise not_found("Voicemail box")
    out = vmsvc.forward(
        db, request.app.state.settings, box, number, body, target, f"{principal.label}"
    )
    _box_audit(
        db,
        ctx,
        principal,
        "voicemail.message_forward",
        box,
        {"folder": body.folder, "number": number, "to_box_id": str(target.id)},
    )
    db.commit()
    return out


@router.delete(
    "/voicemail/{box_id}/messages/{number}",
    status_code=204,
    summary="Delete one of your messages",
)
def my_message_delete(
    box_id: uuid.UUID,
    number: int,
    request: Request,
    folder: str = "INBOX",
    msg_id: str | None = None,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    box = _own_box(db, principal, box_id)
    vmsvc.delete(db, request.app.state.settings, box, folder, number, msg_id)
    _box_audit(
        db, ctx, principal, "voicemail.message_delete", box, {"folder": folder, "number": number}
    )
    db.commit()
    return Response(status_code=204)
