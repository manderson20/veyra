# SPDX-License-Identifier: AGPL-3.0-or-later
"""Devices (docs/DEVICE_PROVISIONING.md §2): physical phones registered by MAC
address with a profile, an extension, extra lines, key and value overrides,
a per-device provisioning credential and the status of their last fetch."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import device_common as common
from veyra.api.v1.device_common import LineKey
from veyra.api.v1.enrollment import device_purpose, new_secret
from veyra.api.v1.extensions import installation_key
from veyra.api.v1.provisioning import catalog_for
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import conflict, forbidden, not_found
from veyra.core.models import (
    Device,
    DeviceProfile,
    Extension,
    FirmwareImage,
    Organization,
    ProvisioningRequest,
    Site,
)
from veyra.core.models.base import utcnow
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.crypto import try_load_installation_key
from veyra.core.security.principal import Principal
from veyra.provisioning import facts
from veyra.provisioning.renderer import normalize_mac
from veyra.provisioning.spec import TemplateError

router = APIRouter(prefix="/devices", tags=["devices"])

READ = "devices.read"
WRITE = "devices.write"
# Poly phones poll once a day (docs/DEVICE_PROVISIONING.md §4.4); a device
# unseen for two polling intervals is stale.
POLLING_HOURS = 24
Status = Literal["never", "provisioned", "stale", "error"]


def _mac(v: str) -> str:
    try:
        return normalize_mac(v)
    except TemplateError as e:
        raise ValueError(str(e)) from e


def _token(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("enter a value")
    if any(ord(c) < 32 for c in v):
        raise ValueError("contains control characters")
    return v


class DeviceIn(BaseModel):
    organization_id: uuid.UUID
    mac_address: str = Field(max_length=32)
    manufacturer: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=64)
    label: str | None = Field(None, max_length=200)
    site_id: uuid.UUID | None = None
    profile_id: uuid.UUID | None = None
    primary_extension_id: uuid.UUID | None = None
    lines: list[uuid.UUID] = Field(default_factory=list, max_length=common.MAX_LINES - 1)
    keys: list[LineKey] | None = Field(None, max_length=common.MAX_KEYS)
    values: dict[str, Any] = Field(default_factory=dict)
    firmware_image_id: uuid.UUID | None = None
    is_enabled: bool = True

    @field_validator("mac_address")
    @classmethod
    def _mac_v(cls, v: str) -> str:
        return _mac(v)

    @field_validator("manufacturer", "model")
    @classmethod
    def _tok(cls, v: str) -> str:
        return _token(v)

    @field_validator("label")
    @classmethod
    def _label(cls, v: str | None) -> str | None:
        return _token(v) if v and v.strip() else None


class DevicePatch(BaseModel):
    mac_address: str | None = Field(None, max_length=32)
    manufacturer: str | None = Field(None, min_length=1, max_length=64)
    model: str | None = Field(None, min_length=1, max_length=64)
    label: str | None = Field(None, max_length=200)
    site_id: uuid.UUID | None = None
    profile_id: uuid.UUID | None = None
    primary_extension_id: uuid.UUID | None = None
    lines: list[uuid.UUID] | None = Field(None, max_length=common.MAX_LINES - 1)
    keys: list[LineKey] | None = Field(None, max_length=common.MAX_KEYS)
    values: dict[str, Any] | None = None
    firmware_image_id: uuid.UUID | None = None
    is_enabled: bool | None = None

    @field_validator("mac_address")
    @classmethod
    def _mac_v(cls, v: str | None) -> str | None:
        return _mac(v) if v is not None else None

    @field_validator("manufacturer", "model")
    @classmethod
    def _tok(cls, v: str | None) -> str | None:
        return _token(v) if v is not None else None

    @field_validator("label")
    @classmethod
    def _label(cls, v: str | None) -> str | None:
        return _token(v) if v and v.strip() else None


class ExtensionRef(BaseModel):
    id: uuid.UUID
    number: str
    display_name: str
    is_enabled: bool


class FirmwareRef(BaseModel):
    id: uuid.UUID
    version: str
    filename: str
    source: Literal["device", "profile"]


class DeviceOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    site_id: uuid.UUID | None
    site_name: str | None
    mac_address: str
    mac_display: str
    manufacturer: str
    model: str
    label: str | None
    profile_id: uuid.UUID | None
    profile_name: str | None
    # Concrete template the profile resolves to for this model.
    template_key: str | None
    extension: ExtensionRef | None
    lines: list[ExtensionRef]
    keys: list[LineKey] | None
    values: dict[str, Any]
    firmware: FirmwareRef | None
    firmware_reported: str | None
    firmware_state: Literal["unknown", "up_to_date", "pending", "none"]
    is_enabled: bool
    status: Status
    last_seen_at: datetime | None
    last_seen_ip: str | None
    last_user_agent: str | None
    last_result: str | None
    credential_user: str
    problems: list[str]
    created_at: datetime
    updated_at: datetime


class UnregisteredOut(BaseModel):
    mac_address: str
    mac_display: str
    organization_id: uuid.UUID | None
    organization_name: str | None
    ip_address: str | None
    user_agent: str | None
    manufacturer: str | None
    model: str | None
    last_seen_at: datetime
    requests: int


def mac_display(mac: str) -> str:
    return ":".join(mac[i : i + 2] for i in range(0, 12, 2))


def credential_user(mac: str) -> str:
    return f"dev-{mac}"


def parse_user_agent(ua: str | None) -> tuple[str | None, str | None, str | None]:
    """Manufacturer, model and firmware from a phone's User-Agent, e.g.
    ``PolycomVVX-VVX_411-UA/6.4.5.1234`` or ``Poly/VVX_450/7.2.0.1234``."""
    if not ua:
        return None, None, None
    text = ua.strip()
    if text.lower().startswith(("polycomvvx", "poly/", "polycom")):
        parts = text.replace("/", "-").split("-")
        model = next((p.replace("_", " ") for p in parts if p.upper().startswith("VVX")), None)
        version = next((p for p in parts if p[:1].isdigit() and "." in p), None)
        return "Poly", model, version
    if text.lower().startswith("yealink"):
        parts = text.split()
        model = parts[1] if len(parts) > 1 else None
        version = parts[2] if len(parts) > 2 else None
        return "Yealink", model, version
    return None, None, None


def _visible(principal: Principal, perm: str) -> Select[Device]:
    stmt = select(Device)
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(Device.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _get(db: Session, principal: Principal, device_id: uuid.UUID, perm: str) -> Device:
    device = db.scalar(_visible(principal, perm).where(Device.id == device_id))
    if device is None:
        raise not_found("Device")
    return device


def status_of(device: Device, now: datetime | None = None) -> Status:
    if device.last_seen_at is None:
        return "never"
    if device.last_result not in ("ok", "uploaded"):
        return "error"
    now = now or utcnow()
    if device.last_seen_at < now - timedelta(hours=2 * POLLING_HOURS):
        return "stale"
    return "provisioned"


def _outs(request: Request, db: Session, rows: list[Device]) -> list[DeviceOut]:
    if not rows:
        return []
    catalog = catalog_for(request, db)
    orgs = {
        o.id: o.name
        for o in db.scalars(
            select(Organization).where(Organization.id.in_({r.organization_id for r in rows}))
        )
    }
    site_ids = {r.site_id for r in rows if r.site_id}
    sites = (
        {s.id: s.name for s in db.scalars(select(Site).where(Site.id.in_(site_ids)))}
        if site_ids
        else {}
    )
    profile_ids = {r.profile_id for r in rows if r.profile_id}
    profiles = (
        {
            p.id: p
            for p in db.scalars(select(DeviceProfile).where(DeviceProfile.id.in_(profile_ids)))
        }
        if profile_ids
        else {}
    )
    ext_ids: set[uuid.UUID] = set()
    for r in rows:
        if r.primary_extension_id:
            ext_ids.add(r.primary_extension_id)
        for line in r.lines:
            try:
                ext_ids.add(uuid.UUID(str(line.get("extension_id"))))
            except (ValueError, AttributeError):
                continue
    exts = (
        {e.id: e for e in db.scalars(select(Extension).where(Extension.id.in_(ext_ids)))}
        if ext_ids
        else {}
    )
    fw_ids = {r.firmware_image_id for r in rows if r.firmware_image_id} | {
        p.firmware_image_id for p in profiles.values() if p.firmware_image_id
    }
    firmware = (
        {f.id: f for f in db.scalars(select(FirmwareImage).where(FirmwareImage.id.in_(fw_ids)))}
        if fw_ids
        else {}
    )
    now = utcnow()
    out = []
    for r in rows:
        problems: list[str] = []
        profile = profiles.get(r.profile_id) if r.profile_id else None
        template_key = None
        if profile is None:
            problems.append("No profile: nothing is served to this phone.")
        else:
            rec = catalog.records.get(profile.template_key)
            if rec is None:
                problems.append(f"Template {profile.template_key} of the profile is missing.")
            elif rec.manifest.template.abstract:
                found = common.model_templates(catalog, profile.template_key, r.model)
                if found:
                    template_key = found[0]
                else:
                    problems.append(
                        f"No template under {profile.template_key} supports model {r.model}."
                    )
            elif r.model not in rec.manifest.template.models:
                problems.append(f"Template {profile.template_key} does not support {r.model}.")
            else:
                template_key = profile.template_key

        def ref(ext_id: uuid.UUID | None) -> ExtensionRef | None:
            e = exts.get(ext_id) if ext_id else None
            if e is None:
                return None
            return ExtensionRef(
                id=e.id, number=e.number, display_name=e.display_name, is_enabled=e.is_enabled
            )

        primary = ref(r.primary_extension_id)
        if r.primary_extension_id and primary is None:
            problems.append("The extension of line 1 no longer exists.")
        lines: list[ExtensionRef] = []
        for line in r.lines:
            try:
                lref = ref(uuid.UUID(str(line.get("extension_id"))))
            except (ValueError, AttributeError):
                lref = None
            if lref is not None:
                lines.append(lref)
        if primary is None:
            problems.append("No extension: the phone will not register.")
        fw_id = r.firmware_image_id or (profile.firmware_image_id if profile else None)
        fw = firmware.get(fw_id) if fw_id else None
        fw_ref = (
            FirmwareRef(
                id=fw.id,
                version=fw.version,
                filename=fw.filename,
                source="device" if r.firmware_image_id else "profile",
            )
            if fw
            else None
        )
        if fw_ref is None:
            fw_state: Literal["unknown", "up_to_date", "pending", "none"] = "none"
        elif not r.firmware_reported:
            fw_state = "unknown"
        elif r.firmware_reported == fw_ref.version:
            fw_state = "up_to_date"
        else:
            fw_state = "pending"
        out.append(
            DeviceOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=orgs.get(r.organization_id, ""),
                site_id=r.site_id,
                site_name=sites.get(r.site_id) if r.site_id else None,
                mac_address=r.mac_address,
                mac_display=mac_display(r.mac_address),
                manufacturer=r.manufacturer,
                model=r.model,
                label=r.label,
                profile_id=r.profile_id,
                profile_name=profile.name if profile else None,
                template_key=template_key,
                extension=primary,
                lines=lines,
                keys=[LineKey.model_validate(k) for k in r.keys] if r.keys is not None else None,
                values=dict(r.values),
                firmware=fw_ref,
                firmware_reported=r.firmware_reported,
                firmware_state=fw_state,
                is_enabled=r.is_enabled,
                status=status_of(r, now),
                last_seen_at=r.last_seen_at,
                last_seen_ip=r.last_seen_ip,
                last_user_agent=r.last_user_agent,
                last_result=r.last_result,
                credential_user=credential_user(r.mac_address),
                problems=problems,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _check_profile(
    db: Session, organization_id: uuid.UUID, profile_id: uuid.UUID | None
) -> DeviceProfile | None:
    if profile_id is None:
        return None
    profile = db.get(DeviceProfile, profile_id)
    if profile is None or profile.organization_id != organization_id:
        raise common.validation("profile_id", "device profile not found in this organization")
    return profile


def _check_extensions(
    db: Session, organization_id: uuid.UUID, primary: uuid.UUID | None, lines: list[uuid.UUID]
) -> None:
    wanted = ([primary] if primary else []) + list(lines)
    if len(set(wanted)) != len(wanted):
        raise common.validation("lines", "an extension is listed twice")
    if not wanted:
        return
    found = {e.id: e for e in db.scalars(select(Extension).where(Extension.id.in_(wanted)))}
    for ext_id in wanted:
        e = found.get(ext_id)
        if e is None or e.organization_id != organization_id:
            field = "primary_extension_id" if ext_id == primary else "lines"
            raise common.validation(field, "extension not found in this organization")


def _check_values(
    request: Request, db: Session, profile: DeviceProfile | None, values: dict[str, Any]
) -> dict[str, Any]:
    if not values:
        return {}
    if profile is None:
        raise common.validation("values", "choose a profile before overriding values")
    resolved = common.resolve_template(catalog_for(request, db), profile.template_key, "profile_id")
    return common.check_values(resolved, values, "values")


def _record(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    device: Device,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=device.organization_id,
        target_type="device",
        target_id=device.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"mac": device.mac_address, "model": device.model, **details},
    )


def _mac_conflict(e: IntegrityError, db: Session) -> Exception:
    db.rollback()
    return conflict("A device with that MAC address is already registered.", "mac_in_use")


@router.get(
    "/unregistered", response_model=list[UnregisteredOut], summary="Phones seen but not registered"
)
def unregistered(
    request: Request,
    organization_id: uuid.UUID | None = None,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> list[UnregisteredOut]:
    since = utcnow() - timedelta(days=7)
    stmt = (
        select(ProvisioningRequest)
        .where(
            ProvisioningRequest.result == "unknown_device",
            ProvisioningRequest.at >= since,
            ProvisioningRequest.mac.is_not(None),
        )
        .order_by(ProvisioningRequest.at.desc())
    )
    orgs = principal.organization_ids_with(READ)
    if orgs is not None:
        stmt = stmt.where(ProvisioningRequest.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    if organization_id:
        stmt = stmt.where(ProvisioningRequest.organization_id == organization_id)
    registered = set(db.scalars(select(Device.mac_address)))
    seen: dict[str, UnregisteredOut] = {}
    org_names = {o.id: o.name for o in db.scalars(select(Organization))}
    for req in db.scalars(stmt.limit(2000)):
        assert req.mac is not None
        if req.mac in registered:
            continue
        if req.mac in seen:
            seen[req.mac].requests += 1
            continue
        manufacturer, model, _ = parse_user_agent(req.user_agent)
        seen[req.mac] = UnregisteredOut(
            mac_address=req.mac,
            mac_display=mac_display(req.mac),
            organization_id=req.organization_id,
            organization_name=org_names.get(req.organization_id) if req.organization_id else None,
            ip_address=req.ip_address,
            user_agent=req.user_agent,
            manufacturer=manufacturer,
            model=model,
            last_seen_at=req.at,
            requests=1,
        )
    return list(seen.values())


@router.get("", response_model=Page[DeviceOut], summary="List devices")
def list_devices(
    request: Request,
    organization_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    profile_id: uuid.UUID | None = None,
    extension_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[DeviceOut]:
    stmt = _visible(principal, READ).order_by(Device.label, Device.mac_address)
    if organization_id:
        stmt = stmt.where(Device.organization_id == organization_id)
    if site_id:
        stmt = stmt.where(Device.site_id == site_id)
    if profile_id:
        stmt = stmt.where(Device.profile_id == profile_id)
    if extension_id:
        stmt = stmt.where(
            or_(
                Device.primary_extension_id == extension_id,
                Device.lines.contains([{"extension_id": str(extension_id)}]),
            )
        )
    if q:
        term = q.strip()
        like = f"%{term}%"
        mac_like = f"%{''.join(c for c in term.lower() if c in '0123456789abcdef')}%"
        ext_ids = select(Extension.id).where(Extension.number.ilike(like))
        stmt = stmt.where(
            or_(
                Device.label.ilike(like),
                Device.model.ilike(like),
                Device.mac_address.like(mac_like) if len(mac_like) > 2 else Device.id.is_(None),
                Device.primary_extension_id.in_(ext_ids),
            )
        )
    rows, total = paginate(db, stmt, params)
    return Page(
        items=_outs(request, db, rows), total=total, limit=params.limit, offset=params.offset
    )


@router.post("", response_model=DeviceOut, status_code=201, summary="Register a device")
def create_device(
    body: DeviceIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> DeviceOut:
    if not principal.has(WRITE, body.organization_id):
        raise forbidden()
    org = db.get(Organization, body.organization_id)
    if org is None:
        raise not_found("Organization")
    key = installation_key(request)
    profile = _check_profile(db, org.id, body.profile_id)
    _check_extensions(db, org.id, body.primary_extension_id, body.lines)
    common.check_site(db, org.id, body.site_id)
    common.check_firmware(db, body.firmware_image_id, body.manufacturer)
    if body.keys is not None:
        common.check_keys(db, org.id, body.keys, "keys")
    values = _check_values(request, db, profile, body.values)
    device = Device(
        id=uuid.uuid4(),
        organization_id=org.id,
        site_id=body.site_id or (profile.site_id if profile else None),
        mac_address=body.mac_address,
        manufacturer=body.manufacturer,
        model=body.model,
        label=body.label,
        profile_id=body.profile_id,
        primary_extension_id=body.primary_extension_id,
        lines=[{"extension_id": str(x)} for x in body.lines],
        keys=[k.model_dump() for k in body.keys] if body.keys is not None else None,
        values=values,
        firmware_image_id=body.firmware_image_id,
        is_enabled=body.is_enabled,
    )
    device.provisioning_secret_ciphertext = key.encrypt(new_secret(), device_purpose(device.id))
    device.provisioning_secret_changed_at = utcnow()
    db.add(device)
    try:
        db.flush()
    except IntegrityError as e:
        raise _mac_conflict(e, db) from e
    _record(db, ctx, principal, "device.create", device, {"profile_id": str(body.profile_id)})
    db.commit()
    return _outs(request, db, [device])[0]


class PreviewOut(BaseModel):
    template_key: str | None
    files: list[dict[str, str]]
    error: str | None = None
    error_code: str | None = None


@router.get(
    "/{device_id}/preview", response_model=PreviewOut, summary="Rendered files, secrets masked"
)
def preview_device(
    device_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> PreviewOut:
    device = _get(db, principal, device_id, READ)
    settings = request.app.state.settings
    catalog = catalog_for(request, db)
    try:
        ctx = facts.resolve_device(catalog, db, device)
        files = facts.render_device(
            db,
            settings,
            catalog,
            device,
            key=try_load_installation_key(settings),
            host=request.headers.get("host"),
            mask_secrets=True,
        )
    except facts.ProvisioningError as e:
        return PreviewOut(template_key=None, files=[], error=str(e), error_code=e.code)
    return PreviewOut(
        template_key=ctx.template_key,
        files=[{"filename": f.filename, "format": f.format, "content": f.content} for f in files],
    )


@router.get("/{device_id}", response_model=DeviceOut)
def get_device(
    device_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> DeviceOut:
    return _outs(request, db, [_get(db, principal, device_id, READ)])[0]


@router.patch("/{device_id}", response_model=DeviceOut)
def update_device(
    device_id: uuid.UUID,
    body: DevicePatch,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> DeviceOut:
    device = _get(db, principal, device_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    details: dict[str, Any] = {}
    org_id = device.organization_id
    profile = (
        _check_profile(db, org_id, changes["profile_id"])
        if "profile_id" in changes
        else (db.get(DeviceProfile, device.profile_id) if device.profile_id else None)
    )
    if "profile_id" in changes and changes["profile_id"] != device.profile_id:
        device.profile_id = changes["profile_id"]
        details["profile_id"] = str(changes["profile_id"]) if changes["profile_id"] else None
    if "primary_extension_id" in changes or "lines" in changes:
        primary = changes.get("primary_extension_id", device.primary_extension_id)
        lines = changes.get("lines")
        line_ids = (
            [uuid.UUID(str(x["extension_id"])) for x in device.lines] if lines is None else lines
        )
        _check_extensions(db, org_id, primary, list(line_ids or []))
        if primary != device.primary_extension_id:
            device.primary_extension_id = primary
            details["primary_extension_id"] = str(primary) if primary else None
        if lines is not None:
            dumped = [{"extension_id": str(x)} for x in lines]
            if dumped != device.lines:
                device.lines = dumped
                details["lines"] = len(dumped)
    if "site_id" in changes and changes["site_id"] != device.site_id:
        common.check_site(db, org_id, changes["site_id"])
        device.site_id = changes["site_id"]
        details["site_id"] = str(changes["site_id"]) if changes["site_id"] else None
    manufacturer = changes.get("manufacturer", device.manufacturer)
    if "firmware_image_id" in changes and changes["firmware_image_id"] != device.firmware_image_id:
        common.check_firmware(db, changes["firmware_image_id"], manufacturer)
        device.firmware_image_id = changes["firmware_image_id"]
        details["firmware_image_id"] = (
            str(changes["firmware_image_id"]) if changes["firmware_image_id"] else None
        )
    if "keys" in changes:
        keys = (
            [LineKey.model_validate(k) for k in changes["keys"]]
            if changes["keys"] is not None
            else None
        )
        if keys is not None:
            common.check_keys(db, org_id, keys, "keys")
        dumped_keys = [k.model_dump() for k in keys] if keys is not None else None
        if dumped_keys != device.keys:
            device.keys = dumped_keys
            details["keys"] = len(dumped_keys) if dumped_keys is not None else None
    if "values" in changes or ("profile_id" in changes and device.values):
        values = _check_values(request, db, profile, changes.get("values", device.values) or {})
        if values != device.values:
            device.values = values
            details["values"] = sorted(values)
    for field in ("mac_address", "manufacturer", "model", "label", "is_enabled"):
        if field in changes and changes[field] != getattr(device, field):
            if field == "mac_address":
                details["mac_from"] = device.mac_address
            setattr(device, field, changes[field])
            details[field] = changes[field]
    if not details:
        return _outs(request, db, [device])[0]
    try:
        db.flush()
    except IntegrityError as e:
        raise _mac_conflict(e, db) from e
    _record(db, ctx, principal, "device.update", device, details)
    db.commit()
    return _outs(request, db, [device])[0]


@router.delete("/{device_id}", status_code=204)
def delete_device(
    device_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    device = _get(db, principal, device_id, WRITE)
    _record(db, ctx, principal, "device.delete", device, {})
    db.delete(device)
    db.commit()
    return Response(status_code=204)


def devices_of_extension(db: Session, extension_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count(Device.id)).where(
                or_(
                    Device.primary_extension_id == extension_id,
                    Device.lines.contains([{"extension_id": str(extension_id)}]),
                )
            )
        )
        or 0
    )
