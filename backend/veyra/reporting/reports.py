# SPDX-License-Identifier: AGPL-3.0-or-later
"""Report queries (docs/REPORTING.md §5.1) over ``calls``, ``queue_events``
and ``call_samples``. Days and hours are bucketed in the organization's time
zone so "Monday 8 am" means the school's Monday morning."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import Integer, and_, case, cast, func, select
from sqlalchemy.orm import Session

from veyra.core import tenancy
from veyra.core.models import (
    CallQueue,
    CallRecord,
    CallSample,
    Extension,
    QueueEvent,
    SipTrunk,
)
from veyra.reporting.cdr import endpoint_of
from veyra.telephony.asterisk.names import Names

SERVICE_LEVEL_SECONDS = 20
MISSED = ("missed", "abandoned")


def _scope(stmt: Any, org_ids: set[uuid.UUID] | None, organization_id: uuid.UUID | None) -> Any:
    if org_ids is not None:
        stmt = stmt.where(CallRecord.organization_id.in_(org_ids or {uuid.UUID(int=0)}))
    if organization_id is not None:
        stmt = stmt.where(CallRecord.organization_id == organization_id)
    return stmt


def calls_report(
    db: Session,
    *,
    since: datetime,
    until: datetime,
    tz: str,
    org_ids: set[uuid.UUID] | None,
    organization_id: uuid.UUID | None,
) -> dict[str, Any]:
    period = and_(CallRecord.started_at >= since, CallRecord.started_at < until)
    local = func.timezone(tz, CallRecord.started_at)

    day = func.date_trunc("day", local).label("day")
    rows = db.execute(
        _scope(
            select(day, CallRecord.direction, CallRecord.outcome, func.count())
            .where(period)
            .group_by(day, CallRecord.direction, CallRecord.outcome)
            .order_by(day),
            org_ids,
            organization_id,
        )
    ).all()
    by_day: dict[str, dict[str, int]] = {}
    for d, direction, outcome, n in rows:
        key = d.date().isoformat()
        entry = by_day.setdefault(
            key,
            {"inbound": 0, "outbound": 0, "internal": 0, "answered": 0, "missed": 0, "total": 0},
        )
        entry[direction] = entry.get(direction, 0) + n
        entry["total"] += n
        if outcome == "answered":
            entry["answered"] += n
        elif outcome in MISSED:
            entry["missed"] += n

    weekday = cast(func.extract("isodow", local), Integer).label("weekday")
    hour = cast(func.extract("hour", local), Integer).label("hour")
    heat = db.execute(
        _scope(
            select(weekday, hour, func.count()).where(period).group_by(weekday, hour),
            org_ids,
            organization_id,
        )
    ).all()
    heatmap = [[0] * 24 for _ in range(7)]
    for wd, h, n in heat:
        heatmap[int(wd) - 1][int(h)] = n

    answered = CallRecord.outcome == "answered"
    totals_row = db.execute(
        _scope(
            select(
                func.count(),
                func.count().filter(answered),
                func.count().filter(CallRecord.outcome.in_(MISSED)),
                func.count().filter(CallRecord.outcome == "voicemail"),
                func.avg(CallRecord.ring_seconds).filter(answered),
                func.avg(CallRecord.talk_seconds).filter(answered),
                func.count().filter(CallRecord.direction == "inbound"),
                func.count().filter(
                    and_(
                        CallRecord.direction == "inbound",
                        answered,
                        CallRecord.ring_seconds <= SERVICE_LEVEL_SECONDS,
                    )
                ),
            ).where(period),
            org_ids,
            organization_id,
        )
    ).one()
    total, n_answered, n_missed, n_voicemail, avg_ring, avg_talk, inbound, inbound_fast = totals_row

    ext_answered = db.execute(
        _scope(
            select(
                CallRecord.answered_extension_id,
                func.count(),
                func.coalesce(func.sum(CallRecord.talk_seconds), 0),
            )
            .where(period, CallRecord.answered_extension_id.is_not(None))
            .group_by(CallRecord.answered_extension_id),
            org_ids,
            organization_id,
        )
    ).all()
    ext_missed = db.execute(
        _scope(
            select(CallRecord.to_extension_id, func.count())
            .where(
                period,
                CallRecord.to_extension_id.is_not(None),
                CallRecord.outcome.in_((*MISSED, "voicemail")),
            )
            .group_by(CallRecord.to_extension_id),
            org_ids,
            organization_id,
        )
    ).all()
    per_ext: dict[uuid.UUID, dict[str, int]] = defaultdict(
        lambda: {"answered": 0, "talk_seconds": 0, "missed": 0}
    )
    for ext_id, n, talk in ext_answered:
        per_ext[ext_id]["answered"] = n
        per_ext[ext_id]["talk_seconds"] = int(talk)
    for ext_id, n in ext_missed:
        per_ext[ext_id]["missed"] = n
    exts = (
        {e.id: e for e in db.scalars(select(Extension).where(Extension.id.in_(set(per_ext))))}
        if per_ext
        else {}
    )
    ranked = sorted(
        (i for i in per_ext if i in exts),
        key=lambda i: (-per_ext[i]["answered"], -per_ext[i]["missed"], exts[i].number),
    )[:25]
    extensions: list[dict[str, Any]] = [
        {
            "extension_id": str(i),
            "number": exts[i].number,
            "display_name": exts[i].display_name,
            **per_ext[i],
        }
        for i in ranked
    ]

    trunk_rows = db.execute(
        _scope(
            select(
                CallRecord.trunk_id,
                CallRecord.direction,
                func.count(),
                func.coalesce(func.sum(CallRecord.talk_seconds), 0),
            )
            .where(period, CallRecord.trunk_id.is_not(None))
            .group_by(CallRecord.trunk_id, CallRecord.direction),
            org_ids,
            organization_id,
        )
    ).all()
    names = {t.id: t.name for t in db.scalars(select(SipTrunk))}
    trunks: dict[str, dict[str, Any]] = {}
    for trunk_id, direction, n, talk in trunk_rows:
        t = trunks.setdefault(
            str(trunk_id),
            {
                "trunk_id": str(trunk_id),
                "name": names.get(trunk_id, "?"),
                "inbound": 0,
                "outbound": 0,
                "talk_seconds": 0,
            },
        )
        t[direction] = t.get(direction, 0) + n
        t["talk_seconds"] += int(talk)
    peak = db.scalar(
        select(func.max(CallSample.calls_external)).where(
            CallSample.at >= since, CallSample.at < until
        )
    )

    return {
        "timezone": tz,
        "totals": {
            "calls": total,
            "answered": n_answered,
            "missed": n_missed,
            "voicemail": n_voicemail,
            "avg_ring_seconds": round(float(avg_ring or 0), 1),
            "avg_talk_seconds": round(float(avg_talk or 0), 1),
            "inbound": inbound,
            "inbound_answered_within_sl": inbound_fast,
            "service_level_seconds": SERVICE_LEVEL_SECONDS,
        },
        "by_day": [{"day": k, **v} for k, v in sorted(by_day.items())],
        "heatmap": heatmap,
        "extensions": extensions,
        "trunks": sorted(trunks.values(), key=lambda t: t["name"]),
        "peak_external_calls": int(peak or 0),
    }


def queues_report(
    db: Session,
    *,
    since: datetime,
    until: datetime,
    org_ids: set[uuid.UUID] | None,
    organization_id: uuid.UUID | None,
) -> list[dict[str, Any]]:
    stmt = select(CallQueue)
    if org_ids is not None:
        stmt = stmt.where(CallQueue.organization_id.in_(org_ids or {uuid.UUID(int=0)}))
    if organization_id is not None:
        stmt = stmt.where(CallQueue.organization_id == organization_id)
    spaces = tenancy.namespaces(db)
    queues = {
        Names(spaces.get(q.organization_id, "")).queue_key(q.slug): q for q in db.scalars(stmt)
    }
    if not queues:
        return []
    wait = cast(func.nullif(QueueEvent.data1, ""), Integer)
    rows = db.execute(
        select(
            QueueEvent.queue,
            func.count().filter(QueueEvent.event == "ENTERQUEUE"),
            func.count().filter(QueueEvent.event == "CONNECT"),
            func.count().filter(QueueEvent.event == "ABANDON"),
            func.count().filter(QueueEvent.event.in_(("EXITWITHTIMEOUT", "EXITEMPTY"))),
            func.avg(case((QueueEvent.event == "CONNECT", wait))),
            func.count().filter(and_(QueueEvent.event == "CONNECT", wait <= SERVICE_LEVEL_SECONDS)),
        )
        .where(QueueEvent.at >= since, QueueEvent.at < until, QueueEvent.queue.in_(set(queues)))
        .group_by(QueueEvent.queue)
    ).all()
    agents = db.execute(
        select(QueueEvent.queue, QueueEvent.agent, func.count())
        .where(
            QueueEvent.at >= since,
            QueueEvent.at < until,
            QueueEvent.queue.in_(set(queues)),
            QueueEvent.event == "CONNECT",
        )
        .group_by(QueueEvent.queue, QueueEvent.agent)
    ).all()
    by_endpoint = {e.endpoint_name: e for e in db.scalars(select(Extension))}
    per_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for queue, agent, n in agents:
        ext = by_endpoint.get(endpoint_of(f"{agent}-00000000") or agent.removeprefix("PJSIP/"))
        per_agent[queue].append(
            {
                "agent": f"{ext.number} {ext.display_name}" if ext else agent,
                "answered": n,
            }
        )
    out = []
    stats = {r[0]: r for r in rows}
    for slug, q in sorted(queues.items(), key=lambda kv: kv[1].number):
        r = stats.get(slug)
        offered, connected, abandoned, timeouts, avg_wait, within = (
            (r[1], r[2], r[3], r[4], r[5], r[6]) if r else (0, 0, 0, 0, None, 0)
        )
        out.append(
            {
                "queue_id": str(q.id),
                "number": q.number,
                "name": q.name,
                "offered": offered,
                "answered": connected,
                "abandoned": abandoned,
                "timed_out": timeouts,
                "avg_wait_seconds": round(float(avg_wait or 0), 1),
                "answered_within_sl": within,
                "service_level_seconds": SERVICE_LEVEL_SECONDS,
                "agents": sorted(per_agent.get(slug, []), key=lambda a: -a["answered"]),
            }
        )
    return out
