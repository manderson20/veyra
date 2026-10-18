# SPDX-License-Identifier: AGPL-3.0-or-later
"""Telephony objects managed by Veyra. Engine-neutral by design."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey, utcnow


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
    # Intercom (docs/CALL_FEATURES.md §3.6): may other phones make this one
    # answer on speaker? default | allow | deny; default = the organization's.
    intercom: Mapped[str] = mapped_column(String(8), default="default", server_default="default")
    # Class of service (docs/CALL_FEATURES.md §3.8); none: everything allowed.
    class_of_service_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("classes_of_service.id", ondelete="SET NULL", use_alter=True)
    )
    # Phones that may register at once (docs/EXTENSIONS.md §1, issue #82). None:
    # as many as are provisioned with the extension, at least one. The
    # generator takes the larger of this and the provisioned count (1..16).
    max_registrations: Mapped[int | None] = mapped_column(Integer)
    # Dispatchable location (docs/PRODUCTION_HARDENING.md §6): the building
    # and the floor/room text the on-site notification carries.
    building_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("buildings.id", ondelete="SET NULL")
    )
    location: Mapped[str | None] = mapped_column(String(200))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ClassOfService(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """What an organization's phones may do (docs/CALL_FEATURES.md §3.8). An
    extension without a class may do everything; a class restricts."""

    __tablename__ = "classes_of_service"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    # Outbound route ids the class may use; the emergency routes always work.
    allowed_outbound_route_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    # Feature code keys the class may dial; None: every code.
    allowed_feature_code_keys: Mapped[list[str] | None] = mapped_column(JSONB)
    allow_external_forwards: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    allow_external_follow_me: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    allow_intercom: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Simultaneous outside calls of the class's phones together; None: no limit.
    max_outbound_calls: Mapped[int | None] = mapped_column(Integer)


class ExtensionState(Base):
    """What a phone or an administrator set on an extension (docs/CALL_FEATURES.md
    §3.2 to §3.4): Do Not Disturb, the three forwards, follow-me, ring time. The
    engine keeps a copy in its database for the dialplan; the worker keeps the
    two in step."""

    __tablename__ = "extension_states"

    extension_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), primary_key=True
    )
    dnd: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    cf_always: Mapped[str | None] = mapped_column(String(32))
    cf_busy: Mapped[str | None] = mapped_column(String(32))
    cf_no_answer: Mapped[str | None] = mapped_column(String(32))
    fmfm_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ring_seconds: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    # phone | user | admin | sync
    updated_by: Mapped[str] = mapped_column(String(16), default="admin", server_default="admin")


class FollowMe(Base):
    """Find me / follow me of one extension (docs/CALL_FEATURES.md §3.4): the
    legs rung besides the desk phone. Whether it is on lives in
    ``ExtensionState.fmfm_enabled`` (switched from the phone with a code)."""

    __tablename__ = "follow_me"

    extension_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), primary_key=True
    )
    strategy: Mapped[str] = mapped_column(String(16), default="ringall", server_default="ringall")
    # Ring the desk phone alone first; 0 skips it.
    initial_ring_seconds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # An outside leg must press 1, so a mobile's voicemail cannot swallow the call.
    confirm_calls: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # caller: outside legs see the caller's number; extension: this extension's outbound caller ID.
    caller_id_mode: Mapped[str] = mapped_column(
        String(16), default="caller", server_default="caller"
    )
    # [{"type": "extension"|"external", "target": "1002"|"5735550100", "ring_seconds": 20}, ...]
    members: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    # Where the call goes when nobody answers: an extension number, else the
    # extension's own no-answer handling (forward, voicemail).
    no_answer_destination: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    updated_by: Mapped[str] = mapped_column(String(320), default="", server_default="")


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
