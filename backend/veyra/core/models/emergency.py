# SPDX-License-Identifier: AGPL-3.0-or-later
"""Emergency calls and their notifications (docs/PRODUCTION_HARDENING.md §6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, UUIDPrimaryKey, utcnow


class EmergencyCall(UUIDPrimaryKey, Base):
    __tablename__ = "emergency_calls"

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), index=True
    )
    extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL")
    )
    extension_number: Mapped[str] = mapped_column(String(32))
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL")
    )
    number: Mapped[str] = mapped_column(String(32))
    route: Mapped[str | None] = mapped_column(String(40))
    caller_id: Mapped[str | None] = mapped_column(String(32))
    location: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(String(120))
    # test | live
    kind: Mapped[str] = mapped_column(String(8), default="live")
    notifications: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    callback_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
