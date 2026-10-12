# SPDX-License-Identifier: AGPL-3.0-or-later
"""Telephony objects managed by Veyra. Engine-neutral by design."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
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
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Device(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
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
    template_key: Mapped[str | None] = mapped_column(String(128))
    primary_extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL")
    )
