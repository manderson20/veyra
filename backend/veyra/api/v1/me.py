# SPDX-License-Identifier: AGPL-3.0-or-later
"""The caller's own account data for clients such as the Companion
(docs/COMPANION.md §4): own extensions with registration state and the
preferences document. Available to sessions and to bearer tokens carrying
the ``me`` scope."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
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
    ClassOfService,
    Extension,
    FollowMe,
    Organization,
    UserPreference,
    VoicemailBox,
    VoicemailBoxMember,
)
from veyra.core.security.principal import Principal
from veyra.portal import contacts as portal_contacts
from veyra.portal import layouts as portal_layouts
from veyra.telephony import extension_state, features, routing
from veyra.telephony.numbering import load_numbering_plan
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
    changes = body.model_dump(exclude_unset=True)
    _check_forward_limits(db, ext, changes)
    try:
        details = extension_state.apply(
            db,
            ext,
            changes,
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


def _check_forward_limits(db: Session, ext: Extension, changes: dict[str, Any]) -> None:
    """The administrator's limits apply to self-service too (docs/USER_PORTAL.md
    §4): a class of service without outside forwards refuses a forward target
    longer than an extension number."""
    targets = {
        k: str(v or "") for k, v in changes.items() if k in ("cf_always", "cf_busy", "cf_no_answer")
    }
    if not any(targets.values()) or ext.class_of_service_id is None:
        return
    cos = db.get(ClassOfService, ext.class_of_service_id)
    if cos is None or cos.allow_external_forwards:
        return
    ext_len = load_numbering_plan(db).extension_length
    for field, value in targets.items():
        digits = re.sub(r"[\s().-]", "", value)
        if digits and len(digits.lstrip("+")) > ext_len:
            raise ProblemError(
                422,
                "Outside forwards not allowed",
                "Your phone's class of service does not allow forwarding to outside numbers; "
                "ask an administrator.",
                code="cos_denied",
                errors=[{"field": field, "message": "outside numbers are not allowed"}],
            )


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


class PresenceRule(BaseModel):
    """What happens when the user picks a presence state (docs/USER_PORTAL.md §7)."""

    model_config = ConfigDict(extra="forbid")
    dnd: bool | None = None
    # A forward target, "" to clear the forward, None to leave it alone.
    cf_always: str | None = None

    @field_validator("cf_always")
    @classmethod
    def _cf(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        v = re.sub(r"[\s().-]", "", v.strip())
        if not _NUMBER_RE.match(v):
            raise ValueError("digits only (a leading + is allowed)")
        return v


class PortalPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    presence_rules: dict[str, PresenceRule] = Field(default_factory=dict)
    # The user's own canvas (docs/USER_PORTAL.md §10), validated as a layout
    # document when set; None: the template (or the default) applies.
    layout: dict[str, Any] | None = None

    @field_validator("layout")
    @classmethod
    def _layout(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return portal_layouts.validate_layout(v) if v is not None else None

    @field_validator("presence_rules")
    @classmethod
    def _states(cls, v: dict[str, PresenceRule]) -> dict[str, PresenceRule]:
        bad = [k for k in v if k not in extension_state.PRESENCE_STATES]
        if bad:
            raise ValueError(f"unknown presence state {bad[0]!r}")
        return v


class PreferencesDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    companion: CompanionPreferences = Field(default_factory=CompanionPreferences)
    portal: PortalPreferences = Field(default_factory=PortalPreferences)


class PreferencesOut(BaseModel):
    companion: CompanionPreferences
    portal: PortalPreferences
    updated_at: datetime | None


def _load(db: Session, user_id: uuid.UUID) -> UserPreference | None:
    return db.get(UserPreference, user_id)


def _out(row: UserPreference | None) -> PreferencesOut:
    doc = PreferencesDoc.model_validate(row.data if row and row.data else {})
    return PreferencesOut(
        companion=doc.companion, portal=doc.portal, updated_at=row.updated_at if row else None
    )


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
    names = portal_contacts.names_by_number(db, principal.user_id)
    return vmsvc.list_messages(db, request.app.state.settings, box, folder, names)


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


# ------------------------------------------------- voicemail greetings (§3)


@router.get(
    "/voicemail/{box_id}/greetings",
    response_model=list[vmsvc.GreetingOut],
    summary="Your greetings (unavailable, busy, name, temporary)",
)
def my_greetings(
    box_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> list[vmsvc.GreetingOut]:
    box = _own_box(db, principal, box_id)
    return vmsvc.greeting_list(db, request.app.state.settings, box)


@router.get("/voicemail/{box_id}/greetings/{kind}/audio", summary="Listen to one of your greetings")
def my_greeting_audio(
    box_id: uuid.UUID,
    kind: str,
    request: Request,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> Response:
    box = _own_box(db, principal, box_id)
    media, data = vmsvc.greeting_audio(db, request.app.state.settings, box, kind)
    return Response(content=data, media_type=media, headers={"Cache-Control": "private, no-store"})


@router.put(
    "/voicemail/{box_id}/greetings/{kind}",
    response_model=list[vmsvc.GreetingOut],
    summary="Upload or record one of your greetings",
)
async def my_greeting_put(
    box_id: uuid.UUID,
    kind: str,
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> list[vmsvc.GreetingOut]:
    box = _own_box(db, principal, box_id)
    data = await file.read(vmsvc.audio_tools.MAX_COMPRESSED_BYTES + 1)
    duration = vmsvc.greeting_save(db, request.app.state.settings, box, kind, data, file.filename)
    _box_audit(
        db,
        ctx,
        principal,
        "voicemail.greeting_set",
        box,
        {"kind": kind, "duration_seconds": round(duration, 1), "filename": file.filename},
    )
    db.commit()
    return vmsvc.greeting_list(db, request.app.state.settings, box)


@router.delete(
    "/voicemail/{box_id}/greetings/{kind}",
    response_model=list[vmsvc.GreetingOut],
    summary="Remove one of your greetings (the phone system's default plays)",
)
def my_greeting_delete(
    box_id: uuid.UUID,
    kind: str,
    request: Request,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> list[vmsvc.GreetingOut]:
    box = _own_box(db, principal, box_id)
    if vmsvc.greeting_remove(db, request.app.state.settings, box, kind):
        _box_audit(db, ctx, principal, "voicemail.greeting_delete", box, {"kind": kind})
        db.commit()
    return vmsvc.greeting_list(db, request.app.state.settings, box)


# ------------------------------------------------- presence (§7)


class PresenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str = Field(pattern="^(" + "|".join(extension_state.PRESENCE_STATES) + ")$")
    message: str | None = Field(None, max_length=60)


class PresenceOut(BaseModel):
    state: str
    label: str
    message: str | None
    states: list[dict[str, str]]
    applied: dict[str, Any] = Field(default_factory=dict)


def _presence_out(row: Any, applied: dict[str, Any] | None = None) -> PresenceOut:
    state = (row.presence if row is not None else None) or "available"
    return PresenceOut(
        state=state,
        label=extension_state.PRESENCE_LABELS[state],
        message=row.presence_message if row is not None else None,
        states=[{"key": k, "label": v} for k, v in extension_state.PRESENCE_LABELS.items()],
        applied=applied or {},
    )


@router.get(
    "/extensions/{extension_id}/presence",
    response_model=PresenceOut,
    summary="The presence your colleagues see",
)
def my_presence(
    extension_id: uuid.UUID,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> PresenceOut:
    ext = _own_extension(db, principal, extension_id)
    return _presence_out(extension_state.get(db, ext.id))


@router.put(
    "/extensions/{extension_id}/presence",
    response_model=PresenceOut,
    summary="Set your presence (and its automatic actions)",
)
def put_my_presence(
    extension_id: uuid.UUID,
    body: PresenceIn,
    request: Request,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PresenceOut:
    ext = _own_extension(db, principal, extension_id)
    prefs = _load(db, principal.user_id)
    doc = PreferencesDoc.model_validate(prefs.data if prefs and prefs.data else {})
    rules = {k: v.model_dump() for k, v in doc.portal.presence_rules.items()}
    rule = rules.get(body.state) or {}
    if rule.get("cf_always"):
        _check_forward_limits(db, ext, {"cf_always": rule["cf_always"]})
    try:
        applied = extension_state.set_presence(
            db,
            ext,
            body.state,
            body.message,
            by="user",
            rules=rules,
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
    if applied:
        _own_audit(db, ctx, principal, "extension.presence_update", ext, applied)
    db.commit()
    return _presence_out(extension_state.get(db, ext.id), applied)


# ------------------------------------------------- portal layout (§10)


class LayoutOut(BaseModel):
    # The user's own layout when saved, else the template's, else none (the
    # interface then uses its built-in default).
    layout: dict[str, Any] | None
    source: Literal["user", "template", "default"]
    template_id: uuid.UUID | None
    template_name: str | None
    locked_widgets: list[str]


class LayoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layout: dict[str, Any]

    @field_validator("layout")
    @classmethod
    def _layout(cls, v: dict[str, Any]) -> dict[str, Any]:
        return portal_layouts.validate_layout(v)


def _layout_out(db: Session, principal: Principal) -> LayoutOut:
    prefs = _load(db, principal.user_id)
    doc = PreferencesDoc.model_validate(prefs.data if prefs and prefs.data else {})
    template = portal_layouts.resolve_template(db, principal.user_id, None)
    locked = list(template.locked_widgets or []) if template else []
    if doc.portal.layout:
        return LayoutOut(
            layout=doc.portal.layout,
            source="user",
            template_id=template.id if template else None,
            template_name=template.name if template else None,
            locked_widgets=locked,
        )
    if template is not None:
        return LayoutOut(
            layout=dict(template.layout or {}),
            source="template",
            template_id=template.id,
            template_name=template.name,
            locked_widgets=locked,
        )
    return LayoutOut(
        layout=None, source="default", template_id=None, template_name=None, locked_widgets=[]
    )


@router.get("/portal/layout", response_model=LayoutOut, summary="Your portal layout")
def my_layout(
    principal: Principal = Depends(require_me), db: Session = Depends(get_db)
) -> LayoutOut:
    return _layout_out(db, principal)


@router.put("/portal/layout", response_model=LayoutOut, summary="Save your portal layout")
def put_my_layout(
    body: LayoutIn,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> LayoutOut:
    template = portal_layouts.resolve_template(db, principal.user_id, None)
    locked = set(template.locked_widgets or []) if template else set()
    present = {w["key"] for t in body.layout["tabs"] for w in t["widgets"]}
    missing = sorted(locked - present)
    if missing:
        raise ProblemError(
            422,
            "Locked widget",
            f"The widget {missing[0]!r} is required by your administrators and cannot be removed.",
            code="widget_locked",
            errors=[{"field": "layout", "message": f"{missing[0]} is locked"}],
        )
    row = _load(db, principal.user_id)
    data: dict[str, Any] = dict(row.data or {}) if row else {}
    portal = dict(data.get("portal") or {})
    portal["layout"] = body.layout
    data["portal"] = portal
    if row is None:
        row = UserPreference(user_id=principal.user_id, data=data)
        db.add(row)
    else:
        row.data = data
    audit.record(
        db,
        action="portal.layout_update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=None,
        target_type="user",
        target_id=principal.user_id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={
            "self_service": True,
            "tabs": len(body.layout["tabs"]),
            "widgets": sum(len(t["widgets"]) for t in body.layout["tabs"]),
        },
    )
    db.commit()
    return _layout_out(db, principal)


@router.post("/portal/layout/reset", response_model=LayoutOut, summary="Back to the default layout")
def reset_my_layout(
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> LayoutOut:
    row = _load(db, principal.user_id)
    if row is not None and (row.data or {}).get("portal", {}).get("layout"):
        data = dict(row.data or {})
        portal = dict(data.get("portal") or {})
        portal.pop("layout", None)
        data["portal"] = portal
        row.data = data
        audit.record(
            db,
            action="portal.layout_reset",
            actor_user_id=principal.user_id,
            actor_label=principal.label,
            organization_id=None,
            target_type="user",
            target_id=principal.user_id,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"self_service": True},
        )
        db.commit()
    return _layout_out(db, principal)
