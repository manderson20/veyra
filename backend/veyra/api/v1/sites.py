# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sites: the locations (buildings, campuses) of an organization. Devices,
device profiles, paging zones and extensions may belong to one; a site's
emergency caller ID is the default for its extensions (docs/TRUNKS_ROUTING.md §7)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.models import Building, Device, Extension, Organization, Site
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import routing

router = APIRouter(prefix="/sites", tags=["sites"])

READ = "organizations.read"
WRITE = "organizations.write"
_CALLER_ID_NUMBER_RE = re.compile(r"^[0-9+]{1,32}$")


def _caller_id_number(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if not _CALLER_ID_NUMBER_RE.match(v):
        raise ValueError("digits (and a leading +) only")
    return v


def _timezone(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    v = v.strip()
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError("enter an IANA time zone such as America/Chicago") from e
    return v


def _text(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class SiteIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    timezone: str | None = Field(None, max_length=64)
    street: str | None = Field(None, max_length=200)
    city: str | None = Field(None, max_length=100)
    region: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    country: str | None = Field(None, max_length=2)
    emergency_caller_id_number: str | None = Field(None, max_length=32)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        routing.slugify(v)
        return v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        return _timezone(v)

    @field_validator("street", "city", "region", "postal_code")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return _text(v)

    @field_validator("country")
    @classmethod
    def _country(cls, v: str | None) -> str | None:
        v = _text(v)
        if v is not None and not re.match(r"^[A-Za-z]{2}$", v):
            raise ValueError("two-letter country code")
        return v.upper() if v else None

    @field_validator("emergency_caller_id_number")
    @classmethod
    def _ecid(cls, v: str | None) -> str | None:
        return _caller_id_number(v)


class SitePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    timezone: str | None = Field(None, max_length=64)
    street: str | None = Field(None, max_length=200)
    city: str | None = Field(None, max_length=100)
    region: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    country: str | None = Field(None, max_length=2)
    emergency_caller_id_number: str | None = Field(None, max_length=32)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return SiteIn._name(v) if v is not None else None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        return _timezone(v)

    @field_validator("street", "city", "region", "postal_code")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return _text(v)

    @field_validator("country")
    @classmethod
    def _country(cls, v: str | None) -> str | None:
        return SiteIn._country(v)

    @field_validator("emergency_caller_id_number")
    @classmethod
    def _ecid(cls, v: str | None) -> str | None:
        return _caller_id_number(v)


class SiteOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    slug: str
    timezone: str | None
    street: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country: str | None
    emergency_caller_id_number: str | None
    extensions: int
    devices: int
    created_at: datetime
    updated_at: datetime


def _visible(principal: Principal, perm: str) -> Select[Site]:
    stmt = select(Site)
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(Site.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _get(db: Session, principal: Principal, site_id: uuid.UUID, perm: str) -> Site:
    site = db.scalar(_visible(principal, perm).where(Site.id == site_id))
    if site is None:
        raise not_found("Site")
    return site


def _outs(db: Session, rows: list[Site]) -> list[SiteOut]:
    if not rows:
        return []
    ids = {r.id for r in rows}
    orgs = {
        o.id: o.name
        for o in db.scalars(
            select(Organization).where(Organization.id.in_({r.organization_id for r in rows}))
        )
    }
    ext_counts = dict(
        db.execute(
            select(Extension.site_id, func.count(Extension.id))
            .where(Extension.site_id.in_(ids))
            .group_by(Extension.site_id)
        ).all()
    )
    dev_counts = dict(
        db.execute(
            select(Device.site_id, func.count(Device.id))
            .where(Device.site_id.in_(ids))
            .group_by(Device.site_id)
        ).all()
    )
    return [
        SiteOut(
            id=r.id,
            organization_id=r.organization_id,
            organization_name=orgs.get(r.organization_id, ""),
            name=r.name,
            slug=r.slug,
            timezone=r.timezone,
            street=r.street,
            city=r.city,
            region=r.region,
            postal_code=r.postal_code,
            country=r.country,
            emergency_caller_id_number=r.emergency_caller_id_number,
            extensions=int(ext_counts.get(r.id, 0)),
            devices=int(dev_counts.get(r.id, 0)),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


def _check_name(
    db: Session, organization_id: uuid.UUID, name: str, exclude: uuid.UUID | None
) -> None:
    stmt = select(Site.id).where(
        Site.organization_id == organization_id, func.lower(Site.name) == name.lower()
    )
    if exclude is not None:
        stmt = stmt.where(Site.id != exclude)
    if db.scalar(stmt) is not None:
        raise conflict("A site with that name exists in this organization.", "name_in_use")


def _unique_slug(db: Session, organization_id: uuid.UUID, name: str) -> str:
    base = routing.slugify(name)[:63]
    slug, n = base, 2
    while (
        db.scalar(select(Site.id).where(Site.organization_id == organization_id, Site.slug == slug))
        is not None
    ):
        slug = f"{base[: 63 - len(str(n)) - 1]}-{n}"
        n += 1
    return slug


def _record(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    site: Site,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=site.organization_id,
        target_type="site",
        target_id=site.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": site.name, **details},
    )


@router.get("", response_model=Page[SiteOut], summary="List sites")
def list_sites(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[SiteOut]:
    stmt = _visible(principal, READ).order_by(Site.name)
    if organization_id:
        stmt = stmt.where(Site.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Site.name.ilike(like), Site.city.ilike(like)))
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post("", response_model=SiteOut, status_code=201, summary="Create a site")
def create_site(
    body: SiteIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> SiteOut:
    if not principal.has(WRITE, body.organization_id):
        raise forbidden()
    org = db.get(Organization, body.organization_id)
    if org is None:
        raise not_found("Organization")
    _check_name(db, org.id, body.name, None)
    site = Site(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=_unique_slug(db, org.id, body.name),
        **body.model_dump(exclude={"organization_id"}),
    )
    db.add(site)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("A site with that name exists in this organization.", "name_in_use") from e
    _record(db, ctx, principal, "site.create", site, {"slug": site.slug})
    db.commit()
    return _outs(db, [site])[0]


@router.get("/{site_id}", response_model=SiteOut)
def get_site(
    site_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> SiteOut:
    return _outs(db, [_get(db, principal, site_id, READ)])[0]


@router.patch("/{site_id}", response_model=SiteOut)
def update_site(
    site_id: uuid.UUID,
    body: SitePatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> SiteOut:
    site = _get(db, principal, site_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("name"):
        _check_name(db, site.organization_id, changes["name"], site.id)
    details: dict[str, Any] = {}
    for field, value in changes.items():
        if value != getattr(site, field):
            details[field] = value
            setattr(site, field, value)
    if not details:
        return _outs(db, [site])[0]
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("A site with that name exists in this organization.", "name_in_use") from e
    _record(db, ctx, principal, "site.update", site, details)
    db.commit()
    return _outs(db, [site])[0]


@router.delete("/{site_id}", status_code=204)
def delete_site(
    site_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    site = _get(db, principal, site_id, WRITE)
    used = db.scalar(select(func.count(Building.id)).where(Building.site_id == site.id)) or 0
    if used:
        raise ProblemError(
            409, "Site in use", "Buildings still belong to this site.", code="site_in_use"
        )
    _record(db, ctx, principal, "site.delete", site, {"slug": site.slug})
    db.delete(site)
    db.commit()
    return Response(status_code=204)
