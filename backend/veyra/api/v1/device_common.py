# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared validation for device profiles and devices (docs/DEVICE_PROVISIONING.md):
template resolution, variable values, line keys and firmware."""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.errors import ProblemError
from veyra.core.models import CallFlow, FirmwareImage, PagingZone, ParkingLot, Site, TimeCondition
from veyra.provisioning.renderer import ResolvedTemplate, TemplateCatalog, coerce_one
from veyra.provisioning.spec import TemplateError

MAX_KEYS = 48
MAX_LINES = 8
# "user": a slot left to the phone's user (docs/USER_PORTAL.md §8); the
# administrator's other keys are locked for the user.
# M21 (docs/PROVISIONING_BREADTH.md §3): park, voicemail, transfer,
# intercom, dnd and toggle render as BLF or speed-dial keys any template
# understands; their lamps are hints the generator publishes.
KeyType = Literal[
    "line",
    "blf",
    "speed_dial",
    "page",
    "user",
    "park",
    "voicemail",
    "transfer",
    "intercom",
    "dnd",
    "toggle",
]
_TOGGLE_RE = re.compile(r"^(flow:[a-z0-9]+(?:-[a-z0-9]+)*|tc:[0-9a-f-]{36}|agent)$")
_PARK_RE = re.compile(r"^([a-z0-9]+(?:-[a-z0-9]+)*)(?::([0-9]{1,6}))?$")
_NUMBER_RE = re.compile(r"^[0-9*#+]{1,32}$")
# A key value naming a provisioning variable (docs/PROVISIONING_BREADTH.md §2.3).
REF_RE = re.compile(r"^\$[a-z][a-z0-9_]{0,39}$")
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


class LineKey(BaseModel):
    """One programmable key (§4.2): a registration, a BLF lamp, a speed dial
    or a paging zone."""

    type: KeyType
    label: str | None = Field(None, max_length=40)
    value: str = Field("", max_length=64)

    @field_validator("label")
    @classmethod
    def _label(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if any(ord(c) < 32 for c in v):
            raise ValueError("contains control characters")
        return v or None

    @field_validator("value")
    @classmethod
    def _value(cls, v: str) -> str:
        return v.strip()


def check_keys(db: Session, organization_id: uuid.UUID, keys: list[LineKey], field: str) -> None:
    if len(keys) > MAX_KEYS:
        raise validation(field, f"at most {MAX_KEYS} keys")
    zone_slugs: set[str] | None = None
    for i, key in enumerate(keys, 1):
        if key.type == "user":
            continue  # an open slot has no target of its own
        if REF_RE.match(key.value.strip()):
            continue  # "$name": a provisioning variable, resolved per phone
        if key.type == "line":
            if not key.value.isdigit() or not 1 <= int(key.value) <= MAX_LINES:
                raise validation(field, f"key {i}: a line key names a line number 1-{MAX_LINES}")
        elif key.type in ("blf", "speed_dial", "intercom"):
            if not _NUMBER_RE.match(key.value):
                raise validation(field, f"key {i}: enter a number to dial or watch")
        elif key.type in ("dnd", "transfer"):
            continue  # no target: the phone's own line
        elif key.type == "voicemail":
            if key.value and not (key.value.isdigit() and 1 <= int(key.value) <= MAX_LINES):
                raise validation(field, f"key {i}: a voicemail key names a line number or nothing")
        elif key.type == "toggle":
            if not _TOGGLE_RE.match(key.value):
                raise validation(
                    field, f"key {i}: a toggle is flow:<call flow>, tc:<time condition> or agent"
                )
            check_toggle_target(db, organization_id, key.value, field, i)
        elif key.type == "park":
            m = _PARK_RE.match(key.value)
            if m is None:
                raise validation(field, f"key {i}: a park key names a parking lot (and a slot)")
            lot = db.scalar(
                select(ParkingLot).where(
                    ParkingLot.organization_id == organization_id, ParkingLot.slug == m.group(1)
                )
            )
            if lot is None:
                raise validation(field, f"key {i}: parking lot {m.group(1)!r} not found")
            if m.group(2) and not lot.slot_first <= int(m.group(2)) <= lot.slot_last:
                raise validation(
                    field, f"key {i}: slot {m.group(2)} is not in {lot.slot_first}-{lot.slot_last}"
                )
        else:
            if zone_slugs is None:
                zone_slugs = set(
                    db.scalars(
                        select(PagingZone.slug).where(PagingZone.organization_id == organization_id)
                    )
                )
            if key.value not in zone_slugs:
                raise validation(field, f"key {i}: paging zone {key.value!r} not found")


def check_toggle_target(
    db: Session, organization_id: uuid.UUID, value: str, field: str, i: int
) -> None:
    if value.startswith("flow:"):
        flow = db.scalar(
            select(CallFlow).where(
                CallFlow.organization_id == organization_id, CallFlow.slug == value[5:]
            )
        )
        if flow is None:
            raise validation(field, f"key {i}: call flow {value[5:]!r} not found")
    elif value.startswith("tc:"):
        try:
            tc = db.get(TimeCondition, uuid.UUID(value[3:]))
        except ValueError:
            tc = None
        if tc is None or tc.organization_id != organization_id:
            raise validation(field, f"key {i}: time condition not found")
        if tc.code_index is None:
            raise validation(field, f"key {i}: the time condition {tc.name} has no override code")


def resolve_template(catalog: TemplateCatalog, key: str, field: str) -> ResolvedTemplate:
    try:
        return catalog.resolve(key)
    except TemplateError as e:
        raise validation(field, str(e)) from e


def check_values(resolved: ResolvedTemplate, values: dict[str, Any], field: str) -> dict[str, Any]:
    """Provided values only (a profile need not fill every required variable:
    lines come from the device); sensitive core values cannot be stored."""
    out: dict[str, Any] = {}
    for name, raw in values.items():
        var = resolved.variables.get(name)
        if var is None:
            raise validation(field, f"unknown variable {name!r}")
        if name == "sip_password":
            raise validation(field, "the SIP secret comes from the extension")
        if raw is None or raw == "":
            continue
        try:
            out[name] = coerce_one(var, raw)
        except (ValueError, TypeError) as e:
            raise validation(field, f"{name} {e}") from e
    return out


def check_site(db: Session, organization_id: uuid.UUID, site_id: uuid.UUID | None) -> None:
    if site_id is None:
        return
    site = db.get(Site, site_id)
    if site is None or site.organization_id != organization_id:
        raise validation("site_id", "site not found in this organization")


def check_firmware(db: Session, image_id: uuid.UUID | None, manufacturer: str | None) -> None:
    if image_id is None:
        return
    image = db.get(FirmwareImage, image_id)
    if image is None:
        raise validation("firmware_image_id", "firmware image not found")
    if manufacturer and image.manufacturer.lower() != manufacturer.lower():
        raise validation("firmware_image_id", f"this image is for {image.manufacturer} devices")


def model_templates(catalog: TemplateCatalog, family_key: str, model: str) -> list[str]:
    """Concrete templates under ``family_key`` (itself included) that support
    ``model``; local templates first, then the closest descendants."""
    matches: list[tuple[int, int, str]] = []
    for rec in catalog.records.values():
        t = rec.manifest.template
        if t.abstract or model not in t.models:
            continue
        depth = 0
        cur: str | None = t.key
        found = False
        while cur is not None:
            if cur == family_key:
                found = True
                break
            parent = catalog.records.get(cur)
            cur = parent.manifest.template.parent if parent else None
            depth += 1
            if depth > 8:
                break
        if found:
            matches.append((0 if rec.source == "local" else 1, depth, t.key))
    return [k for _, _, k in sorted(matches)]


def catalog_models(catalog: TemplateCatalog) -> dict[str, list[str]]:
    out: dict[str, set[str]] = {}
    for rec in catalog.records.values():
        t = rec.manifest.template
        if t.abstract:
            continue
        out.setdefault(t.manufacturer, set()).update(t.models)
    return {m: sorted(v) for m, v in sorted(out.items())}


def slug_ok(value: str) -> bool:
    return bool(_SLUG_RE.match(value))
