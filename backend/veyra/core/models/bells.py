# SPDX-License-Identifier: AGPL-3.0-or-later
"""Calendars and bell schedules (docs/PAGING_RECORDINGS.md §4): an external
calendar subscription polled by the worker, its cached events, the schedules
that ring a page at event starts, and the ring log."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class Calendar(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """An iCal/ICS feed (Google Calendar's secret address or any feed). The
    URL is a secret for Google, so it is encrypted with the installation key
    (purpose ``calendar.url:<id>``)."""

    __tablename__ = "calendars"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(16), default="ical")
    url_ciphertext: Mapped[str] = mapped_column(Text)
    # Shown instead of the URL: scheme and host only.
    url_display: Mapped[str] = mapped_column(String(200))
    poll_minutes: Mapped[int] = mapped_column(Integer, default=3)
    timezone: Mapped[str | None] = mapped_column(String(64))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(16))  # ok | failed
    last_error: Mapped[str | None] = mapped_column(Text)
    event_count: Mapped[int] = mapped_column(Integer, default=0)


class CalendarEvent(UUIDPrimaryKey, Base):
    """Occurrences of the next days, expanded from recurring rules."""

    __tablename__ = "calendar_events"
    __table_args__ = (UniqueConstraint("calendar_id", "uid", "starts_at"),)

    calendar_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calendars.id", ondelete="CASCADE"), index=True
    )
    uid: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(String(200))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)


class BellSchedule(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """Rings ``page`` at the start (or end) of the calendar's events."""

    __tablename__ = "bell_schedules"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    calendar_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calendars.id", ondelete="CASCADE"), index=True
    )
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"))
    # Glob on the event summary (``*`` = every event), case-insensitive.
    match: Mapped[str] = mapped_column(String(100), default="*")
    trigger: Mapped[str] = mapped_column(String(8), default="start")  # start | end | both
    tolerance_seconds: Mapped[int] = mapped_column(Integer, default=90)
    all_day_events: Mapped[bool] = mapped_column(Boolean, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class BellRing(UUIDPrimaryKey, Base):
    """One ring per (schedule, event occurrence, trigger): the ring-once guard
    and the history. Pruned after 90 days."""

    __tablename__ = "bell_rings"
    __table_args__ = (UniqueConstraint("schedule_id", "event_key"),)

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bell_schedules.id", ondelete="CASCADE"), index=True
    )
    # ``<uid>|<starts_at iso>|<trigger>``
    event_key: Mapped[str] = mapped_column(String(400))
    summary: Mapped[str] = mapped_column(String(200))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    rang_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(16))  # started | failed | skipped
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
