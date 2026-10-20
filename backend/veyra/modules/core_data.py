# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read-only core data for modules (module API 1.3, #149).

Modules get these frozen records from ``ctx.organizations()``,
``ctx.sites()``, ``ctx.extensions()``, ``ctx.devices()`` and ``ctx.users()``
instead of importing ``veyra.core.models``. The records are a stable
contract: fields may be added, never renamed or removed within API 1.x.
Secrets (SIP and provisioning passwords, voicemail PINs, password hashes)
are never included."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.models import Device, Extension, Organization, Site, User


@dataclass(frozen=True)
class OrganizationInfo:
    id: uuid.UUID
    slug: str
    name: str
    timezone: str
    is_active: bool


@dataclass(frozen=True)
class SiteInfo:
    id: uuid.UUID
    organization_id: uuid.UUID
    slug: str
    name: str
    timezone: str | None


@dataclass(frozen=True)
class ExtensionInfo:
    id: uuid.UUID
    organization_id: uuid.UUID
    site_id: uuid.UUID | None
    user_id: uuid.UUID | None
    number: str
    display_name: str
    caller_id_name: str | None
    caller_id_number: str | None
    location: str | None
    is_enabled: bool


@dataclass(frozen=True)
class DeviceInfo:
    id: uuid.UUID
    organization_id: uuid.UUID
    site_id: uuid.UUID | None
    mac_address: str
    manufacturer: str
    model: str
    label: str | None
    primary_extension_id: uuid.UUID | None
    location: str | None
    is_enabled: bool


@dataclass(frozen=True)
class UserInfo:
    id: uuid.UUID
    home_organization_id: uuid.UUID | None
    email: str
    display_name: str
    is_active: bool


def organizations(db: Session) -> list[OrganizationInfo]:
    return [
        OrganizationInfo(o.id, o.slug, o.name, o.timezone, o.is_active)
        for o in db.scalars(select(Organization).order_by(Organization.name))
    ]


def sites(db: Session, organization_id: uuid.UUID) -> list[SiteInfo]:
    rows = db.scalars(
        select(Site).where(Site.organization_id == organization_id).order_by(Site.name)
    )
    return [SiteInfo(s.id, s.organization_id, s.slug, s.name, s.timezone) for s in rows]


def _extension(e: Extension) -> ExtensionInfo:
    return ExtensionInfo(
        e.id,
        e.organization_id,
        e.site_id,
        e.user_id,
        e.number,
        e.display_name,
        e.caller_id_name,
        e.caller_id_number,
        e.location,
        e.is_enabled,
    )


def extensions(
    db: Session,
    organization_id: uuid.UUID,
    *,
    site_id: uuid.UUID | None = None,
    number: str | None = None,
) -> list[ExtensionInfo]:
    q = select(Extension).where(Extension.organization_id == organization_id)
    if site_id is not None:
        q = q.where(Extension.site_id == site_id)
    if number is not None:
        q = q.where(Extension.number == number)
    return [_extension(e) for e in db.scalars(q.order_by(Extension.number))]


def extension(db: Session, extension_id: uuid.UUID) -> ExtensionInfo | None:
    e = db.get(Extension, extension_id)
    return _extension(e) if e else None


def devices(
    db: Session, organization_id: uuid.UUID, *, site_id: uuid.UUID | None = None
) -> list[DeviceInfo]:
    q = select(Device).where(Device.organization_id == organization_id)
    if site_id is not None:
        q = q.where(Device.site_id == site_id)
    return [
        DeviceInfo(
            d.id,
            d.organization_id,
            d.site_id,
            d.mac_address,
            d.manufacturer,
            d.model,
            d.label,
            d.primary_extension_id,
            d.location,
            d.is_enabled,
        )
        for d in db.scalars(q.order_by(Device.mac_address))
    ]


def users(db: Session, organization_id: uuid.UUID) -> list[UserInfo]:
    """Users whose home organization is ``organization_id``."""
    rows = db.scalars(
        select(User).where(User.home_organization_id == organization_id).order_by(User.email)
    )
    return [
        UserInfo(u.id, u.home_organization_id, u.email, u.display_name, u.is_active) for u in rows
    ]
