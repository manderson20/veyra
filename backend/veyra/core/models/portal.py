# SPDX-License-Identifier: AGPL-3.0-or-later
"""User portal objects (docs/USER_PORTAL.md): personal contacts."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, Timestamps, UUIDPrimaryKey


class UserContact(UUIDPrimaryKey, Timestamps, Base):
    """A personal contact of one user (docs/USER_PORTAL.md §6): a name, up to
    five numbers, an optional speed-dial slot (1 to 99, unique per user). Used
    to resolve names on the user's call history and voicemail list, for
    click-to-dial, and as targets of user-set phone keys (§8)."""

    __tablename__ = "user_contacts"
    __table_args__ = (UniqueConstraint("user_id", "speed_dial"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    company: Mapped[str | None] = mapped_column(String(100))
    # [{"label": "work|mobile|home|other", "number": "+15735550100"}]
    numbers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    email: Mapped[str | None] = mapped_column(String(254))
    favourite: Mapped[bool] = mapped_column(Boolean, default=False)
    speed_dial: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)


class PortalTemplate(UUIDPrimaryKey, Timestamps, Base):
    """A default portal layout an administrator assigns by scope
    (docs/USER_PORTAL.md §10): system-wide (``organization_id`` NULL,
    ``scope`` = system), an organization, a building, a department or a
    role. For a user the nearest scope wins (role, department, building,
    organization, system; then the highest ``priority``); the user's own
    layout layers on top and ``locked_widgets`` cannot be removed."""

    __tablename__ = "portal_templates"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    # system | organization | building | department | role
    scope: Mapped[str] = mapped_column(String(16))
    # The building or department id, or the role key; NULL for system/organization.
    scope_ref: Mapped[str | None] = mapped_column(String(64))
    # {"version": 1, "tabs": [{"id", "name", "widgets": [{key, instance, x, y, w, h, settings}]}]}
    layout: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Widget keys the user cannot remove (an all-call or emergency widget).
    locked_widgets: Mapped[list[str]] = mapped_column(JSONB, default=list)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
