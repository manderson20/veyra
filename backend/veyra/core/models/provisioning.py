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
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    # {model: line keys} for the models that do not use ``keys``.
    model_keys: Mapped[dict[str, list[dict[str, Any]]]] = mapped_column(JSONB, default=dict)
    # Base File Edit: [{file, parameter, value, remove, models}], applied after rendering.
    base_edits: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # New phones of this brand in the organization start on this template.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    firmware_image_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("firmware_images.id", ondelete="SET NULL")
    )
    # Configuration checks (docs/CONFIG_VERIFICATION.md §5): enforce |
    # advisory | off; NULL follows the organization.
    config_check_mode: Mapped[str | None] = mapped_column(String(16))

    def keys_for(self, model: str) -> list[dict[str, Any]]:
        own = (self.model_keys or {}).get(model)
        return own if own is not None else (self.keys or [])


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


class ProvisioningVariable(UUIDPrimaryKey, Timestamps, Base):
    """A named value templates read as ``vars.<name>`` and key lists reference
    as ``$name`` (docs/PROVISIONING_BREADTH.md §2), defined at installation,
    organization, site or profile scope; the nearest scope wins per phone."""

    __tablename__ = "provisioning_variables"
    __table_args__ = (UniqueConstraint("scope", "scope_id", "name"),)

    scope: Mapped[str] = mapped_column(String(16))  # installation | organization | site | profile
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # The organization the scope belongs to (NULL for installation): the
    # permission check and the list filter use it.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(40))
    value: Mapped[str] = mapped_column(Text)
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)


class ConfigCheckOverride(UUIDPrimaryKey, Base):
    """An administrator's decision to save despite one configuration check
    finding (docs/CONFIG_VERIFICATION.md §6). It covers exactly one
    fingerprint on one template, profile or device: a change of value,
    model or firmware release is a new finding."""

    __tablename__ = "config_check_overrides"
    __table_args__ = (
        # One live override per finding and scope; a revoked one stays as history.
        Index(
            "uq_config_check_overrides_live",
            "scope_type",
            "scope_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    scope_type: Mapped[str] = mapped_column(String(16))  # template | profile | device
    scope_id: Mapped[str] = mapped_column(String(128))
    fingerprint: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(16))
    rule: Mapped[str] = mapped_column(String(40))
    vendor: Mapped[str] = mapped_column(String(40))
    family: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(64))
    release: Mapped[str] = mapped_column(String(40))
    catalog_revision: Mapped[int] = mapped_column(Integer, default=0)
    file: Mapped[str] = mapped_column(String(128))
    parameter: Mapped[str] = mapped_column(String(200))
    # NULL for a secret: only its hash is kept.
    value: Mapped[str | None] = mapped_column(Text)
    value_sha256: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text)
    checker_wrong: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by_label: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The finding no longer occurs (after a catalog or configuration change).
    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CapabilityPack(UUIDPrimaryKey, Base):
    """A capability pack an administrator imported (docs/CONFIG_VERIFICATION.md
    §2.0), kept in the database so it reaches an HA standby and backups with
    the rest; installation-wide, like the built-in packs."""

    __tablename__ = "capability_packs"

    pack_id: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    vendor: Mapped[str] = mapped_column(String(40))
    version: Mapped[str] = mapped_column(String(40))
    # {relative path: text} of every file of the pack.
    files: Mapped[dict[str, str]] = mapped_column(JSONB)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    uploaded_by_label: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Each import sets it: running services notice and reload the packs.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
