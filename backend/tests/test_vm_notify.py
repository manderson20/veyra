# SPDX-License-Identifier: AGPL-3.0-or-later
"""VM Notify (FreePBX, issue #392): a new message calls a list of numbers in
order until someone presses 1, in rounds; hearing the messages stops it."""

import uuid
from datetime import timedelta

from fake_adapter import FakeAdapter
from test_api_ivr import _ext, _org
from test_features import _section, _snapshot

from veyra.core.db import session_scope
from veyra.core.models import VoicemailBox, VoicemailNotifyJob
from veyra.core.models.base import utcnow
from veyra.integrations import sources
from veyra.telephony.asterisk import events, generator
from veyra.voicemail import notify


def test_dialplan_context_asks_for_1_then_the_box():
    d = {f.path: f.content for f in generator.generate(_snapshot())}["extensions.conf"]
    ctx = _section(d, "veyra-vmnotify")
    assert "Read(VEYRA_KEY,vm-press&digits/1,1,,1,6)" in ctx
    assert "UserEvent(VeyraVmNotify,Job: ${VEYRA_VMN_JOB},Result: accepted)" in ctx
    assert "VoiceMailMain(${VEYRA_VMN_BOX}@${VEYRA_VMN_CONTEXT})" in ctx
    assert ",s)" not in ctx  # the PIN is always asked


def _box(admin, numbers, **over):
    org = _org(admin)
    ext = _ext(admin, org["id"], "3201")
    _ext(admin, org["id"], "3202")
    r = admin.post("/api/v1/voicemail", json={"extension_id": ext["id"]})
    assert r.status_code == 201, r.text
    box = r.json()
    r = admin.patch(f"/api/v1/voicemail/{box['id']}", json={"notify_numbers": numbers, **over})
    assert r.status_code == 200, r.text
    return box, r.json()


def test_api_numbers_are_checked(admin):
    box, out = _box(admin, ["3202", "(573) 555-0100", "3202"], notify_rounds=3)
    assert out["notify_numbers"] == ["3202", "5735550100"] and out["notify_rounds"] == 3
    r = admin.patch(f"/api/v1/voicemail/{box['id']}", json={"notify_numbers": ["911"]})
    assert r.status_code == 422, r.text
    r = admin.patch(f"/api/v1/voicemail/{box['id']}", json={"notify_numbers": ["12ab"]})
    assert r.status_code == 422, r.text


def test_calls_in_order_rounds_accept_and_cancel(admin):
    box, _ = _box(admin, ["3202", "5735550100"], notify_rounds=2, notify_retry_minutes=10)
    adapter = FakeAdapter()
    now = utcnow()
    with session_scope() as db:
        row = db.get(VoicemailBox, uuid.UUID(box["id"]))
        job = notify.start(db, row, now)
        assert job is not None and notify.start(db, row, now) is None  # one at a time
        assert notify.tick(db, adapter, now) == 1
        endpoint, _exten, context, variables = adapter.originated_channels[-1]
        assert endpoint == "Local/3202@veyra-internal/n" and context == "veyra-vmnotify"
        assert variables["VEYRA_VMN_BOX"] == "3201" and variables["VEYRA_VMN_JOB"] == str(job.id)
        assert notify.tick(db, adapter, now) == 0  # not due yet
        later = now + timedelta(seconds=notify.CALL_SECONDS)
        assert notify.tick(db, adapter, later) == 1
        assert adapter.originated_channels[-1][0] == "Local/5735550100@veyra-outbound/n"
        # End of the list: wait, then a second round.
        later += timedelta(seconds=notify.CALL_SECONDS)
        assert notify.tick(db, adapter, later) == 0 and job.round == 1
        later += timedelta(minutes=10)
        assert notify.tick(db, adapter, later) == 1
        assert notify.accept(db, str(job.id)) and job.state == "accepted"
        assert not notify.accept(db, str(job.id))
        # A new message starts again; hearing them cancels it.
        job2 = notify.start(db, row, later)
        assert job2 is not None and notify.cancel(db, row.id) == 1
        assert job2.state == "cancelled"


def test_list_runs_out(admin):
    box, _ = _box(admin, ["3202"], notify_rounds=1)
    adapter = FakeAdapter()
    now = utcnow()
    with session_scope() as db:
        row = db.get(VoicemailBox, uuid.UUID(box["id"]))
        job = notify.start(db, row, now)
        notify.tick(db, adapter, now)
        notify.tick(db, adapter, now + timedelta(seconds=notify.CALL_SECONDS))
        assert job.state == "exhausted"


def test_new_message_starts_and_hearing_cancels(admin, app):
    _box(admin, ["3202"])
    qdir = app.state.settings.mailqueue_dir
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / "a.vmevent").write_text("veyra 3201 1 0 0\n")
    with session_scope() as db:
        sources.voicemail_notifications(db, qdir)
    with session_scope() as db:
        jobs = db.query(VoicemailNotifyJob).all()
        assert [j.state for j in jobs] == ["pending"]
    (qdir / "b.vmevent").write_text("veyra 3201 0 1 0\n")
    with session_scope() as db:
        sources.voicemail_notifications(db, qdir)
    with session_scope() as db:
        assert [j.state for j in db.query(VoicemailNotifyJob).all()] == ["cancelled"]


def test_accept_event_is_recognised():
    event = {"type": "ChannelUserevent", "eventname": "VeyraVmNotify", "userevent": {}}
    assert events.is_vm_notify_event(event)
