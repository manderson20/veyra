# SPDX-License-Identifier: AGPL-3.0-or-later
"""Device profiles (docs/DEVICE_PROVISIONING.md §1): a template family or
model plus values, line keys, paging-zone memberships and firmware. Devices
point at a profile; one profile per building separates identical phone
settings by their paging zones."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import device_common as common
from veyra.api.v1.device_common import LineKey
from veyra.api.v1.provisioning import catalog_for
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.models import (
    Device,
    DeviceProfile,
    DeviceProfilePaging,
    FirmwareImage,
    Organization,
    PagingZone,
    Site,
)
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal

router = APIRouter(prefix="/device-profiles", tags=["devices"])

READ = "devices.read"
WRITE = "devices.write"
MAX_ZONES = 25
Role = Literal["none", "default", "priority", "emergency"]


class PagingMembershipIn(BaseModel):
    zone_id: uuid.UUID
    subscribed: bool = True
    transmit: bool = True
    role: Role = "none"


class ProfileIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    site_id: uuid.UUID | None = None
    template_key: str = Field(min_length=1, max_length=128)
    values: dict[str, Any] = Field(default_factory=dict)
    keys: list[LineKey] = Field(default_factory=list, max_length=common.MAX_KEYS)
    paging: list[PagingMembershipIn] = Field(default_factory=list, max_length=MAX_ZONES)
    firmware_image_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        return v


class ProfilePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    site_id: uuid.UUID | None = None
    template_key: str | None = Field(None, min_length=1, max_length=128)
    values: dict[str, Any] | None = None
    keys: list[LineKey] | None = Field(None, max_length=common.MAX_KEYS)
    paging: list[PagingMembershipIn] | None = Field(None, max_length=MAX_ZONES)
    firmware_image_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return ProfileIn._name(v) if v is not None else None


class PagingMembershipOut(PagingMembershipIn):
    zone_name: str
    poly_group: int
    kind: str


class FirmwareRef(BaseModel):
    id: uuid.UUID
    manufacturer: str
    version: str
    filename: str


class ProfileOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    site_id: uuid.UUID | None
    site_name: str | None
    name: str
    description: str | None
    template_key: str
    template_name: str | None
    template_abstract: bool | None
    manufacturer: str | None
    # Concrete templates the family resolves to, by model.
    models: dict[str, str]
    values: dict[str, Any]
    keys: list[LineKey]
    paging: list[PagingMembershipOut]
    firmware: FirmwareRef | None
    devices: int
    problems: list[str]
    created_at: datetime
    updated_at: datetime


def _visible(principal: Principal, perm: str) -> Select[DeviceProfile]:
    stmt = select(DeviceProfile)
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(DeviceProfile.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _get(db: Session, principal: Principal, profile_id: uuid.UUID, perm: str) -> DeviceProfile:
    profile = db.scalar(_visible(principal, perm).where(DeviceProfile.id == profile_id))
    if profile is None:
        raise not_found("Device profile")
    return profile


def _memberships(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, list[DeviceProfilePaging]]:
    out: dict[uuid.UUID, list[DeviceProfilePaging]] = {i: [] for i in ids}
    if ids:
        for m in db.scalars(
            select(DeviceProfilePaging).where(DeviceProfilePaging.profile_id.in_(ids))
        ):
            out[m.profile_id].append(m)
    return out


def _outs(request: Request, db: Session, rows: list[DeviceProfile]) -> list[ProfileOut]:
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
    members = _memberships(db, {r.id for r in rows})
    zone_ids = {m.zone_id for ms in members.values() for m in ms}
    zones = (
        {z.id: z for z in db.scalars(select(PagingZone).where(PagingZone.id.in_(zone_ids)))}
        if zone_ids
        else {}
    )
    fw_ids = {r.firmware_image_id for r in rows if r.firmware_image_id}
    firmware = (
        {f.id: f for f in db.scalars(select(FirmwareImage).where(FirmwareImage.id.in_(fw_ids)))}
        if fw_ids
        else {}
    )
    counts = dict(
        db.execute(
            select(Device.profile_id, func.count(Device.id))
            .where(Device.profile_id.in_({r.id for r in rows}))
            .group_by(Device.profile_id)
        ).all()
    )
    out = []
    for r in rows:
        rec = catalog.records.get(r.template_key)
        problems: list[str] = []
        models: dict[str, str] = {}
        if rec is None:
            problems.append(f"Template {r.template_key} is missing; devices cannot be provisioned.")
        else:
            t = rec.manifest.template
            if t.abstract:
                for model in sorted(
                    {m for x in catalog.records.values() for m in x.manifest.template.models}
                ):
                    found = common.model_templates(catalog, t.key, model, r.organization_id)
                    if found:
                        models[model] = found[0]
                if not models:
                    problems.append("No model template inherits from this family yet.")
            else:
                models = {m: t.key for m in t.models}
        paging = []
        for m in sorted(
            members[r.id], key=lambda m: zones[m.zone_id].poly_group if m.zone_id in zones else 0
        ):
            z = zones.get(m.zone_id)
            if z is None:
                continue
            paging.append(
                PagingMembershipOut(
                    zone_id=z.id,
                    subscribed=m.subscribed,
                    transmit=m.transmit,
                    role=m.role,
                    zone_name=z.name,
                    poly_group=z.poly_group,
                    kind=z.kind,
                )
            )
        fw = firmware.get(r.firmware_image_id) if r.firmware_image_id else None
        out.append(
            ProfileOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=orgs.get(r.organization_id, ""),
                site_id=r.site_id,
                site_name=sites.get(r.site_id) if r.site_id else None,
                name=r.name,
                description=r.description,
                template_key=r.template_key,
                template_name=rec.manifest.template.name if rec else None,
                template_abstract=rec.manifest.template.abstract if rec else None,
                manufacturer=rec.manifest.template.manufacturer if rec else None,
                models=models,
                values=common.masked(
                    dict(r.values), common.sensitive_names(catalog, r.template_key)
                ),
                keys=[LineKey.model_validate(k) for k in r.keys],
                paging=paging,
                firmware=(
                    FirmwareRef(
                        id=fw.id,
                        manufacturer=fw.manufacturer,
                        version=fw.version,
                        filename=fw.filename,
                    )
                    if fw
                    else None
                ),
                devices=int(counts.get(r.id, 0)),
                problems=problems,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _check_paging(
    db: Session, organization_id: uuid.UUID, paging: list[PagingMembershipIn]
) -> dict[uuid.UUID, PagingZone]:
    ids = [p.zone_id for p in paging]
    if len(set(ids)) != len(ids):
        raise common.validation("paging", "a zone is listed twice")
    zones = (
        {z.id: z for z in db.scalars(select(PagingZone).where(PagingZone.id.in_(ids)))}
        if ids
        else {}
    )
    for zid in ids:
        z = zones.get(zid)
        if z is None or z.organization_id != organization_id:
            raise common.validation("paging", "paging zone not found in this organization")
    for role in ("default", "priority", "emergency"):
        if sum(1 for p in paging if p.role == role) > 1:
            raise common.validation("paging", f"only one zone can be the {role} group")
    return zones


def _set_paging(db: Session, profile: DeviceProfile, paging: list[PagingMembershipIn]) -> None:
    for old in db.scalars(
        select(DeviceProfilePaging).where(DeviceProfilePaging.profile_id == profile.id)
    ):
        db.delete(old)
    db.flush()
    for p in paging:
        db.add(
            DeviceProfilePaging(
                profile_id=profile.id,
                zone_id=p.zone_id,
                subscribed=p.subscribed,
                transmit=p.transmit,
                role=p.role,
            )
        )
    db.flush()


def _record(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    profile: DeviceProfile,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=profile.organization_id,
        target_type="device_profile",
        target_id=profile.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": profile.name, **details},
    )


def _name_conflict(e: IntegrityError, db: Session) -> Exception:
    db.rollback()
    return conflict("A device profile with that name exists in this organization.", "name_in_use")


@router.get("", response_model=Page[ProfileOut], summary="List device profiles")
def list_profiles(
    request: Request,
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[ProfileOut]:
    stmt = _visible(principal, READ).order_by(DeviceProfile.name)
    if organization_id:
        stmt = stmt.where(DeviceProfile.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(DeviceProfile.name.ilike(like), DeviceProfile.template_key.ilike(like))
        )
    rows, total = paginate(db, stmt, params)
    return Page(
        items=_outs(request, db, rows), total=total, limit=params.limit, offset=params.offset
    )


@router.post("", response_model=ProfileOut, status_code=201, summary="Create a device profile")
def create_profile(
    body: ProfileIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ProfileOut:
    if not principal.has(WRITE, body.organization_id):
        raise forbidden()
    org = db.get(Organization, body.organization_id)
    if org is None:
        raise not_found("Organization")
    catalog = catalog_for(request, db)
    resolved = common.resolve_template(catalog, body.template_key, "template_key", org.id)
    values = common.check_values(resolved, body.values, "values")
    common.check_srtp(db, values)
    common.check_keys(db, org.id, body.keys, "keys")
    common.check_site(db, org.id, body.site_id)
    common.check_firmware(
        db, body.firmware_image_id, resolved.record.manifest.template.manufacturer
    )
    _check_paging(db, org.id, body.paging)
    profile = DeviceProfile(
        id=uuid.uuid4(),
        organization_id=org.id,
        site_id=body.site_id,
        name=body.name,
        description=(body.description or "").strip() or None,
        template_key=body.template_key,
        values=values,
        keys=[k.model_dump() for k in body.keys],
        firmware_image_id=body.firmware_image_id,
    )
    db.add(profile)
    try:
        db.flush()
    except IntegrityError as e:
        raise _name_conflict(e, db) from e
    _set_paging(db, profile, body.paging)
    _record(
        db,
        ctx,
        principal,
        "device_profile.create",
        profile,
        {"template_key": profile.template_key, "zones": len(body.paging)},
    )
    db.commit()
    return _outs(request, db, [profile])[0]


@router.get("/{profile_id}", response_model=ProfileOut)
def get_profile(
    profile_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> ProfileOut:
    return _outs(request, db, [_get(db, principal, profile_id, READ)])[0]


@router.patch("/{profile_id}", response_model=ProfileOut)
def update_profile(
    profile_id: uuid.UUID,
    body: ProfilePatch,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ProfileOut:
    profile = _get(db, principal, profile_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    details: dict[str, Any] = {}
    catalog = catalog_for(request, db)
    template_key = changes.get("template_key") or profile.template_key
    resolved = common.resolve_template(
        catalog, template_key, "template_key", profile.organization_id
    )
    if template_key != profile.template_key:
        details["template_key"] = {"from": profile.template_key, "to": template_key}
        profile.template_key = template_key
    if "values" in changes or "template_key" in changes:
        values = common.check_values(
            resolved, changes.get("values", profile.values) or {}, "values", profile.values
        )
        common.check_srtp(db, values)
        if values != profile.values:
            profile.values = values
            details["values"] = sorted(values)
    if "keys" in changes:
        keys = [LineKey.model_validate(k) for k in (changes["keys"] or [])]
        common.check_keys(db, profile.organization_id, keys, "keys")
        dumped = [k.model_dump() for k in keys]
        if dumped != profile.keys:
            profile.keys = dumped
            details["keys"] = len(dumped)
    if "site_id" in changes and changes["site_id"] != profile.site_id:
        common.check_site(db, profile.organization_id, changes["site_id"])
        profile.site_id = changes["site_id"]
        details["site_id"] = str(changes["site_id"]) if changes["site_id"] else None
    if "firmware_image_id" in changes and changes["firmware_image_id"] != profile.firmware_image_id:
        common.check_firmware(
            db, changes["firmware_image_id"], resolved.record.manifest.template.manufacturer
        )
        profile.firmware_image_id = changes["firmware_image_id"]
        details["firmware_image_id"] = (
            str(changes["firmware_image_id"]) if changes["firmware_image_id"] else None
        )
    for field in ("name", "description"):
        if field in changes:
            value = changes[field]
            if field == "description":
                value = (value or "").strip() or None
            if value != getattr(profile, field):
                setattr(profile, field, value)
                details[field] = value
    if "paging" in changes:
        paging = [PagingMembershipIn.model_validate(p) for p in (changes["paging"] or [])]
        _check_paging(db, profile.organization_id, paging)
        _set_paging(db, profile, paging)
        details["zones"] = len(paging)
    if not details:
        return _outs(request, db, [profile])[0]
    try:
        db.flush()
    except IntegrityError as e:
        raise _name_conflict(e, db) from e
    _record(db, ctx, principal, "device_profile.update", profile, details)
    db.commit()
    return _outs(request, db, [profile])[0]


@router.delete("/{profile_id}", status_code=204)
def delete_profile(
    profile_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    profile = _get(db, principal, profile_id, WRITE)
    used = db.scalar(select(func.count(Device.id)).where(Device.profile_id == profile.id)) or 0
    if used:
        raise ProblemError(
            409,
            "Device profile in use",
            f"{used} device(s) use this profile; move them to another profile first.",
            code="profile_in_use",
        )
    _record(db, ctx, principal, "device_profile.delete", profile, {})
    db.delete(profile)
    db.commit()
    return Response(status_code=204)
