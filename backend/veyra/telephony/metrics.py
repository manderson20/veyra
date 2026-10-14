# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call samples for the dashboard graphs (docs/INTERFACE_REWORK.md §2):
the worker records one row per iteration, the API serves downsampled series."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from veyra.core.models import CallSample
from veyra.core.models.base import utcnow
from veyra.telephony.adapter import ActiveCall, Capability, EngineUnavailable, TelephonyAdapter

RETENTION_DAYS = 14
MAX_POINTS = 300
RANGES: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}
TRUNK_PREFIX = "trunk-"


@dataclass(frozen=True)
class Reading:
    channels: int
    calls_internal: int
    calls_external: int
    registrations: int

    def as_dict(self) -> dict[str, int]:
        return {
            "channels": self.channels,
            "calls_internal": self.calls_internal,
            "calls_external": self.calls_external,
            "registrations": self.registrations,
        }


def classify(calls: list[ActiveCall], registrations: int) -> Reading:
    """Channels are the engine legs with an endpoint (``Local/`` helper
    channels have none); each outside call has exactly one trunk leg; the
    remaining legs pair up into internal calls (an estimate during set-up)."""
    legs = [c for c in calls if c.endpoint]
    external = sum(1 for c in legs if c.endpoint and c.endpoint.startswith(TRUNK_PREFIX))
    internal = max(0, (len(legs) - 2 * external) // 2)
    return Reading(len(legs), internal, external, registrations)


def read(adapter: TelephonyAdapter) -> Reading | None:
    """A live reading, or None when the engine cannot report calls."""
    try:
        if adapter.health().state != "running":
            return None
        caps = adapter.capabilities()
        if Capability.ACTIVE_CALLS not in caps:
            return None
        calls = adapter.active_calls()
        registrations = (
            sum(1 for e in adapter.endpoint_statuses() if e.registered)
            if Capability.ENDPOINT_STATUS in caps
            else 0
        )
    except EngineUnavailable:
        return None
    return classify(calls, registrations)


def record_sample(db: Session, adapter: TelephonyAdapter) -> Reading | None:
    reading = read(adapter)
    if reading is None:
        return None
    db.add(CallSample(at=utcnow(), **reading.as_dict()))
    db.commit()
    return reading


def prune(db: Session, days: int = RETENTION_DAYS) -> int:
    cutoff = utcnow() - timedelta(days=days)
    result = db.execute(delete(CallSample).where(CallSample.at < cutoff))
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def series(db: Session, range_key: str, now: datetime | None = None) -> dict[str, Any]:
    """Samples of the range bucketed to at most ``MAX_POINTS`` points; each
    bucket keeps the maximum of every column so peaks survive."""
    span = RANGES[range_key]
    now = now or utcnow()
    since = now - span
    step = max(30, int(span.total_seconds() // MAX_POINTS))
    rows = db.scalars(
        select(CallSample).where(CallSample.at >= since).order_by(CallSample.at)
    ).all()
    buckets: dict[int, dict[str, int]] = {}
    for r in rows:
        key = int((r.at - since).total_seconds() // step)
        b = buckets.get(key)
        values = {
            "channels": r.channels,
            "calls_internal": r.calls_internal,
            "calls_external": r.calls_external,
            "registrations": r.registrations,
        }
        if b is None:
            buckets[key] = values
        else:
            for k, v in values.items():
                b[k] = max(b[k], v)
    points = [
        {"at": (since + timedelta(seconds=key * step)).isoformat(), **values}
        for key, values in sorted(buckets.items())
    ]
    return {"range": range_key, "step_seconds": step, "since": since.isoformat(), "points": points}
