# SPDX-License-Identifier: AGPL-3.0-or-later
"""The user's own phones and the keys they may set (docs/USER_PORTAL.md §8):
the slots a device profile (or the device's own key list) marks ``user``;
every other key is the administrator's and locked."""

from __future__ import annotations

import contextlib
import re
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1.me import _own_audit, require_me
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, forbidden, not_found
from veyra.core.models import CallQueue, Device, DeviceProfile, Extension, RingGroup, UserContact
from veyra.core.models.base import utcnow
from veyra.core.security.principal import Principal
from veyra.provisioning import facts
from veyra.telephony.asterisk import cli

router = APIRouter(prefix="/me/devices", tags=["me"])

_NUMBER_RE = re.compile(r"^\+?[0-9*#]{1,32}$")


class UserKeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["speed_dial", "blf", "presence"]
    label: str | None = Field(None, max_length=40)
    value: str = Field(min_length=1, max_length=40)
    # A contact of the user: its first number becomes the value and its name the label.
    contact_id: uuid.UUID | None = None

    @field_validator("label")
    @classmethod
    def _label(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None

    @field_validator("value")
    @classmethod
    def _value(cls, v: str) -> str:
        v = re.sub(r"[\s().-]", "", v.strip())
        if not _NUMBER_RE.match(v):
            raise ValueError("digits (and a leading +) only")
        return v


class UserKeysIn(BaseModel):
    """The user's slots: ``{"<slot index>": key | null}``; a missing or null
    slot is emptied."""

    model_config = ConfigDict(extra="forbid")
    keys: dict[str, UserKeyIn | None] = Field(default_factory=dict)


class SlotOut(BaseModel):
    index: int
    # locked: the administrator's key; user: the user's slot (filled or empty).
    kind: Literal["locked", "user"]
    type: str | None
    label: str | None
    value: str | None


class MyDeviceOut(BaseModel):
    id: uuid.UUID
    label: str | None
    manufacturer: str
    model: str
    mac_display: str
    extension_id: uuid.UUID
    extension_number: str
    profile_name: str | None
    slots: list[SlotOut]
    user_slots: int


def _own_devices(db: Session, principal: Principal) -> list[tuple[Device, Extension]]:
    rows = db.execute(
        select(Device, Extension)
        .join(Extension, Extension.id == Device.primary_extension_id)
        .where(Extension.user_id == principal.user_id)
        .order_by(Extension.number, Device.label)
    ).all()
    return [(d, e) for d, e in rows]


def _own_device(
    db: Session, principal: Principal, device_id: uuid.UUID
) -> tuple[Device, Extension]:
    for d, e in _own_devices(db, principal):
        if d.id == device_id:
            return d, e
    raise not_found("Phone")


def _raw_keys(db: Session, device: Device) -> list[dict[str, Any]]:
    if device.keys is not None:
        return list(device.keys)
    profile = db.get(DeviceProfile, device.profile_id) if device.profile_id else None
    return list(profile.keys_for(device.model)) if profile else []


def _mac_display(mac: str) -> str:
    return ":".join(mac[i : i + 2] for i in range(0, len(mac), 2)).upper()


def _out(db: Session, device: Device, ext: Extension) -> MyDeviceOut:
    raw = _raw_keys(db, device)
    merged = facts.merge_user_keys(raw, device.user_keys)
    slots: list[SlotOut] = []
    for i, (orig, k) in enumerate(zip(raw, merged, strict=True), 1):
        if str(orig.get("type") or "") == "user":
            filled = str(k.get("type") or "") != "user"
            slots.append(
                SlotOut(
                    index=i,
                    kind="user",
                    type=k.get("type") if filled else None,
                    label=k.get("label") if filled else None,
                    value=str(k.get("value") or "") if filled else None,
                )
            )
        else:
            slots.append(
                SlotOut(
                    index=i,
                    kind="locked",
                    type=str(orig.get("type") or ""),
                    label=orig.get("label"),
                    value=str(orig.get("value") or ""),
                )
            )
    profile = db.get(DeviceProfile, device.profile_id) if device.profile_id else None
    return MyDeviceOut(
        id=device.id,
        label=device.label,
        manufacturer=device.manufacturer,
        model=device.model,
        mac_display=_mac_display(device.mac_address),
        extension_id=ext.id,
        extension_number=ext.number,
        profile_name=profile.name if profile else None,
        slots=slots,
        user_slots=sum(1 for s in slots if s.kind == "user"),
    )


@router.get("", response_model=list[MyDeviceOut], summary="Your phones and their keys")
def my_devices(
    principal: Principal = Depends(require_me), db: Session = Depends(get_db)
) -> list[MyDeviceOut]:
    return [_out(db, d, e) for d, e in _own_devices(db, principal)]


def _check_targets(db: Session, owner_id: Any, ext: Extension, body: UserKeysIn) -> None:
    """A BLF watches an extension, ring group or queue of the user's
    organization; a speed dial is any dialable number or a contact."""
    org = ext.organization_id
    wanted_blf = {k.value for k in body.keys.values() if k and k.type == "blf"}
    if wanted_blf:
        known = set(
            db.scalars(
                select(Extension.number).where(
                    Extension.organization_id == org, Extension.number.in_(wanted_blf)
                )
            )
        )
        for model in (RingGroup, CallQueue):
            known |= set(
                db.scalars(
                    select(model.number).where(
                        model.organization_id == org, model.number.in_(wanted_blf)
                    )
                )
            )
        missing = sorted(wanted_blf - known)
        if missing:
            raise ProblemError(
                422,
                "Unknown number",
                f"{missing[0]} is not an extension, ring group or queue of your organization.",
                code="validation_failed",
                errors=[{"field": "keys", "message": f"{missing[0]}: not a number you can watch"}],
            )
    wanted_presence = {k.value for k in body.keys.values() if k and k.type == "presence"}
    if wanted_presence:
        extensions = set(
            db.scalars(
                select(Extension.number).where(
                    Extension.organization_id == org, Extension.number.in_(wanted_presence)
                )
            )
        )
        missing = sorted(wanted_presence - extensions)
        if missing:
            raise ProblemError(
                422,
                "Unknown number",
                f"{missing[0]} is not an extension of your organization.",
                code="validation_failed",
                errors=[{"field": "keys", "message": f"{missing[0]}: presence is of extensions"}],
            )
    for slot, k in body.keys.items():
        if k and k.contact_id is not None:
            contact = db.get(UserContact, k.contact_id)
            if contact is None or contact.user_id != owner_id:
                raise ProblemError(
                    422,
                    "Unknown contact",
                    f"Slot {slot}: the contact does not exist.",
                    code="validation_failed",
                    errors=[{"field": "keys", "message": f"slot {slot}: unknown contact"}],
                )


def apply_user_keys(
    db: Session, device: Device, ext: Extension, body: UserKeysIn
) -> tuple[dict[str, Any], set[str]]:
    """Validate and store the user's slots of a phone (the user on My Phone,
    or an administrator for them, issue #136); returns them and the open slots."""
    raw = _raw_keys(db, device)
    user_slots = {str(i) for i, k in enumerate(raw, 1) if str(k.get("type") or "") == "user"}
    for slot in body.keys:
        if slot not in user_slots:
            raise ProblemError(
                422,
                "Locked key",
                f"Key {slot} is set by an administrator and cannot be changed.",
                code="slot_locked",
                errors=[{"field": "keys", "message": f"slot {slot} is locked"}],
            )
    _check_targets(db, ext.user_id, ext, body)
    new: dict[str, Any] = {}
    for slot, k in body.keys.items():
        if k is None:
            continue
        entry: dict[str, Any] = {"type": k.type, "label": k.label, "value": k.value}
        if k.contact_id is not None:
            contact = db.get(UserContact, k.contact_id)
            if contact is not None:
                numbers = contact.numbers or []
                if numbers and not k.value:
                    entry["value"] = str(numbers[0].get("number") or "")
                entry["label"] = k.label or contact.name
                entry["contact_id"] = str(contact.id)
        new[slot] = entry
    device.user_keys = new
    device.config_changed_at = utcnow()
    return new, user_slots


@router.put("/{device_id}/keys", response_model=MyDeviceOut, summary="Set your keys on a phone")
def put_my_keys(
    device_id: uuid.UUID,
    body: UserKeysIn,
    request: Request,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MyDeviceOut:
    device, ext = _own_device(db, principal, device_id)
    new, user_slots = apply_user_keys(db, device, ext, body)
    _own_audit(
        db,
        ctx,
        principal,
        "device.user_keys",
        ext,
        {"device_id": str(device.id), "slots": sorted(new), "user_slots": len(user_slots)},
    )
    db.commit()
    db.refresh(device)
    # The phone fetches its configuration again (best effort; the next
    # reboot or resync applies it otherwise).
    if getattr(request.app.state, "telephony", None) is not None:
        with contextlib.suppress(Exception):
            cli.send_notify("check_config", ext.endpoint_name)
    return _out(db, device, ext)


# ---------------------------------------------------------------- administrators

admin_router = APIRouter(prefix="/devices", tags=["devices"])


def _admin_device(
    db: Session, principal: Principal, device_id: uuid.UUID, perm: str
) -> tuple[Device, Extension]:
    device = db.get(Device, device_id)
    if device is None or not principal.has("devices.read", device.organization_id):
        raise not_found("Phone")
    if not principal.has(perm, device.organization_id):
        raise forbidden()
    ext = db.get(Extension, device.primary_extension_id) if device.primary_extension_id else None
    if ext is None:
        raise ProblemError(
            409,
            "No extension",
            "The phone has no extension, so it has no user keys.",
            code="no_extension",
        )
    return device, ext


@admin_router.get(
    "/{device_id}/user-keys", response_model=MyDeviceOut, summary="The user's own keys on a phone"
)
def get_user_keys(
    device_id: uuid.UUID,
    principal: Principal = Depends(require("devices.read")),
    db: Session = Depends(get_db),
) -> MyDeviceOut:
    device, ext = _admin_device(db, principal, device_id, "devices.read")
    return _out(db, device, ext)


@admin_router.put(
    "/{device_id}/user-keys",
    response_model=MyDeviceOut,
    summary="Set or clear the user's own keys on a phone (administrators)",
)
def put_user_keys(
    device_id: uuid.UUID,
    body: UserKeysIn,
    request: Request,
    principal: Principal = Depends(require("devices.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MyDeviceOut:
    """The same slots the user fills on My Phone (issue #136): an administrator
    fixes a wrong key or clears a slot without changing the profile."""
    device, ext = _admin_device(db, principal, device_id, "devices.write")
    new, user_slots = apply_user_keys(db, device, ext, body)
    audit.record(
        db,
        action="device.user_keys",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=device.organization_id,
        target_type="device",
        target_id=device.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"slots": sorted(new), "user_slots": len(user_slots), "by_administrator": True},
    )
    db.commit()
    db.refresh(device)
    if getattr(request.app.state, "telephony", None) is not None:
        with contextlib.suppress(Exception):
            cli.send_notify("check_config", ext.endpoint_name)
    return _out(db, device, ext)
