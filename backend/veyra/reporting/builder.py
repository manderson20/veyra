# SPDX-License-Identifier: AGPL-3.0-or-later
"""The report builder (docs/REPORT_BUILDER.md §1): a validated definition
turned into one grouped query over ``calls`` plus a totals row."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Integer, String, and_, cast, false, func, not_, or_, select
from sqlalchemy.orm import Session

from veyra.core.models import (
    CallQueue,
    CallRecord,
    Extension,
    Organization,
    RingGroup,
    SipTrunk,
    TimeCondition,
)
from veyra.core.models.base import utcnow
from veyra.telephony.routing import DAYS

Group = Literal[
    "day",
    "week",
    "month",
    "hour",
    "weekday",
    "direction",
    "outcome",
    "answered_by",
    "called_extension",
    "calling_extension",
    "did",
    "trunk",
    "queue",
    "ring_group",
    "caller",
]
Measure = Literal[
    "calls",
    "answered",
    "missed",
    "voicemail",
    "answer_rate",
    "avg_ring",
    "total_ring",
    "avg_talk",
    "total_talk",
    "within_sl",
]
PeriodKind = Literal[
    "today",
    "yesterday",
    "last_7_days",
    "last_30_days",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "this_year",
    "custom",
]

GROUP_LABELS: dict[str, str] = {
    "day": "Day",
    "week": "Week of",
    "month": "Month",
    "hour": "Hour",
    "weekday": "Weekday",
    "direction": "Direction",
    "outcome": "Outcome",
    "answered_by": "Answered by",
    "called_extension": "Called extension",
    "calling_extension": "Calling extension",
    "did": "Number dialled (DID)",
    "trunk": "Trunk",
    "queue": "Queue",
    "ring_group": "Ring group",
    "caller": "Caller",
}
MEASURE_LABELS: dict[str, tuple[str, str]] = {
    "calls": ("Calls", "count"),
    "answered": ("Answered", "count"),
    "missed": ("Missed", "count"),
    "voicemail": ("Voicemail", "count"),
    "answer_rate": ("Answer rate", "percent"),
    "avg_ring": ("Average ring", "seconds"),
    "total_ring": ("Total ring", "seconds"),
    "avg_talk": ("Average talk", "seconds"),
    "total_talk": ("Total talk", "seconds"),
    "within_sl": ("Answered within service level", "percent"),
}
TIME_GROUPS = {"day", "week", "month", "hour", "weekday"}
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_ROWS = 1000
MAX_DAYS = 400


def _default_measures() -> list[Measure]:
    return ["calls"]


class Filters(BaseModel):
    directions: list[Literal["internal", "inbound", "outbound"]] = Field(default_factory=list)
    outcomes: list[Literal["answered", "missed", "busy", "failed", "voicemail", "abandoned"]] = (
        Field(default_factory=list)
    )
    extension_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    dids: list[str] = Field(default_factory=list, max_length=200)
    trunk_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    queues: list[str] = Field(default_factory=list, max_length=100)
    ring_groups: list[str] = Field(default_factory=list, max_length=100)
    caller_contains: str | None = Field(None, max_length=40)
    min_talk_seconds: int | None = Field(None, ge=0, le=86400)
    business_hours: Literal["any", "inside", "outside"] = "any"
    time_condition_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _hours(self) -> Filters:
        if self.business_hours != "any" and self.time_condition_id is None:
            raise ValueError("choose the time condition that defines business hours")
        return self


class Period(BaseModel):
    kind: PeriodKind = "last_7_days"
    from_date: date | None = None
    to_date: date | None = None

    @model_validator(mode="after")
    def _custom(self) -> Period:
        if self.kind == "custom":
            if self.from_date is None or self.to_date is None:
                raise ValueError("a custom period needs both dates")
            if self.to_date < self.from_date:
                raise ValueError("the period ends before it starts")
            if (self.to_date - self.from_date).days >= MAX_DAYS:
                raise ValueError(f"a report covers at most {MAX_DAYS} days")
        return self


class Definition(BaseModel):
    organization_id: uuid.UUID | None = None
    group_by: list[Group] = Field(default_factory=list, max_length=2)
    measures: list[Measure] = Field(default_factory=lambda: _default_measures(), min_length=1)
    filters: Filters = Field(default_factory=Filters)
    period: Period = Field(default_factory=Period)
    show_as: Literal["table", "bars", "line"] = "table"
    sort_by: str | None = None  # a measure, or "group"
    sort_desc: bool = True
    limit: int = Field(100, ge=1, le=MAX_ROWS)
    sl_seconds: int = Field(20, ge=1, le=600)

    @field_validator("group_by", "measures")
    @classmethod
    def _distinct(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("choose each item once")
        return v

    @model_validator(mode="after")
    def _sort(self) -> Definition:
        if (
            self.sort_by is not None
            and self.sort_by != "group"
            and self.sort_by not in self.measures
        ):
            raise ValueError("sort by the grouping or one of the chosen measures")
        return self


class ReportError(ValueError):
    pass


# ----------------------------------------------------------------- period


def resolve_period(
    p: Period, tz: str, now: datetime | None = None
) -> tuple[datetime, datetime, str]:
    """[start, end) in UTC and a label, with relative periods resolved in ``tz``."""
    zone = ZoneInfo(tz)
    local_now = (now or utcnow()).astimezone(zone)
    today = local_now.date()

    def at(d: date) -> datetime:
        return datetime.combine(d, time(0), zone)

    if p.kind == "custom":
        assert p.from_date and p.to_date
        start, end = p.from_date, p.to_date + timedelta(days=1)
    elif p.kind == "today":
        start, end = today, today + timedelta(days=1)
    elif p.kind == "yesterday":
        start, end = today - timedelta(days=1), today
    elif p.kind == "last_7_days":
        start, end = today - timedelta(days=6), today + timedelta(days=1)
    elif p.kind == "last_30_days":
        start, end = today - timedelta(days=29), today + timedelta(days=1)
    elif p.kind == "this_week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)
    elif p.kind == "last_week":
        end = today - timedelta(days=today.weekday())
        start = end - timedelta(days=7)
    elif p.kind == "this_month":
        start = today.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1)
    elif p.kind == "last_month":
        end = today.replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
    else:  # this_year
        start, end = (
            today.replace(month=1, day=1),
            today.replace(year=today.year + 1, month=1, day=1),
        )
    last = end - timedelta(days=1)
    label = start.isoformat() if start == last else f"{start.isoformat()} to {last.isoformat()}"
    return at(start), at(end), label


# ------------------------------------------------------------------ query


def _business_hours(tc: TimeCondition) -> Any:
    """SQL: the call started inside the condition's ranges and not on a holiday."""
    local = func.timezone(tc.timezone or "UTC", CallRecord.started_at)
    weekday = cast(func.extract("isodow", local), Integer)
    hhmm = func.to_char(local, "HH24:MI")
    ranges = [
        and_(
            weekday.in_([DAYS.index(d) + 1 for d in r.get("days") or []]),
            hhmm >= str(r.get("start")),
            hhmm < str(r.get("end")),
        )
        for r in tc.ranges or []
    ]
    inside: Any = or_(*ranges) if ranges else false()
    holidays = list(tc.holidays or [])
    if holidays:
        inside = and_(inside, not_(func.to_char(local, "MM-DD").in_(holidays)))
    return inside


