# SPDX-License-Identifier: AGPL-3.0-or-later
"""Asterisk's queue_log for queue reports (docs/REPORTING.md §5.1).

Lines are ``epoch|callid|queue|agent|event|data1|data2|data3…``; only
Veyra's queues (``veyra-<slug>``) are kept, with the slug as the queue."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from veyra.core.models import CallQueue, Extension, QueueEvent, QueueMember
from veyra.core.models.base import utcnow
from veyra.reporting.cdr import CdrReader, retention_days
from veyra.telephony import agents
from veyra.telephony.asterisk.names import queue_key_of

log = logging.getLogger("veyra.reporting")

QUEUE_LOG = Path("/var/log/asterisk/queue_log")
CURSOR_KEY = "queue_log.cursor"
EVENTS = {
    "ENTERQUEUE",
    "CONNECT",
    "ABANDON",
    "EXITWITHTIMEOUT",
    "EXITWITHKEY",
    "EXITEMPTY",
    "COMPLETECALLER",
    "COMPLETEAGENT",
    "RINGNOANSWER",
    "TRANSFER",
    # Agent states for the queue report (issue #135).
    "ADDMEMBER",
    "REMOVEMEMBER",
    "PAUSE",
    "UNPAUSE",
}


def parse_line(line: str) -> QueueEvent | None:
    parts = line.rstrip("\n").split("|")
    if len(parts) < 5:
        return None
    epoch, callid, queue, agent, event = parts[:5]
    key = queue_key_of(queue)
    if event not in EVENTS or key is None:
        return None
    try:
        at = datetime.fromtimestamp(int(epoch), UTC)
    except (ValueError, OverflowError, OSError):
        return None
    data = [*parts[5:8], "", "", ""][:3]
    return QueueEvent(
        id=uuid.uuid4(),
        at=at,
        callid=callid[:64],
        queue=key[:80],
        agent=agent[:128] if agent != "NONE" else "",
        event=event,
        data1=data[0][:64],
        data2=data[1][:64],
        data3=data[2][:64],
    )


def ingest(db: Session, lines: Iterable[str]) -> int:
    n = 0
    for line in lines:
        ev = parse_line(line)
        if ev is not None:
            db.add(ev)
            n += 1
    db.flush()
    return n


def process(db: Session, reader: CdrReader | None = None, adapter: Any = None) -> int:
    n = ingest(db, (reader or CdrReader(QUEUE_LOG, CURSOR_KEY)).read(db))
    if n:
        auto_pause(db, adapter)
    return n


def auto_pause(db: Session, adapter: Any = None) -> int:
    """Pause a logged-in dynamic agent whose last calls in a row rang out
    (issue #392): the rows stay the truth, so this goes through ``agents`` and
    not the engine's own autopause. A ring of under a second is a phone that
    was busy or gone, not a missed call."""
    paused = 0
    rows = db.execute(
        select(QueueMember, CallQueue, Extension)
        .join(CallQueue, CallQueue.id == QueueMember.queue_id)
        .join(Extension, Extension.id == QueueMember.extension_id)
        .where(
            CallQueue.auto_pause_misses > 0,
            CallQueue.is_enabled.is_(True),
            QueueMember.dynamic.is_(True),
            QueueMember.logged_in.is_(True),
            QueueMember.paused.is_(False),
        )
    ).all()
    for member, queue, ext in rows:
        # The log names an agent by its member name or its interface.
        stmt = select(QueueEvent.event, QueueEvent.data1).where(
            QueueEvent.queue == queue.slug,
            QueueEvent.agent.in_([ext.display_name, f"PJSIP/{ext.endpoint_name}"]),
            QueueEvent.event.in_(("RINGNOANSWER", "CONNECT", "UNPAUSE", "ADDMEMBER")),
        )
        if member.state_at is not None:
            # Misses before the agent's last change don't count.
            stmt = stmt.where(QueueEvent.at > member.state_at)
        latest = db.execute(
            stmt.order_by(QueueEvent.at.desc()).limit(queue.auto_pause_misses)
        ).all()
        missed = [e for e, ms in latest if e == "RINGNOANSWER" and ms.isdigit() and int(ms) >= 1000]
        if len(latest) == queue.auto_pause_misses == len(missed):
            agents.set_state(db, queue, ext, paused=True, by="auto-pause", adapter=adapter)
            paused += 1
    return paused


def prune(db: Session, now: datetime | None = None) -> int:
    cutoff = (now or utcnow()) - timedelta(days=retention_days(db))
    res = db.execute(delete(QueueEvent).where(QueueEvent.at < cutoff))
    return int(getattr(res, "rowcount", 0) or 0)
