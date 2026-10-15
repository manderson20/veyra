# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paging zones (docs/DEVICE_PROVISIONING.md §5): the multicast group the
speakers listen to and the Poly group number the phones subscribe to. Device
profiles subscribe phones to zones; Milestone 9c sends pages into them."""

from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import group_helpers as helpers
from veyra.api.v1.group_helpers import MemberOut
from veyra.configmgmt import service as configmgmt
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.models import (
    DeviceProfile,
    DeviceProfilePaging,
    Organization,
    PagingZone,
    PagingZoneMember,
    Site,
)
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import routing

router = APIRouter(prefix="/paging-zones", tags=["paging"])

READ = "paging.read"
WRITE = "paging.write"
POLY_DEFAULT_ADDRESS = "224.0.1.116"
POLY_DEFAULT_PORT = 5001
EMERGENCY_GROUP = 25
Kind = Literal["normal", "priority", "emergency"]
Codec = Literal["G.711Mu", "G.722"]
Allowed = Literal["everyone", "members", "administrators"]


def multicast_address(v: str) -> str:
    v = v.strip()
    try:
        addr = ipaddress.ip_address(v)
    except ValueError as e:
        raise ValueError("enter an IP address") from e
    if not addr.is_multicast:
        raise ValueError("enter a multicast address (224.0.0.0 to 239.255.255.255)")
    return str(addr)


def port(v: int) -> int:
    if not 1024 <= v <= 65535:
        raise ValueError("port between 1024 and 65535")
    return v


class ZoneIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    site_id: uuid.UUID | None = None
    multicast_address: str = Field(max_length=45)
    multicast_port: int
    poly_address: str = Field(POLY_DEFAULT_ADDRESS, max_length=45)
    poly_port: int = POLY_DEFAULT_PORT
    poly_group: int = Field(ge=1, le=EMERGENCY_GROUP)
    kind: Kind = "normal"
    codec: Codec = "G.711Mu"
    is_enabled: bool = True
    # Milestone 9c: dialable number, who may page, longest page.
    number: str | None = Field(None, max_length=32)
    allowed: Allowed = "everyone"
    members: list[uuid.UUID] = Field(default_factory=list, max_length=64)
    max_seconds: int = Field(120, ge=5, le=600)

    @field_validator("number")
    @classmethod
    def _number(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        routing.slugify(v)
        return v

    @field_validator("multicast_address", "poly_address")
    @classmethod
    def _addr(cls, v: str) -> str:
        return multicast_address(v)

    @field_validator("multicast_port", "poly_port")
    @classmethod
    def _port(cls, v: int) -> int:
        return port(v)


class ZonePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    site_id: uuid.UUID | None = None
    multicast_address: str | None = Field(None, max_length=45)
    multicast_port: int | None = None
    poly_address: str | None = Field(None, max_length=45)
    poly_port: int | None = None
    poly_group: int | None = Field(None, ge=1, le=EMERGENCY_GROUP)
    kind: Kind | None = None
    codec: Codec | None = None
    is_enabled: bool | None = None
    number: str | None = Field(None, max_length=32)
    allowed: Allowed | None = None
    members: list[uuid.UUID] | None = Field(None, max_length=64)
    max_seconds: int | None = Field(None, ge=5, le=600)

    @field_validator("number")
    @classmethod
    def _number(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return ZoneIn._name(v) if v is not None else None

    @field_validator("multicast_address", "poly_address")
    @classmethod
    def _addr(cls, v: str | None) -> str | None:
        return multicast_address(v) if v is not None else None

    @field_validator("multicast_port", "poly_port")
    @classmethod
    def _port(cls, v: int | None) -> int | None:
        return port(v) if v is not None else None


class ProfileRef(BaseModel):
    id: uuid.UUID
    name: str


class ZoneOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    site_id: uuid.UUID | None
    site_name: str | None
    name: str
    slug: str
    description: str | None
    multicast_address: str
    multicast_port: int
    poly_address: str
    poly_port: int
    poly_group: int
    kind: str
    codec: str
    is_enabled: bool
    number: str | None
    allowed: str
    members: list[MemberOut]
    max_seconds: int
    profiles: list[ProfileRef]
    problems: list[str]
    created_at: datetime
    updated_at: datetime


def _visible(principal: Principal, perm: str) -> Select[PagingZone]:
    stmt = select(PagingZone)
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(PagingZone.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _get(db: Session, principal: Principal, zone_id: uuid.UUID, perm: str) -> PagingZone:
    zone = db.scalar(_visible(principal, perm).where(PagingZone.id == zone_id))
    if zone is None:
        raise not_found("Paging zone")
    return zone


def _outs(db: Session, rows: list[PagingZone]) -> list[ZoneOut]:
    if not rows:
        return []
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
    links = db.execute(
        select(DeviceProfilePaging.zone_id, DeviceProfile.id, DeviceProfile.name)
        .join(DeviceProfile, DeviceProfile.id == DeviceProfilePaging.profile_id)
        .where(DeviceProfilePaging.zone_id.in_({r.id for r in rows}))
        .order_by(DeviceProfile.name)
    ).all()
    profiles: dict[uuid.UUID, list[ProfileRef]] = {r.id: [] for r in rows}
    for zone_id, pid, pname in links:
        profiles[zone_id].append(ProfileRef(id=pid, name=pname))
    # Poly phones listen on one address and port: zones of an organization
    # must agree on them.
    poly: dict[uuid.UUID, set[tuple[str, int]]] = {}
    for z in db.scalars(
        select(PagingZone).where(PagingZone.organization_id.in_({r.organization_id for r in rows}))
    ):
        poly.setdefault(z.organization_id, set()).add((z.poly_address, z.poly_port))
    # Multicast addresses are network-wide: another organization's zone on the
    # same group would be heard by both (docs/MULTI_TENANCY.md §4).
    groups_of: dict[tuple[str, int], set[uuid.UUID]] = {}
    for z_org, addr, port in db.execute(
        select(PagingZone.organization_id, PagingZone.multicast_address, PagingZone.multicast_port)
    ):
        groups_of.setdefault((addr, port), set()).add(z_org)
    member_ids: dict[uuid.UUID, list[uuid.UUID]] = {r.id: [] for r in rows}
    for m in db.scalars(
        select(PagingZoneMember).where(PagingZoneMember.zone_id.in_({r.id for r in rows}))
    ):
        member_ids[m.zone_id].append(m.extension_id)
    exts = helpers.extensions_by_id(db, {e for ms in member_ids.values() for e in ms})
    out = []
    for r in rows:
        problems = []
        if r.allowed == "members" and not member_ids[r.id]:
            problems.append("Only members may page this zone, and it has none.")
        if len(poly.get(r.organization_id, set())) > 1:
            problems.append(
                "Zones of this organization use different Poly paging addresses or ports; "
                "Poly phones listen on one address, so only one set of zones will reach them."
            )
        if len(groups_of.get((r.multicast_address, r.multicast_port), set())) > 1:
            problems.append(
                "Another organization pages the same multicast address and port; "
                "on a shared network both organizations' speakers would play each other's pages."
            )
        if r.kind == "emergency" and r.poly_group != EMERGENCY_GROUP:
            problems.append(f"Poly phones use group {EMERGENCY_GROUP} for emergency pages.")
        out.append(
            ZoneOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=orgs.get(r.organization_id, ""),
                site_id=r.site_id,
                site_name=sites.get(r.site_id) if r.site_id else None,
                name=r.name,
                slug=r.slug,
                description=r.description,
                multicast_address=r.multicast_address,
                multicast_port=r.multicast_port,
                poly_address=r.poly_address,
                poly_port=r.poly_port,
                poly_group=r.poly_group,
                kind=r.kind,
                codec=r.codec,
                is_enabled=r.is_enabled,
                number=r.number,
                allowed=r.allowed,
                members=sorted(
                    (
                        MemberOut(
                            extension_id=e.id,
                            number=e.number,
                            display_name=e.display_name,
                            is_enabled=e.is_enabled,
                        )
                        for e in (exts.get(i) for i in member_ids[r.id])
                        if e is not None
                    ),
                    key=lambda m: m.number,
                ),
                max_seconds=r.max_seconds,
                profiles=profiles[r.id],
                problems=problems,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _unique_slug(db: Session, organization_id: uuid.UUID, name: str) -> str:
    base = routing.slugify(name)[:40]
    slug, n = base, 2
    while (
        db.scalar(
            select(PagingZone.id).where(
                PagingZone.organization_id == organization_id, PagingZone.slug == slug
            )
        )
        is not None
    ):
        slug = f"{base[: 40 - len(str(n)) - 1]}-{n}"
        n += 1
    return slug


def _check_site(db: Session, organization_id: uuid.UUID, site_id: uuid.UUID | None) -> None:
    if site_id is None:
        return
    site = db.get(Site, site_id)
    if site is None or site.organization_id != organization_id:
        raise ProblemError(
            422,
            "Validation failed",
            "The site must belong to the same organization.",
            code="validation_failed",
            errors=[{"field": "site_id", "message": "must belong to the same organization"}],
        )


def _set_members(db: Session, zone: PagingZone, extension_ids: list[uuid.UUID]) -> None:
    for old in db.scalars(select(PagingZoneMember).where(PagingZoneMember.zone_id == zone.id)):
        db.delete(old)
    db.flush()
    for ext_id in extension_ids:
        db.add(PagingZoneMember(zone_id=zone.id, extension_id=ext_id))
    db.flush()


def _conflict(e: IntegrityError, db: Session) -> Exception:
    db.rollback()
    text = str(e.orig).lower() if e.orig else ""
    if "number" in text:
        return conflict("That number is already used.", "number_in_use")
    if "poly_group" in text:
        return conflict(
            "Another zone of this organization already uses that Poly group number.",
            "poly_group_in_use",
        )
    return conflict("A paging zone with that name exists in this organization.", "name_in_use")


def _record(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    zone: PagingZone,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=zone.organization_id,
        target_type="paging_zone",
        target_id=zone.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": zone.name, **details},
    )


@router.get("", response_model=Page[ZoneOut], summary="List paging zones")
def list_zones(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[ZoneOut]:
    stmt = _visible(principal, READ).order_by(PagingZone.poly_group, PagingZone.name)
    if organization_id:
        stmt = stmt.where(PagingZone.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                PagingZone.name.ilike(like),
                PagingZone.description.ilike(like),
                PagingZone.multicast_address.ilike(like),
            )
        )
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post("", response_model=ZoneOut, status_code=201, summary="Create a paging zone")
def create_zone(
    body: ZoneIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ZoneOut:
    if not principal.has(WRITE, body.organization_id):
        raise forbidden()
    org = db.get(Organization, body.organization_id)
    if org is None:
        raise not_found("Organization")
    _check_site(db, org.id, body.site_id)
    if body.number:
        helpers.check_number(db, body.number, "paging zone", None, org.id)
    helpers.load_members(db, org.id, body.members, "members")
    fields = body.model_dump(exclude={"members"})
    zone = PagingZone(
        id=uuid.uuid4(),
        slug=_unique_slug(db, org.id, body.name),
        **{**fields, "description": (body.description or "").strip() or None},
    )
    db.add(zone)
    try:
        db.flush()
    except IntegrityError as e:
        raise _conflict(e, db) from e
    _set_members(db, zone, body.members)
    _record(db, ctx, principal, "paging_zone.create", zone, {"poly_group": zone.poly_group})
    configmgmt.mark_changed(db, by=principal.label, what=f"paging zone {zone.name}")
    db.commit()
    return _outs(db, [zone])[0]


@router.get("/{zone_id}", response_model=ZoneOut)
def get_zone(
    zone_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> ZoneOut:
    return _outs(db, [_get(db, principal, zone_id, READ)])[0]


@router.patch("/{zone_id}", response_model=ZoneOut)
def update_zone(
    zone_id: uuid.UUID,
    body: ZonePatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ZoneOut:
    zone = _get(db, principal, zone_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    if "site_id" in changes:
        _check_site(db, zone.organization_id, changes["site_id"])
    if "description" in changes:
        changes["description"] = (changes["description"] or "").strip() or None
    if changes.get("number") and changes["number"] != zone.number:
        helpers.check_number(db, changes["number"], "paging zone", zone.id, zone.organization_id)
    members = changes.pop("members", None)
    details: dict[str, Any] = {}
    for field, value in changes.items():
        if value is None and field not in ("site_id", "description", "number"):
            continue
        if value != getattr(zone, field):
            details[field] = value
            setattr(zone, field, value)
    if members is not None:
        helpers.load_members(db, zone.organization_id, list(members), "members")
        have = sorted(
            str(m.extension_id)
            for m in db.scalars(select(PagingZoneMember).where(PagingZoneMember.zone_id == zone.id))
        )
        if sorted(str(x) for x in members) != have:
            _set_members(db, zone, list(members))
            details["members"] = len(members)
    if not details:
        return _outs(db, [zone])[0]
    try:
        db.flush()
    except IntegrityError as e:
        raise _conflict(e, db) from e
    _record(db, ctx, principal, "paging_zone.update", zone, details)
    configmgmt.mark_changed(db, by=principal.label, what=f"paging zone {zone.name}")
    db.commit()
    return _outs(db, [zone])[0]


@router.delete("/{zone_id}", status_code=204)
def delete_zone(
    zone_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    zone = _get(db, principal, zone_id, WRITE)
    used = _outs(db, [zone])[0].profiles
    if used:
        raise ProblemError(
            409,
            "Paging zone in use",
            "Device profiles still subscribe to this zone: "
            + ", ".join(p.name for p in used[:5])
            + ("…" if len(used) > 5 else "")
            + ".",
            code="zone_in_use",
        )
    _record(db, ctx, principal, "paging_zone.delete", zone, {"slug": zone.slug})
    db.delete(zone)
    configmgmt.mark_changed(db, by=principal.label, what=f"delete paging zone {zone.name}")
    db.commit()
    return Response(status_code=204)
