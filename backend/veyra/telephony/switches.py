# SPDX-License-Identifier: AGPL-3.0-or-later
"""Engine switches (docs/CALL_FEATURES.md §4.5, §4.6): named on/off states the
dialplan reads at call time and phones flip with a feature code, kept in
the engine's store (``veyra/switch/<kind>/<org>/<key>``) behind a custom
device state for the BLF lamp (``Custom:veyra-<kind>-<org>-<key>``).

Two kinds: ``flow`` (a call flow is switched to its override destination,
value ``1``) and ``tc`` (a time condition is forced ``open`` or ``closed``).
The rows are the truth: the API writes the row and the engine, the dialplan
writes the engine and tells the API through ``UserEvent(VeyraSwitch)``, and
the worker's sync makes the engine match the rows every pass and clears
temporary time-condition overrides once the schedule itself has moved on.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.events import Event, bus
from veyra.core.models import Calendar, CalendarEvent, CallFlow, Organization, TimeCondition
from veyra.core.models.base import utcnow
from veyra.telephony import routing
from veyra.telephony.adapter import Capability, EngineUnavailable, NotSupported

log = logging.getLogger("veyra.switches")

FAMILY = "veyra/switch"
KINDS = ("flow", "tc")
# Lamp-only kinds written by the agents module (docs/CALL_FEATURES.md §4.9).
LAMP_KINDS = ("agent", "agentpause")
SWITCH_EVENT = "VeyraSwitch"
TC_STATES = ("open", "closed")
# The engine's value while a calendar event closes a condition: callers get
# "closed", but the phone code forces it open instead of clearing it.
TC_CALENDAR = "calendar"


def device(kind: str, org: str, key: str) -> str:
    """The custom device state behind a switch's BLF lamp."""
    return f"Custom:veyra-{kind}-{org}-{key}"


def supports(adapter: Any) -> bool:
    try:
        return adapter is not None and Capability.EXTENSION_STATE in adapter.capabilities()
    except Exception:
        return False


def tc_key(tc: TimeCondition) -> str:
    return str(tc.id)


# ----------------------------------------------------------------- writes


def _write(adapter: Any, kind: str, org: str, key: str, value: str | None) -> None:
    if not supports(adapter):
        return
    try:
        adapter.set_switch(kind, org, key, value)
    except (EngineUnavailable, NotSupported, ValueError) as e:
        log.warning("Switch %s/%s/%s not written to the engine: %s", kind, org, key, e)


def set_flow(db: Session, flow: CallFlow, override: bool, *, by: str, adapter: Any = None) -> bool:
    """Switch a call flow; returns whether anything changed."""
    if flow.override == override:
        return False
    flow.override = override
    flow.override_by = by
    flow.override_at = utcnow()
    db.flush()
    org = db.get(Organization, flow.organization_id)
    _write(adapter, "flow", org.slug if org else "", flow.slug, "1" if override else None)
    bus.publish(
        Event(
            "call_flow.switched",
            {
                "call_flow_id": str(flow.id),
                "organization_id": str(flow.organization_id),
                "override": override,
                "by": by,
            },
        )
    )
    return True


def set_time_condition(
    db: Session,
    tc: TimeCondition,
    state: str | None,
    *,
    temporary: bool,
    by: str,
    adapter: Any = None,
    now: datetime | None = None,
) -> bool:
    """Force a time condition ``open`` or ``closed`` (None: back to the
    schedule). A temporary override ends when the schedule itself changes
    state; returns whether anything changed."""
    if state is not None and state not in TC_STATES:
        raise ValueError("state must be open, closed or null")
    if tc.override == state and (state is None or tc.override_temporary == temporary):
        return False
    tc.override = state
    tc.override_temporary = bool(temporary) if state else False
    tc.override_since_open = (
        routing.is_open(list(tc.ranges or []), list(tc.holidays or []), tc.timezone, now)
        if state
        else None
    )
    tc.override_by = by if state else None
    tc.override_at = utcnow() if state else None
    db.flush()
    org = db.get(Organization, tc.organization_id)
    _write(adapter, "tc", org.slug if org else "", tc_key(tc), state)
    bus.publish(
        Event(
            "time_condition.override",
            {
                "time_condition_id": str(tc.id),
                "organization_id": str(tc.organization_id),
                "override": state,
                "temporary": tc.override_temporary,
                "by": by,
            },
        )
    )
    return True


# ----------------------------------------------------------------- events


def parse_userevent(userevent: dict[str, Any]) -> dict[str, str]:
    """The fields the feature-code dialplan sends: Kind, Org, Key, Value."""
    out: dict[str, str] = {}
    for key in ("Kind", "Org", "Key", "Value"):
        value = userevent.get(key)
        if value is None:
            value = userevent.get(key.lower())
        out[key.lower()] = str(value or "").strip()
    return out


