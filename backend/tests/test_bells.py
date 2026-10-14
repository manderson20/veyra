# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 9c: calendars (iCal expansion, polling) and bell schedules
(ring once within the tolerance) — docs/PAGING_RECORDINGS.md §4."""

from datetime import UTC, datetime, timedelta

import pytest
from fake_adapter import FakeAdapter
from test_api_ivr import _upload

from veyra.bells import calendars, scheduler
from veyra.core.db import session_scope
from veyra.core.models import BellSchedule, Calendar, CalendarEvent
from veyra.core.models.base import utcnow

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
X-WR-TIMEZONE:America/Chicago
BEGIN:VEVENT
UID:period1@test
SUMMARY:Bell: first period
DTSTART;TZID=America/Chicago:20261012T080000
DTEND;TZID=America/Chicago:20261012T080100
RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR
EXDATE;TZID=America/Chicago:20261014T080000
END:VEVENT
BEGIN:VEVENT
UID:holiday@test
SUMMARY:Teacher workday
DTSTART;VALUE=DATE:20261015
DTEND;VALUE=DATE:20261016
END:VEVENT
BEGIN:VEVENT
UID:once@test
SUMMARY:Assembly
DTSTART:20261015T150000Z
DTEND:20261015T160000Z
END:VEVENT
END:VCALENDAR
"""


def test_expand_handles_recurrence_exceptions_all_day_and_single_events():
    start = datetime(2026, 10, 14, 0, 0, tzinfo=UTC)
    out = calendars.expand(ICS, start=start, end=start + timedelta(days=2), default_tz=None)
    by_uid: dict[str, list] = {}
    for o in out:
        by_uid.setdefault(o.uid, []).append(o)
    # Weekly rule, Wednesday the 14th excluded, Thursday the 15th at 08:00 Chicago = 13:00 UTC.
    starts = [o.starts_at for o in by_uid["period1@test"]]
    assert datetime(2026, 10, 15, 13, 0, tzinfo=UTC) in starts
    assert datetime(2026, 10, 14, 13, 0, tzinfo=UTC) not in starts
    assert all(o.ends_at == o.starts_at + timedelta(minutes=1) for o in by_uid["period1@test"])
    assert by_uid["holiday@test"][0].all_day is True
    assert by_uid["once@test"][0].starts_at == datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
    with pytest.raises(calendars.CalendarError):
        calendars.expand(b"not a calendar", start=start, end=start, default_tz=None)
    assert (
        calendars.display_url("https://calendar.google.com/calendar/ical/abc/private-xyz/basic.ics")
        == "https://calendar.google.com/…"
    )
    assert calendars.check_url("webcal://example.org/feed.ics") == "https://example.org/feed.ics"


def _setup(admin, app, monkeypatch):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    bell = _upload(admin, org["id"], "Bell tone", kind="bell")
    zone = admin.post(
        "/api/v1/paging-zones",
        json={
            "organization_id": org["id"],
            "name": "Building A",
            "multicast_address": "239.1.2.10",
            "multicast_port": 5004,
            "poly_group": 1,
        },
    ).json()
    page = admin.post(
        "/api/v1/pages",
        json={
            "organization_id": org["id"],
            "name": "Bell page",
            "zones": [zone["id"]],
            "audio_id": bell["id"],
        },
    ).json()
    monkeypatch.setattr(calendars, "fetch", lambda url: ICS)
    r = admin.post(
        "/api/v1/calendars",
        json={
            "organization_id": org["id"],
            "name": "School bells",
            "url": "https://calendar.google.com/calendar/ical/x/private-y/basic.ics",
            "timezone": "America/Chicago",
        },
    )
    assert r.status_code == 201, r.text
    return org, page, r.json()


def test_calendar_api_hides_the_url_and_polls(admin, app, monkeypatch):
    org, _page, cal = _setup(admin, app, monkeypatch)
    assert cal["url_display"] == "https://calendar.google.com/…" and "private-y" not in str(cal)
    assert cal["last_polled_at"] is None and cal["event_count"] == 0
    r = admin.post(f"/api/v1/calendars/{cal['id']}/poll")
    assert r.status_code == 200 and r.json()["last_status"] == "ok" and r.json()["event_count"] >= 1
    events = admin.get(f"/api/v1/calendars/{cal['id']}/events").json()
    assert all("summary" in e for e in events)
    r = admin.post(
        "/api/v1/calendars", json={"organization_id": org["id"], "name": "x", "url": "ftp://nope"}
    )
    assert r.status_code == 422

    # A failing fetch is recorded on the calendar, not raised.
    def boom(url):
        raise calendars.CalendarError("the calendar server answered 403")

    monkeypatch.setattr(calendars, "fetch", boom)
    r = admin.post(f"/api/v1/calendars/{cal['id']}/poll")
    assert r.json()["last_status"] == "failed" and "403" in r.json()["last_error"]


def test_bell_schedule_rings_once_within_tolerance(admin, app, monkeypatch):
    org, page, cal = _setup(admin, app, monkeypatch)
    r = admin.post(
        "/api/v1/bell-schedules",
        json={
            "organization_id": org["id"],
            "name": "Periods",
            "calendar_id": cal["id"],
            "page_id": page["id"],
            "match": "Bell:*",
        },
    )
    assert r.status_code == 201, r.text
    sched = r.json()
    assert sched["problems"] == [] and sched["page_name"] == "Bell page"
    adapter = FakeAdapter(prompts_dir=app.state.settings.prompts_dir)
    app.state.telephony = adapter
    now = utcnow()
    with session_scope() as db:
        # Cached events: due 20 s ago (within tolerance), 10 minutes ago (too late), unmatched.
        for uid, summary, offset in (
            ("a", "Bell: first", -20),
            ("b", "Bell: old", -600),
            ("c", "Lunch", -10),
        ):
            db.add(
                CalendarEvent(
                    calendar_id=cal["id"],
                    uid=uid,
                    summary=summary,
                    starts_at=now + timedelta(seconds=offset),
                    ends_at=None,
                    all_day=False,
                )
            )
        db.commit()
        rings = scheduler.ring(db, adapter, now=now)
        assert [r.summary for r in rings] == ["Bell: first"] and rings[0].outcome == "started"
        assert adapter.originated[-1][0] == "play-bell-page@veyra-page-play"
        # A second pass does not ring it again.
        assert scheduler.ring(db, adapter, now=now + timedelta(seconds=5)) == []
    history = admin.get(f"/api/v1/bell-schedules/{sched['id']}/rings").json()
    assert history[0]["summary"] == "Bell: first" and history[0]["outcome"] == "started"
    assert admin.get(f"/api/v1/bell-schedules/{sched['id']}").json()["next_rings"] == []
    r = admin.post(f"/api/v1/bell-schedules/{sched['id']}/ring")
    assert r.status_code == 200 and r.json()["started"] is True
    log = admin.get("/api/v1/pages/log").json()["items"]
    assert {e["trigger"] for e in log} >= {"bell", "ui"}
    # Deleting the calendar removes the schedule.
    assert admin.delete(f"/api/v1/calendars/{cal['id']}").status_code == 204
    assert admin.get(f"/api/v1/bell-schedules/{sched['id']}").status_code == 404
    with session_scope() as db:
        assert (
            db.scalar(
                __import__("sqlalchemy").select(
                    __import__("sqlalchemy").func.count(BellSchedule.id)
                )
            )
            == 0
        )
        assert (
            db.scalar(
                __import__("sqlalchemy").select(__import__("sqlalchemy").func.count(Calendar.id))
            )
            == 0
        )
