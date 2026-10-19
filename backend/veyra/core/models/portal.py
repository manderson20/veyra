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
