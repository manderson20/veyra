# SPDX-License-Identifier: AGPL-3.0-or-later
"""Engine switches (docs/CALL_FEATURES.md §4.5, §4.6): call-flow toggles and
time-condition overrides, from the API and from phones, and the worker's
sync and expiry."""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fake_adapter import FakeAdapter
from test_api_ivr import _ext, _org

from veyra.core.db import session_scope
from veyra.core.models import Calendar, CalendarEvent, CallFlow, TimeCondition
from veyra.core.models.base import utcnow
from veyra.telephony import switches
from veyra.telephony.asterisk import generator

FLOWS = "/api/v1/call-flows"
TC = "/api/v1/routing/time-conditions"
INBOUND = "/api/v1/routing/inbound"


def _fake(app):
    adapter = FakeAdapter(prompts_dir=app.state.settings.prompts_dir)
    app.state.telephony = adapter
    return adapter


def test_call_flow_crud_switching_and_destination(admin, app):
    adapter = _fake(app)
    org = _org(admin)
    ext = _ext(admin, org["id"], "4001")
    r = admin.post(
        FLOWS,
        json={
            "organization_id": org["id"],
            "name": "Night mode",
            "code_index": 1,
            "pin": "1234",
            "normal": {"type": "extension", "extension_id": ext["id"]},
            "override_destination": {"type": "directory"},
        },
    )
    assert r.status_code == 201, r.text
    f = r.json()
    assert f["slug"] == "night-mode" and f["context"] == "veyra-flow-night-mode"
    assert f["code"] == "*281" and f["has_pin"] and not f["override"] and f["problems"] == []
    assert (
        f["normal"]["label"].startswith("4001") and f["override_destination"]["type"] == "directory"
    )
    # Validation: duplicate index, out-of-range index, bad PIN, self reference.
    r = admin.post(FLOWS, json={"organization_id": org["id"], "name": "Clash", "code_index": 1})
    assert r.status_code == 409 and r.json()["code"] == "code_index_in_use"
    assert (
        admin.post(
            FLOWS, json={"organization_id": org["id"], "name": "Big", "code_index": 100}
        ).status_code
        == 422
    )
    assert admin.patch(f"{FLOWS}/{f['id']}", json={"pin": "12"}).status_code == 422
    r = admin.patch(
        f"{FLOWS}/{f['id']}", json={"normal": {"type": "call_flow", "call_flow_id": f["id"]}}
    )
    assert r.status_code == 422 and "itself" in r.text
    # Switching writes the row and the engine live, without a deployment.
    r = admin.post(f"{FLOWS}/{f['id']}/state", json={"override": True})
    assert r.status_code == 200, r.text
    assert r.json()["override"] and r.json()["override_by"]
    assert adapter.switch_calls[-1] == ("flow", org["slug"], "night-mode", "1")
    r = admin.post(f"{FLOWS}/{f['id']}/state", json={"override": False})
    assert not r.json()["override"]
    assert adapter.switch_calls[-1] == ("flow", org["slug"], "night-mode", None)
    # As a destination: an inbound route; then the flow is in use.
    r = admin.post(
        INBOUND,
        json={
            "organization_id": org["id"],
            "did": "5735550201",
            "destination_type": "call_flow",
            "destination_call_flow_id": f["id"],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["destination"]["label"] == "Call flow: Night mode"
    assert admin.get(f"{FLOWS}/{f['id']}").json()["in_use_by"] == 1
    assert admin.delete(f"{FLOWS}/{f['id']}").status_code == 409
    # Disabling the toggle code is reported as a problem.
    admin.put(
        "/api/v1/telephony/feature-codes",
        json={"codes": {"callflow_toggle_prefix": {"code": "*28", "enabled": False}}},
    )
    flow = admin.get(f"{FLOWS}/{f['id']}").json()
    assert flow["code"] is None and any("toggle code is disabled" in p for p in flow["problems"])


def test_time_condition_override_from_api_and_phone(admin, app):
    adapter = _fake(app)
    org = _org(admin)
    r = admin.post(
        TC,
        json={
            "organization_id": org["id"],
            "name": "Office hours",
            "timezone": "UTC",
            "ranges": [
                {
                    "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                    "start": "00:00",
                    "end": "23:59",
                }
            ],
            "holidays": ["12-25"],
            "code_index": 5,
            "pin": "2468",
        },
    )
    assert r.status_code == 201, r.text
    tc = r.json()
    assert tc["code"] == "*275" and tc["has_pin"] and tc["override"] is None
    r = admin.post(
        TC,
        json={"organization_id": org["id"], "name": "Dup", "ranges": tc["ranges"], "code_index": 5},
    )
    assert r.status_code == 409 and r.json()["code"] == "code_index_in_use"
    # Force closed, permanently: effective state flips, the engine is written.
    r = admin.post(f"{TC}/{tc['id']}/override", json={"state": "closed", "temporary": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        body["override"] == "closed"
        and not body["override_temporary"]
        and not body["effective_open"]
    )
    assert adapter.switch_calls[-1] == ("tc", org["slug"], tc["id"], "closed")
    r = admin.post(f"{TC}/{tc['id']}/override", json={"state": None})
    assert r.json()["override"] is None and adapter.switch_calls[-1][3] is None
    # A phone's UserEvent sets a temporary override; the row follows.
    with session_scope() as db:
        changed = switches.handle_userevent(
            db, {"Kind": "tc", "Org": org["slug"], "Key": tc["id"], "Value": "open"}
        )
        assert changed
        row = db.get(TimeCondition, __import__("uuid").UUID(tc["id"]))
        assert row.override == "open" and row.override_temporary and row.override_by == "phone"
        # The worker's sync pushes the wanted switch to an engine that lost it.
        adapter.switch_states.clear()
        fixed = switches.sync(db, adapter)
        assert fixed == 1 and adapter.switch_states[("tc", org["slug"], tc["id"])] == "open"
        # ... and clears a temporary override once the schedule changes state:
        # the condition is open every day except Christmas, which closes it.
        assert row.override_since_open is True
        christmas = datetime(2026, 12, 25, 12, 0, tzinfo=ZoneInfo("UTC"))
        cleared = switches.expire(db, now=christmas)
        assert [c.id for c in cleared] == [row.id] and row.override is None
        assert switches.sync(db, adapter, now=christmas) == 1
        assert ("tc", org["slug"], tc["id"]) not in adapter.switch_states
    # An unknown switch in the engine is removed by the sync.
    adapter.switch_states[("flow", org["slug"], "ghost")] = "1"
    with session_scope() as db:
        assert switches.sync(db, adapter) == 1
    assert ("flow", org["slug"], "ghost") not in adapter.switch_states


def test_time_condition_closed_by_a_calendar(admin, app):
    adapter = _fake(app)
    org = _org(admin)
    now = utcnow()
    with session_scope() as db:
        calendar = Calendar(
            organization_id=uuid.UUID(org["id"]),
            name="Closures",
            url_ciphertext="x",
            url_display="https://example.org",
        )
        db.add(calendar)
        db.flush()
        for uid, summary, start, end, all_day in (
            ("a", "Closed: snow", now - timedelta(hours=1), now + timedelta(hours=1), False),
            ("b", "Board meeting", now - timedelta(hours=1), now + timedelta(hours=1), False),
            ("c", "Closed last week", now - timedelta(days=7), now - timedelta(days=6), False),
        ):
            db.add(
                CalendarEvent(
                    calendar_id=calendar.id,
                    uid=uid,
                    summary=summary,
                    starts_at=start,
                    ends_at=end,
                    all_day=all_day,
                )
            )
        calendar_id = str(calendar.id)
    every = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    r = admin.post(
        TC,
        json={
            "organization_id": org["id"],
            "name": "Hours",
            "timezone": "UTC",
            "ranges": [{"days": every, "start": "00:00", "end": "23:59"}],
            "closed_calendar_id": calendar_id,
            "closed_calendar_match": "closed",
        },
    )
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["calendar_closed"] is True and t["effective_open"] is False
    key = ("tc", org["slug"], t["id"])
    with session_scope() as db:
        switches.sync(db, adapter)
    assert adapter.switches()[key] == "calendar"
    # A title that doesn't match leaves it to the schedule, and clears the engine.
    r = admin.patch(f"{TC}/{t['id']}", json={"closed_calendar_match": "holiday"})
    assert r.json()["calendar_closed"] is False and r.json()["effective_open"] is True
    with session_scope() as db:
        switches.sync(db, adapter)
    assert key not in adapter.switches()
    # An override wins over the calendar.
    admin.patch(f"{TC}/{t['id']}", json={"closed_calendar_match": None})
    with session_scope() as db:
        tc = db.get(TimeCondition, uuid.UUID(t["id"]))
        switches.set_time_condition(db, tc, "open", temporary=False, by="test")
    with session_scope() as db:
        switches.sync(db, adapter)
    assert adapter.switches()[key] == "open"
    # A calendar that isn't the organization's is refused.
    r = admin.patch(f"{TC}/{t['id']}", json={"closed_calendar_id": str(uuid.uuid4())})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "closed_calendar_id"


def test_generator_calendar_value_means_closed_and_the_code_opens_it():
    assert switches.TC_CALENDAR == "calendar"
    assert 'GotoIf($["${VEYRA_TC}"="calendar"]?closed)' in generator._CALENDAR_CLOSED[0]
    codes = {"tc_override_prefix": "*27"}
    lines = generator._tc_override_codes(
        codes, [{"key": "abc", "organization": "example", "code_index": 1, "name": "Hours"}]
    )
    text = "\n".join(lines)
    assert text.index('="calendar"]?isclosed') < text.index('!=""]?clear')


def test_call_flow_userevent_and_sync(admin, app):
    adapter = _fake(app)
    org = _org(admin)
    f = admin.post(
        FLOWS, json={"organization_id": org["id"], "name": "Snow day", "code_index": 7}
    ).json()
    with session_scope() as db:
        assert switches.handle_userevent(
            db, {"Kind": "flow", "Org": org["slug"], "Key": "snow-day", "Value": "1"}
        )
        row = db.get(CallFlow, __import__("uuid").UUID(f["id"]))
        assert row.override and row.override_by == "phone"
        assert not switches.handle_userevent(
            db, {"Kind": "flow", "Org": org["slug"], "Key": "nope", "Value": "1"}
        )
        assert switches.wanted(db) == {("flow", org["slug"], "snow-day"): "1"}
        assert switches.sync(db, adapter) == 1 and adapter.switch_states == {
            ("flow", org["slug"], "snow-day"): "1"
        }