def _group_expr(g: str, tz: str) -> Any:
    local = func.timezone(tz, CallRecord.started_at)
    return {
        "day": func.to_char(func.date_trunc("day", local), "YYYY-MM-DD"),
        "week": func.to_char(func.date_trunc("week", local), "YYYY-MM-DD"),
        "month": func.to_char(func.date_trunc("month", local), "YYYY-MM"),
        "hour": cast(func.extract("hour", local), Integer),
        "weekday": cast(func.extract("isodow", local), Integer),
        "direction": CallRecord.direction,
        "outcome": CallRecord.outcome,
        "answered_by": cast(CallRecord.answered_extension_id, String),
        "called_extension": cast(CallRecord.to_extension_id, String),
        "calling_extension": cast(CallRecord.from_extension_id, String),
        "did": CallRecord.did,
        "trunk": cast(CallRecord.trunk_id, String),
        "queue": CallRecord.queue,
        "ring_group": CallRecord.ring_group,
        "caller": CallRecord.from_number,
    }[g]


def _aggregates(sl: int) -> list[Any]:
    answered = CallRecord.outcome == "answered"
    return [
        func.count().label("calls"),
        func.count().filter(answered).label("answered"),
        func.count().filter(CallRecord.outcome.in_(("missed", "abandoned"))).label("missed"),
        func.count().filter(CallRecord.outcome == "voicemail").label("voicemail"),
        func.avg(CallRecord.ring_seconds).filter(answered).label("avg_ring"),
        func.coalesce(func.sum(CallRecord.ring_seconds), 0).label("total_ring"),
        func.avg(CallRecord.talk_seconds).filter(answered).label("avg_talk"),
        func.coalesce(func.sum(CallRecord.talk_seconds), 0).label("total_talk"),
        func.count().filter(and_(answered, CallRecord.ring_seconds <= sl)).label("sl"),
    ]


