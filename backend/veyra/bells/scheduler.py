# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ring bells (docs/PAGING_RECORDINGS.md §4.2): for every enabled schedule,
find event starts (or ends) due now, ring the page once per occurrence, and
never ring late beyond the tolerance."""

from __future__ import annotations

import fnmatch
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.core.models import BellRing, BellSchedule, Calendar, CalendarEvent, Page
from veyra.core.models.base import utcnow

log = logging.getLogger("veyra.bells")


def matches(pattern: str, summary: str) -> bool:
    pattern = (pattern or "*").strip() or "*"
    return fnmatch.fnmatchcase(summary.lower(), pattern.lower())


def due_rings(
    db: Session, schedule: BellSchedule, now: datetime
) -> list[tuple[CalendarEvent, str, datetime]]:
    """``(event, trigger, due_at)`` for occurrences whose time passed within
    the tolerance and that have not rung yet."""
    tolerance = timedelta(seconds=max(0, schedule.tolerance_seconds))
    since = now - tolerance - timedelta(hours=1)
    events = db.scalars(
        select(CalendarEvent)
        .where(CalendarEvent.calendar_id == schedule.calendar_id, CalendarEvent.starts_at >= since)
        .order_by(CalendarEvent.starts_at)
    ).all()
    rung = set(
        db.scalars(
            select(BellRing.event_key).where(
                BellRing.schedule_id == schedule.id, BellRing.due_at >= since
            )
        )
    )
    out = []
    for ev in events:
        if ev.all_day and not schedule.all_day_events:
            continue
        if not matches(schedule.match, ev.summary):
            continue
        triggers = []
        if schedule.trigger in ("start", "both"):
            triggers.append(("start", ev.starts_at))
        if schedule.trigger in ("end", "both") and ev.ends_at:
            triggers.append(("end", ev.ends_at))
        for trigger, due in triggers:
            if due <= now <= due + tolerance and event_key(ev, trigger) not in rung:
                out.append((ev, trigger, due))
    return out


def event_key(ev: CalendarEvent, trigger: str) -> str:
    return f"{ev.uid}|{ev.starts_at.isoformat()}|{trigger}"[:400]


def ring(db: Session, adapter: Any, now: datetime | None = None) -> list[BellRing]:
    """One pass: ring everything due. Called by the worker every few seconds."""
    from veyra.api.v1.pages import start_page

    now = now or utcnow()
    rings: list[BellRing] = []
    schedules = db.scalars(
        select(BellSchedule)
        .join(Calendar, Calendar.id == BellSchedule.calendar_id)
        .where(BellSchedule.is_enabled.is_(True), Calendar.is_enabled.is_(True))
    ).all()
    for schedule in schedules:
        page = db.get(Page, schedule.page_id)
        for ev, trigger, due in due_rings(db, schedule, now):
            row = BellRing(
                id=uuid.uuid4(),
                schedule_id=schedule.id,
                event_key=event_key(ev, trigger),
                summary=ev.summary,
                due_at=due,
                rang_at=now,
                outcome="skipped",
                detail={"trigger": trigger},
            )
            db.add(row)
            try:
                db.flush()  # the unique key is the ring-once guard across workers
            except IntegrityError:
                db.rollback()
                continue
            if page is None:
                row.detail = {**row.detail, "reason": "no_page"}
                db.commit()
                rings.append(row)
                continue
            started, message, channel = start_page(
                db, adapter, page, trigger="bell", actor=f"bell schedule {schedule.name}"
            )
            row.outcome = "started" if started else "failed"
            row.detail = {**row.detail, "message": message, "channel": channel}
            db.commit()
            rings.append(row)
            log.info(
                "bell %s: %s at %s -> %s", schedule.name, ev.summary, due.isoformat(), row.outcome
            )
    return rings


def prune(db: Session, days: int = 90) -> int:
    cutoff = utcnow() - timedelta(days=days)
    result = db.execute(delete(BellRing).where(BellRing.rang_at < cutoff))
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)
