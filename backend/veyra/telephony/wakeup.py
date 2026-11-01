# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wake-up calls (issue #392): the worker rings a phone at a chosen time and
plays a message. The dialplan reports the answer with ``UserEvent(VeyraWakeup)``.
An unanswered call is tried again, three times in all, five minutes apart."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core import tenancy
from veyra.core.models import Extension, Organization, WakeupCall
from veyra.core.models.base import utcnow

log = logging.getLogger("veyra.wakeup")

MAX_PER_EXTENSION = 5
ATTEMPTS = 3
RETRY = timedelta(minutes=5)
# Later than this (the worker was down): skipped, nobody wants it at noon.
TOO_LATE = timedelta(minutes=30)


def next_occurrence(hhmm: str, timezone: str, now: datetime | None = None) -> datetime:
    """The next time the clock in ``timezone`` shows ``hhmm``, in UTC."""
    tz = ZoneInfo(timezone or "UTC")
    local = (now or utcnow()).astimezone(tz)
    at = local.replace(hour=int(hhmm[:2]), minute=int(hhmm[2:]), second=0, microsecond=0)
    if at <= local:
        at = (at.replace(tzinfo=None) + timedelta(days=1)).replace(tzinfo=tz)
    return at.astimezone(UTC)


def valid_time(hhmm: str) -> bool:
    return len(hhmm) == 4 and hhmm.isdigit() and int(hhmm[:2]) < 24 and int(hhmm[2:]) < 60


def schedule(db: Session, ext: Extension, hhmm: str, *, daily: bool, by: str) -> WakeupCall | None:
    """Add a wake-up call, or reset the one already at that time; None when
    the extension already has as many as it may."""
    org = db.get(Organization, ext.organization_id)
    rows = list(db.scalars(select(WakeupCall).where(WakeupCall.extension_id == ext.id)))
    row = next((r for r in rows if r.hhmm == hhmm), None)
    if row is None:
        if len(rows) >= MAX_PER_EXTENSION:
            return None
        row = WakeupCall(
            id=uuid.uuid4(),
            organization_id=ext.organization_id,
            extension_id=ext.id,
            hhmm=hhmm,
        )
        db.add(row)
    row.daily = daily
    row.next_at = next_occurrence(hhmm, org.timezone if org else "UTC")
    row.attempts = 0
    row.last_result = None
    row.created_by = by[:320]
    db.flush()
    return row


def _finish(db: Session, row: WakeupCall, result: str, timezone: str) -> None:
    """After an answer, or the last try: a daily one moves to tomorrow; a
    one-time one goes away if answered and stays on show if not."""
    row.attempts = 0
    row.last_result = result
    if row.daily:
        row.next_at = next_occurrence(row.hhmm, timezone)
    elif result == "answered":
        db.delete(row)
    else:
        row.next_at = None
    log.info("Wake-up call at %s: %s", row.hhmm, result)


def handle_event(db: Session, userevent: dict[str, Any]) -> int:
    """``UserEvent(VeyraWakeup)``: Action ``answered`` with Id, or from the
    phone's codes ``set`` with Time and ``cancel``, with Org and Extension."""
    f = {
        k: str(userevent.get(k) or userevent.get(k.lower()) or "").strip()
        for k in ("Org", "Extension", "Action", "Time", "Id")
    }
    if f["Action"] == "answered":
        try:
            row = db.get(WakeupCall, uuid.UUID(f["Id"]))
        except ValueError:
            return 0
        if row is None:
            return 0
        org = db.get(Organization, row.organization_id)
        _finish(db, row, "answered", org.timezone if org else "UTC")
        return 1
    org = db.scalar(select(Organization).where(Organization.slug == f["Org"]))
    if org is None:
        return 0
    ext = db.scalar(
        select(Extension).where(
            Extension.organization_id == org.id, Extension.number == f["Extension"]
        )
    )
    if ext is None:
        return 0
    if f["Action"] == "set" and valid_time(f["Time"]):
        return 1 if schedule(db, ext, f["Time"], daily=False, by="phone") else 0
    if f["Action"] == "cancel":
        n = 0
        for row in db.scalars(select(WakeupCall).where(WakeupCall.extension_id == ext.id)):
            db.delete(row)
            n += 1
        return n
    return 0


def tick(db: Session, adapter: Any) -> int:
    """Place the wake-up calls that are due (worker, every pass)."""
    if adapter is None or not hasattr(adapter, "originate_channel"):
        return 0
    now = utcnow()
    placed = 0
    zones = {o.id: o.timezone for o in db.scalars(select(Organization))}
    for row in db.scalars(select(WakeupCall).where(WakeupCall.next_at <= now)):
        timezone = zones.get(row.organization_id, "UTC")
        if row.attempts >= ATTEMPTS:
            _finish(db, row, "missed", timezone)
            continue
        if row.attempts == 0 and row.next_at is not None and now - row.next_at > TOO_LATE:
            _finish(db, row, "skipped", timezone)
            continue
        ext = db.get(Extension, row.extension_id)
        if ext is None or not ext.is_enabled:
            _finish(db, row, "missed", timezone)
            continue
        row.attempts += 1
        row.next_at = now + RETRY
        try:
            adapter.originate_channel(
                f"PJSIP/{ext.endpoint_name}",
                "s",
                context=tenancy.names_of(db, row.organization_id).wakeup,
                caller_id="Wake-up call <0>",
                timeout=30,
                variables={"VEYRA_WAKE_ID": str(row.id)},
            )
            placed += 1
        except Exception as e:
            log.warning("Wake-up call for %s not placed: %s", ext.number, e)
    db.flush()
    return placed
