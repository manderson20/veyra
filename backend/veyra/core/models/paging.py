# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paging objects (docs/PAGING_RECORDINGS.md): who may page a zone, pages
(a named action over zones with live or recorded audio) and the page log.
``PagingZone`` itself lives in ``provisioning.py``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class PagingZoneMember(Base):
    """Extensions allowed to page a zone whose ``allowed`` is ``members``."""

    __tablename__ = "paging_zone_members"

    zone_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paging_zones.id", ondelete="CASCADE"), primary_key=True
    )
    extension_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), primary_key=True
    )


class Page(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A page: one or more zones, live audio from the caller or a recording,
    a Poly priority, dialable by number and triggered by bells and the API."""

    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        UniqueConstraint("organization_id", "slug"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    # From the shared number space; optional (API- and bell-only pages).
    number: Mapped[str | None] = mapped_column(String(32), unique=True)
    # A recording from the audio library; None = live audio from the caller.
    audio_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompts.id", ondelete="SET NULL")
    )
    pre_tone: Mapped[bool] = mapped_column(Boolean, default=True)
    repeat: Mapped[int] = mapped_column(Integer, default=1)
    priority: Mapped[str] = mapped_column(String(16), default="normal")  # normal|priority|emergency
    allowed: Mapped[str] = mapped_column(
        String(16), default="everyone"
    )  # everyone|members|administrators
    max_seconds: Mapped[int] = mapped_column(Integer, default=120)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class PageZone(Base):
    __tablename__ = "page_zones"

    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True
    )
    zone_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paging_zones.id", ondelete="CASCADE"), primary_key=True
    )


class PageMember(Base):
    """Extensions allowed to start a page whose ``allowed`` is ``members``."""

    __tablename__ = "page_members"

    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True
    )
    extension_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), primary_key=True
    )


class PageLog(UUIDPrimaryKey, Base):
    """Every page started: from a phone (dialplan), the API, a bell or the
    interface. Pruned after 90 days by the worker."""

    __tablename__ = "page_log"

    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    page_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pages.id", ondelete="SET NULL"))
    page_name: Mapped[str] = mapped_column(String(100))
    zones: Mapped[list[str]] = mapped_column(JSONB, default=list)
    trigger: Mapped[str] = mapped_column(String(16))  # dial|api|bell|ui
    actor: Mapped[str | None] = mapped_column(String(200))
    outcome: Mapped[str] = mapped_column(String(16))  # started|failed
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
