# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wake-up calls (issue #392): the time arithmetic, the API, phone events, the
worker's tries and the generated dialplan."""

import uuid
from datetime import UTC, datetime, timedelta

from fake_adapter import FakeAdapter
from test_api_ivr import _ext, _org
from test_generator_callflow import _context, _files, _snapshot

from veyra.core.db import session_scope
from veyra.core.models import WakeupCall
from veyra.core.models.base import utcnow
from veyra.telephony import wakeup


def test_next_occurrence_uses_the_time_zone():
    now = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)  # 06:00 in Chicago, after DST ended
    assert wakeup.next_occurrence("0630", "America/Chicago", now) == datetime(
        2026, 11, 1, 12, 30, tzinfo=UTC
    )
    assert wakeup.next_occurrence("0530", "America/Chicago", now) == datetime(
        2026, 11, 2, 11, 30, tzinfo=UTC
    )
    assert wakeup.valid_time("2359") and not wakeup.valid_time("2400")
    assert not wakeup.valid_time("0760") and not wakeup.valid_time("63")


def test_wakeup_api_events_and_worker(admin, app):
    adapter = FakeAdapter(prompts_dir=app.state.settings.prompts_dir)
    org = _org(admin)
    ext = _ext(admin, org["id"], "6201", "Night desk")
    url = f"/api/v1/extensions/{ext['id']}/wakeup-calls"
    assert admin.post(url, json={"time": "25:00"}).status_code == 422
    r = admin.post(url, json={"time": "06:30", "daily": True})
    assert r.status_code == 201, r.text
    daily = r.json()
    assert daily["time"] == "06:30" and daily["daily"] is True and daily["next_at"]
    for hhmm in ("07:00", "07:01", "07:02", "07:03"):
        assert admin.post(url, json={"time": hhmm}).status_code == 201
    assert admin.post(url, json={"time": "07:04"}).status_code == 409
    # The same time again resets rather than adding.
    assert admin.post(url, json={"time": "07:03"}).status_code == 201
    assert len(admin.get(url).json()) == 5

    # From the phone: cancel all, then set one; a bad time is ignored.
    event = {"Org": org["slug"], "Extension": "6201"}
    with session_scope() as db:
        assert wakeup.handle_event(db, {**event, "Action": "cancel"}) == 5
        assert wakeup.handle_event(db, {**event, "Action": "set", "Time": "9999"}) == 0
        assert wakeup.handle_event(db, {**event, "Action": "set", "Time": "0645"}) == 1
    once = admin.get(url).json()[0]
    assert (once["time"], once["daily"]) == ("06:45", False)
    call_id = uuid.UUID(once["id"])

    def due(minutes=1):
        with session_scope() as db:
            db.get(WakeupCall, call_id).next_at = utcnow() - timedelta(minutes=minutes)

    # Tried three times, then shown as missed and no longer due.
    calls = []
    original = adapter.originate_channel

    def spy(endpoint, extension, **kw):
        calls.append((endpoint, kw["context"], kw["variables"]["VEYRA_WAKE_ID"]))
        return original(endpoint, extension, **kw)

    adapter.originate_channel = spy
    for _ in range(3):
        due()
        with session_scope() as db:
            assert wakeup.tick(db, adapter) == 1
    assert calls[0] == (f"PJSIP/{ext['endpoint_name']}", "veyra-wakeup", str(call_id))
    assert len(calls) == 3
    due()
    with session_scope() as db:
        assert wakeup.tick(db, adapter) == 0
    got = admin.get(url).json()[0]
    assert got["last_result"] == "missed" and got["next_at"] is None

    # Answered: a one-time call goes away.
    with session_scope() as db:
        wakeup.handle_event(db, {"Action": "answered", "Id": str(call_id)})
    assert admin.get(url).json() == []

    # A daily one moves to tomorrow when answered; far too late is skipped.
    r = admin.post(url, json={"time": "08:00", "daily": True}).json()
    call_id = uuid.UUID(r["id"])
    with session_scope() as db:
        wakeup.handle_event(db, {"Action": "answered", "Id": str(call_id)})
    got = admin.get(url).json()[0]
    assert got["last_result"] == "answered" and got["next_at"]
    due(minutes=45)
    before = len(calls)
    with session_scope() as db:
        assert wakeup.tick(db, adapter) == 0
    assert len(calls) == before
    assert admin.get(url).json()[0]["last_result"] == "skipped"

    assert admin.delete(f"{url}/{call_id}").status_code == 204
    assert admin.delete(f"{url}/{call_id}").status_code == 404


def test_generated_wakeup():
    codes = {"wakeup_set": "*64", "wakeup_cancel": "*65"}
    dp = _files(_snapshot(feature_codes=codes))["extensions.conf"]
    features = _context(dp, "veyra-features")
    assert "exten => *64,1,NoOp(Veyra wake-up call" in features
    assert "Action: set,Time: ${VEYRA_TIME})" in features
    assert "exten => *65,1,NoOp(Veyra wake-up calls cancelled" in features
    answered = _context(dp, "veyra-wakeup")
    assert "UserEvent(VeyraWakeup,Action: answered,Id: ${VEYRA_WAKE_ID})" in answered
    assert answered.index("UserEvent") < answered.index("Playback")
