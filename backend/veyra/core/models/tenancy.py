# SPDX-License-Identifier: AGPL-3.0-or-later
"""Installation and tenancy hierarchy: installation → organization → site → building/department."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class Installation(UUIDPrimaryKey, Timestamps, Base):
    """Exactly one row: the identity of this Veyra installation.

    ``instance_id`` is the persistent identity used for central management
    enrollment and HA pairing; it never changes after creation, even across
    HA role changes or hostname changes.
    """

    __tablename__ = "installation"

    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), default="Veyra")
    deployment_mode: Mapped[str] = mapped_column(String(32), default="standalone")
    multi_tenancy_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    central_management_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    setup_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Organization(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "organizations"

    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Site(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("organization_id", "slug"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    slug: Mapped[str] = mapped_column(String(63))
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str | None] = mapped_column(String(64))
    # Civic address — the basis for a future dispatchable location (E911).
    street: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(2))


class Building(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    __tablename__ = "buildings"
    __table_args__ = (UniqueConstraint("site_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(200))


class Department(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
