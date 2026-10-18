# SPDX-License-Identifier: AGPL-3.0-or-later
"""Telephony objects managed by Veyra. Engine-neutral by design."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class Extension(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    __tablename__ = "extensions"
    __table_args__ = (UniqueConstraint("organization_id", "number"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    number: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(200))
    # Engine endpoint name. Globally unique because SIP endpoints share one
    # namespace inside the telephony engine regardless of organization.
    endpoint_name: Mapped[str] = mapped_column(String(80), unique=True)
    # SIP secret encrypted with the installation key (veyra.core.security.crypto);
    # never plaintext. Purpose string: ``extension.sip_secret:<id>``.
    sip_secret_ciphertext: Mapped[str | None] = mapped_column(Text)
    sip_secret_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    caller_id_name: Mapped[str | None] = mapped_column(String(80))
    caller_id_number: Mapped[str | None] = mapped_column(String(32))
    # Number presented on emergency routes instead of the regular caller ID
    # (docs/TRUNKS_ROUTING.md §7): the building's ELIN or registered DID.
    emergency_caller_id_number: Mapped[str | None] = mapped_column(String(32))
    # Presented on trunk calls (docs/CALL_FEATURES.md §3.5): one of the
    # organization's DIDs or an allowed number; the route may force its own.
    outbound_caller_id_number: Mapped[str | None] = mapped_column(String(32))
    outbound_caller_id_name: Mapped[str | None] = mapped_column(String(80))
    # Dispatchable location (docs/PRODUCTION_HARDENING.md §6): the building
    # and the floor/room text the on-site notification carries.
    building_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("buildings.id", ondelete="SET NULL")
    )
    location: Mapped[str | None] = mapped_column(String(200))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Device(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A physical phone registered by MAC address (docs/DEVICE_PROVISIONING.md §2)."""

    __tablename__ = "devices"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    # Normalized: 12 lower-case hex digits, no separators.
    mac_address: Mapped[str] = mapped_column(String(12), unique=True)
    manufacturer: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    label: Mapped[str | None] = mapped_column(String(200))
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("device_profiles.id", ondelete="SET NULL")
    )
    primary_extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL")
    )
    # Extra registrations [{"extension_id": ...}] (line 2 onwards).
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # Line keys replacing the profile's when not null (§4.2).
    keys: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    # Per-device variable values overriding the profile's.
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    firmware_image_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("firmware_images.id", ondelete="SET NULL")
    )
    # Per-device HTTP credential for the provisioning server (§3.2), encrypted
    # with the installation key. Purpose string: ``device.provisioning_secret:<id>``.
    provisioning_secret_ciphertext: Mapped[str | None] = mapped_column(Text)
    provisioning_secret_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_ip: Mapped[str | None] = mapped_column(String(45))
    last_user_agent: Mapped[str | None] = mapped_column(String(200))
    last_result: Mapped[str | None] = mapped_column(String(32))
    firmware_reported: Mapped[str | None] = mapped_column(String(64))
    building_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("buildings.id", ondelete="SET NULL")
    )
    location: Mapped[str | None] = mapped_column(String(200))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Phone trust (docs/FIREWALL_TRUST.md §6.3): the first HTTPS fetch; after
    # it, plain-HTTP bootstrap is refused until allow_bootstrap is set again.
    https_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    allow_bootstrap: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
