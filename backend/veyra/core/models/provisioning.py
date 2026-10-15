# SPDX-License-Identifier: AGPL-3.0-or-later
"""Device provisioning objects (docs/DEVICE_PROVISIONING.md): paging zones,
device profiles, firmware images and the log of what phones asked for.
``Device`` itself lives in ``telephony.py``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class PagingZone(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A multicast page group (§5): the speakers' address and port plus the
    Poly group number the phones subscribe to."""

    __tablename__ = "paging_zones"
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        UniqueConstraint("organization_id", "slug"),
        UniqueConstraint("organization_id", "poly_group"),
        UniqueConstraint("organization_id", "number"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    # Plain multicast RTP group the speakers listen to.
    multicast_address: Mapped[str] = mapped_column(String(45))
    multicast_port: Mapped[int] = mapped_column(Integer)
    # Poly group paging: one address and port for the organization's phones,
    # groups 1-25 (25 = emergency) on it.
    poly_address: Mapped[str] = mapped_column(String(45), default="224.0.1.116")
    poly_port: Mapped[int] = mapped_column(Integer, default=5001)
    poly_group: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16), default="normal")  # normal|priority|emergency
    codec: Mapped[str] = mapped_column(String(16), default="G.711Mu")  # G.711Mu|G.722
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Milestone 9c (docs/PAGING_RECORDINGS.md §2): dialable number from the
    # shared number space, who may page it and the longest page.
    number: Mapped[str | None] = mapped_column(String(32))
    allowed: Mapped[str] = mapped_column(
        String(16), default="everyone"
    )  # everyone|members|administrators
    max_seconds: Mapped[int] = mapped_column(Integer, default=120)


class FirmwareImage(UUIDPrimaryKey, Timestamps, Base):
    """A vendor firmware file uploaded by an administrator (§3.4), stored under
    ``<data dir>/firmware/<id>/<filename>`` and served by NGINX."""

    __tablename__ = "firmware_images"
    __table_args__ = (UniqueConstraint("manufacturer", "version", "filename"),)

    manufacturer: Mapped[str] = mapped_column(String(64))
    models: Mapped[list[str]] = mapped_column(JSONB, default=list)
    version: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class DeviceProfile(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A template (family or model) plus values, line keys, paging memberships
    and firmware: the same settings separated by use, e.g. one per building (§1)."""

    __tablename__ = "device_profiles"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    template_key: Mapped[str] = mapped_column(String(128))
    # {variable: value} for the resolved template's variables.
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Line keys [{type, label, value}], see docs/DEVICE_PROVISIONING.md §4.2.
    keys: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    firmware_image_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("firmware_images.id", ondelete="SET NULL")
    )


class DeviceProfilePaging(Base):
    __tablename__ = "device_profile_paging"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("device_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    zone_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paging_zones.id", ondelete="CASCADE"), primary_key=True
    )
    subscribed: Mapped[bool] = mapped_column(Boolean, default=True)
    transmit: Mapped[bool] = mapped_column(Boolean, default=True)
    # none | default | priority | emergency: the phone's special groups.
    role: Mapped[str] = mapped_column(String(16), default="none")


class ProvisioningRequest(UUIDPrimaryKey, Base):
    """What asked for which file: feeds device status and the list of
    unregistered phones seen (§3.2). Pruned by the worker after 30 days."""

    __tablename__ = "provisioning_requests"

    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    mac: Mapped[str | None] = mapped_column(String(12), index=True)
    filename: Mapped[str] = mapped_column(String(128))
    method: Mapped[str] = mapped_column(String(8))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(200))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL")
    )
    # ok | uploaded | unauthorized | unknown_device | disabled | not_found | render_error
    result: Mapped[str] = mapped_column(String(32))
    status: Mapped[int] = mapped_column(Integer)
