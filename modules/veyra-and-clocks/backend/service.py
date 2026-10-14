# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sending messages, bell messages and reachability checks.

Messages are rows: a message sent now is delivered by the API request that
created it; scheduled and bell messages are delivered by the worker's
periodic task. ``FOR UPDATE SKIP LOCKED`` keeps two workers (HA) from
sending one message twice.
"""

from __future__ import annotations

import fnmatch
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import Row, func, insert, select, update
from sqlalchemy.orm import Session

from veyra.sdk import Event, ModuleContext, utcnow

from . import delivery as dl
from .models import bell_messages, clocks, delivery, messages

ALL = ("", "all", "*")


def target_label(send_to: str) -> str:
    return "All clocks" if send_to.strip().lower() in ALL else send_to.strip()


def resolve(db: Session, organization_id: uuid.UUID, send_to: str) -> list[Row[Any]]:
    """The clocks a message goes to: all of them, a group, or one clock
    (group names win over clock names; both case-insensitive)."""
    stmt = select(clocks).where(clocks.c.organization_id == organization_id)
    target = send_to.strip().lower()
    if target in ALL:
        return list(db.execute(stmt.order_by(clocks.c.name)))
    group = list(
        db.execute(stmt.where(func.lower(clocks.c.group_name) == target).order_by(clocks.c.name))
    )
    if group:
        return group
    return list(db.execute(stmt.where(func.lower(clocks.c.name) == target)))


def load_delivery(
    ctx: ModuleContext, db: Session, organization_id: uuid.UUID
) -> dl.Delivery | None:
    row = db.execute(select(delivery).where(delivery.c.organization_id == organization_id)).first()
    if row is None:
        return None
    password = ctx.decrypt(row.password_ciphertext) if row.password_ciphertext else ""
    return dl.Delivery(
        method=row.method,
        scheme=row.scheme,
        path=row.path,
        content_type=row.content_type,
        body=row.body,
        auth=row.auth,
        username=row.username,
        password=password,
    )


def deliver(ctx: ModuleContext, message_id: uuid.UUID) -> dict[str, Any]:
    """Send one message already marked ``sending``; records the outcome."""
    with ctx.session() as db:
        msg = db.execute(select(messages).where(messages.c.id == message_id)).first()
        if msg is None:
            return {}
        org = msg.organization_id
        targets = [(c.name, c.address) for c in resolve(db, org, msg.send_to)]
        setup = load_delivery(ctx, db, org)
        timeout = float(ctx.get_config(db, org)["request_timeout_seconds"])
    status, result, outcomes = "failed", "", []
    if setup is None:
        status, result = "not_sent", "Delivery is not set up (Modules → Clock Delivery)."
    elif not targets:
        result = f"No clock or group is called {msg.send_to!r}."
    else:
        sent = dl.send(
            targets,
            dl.Message(msg.text, msg.color, msg.seconds, msg.priority, msg.flashers),
            setup,
            timeout,
        )
        outcomes = [{"clock": o.clock, "ok": o.ok, "detail": o.detail} for o in sent]
        good = sum(o.ok for o in sent)
        status = "sent" if good == len(sent) else "partial" if good else "failed"
        result = f"{good} of {len(sent)} clock{'s' if len(sent) != 1 else ''}"
        failed = [o for o in sent if not o.ok]
        if failed:
            result += f"; {failed[0].clock}: {failed[0].detail}"
    with ctx.session() as db:
        db.execute(
            update(messages)
            .where(messages.c.id == message_id)
            .values(status=status, result=result[:300], outcomes=outcomes, sent_at=utcnow())
        )
        ctx.audit(
            db,
            None,
            "message.send",
            organization_id=org,
            target_type="clock_message",
            target_id=message_id,
            outcome="success" if status == "sent" else "failure",
            details={"status": status, "result": result[:300], "send_to": msg.send_to},
        )
    ctx.publish(
        "and_clocks.message_sent",
        {"message_id": str(message_id), "organization_id": str(org), "status": status},
    )
    return {"status": status, "result": result, "outcomes": outcomes}


def dispatch_due(ctx: ModuleContext) -> int:
    """Worker task: claim the scheduled messages that are due and send them.
    Messages more than an hour overdue (the server was down) are not sent."""
    now = utcnow()
    with ctx.session() as db:
        stale = db.execute(
            update(messages)
            .where(messages.c.status == "scheduled", messages.c.send_at < now - timedelta(hours=1))
            .values(status="not_sent", result="Missed: the server was not running at that time.")
        ).rowcount
        ids = list(
            db.scalars(
                select(messages.c.id)
                .where(messages.c.status == "scheduled", messages.c.send_at <= now)
                .order_by(messages.c.send_at)
                .limit(50)
                .with_for_update(skip_locked=True)
            )
        )
        if ids:
            db.execute(update(messages).where(messages.c.id.in_(ids)).values(status="sending"))
    if stale:
        ctx.log.warning("%d scheduled clock message(s) were missed", stale)
    for message_id in ids:
        deliver(ctx, message_id)
    return len(ids)


def on_bell(ctx: ModuleContext, event: Event) -> None:
    """``bell.rang``: queue the matching bell messages for the worker task."""
    p = event.payload
    try:
        org = uuid.UUID(p["organization_id"])
    except (KeyError, ValueError):
        return
    name = str(p.get("schedule_name", ""))
    summary = str(p.get("summary", ""))
    with ctx.session() as db:
        rules = db.execute(select(bell_messages).where(bell_messages.c.organization_id == org))
        for rule in rules:
            if not fnmatch.fnmatchcase(name.lower(), rule.bell_schedule.strip().lower()):
                continue
            text = (rule.text or "{summary}").replace("{summary}", summary).strip()
            if not text:
                continue
            db.execute(
                insert(messages).values(
                    id=uuid.uuid4(),
                    organization_id=org,
                    text=text[:1000],
                    send_to=rule.send_to,
                    color=rule.color,
                    seconds=rule.seconds,
                    priority="normal",
                    flashers="off",
                    send_at=utcnow(),
                    status="scheduled",
                    source="bell",
                    created_by=f"bell schedule {name}"[:320],
                )
            )


def check_reachability(ctx: ModuleContext) -> int:
    """Worker task: a TCP connection to the clock's web port, at most every
    ``check_interval_minutes``."""
    now = utcnow()
    with ctx.session() as db:
        due = []
        minutes: dict[uuid.UUID, int] = {}
        ports: dict[uuid.UUID, int] = {}
        for c in db.execute(select(clocks)):
            org = c.organization_id
            if org not in minutes:
                minutes[org] = int(ctx.get_config(db, org)["check_interval_minutes"])
                scheme = db.scalar(
                    select(delivery.c.scheme).where(delivery.c.organization_id == org)
                )
                ports[org] = 443 if scheme == "https" else 80
            if c.last_checked_at is None or now - c.last_checked_at >= timedelta(
                minutes=minutes[org]
            ):
                due.append((c.id, c.address, ports[org]))
    if not due:
        return 0
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(16, len(due))) as pool:
        states = list(pool.map(lambda d: dl.reachable(d[1], d[2], 3.0), due))
    with ctx.session() as db:
        for (clock_id, _addr, _port), ok in zip(due, states, strict=True):
            db.execute(
                update(clocks)
                .where(clocks.c.id == clock_id)
                .values(reachability="reachable" if ok else "unreachable", last_checked_at=utcnow())
            )
    return len(due)