def _measures(row: Any) -> dict[str, float]:
    calls, answered = int(row.calls or 0), int(row.answered or 0)
    return {
        "calls": calls,
        "answered": answered,
        "missed": int(row.missed or 0),
        "voicemail": int(row.voicemail or 0),
        "answer_rate": round(100 * answered / calls, 1) if calls else 0.0,
        "avg_ring": round(float(row.avg_ring or 0), 1),
        "total_ring": int(row.total_ring or 0),
        "avg_talk": round(float(row.avg_talk or 0), 1),
        "total_talk": int(row.total_talk or 0),
        "within_sl": round(100 * int(row.sl or 0) / answered, 1) if answered else 0.0,
    }


class Labels:
    """Turns group keys (ids, slugs, numbers) into what people read."""

    def __init__(self, db: Session, org_ids: set[uuid.UUID] | None) -> None:
        self.db = db
        self._ext: dict[str, str] | None = None
        self._trunk: dict[str, str] | None = None
        self._queue: dict[str, str] | None = None
        self._group: dict[str, str] | None = None

    def __call__(self, g: str, key: Any) -> str:
        if key is None or key == "":
            return "(none)"
        if g == "weekday":
            return WEEKDAY_NAMES[int(key) - 1]
        if g == "hour":
            return f"{int(key):02d}:00"
        if g in ("direction", "outcome"):
            return str(key).capitalize()
        if g in ("answered_by", "called_extension", "calling_extension"):
            if self._ext is None:
                self._ext = {
                    str(e.id): f"{e.number} {e.display_name}"
                    for e in self.db.scalars(select(Extension))
                }
            return self._ext.get(str(key), "(removed extension)")
        if g == "trunk":
            if self._trunk is None:
                self._trunk = {str(t.id): t.name for t in self.db.scalars(select(SipTrunk))}
            return self._trunk.get(str(key), "(removed trunk)")
        if g == "queue":
            if self._queue is None:
                self._queue = {
                    q.slug: f"{q.number} {q.name}" for q in self.db.scalars(select(CallQueue))
                }
            return self._queue.get(str(key), str(key))
        if g == "ring_group":
            if self._group is None:
                self._group = {
                    r.slug: f"{r.number} {r.name}" for r in self.db.scalars(select(RingGroup))
                }
            return self._group.get(str(key), str(key))
        return str(key)


def org_timezone(
    db: Session, organization_id: uuid.UUID | None, org_ids: set[uuid.UUID] | None
) -> str:
    org_id = organization_id or (next(iter(org_ids)) if org_ids and len(org_ids) == 1 else None)
    org = db.get(Organization, org_id) if org_id else None
    return org.timezone if org is not None and org.timezone else "UTC"


