# SPDX-License-Identifier: AGPL-3.0-or-later
"""Usage by organization for billing (docs/MULTI_TENANCY_MSP.md §9).

Per organization, trunk and month: outside calls in and out, their minutes,
billable minutes (each call rounded up to a whole minute, owner decision 6),
emergency calls apart (never billable), internal calls as a count, and the
most outside calls the organization had at once.
"""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.models import CallRecord, Organization, SipTrunk


@dataclass
class UsageRow:
    organization_id: str
    organization: str
    trunk: str
    inbound_calls: int = 0
    outbound_calls: int = 0
    inbound_minutes: float = 0.0
    outbound_minutes: float = 0.0
    billable_minutes: int = 0
    emergency_calls: int = 0
    internal_calls: int = 0
    peak_concurrent: int = 0


def month_bounds(month: str) -> tuple[datetime, datetime]:
    """``2026-11`` -> the month's first instant and the next month's (UTC)."""
    year, mon = (int(x) for x in month.split("-", 1))
    if not 1 <= mon <= 12:
        raise ValueError("month must be YYYY-MM")
    start = datetime(year, mon, 1, tzinfo=UTC)
    end = datetime(year + (mon == 12), mon % 12 + 1, 1, tzinfo=UTC)
    return start, end


def _peak(intervals: list[tuple[datetime, datetime]]) -> int:
    events = sorted([(s, 1) for s, _ in intervals] + [(e, -1) for _, e in intervals])
    now = best = 0
    for _, step in events:
        now += step
        best = max(best, now)
    return best


def usage(
    db: Session, month: str, organization_ids: set[uuid.UUID] | None = None
) -> list[UsageRow]:
    start, end = month_bounds(month)
    q = select(CallRecord).where(
        CallRecord.started_at >= start,
        CallRecord.started_at < end,
        CallRecord.organization_id.is_not(None),
    )
    if organization_ids is not None:
        q = q.where(CallRecord.organization_id.in_(organization_ids or {uuid.UUID(int=0)}))
    names = {o.id: o.name for o in db.scalars(select(Organization))}
    trunks = {t.id: t.name for t in db.scalars(select(SipTrunk))}
    rows: dict[tuple[uuid.UUID, str], UsageRow] = {}
    spans: dict[uuid.UUID, list[tuple[datetime, datetime]]] = {}

    def row(org: uuid.UUID, trunk: str) -> UsageRow:
        key = (org, trunk)
        if key not in rows:
            rows[key] = UsageRow(str(org), names.get(org, "(removed organization)"), trunk)
        return rows[key]

    for c in db.scalars(q):
        org = c.organization_id
        assert org is not None
        if c.direction == "internal":
            row(org, "").internal_calls += 1
            continue
        r = row(org, trunks.get(c.trunk_id, "(removed trunk)") if c.trunk_id else "")
        if c.is_emergency:
            r.emergency_calls += 1
            continue
        minutes = (c.talk_seconds or 0) / 60
        if c.direction == "inbound":
            r.inbound_calls += 1
            r.inbound_minutes += minutes
        else:
            r.outbound_calls += 1
            r.outbound_minutes += minutes
        r.billable_minutes += -(-(c.talk_seconds or 0) // 60)
        if c.ended_at is not None:
            spans.setdefault(org, []).append((c.started_at, c.ended_at))
    peaks = {org: _peak(s) for org, s in spans.items()}
    out = sorted(rows.values(), key=lambda r: (r.organization, r.trunk))
    for r in out:
        r.inbound_minutes = round(r.inbound_minutes, 1)
        r.outbound_minutes = round(r.outbound_minutes, 1)
        # The organization's peak over all its trunks, on each of its rows.
        r.peak_concurrent = peaks.get(uuid.UUID(r.organization_id), 0)
    return out


COLUMNS = [
    ("organization", "Organization"),
    ("trunk", "Trunk"),
    ("inbound_calls", "Inbound calls"),
    ("inbound_minutes", "Inbound minutes"),
    ("outbound_calls", "Outbound calls"),
    ("outbound_minutes", "Outbound minutes"),
    ("billable_minutes", "Billable minutes"),
    ("emergency_calls", "Emergency calls"),
    ("internal_calls", "Internal calls"),
    ("peak_concurrent", "Most outside calls at once"),
]


def to_csv(rows: list[UsageRow], month: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Month", *(label for _, label in COLUMNS)])
    for r in rows:
        d = asdict(r)
        w.writerow([month, *(d[key] for key, _ in COLUMNS)])
    return buf.getvalue()
