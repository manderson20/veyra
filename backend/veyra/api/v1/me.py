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

from veyra.api.v1.extensions import RegistrationOut, _registrations, installation_key
from veyra.api.v1.voicemail import set_pin
from veyra.configmgmt import service as configmgmt
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, current_principal, request_context
from veyra.core.errors import forbidden, not_found
from veyra.core.models import Extension, Organization, UserPreference, VoicemailBox
from veyra.core.security.principal import Principal
from veyra.telephony import routing

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
    extension_id: uuid.UUID
    extension_number: str
    extension_name: str
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
    rows = db.execute(
        select(VoicemailBox, Extension)
        .join(Extension, Extension.id == VoicemailBox.extension_id)
        .where(Extension.user_id == principal.user_id)
        .order_by(Extension.number)
    ).all()
    return [
        MyVoicemailOut(
            id=box.id,
            extension_id=ext.id,
            extension_number=ext.number,
            extension_name=ext.display_name,
            email=box.email,
            ring_seconds=box.ring_seconds,
            is_enabled=box.is_enabled,
        )
        for box, ext in rows
    ]


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