def run(
    db: Session,
    d: Definition,
    org_ids: set[uuid.UUID] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """``org_ids``: the organizations the caller may report on (None: all)."""
    if org_ids is not None and d.organization_id is not None and d.organization_id not in org_ids:
        raise ReportError("not allowed to report on that organization")
    tz = org_timezone(db, d.organization_id, org_ids)
    start, end, label = resolve_period(d.period, tz, now)

    conds: list[Any] = [CallRecord.started_at >= start, CallRecord.started_at < end]
    if org_ids is not None:
        conds.append(CallRecord.organization_id.in_(org_ids or {uuid.UUID(int=0)}))
    if d.organization_id is not None:
        conds.append(CallRecord.organization_id == d.organization_id)
    f = d.filters
    if f.directions:
        conds.append(CallRecord.direction.in_(f.directions))
    if f.outcomes:
        conds.append(CallRecord.outcome.in_(f.outcomes))
    if f.extension_ids:
        ids = set(f.extension_ids)
        conds.append(
            or_(
                CallRecord.from_extension_id.in_(ids),
                CallRecord.to_extension_id.in_(ids),
                CallRecord.answered_extension_id.in_(ids),
            )
        )
    if f.dids:
        conds.append(CallRecord.did.in_(f.dids))
    if f.trunk_ids:
        conds.append(CallRecord.trunk_id.in_(set(f.trunk_ids)))
    if f.queues:
        conds.append(CallRecord.queue.in_(f.queues))
    if f.ring_groups:
        conds.append(CallRecord.ring_group.in_(f.ring_groups))
    if f.caller_contains:
        conds.append(CallRecord.from_number.ilike(f"%{f.caller_contains.strip()}%"))
    if f.min_talk_seconds:
        conds.append(CallRecord.talk_seconds >= f.min_talk_seconds)
    if f.business_hours != "any":
        tc = db.get(TimeCondition, f.time_condition_id)
        if tc is None or (org_ids is not None and tc.organization_id not in org_ids):
            raise ReportError("time condition not found")
        inside = _business_hours(tc)
        conds.append(inside if f.business_hours == "inside" else not_(inside))

    aggs = _aggregates(d.sl_seconds)
    totals_row = db.execute(select(*aggs).where(*conds)).one()
    totals = _measures(totals_row)

    groups = [(g, _group_expr(g, tz).label(f"g{i}")) for i, g in enumerate(d.group_by)]
    rows: list[dict[str, Any]] = []
    truncated = False
    if groups:
        stmt = (
            select(*[e for _, e in groups], *aggs).where(*conds).group_by(*[e for _, e in groups])
        )
        result = db.execute(stmt).all()
        labels = Labels(db, org_ids)
        for r in result:
            keys = [getattr(r, f"g{i}") for i in range(len(groups))]
            rows.append(
                {
                    "group": [
                        {"key": None if k is None else str(k), "label": labels(g, k)}
                        for (g, _), k in zip(groups, keys, strict=True)
                    ],
                    **{m: v for m, v in _measures(r).items() if m in d.measures},
                }
            )
        sort_by = d.sort_by or ("group" if d.group_by[0] in TIME_GROUPS else d.measures[0])
        if sort_by == "group":
            # Time groups sort naturally on their keys; others by label.
            def gkey(row: dict[str, Any]) -> tuple[Any, ...]:
                out: list[Any] = []
                for (g, _), part in zip(groups, row["group"], strict=True):
                    k = part["key"]
                    if g in ("hour", "weekday"):
                        out.append(int(k) if k is not None else -1)
                    elif g in TIME_GROUPS:
                        out.append(k or "")
                    else:
                        out.append(part["label"].lower())
                return tuple(out)

            rows.sort(key=gkey, reverse=d.sort_desc and d.sort_by == "group")
        else:
            rows.sort(key=lambda row: row[sort_by], reverse=d.sort_desc)
        if len(rows) > d.limit:
            rows, truncated = rows[: d.limit], True

    columns = [{"key": g, "label": GROUP_LABELS[g], "kind": "group"} for g in d.group_by] + [
        {"key": m, "label": MEASURE_LABELS[m][0], "kind": "measure", "unit": MEASURE_LABELS[m][1]}
        for m in d.measures
    ]
    return {
        "columns": columns,
        "rows": rows,
        "totals": {m: totals[m] for m in d.measures},
        "truncated": truncated,
        "period": {"from": start, "to": end, "label": label, "timezone": tz},
    }


def to_csv(result: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    unit = {"seconds": " (seconds)", "percent": " (%)"}
    w.writerow([c["label"] + unit.get(c.get("unit", ""), "") for c in result["columns"]])
    groups = [c for c in result["columns"] if c["kind"] == "group"]
    measures = [c for c in result["columns"] if c["kind"] == "measure"]
    for row in result["rows"]:
        w.writerow([p["label"] for p in row["group"]] + [row[m["key"]] for m in measures])
    if groups:
        w.writerow(
            ["Total"] + [""] * (len(groups) - 1) + [result["totals"][m["key"]] for m in measures]
        )
    else:
        w.writerow([result["totals"][m["key"]] for m in measures])
    return buf.getvalue()