def handle_userevent(db: Session, userevent: dict[str, Any], adapter: Any = None) -> bool:
    """A phone flipped a switch; the engine's copy is already written by the
    dialplan, so only the row and the event remain. Returns whether a row
    changed."""
    fields = parse_userevent(userevent)
    if fields["kind"] not in KINDS or not fields["key"]:
        return False
    org = db.scalar(select(Organization).where(Organization.slug == fields["org"]))
    if org is None:
        return False
    if fields["kind"] == "flow":
        flow = db.scalar(
            select(CallFlow).where(
                CallFlow.organization_id == org.id, CallFlow.slug == fields["key"]
            )
        )
        if flow is None:
            return False
        return set_flow(db, flow, fields["value"] == "1", by="phone", adapter=None)
    tc = None
    for row in db.scalars(select(TimeCondition).where(TimeCondition.organization_id == org.id)):
        if tc_key(row) == fields["key"]:
            tc = row
            break
    if tc is None:
        return False
    state = fields["value"] if fields["value"] in TC_STATES else None
    return set_time_condition(db, tc, state, temporary=True, by="phone", adapter=None)


# ----------------------------------------------------------------- sync


def expire(db: Session, now: datetime | None = None) -> list[TimeCondition]:
    """Clear temporary time-condition overrides whose schedule has changed
    state since they were set; returns the conditions cleared."""
    cleared = []
    for tc in db.scalars(select(TimeCondition).where(TimeCondition.override.is_not(None))):
        if not tc.override_temporary:
            continue
        open_now = routing.is_open(list(tc.ranges or []), list(tc.holidays or []), tc.timezone, now)
        if tc.override_since_open is not None and open_now != tc.override_since_open:
            tc.override = None
            tc.override_temporary = False
            tc.override_since_open = None
            tc.override_by = None
            tc.override_at = None
            cleared.append(tc)
    if cleared:
        db.flush()
        for tc in cleared:
            bus.publish(
                Event(
                    "time_condition.override",
                    {
                        "time_condition_id": str(tc.id),
                        "organization_id": str(tc.organization_id),
                        "override": None,
                        "temporary": False,
                        "by": "schedule",
                    },
                )
            )
    return cleared


def calendar_closed(db: Session, tc: TimeCondition, now: datetime | None = None) -> bool:
    """An event of the condition's enabled calendar is on now. An all-day event
    without an end lasts a day; a timed one without an end has no length."""
    if tc.closed_calendar_id is None:
        return False
    calendar = db.get(Calendar, tc.closed_calendar_id)
    if calendar is None or not calendar.is_enabled:
        return False
    now = now or utcnow()
    match = (tc.closed_calendar_match or "").casefold()
    events = db.scalars(
        select(CalendarEvent).where(
            CalendarEvent.calendar_id == calendar.id, CalendarEvent.starts_at <= now
        )
    )
    for e in events:
        ends = e.ends_at or (e.starts_at + timedelta(days=1) if e.all_day else e.starts_at)
        if now < ends and match in e.summary.casefold():
            return True
    return False


def wanted(db: Session, now: datetime | None = None) -> dict[tuple[str, str, str], str]:
    """(kind, org, key) -> value for every switch that should be on."""
    slugs = {o.id: o.slug for o in db.scalars(select(Organization))}
    out: dict[tuple[str, str, str], str] = {}
    for flow in db.scalars(select(CallFlow).where(CallFlow.override.is_(True))):
        if flow.is_enabled:
            out[("flow", slugs.get(flow.organization_id, ""), flow.slug)] = "1"
    for tc in db.scalars(select(TimeCondition).where(TimeCondition.override.is_not(None))):
        out[("tc", slugs.get(tc.organization_id, ""), tc_key(tc))] = str(tc.override)
    for tc in db.scalars(
        select(TimeCondition).where(
            TimeCondition.override.is_(None), TimeCondition.closed_calendar_id.is_not(None)
        )
    ):
        if calendar_closed(db, tc, now):
            out[("tc", slugs.get(tc.organization_id, ""), tc_key(tc))] = TC_CALENDAR
    return out


def sync(db: Session, adapter: Any, now: datetime | None = None) -> int:
    """Expire temporary overrides, then make the engine's switches match the
    rows (worker, every pass). Returns how many engine entries were corrected."""
    expire(db, now)
    if not supports(adapter):
        return 0
    try:
        have = adapter.switches()
    except (EngineUnavailable, NotSupported):
        return 0
    want = wanted(db, now)
    fixed = 0
    for key, value in want.items():
        if have.get(key) != value:
            try:
                adapter.set_switch(*key, value)
                fixed += 1
            except (EngineUnavailable, NotSupported, ValueError) as e:
                log.warning("Could not sync switch %s: %s", key, e)
    for key in have:
        if key not in want and key[0] not in LAMP_KINDS:
            try:
                adapter.set_switch(*key, None)
                fixed += 1
            except (EngineUnavailable, NotSupported, ValueError):
                pass
    return fixed
