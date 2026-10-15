# SPDX-License-Identifier: AGPL-3.0-or-later
"""Saved reports of the report builder (docs/REPORT_BUILDER.md §2-3): a
definition, who sees it, and an optional email schedule."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class SavedReport(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    __tablename__ = "saved_reports"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    shared: Mapped[bool] = mapped_column(Boolean, default=True)
    # {"frequency": "daily|weekly|monthly", "hour": 0-23, "weekday": 0-6,
    #  "day": 1-28, "recipients": [...]}; None: not scheduled.
    schedule: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
