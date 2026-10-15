# SPDX-License-Identifier: AGPL-3.0-or-later
"""Monitoring (docs/REPORTING.md §6.1): built-in alert rules (switched and
tuned here) and the alerts they raise. Installation-wide."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, UUIDPrimaryKey, utcnow


class AlertRule(Base):
    __tablename__ = "alert_rules"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Minutes the condition must hold before the alert is raised.
    delay_minutes: Mapped[int] = mapped_column(Integer)
    # Rule-specific limit (percent, count or days); None where it has none.
    threshold: Mapped[int | None] = mapped_column(Integer)
    recipients: Mapped[list[str]] = mapped_column(ARRAY(String(254)), default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Alert(UUIDPrimaryKey, Base):
    """One occurrence: pending (condition seen, delay running), raised,
    cleared. ``subject`` names what it is about (a trunk, a service)."""

    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_rule_subject_state", "rule", "subject", "state"),)

    rule: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(100), default="")
    state: Mapped[str] = mapped_column(String(10))  # pending | raised | cleared
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notify_error: Mapped[str | None] = mapped_column(Text)
