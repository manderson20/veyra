# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extended absence of a voicemail box (issue #169): the absence greeting
becomes the temporary greeting between the dates, the dialplan's flag
refuses messages when asked, and the worker ends a past absence."""

from __future__ import annotations

from datetime import UTC, date, datetime

from conftest import ADMIN_PASSWORD, login
from fake_adapter import FakeAdapter
from fastapi.testclient import TestClient
from test_api_voicemail_inbox import _context, _ext, _user, _wav, helper  # noqa: F401
from test_generator_voicemail_ivr import _files, _snapshot

from veyra.core.db import session_scope
from veyra.core.models import VoicemailBox
from veyra.voicemail import service as vmsvc


def test_dialplan_checks_the_absence_flag_before_voicemail():
    d = _files(_snapshot())["extensions.conf"].content
    flag = 'GotoIf($["${DB(veyra/vmabs/veyra/1002)}"="refuse"]?veyra-vm-absent,1002,1)'
    assert f" same => n,{flag}\n same => n,VoiceMail(1002@veyra,u)" in d
    assert f" same => n,{flag}\n same => n,VoiceMail(1002@veyra,b)" in d
    absent = d.split("[veyra-vm-absent]")[1].split("\n[")[0]
    assert "Playback(/var/spool/asterisk/voicemail/veyra/${EXTEN}/temp)" in absent
    assert "VoiceMail(" not in absent and "Hangup()" in absent


def test_absence_starts_refuses_and_ends_by_itself(admin, app, helper):  # noqa: F811
    adapter = FakeAdapter()
    app.state.telephony = adapter
    uid = _user(admin, "summer@example.org")
    ext = _ext(admin, "1005", uid)
    box = admin.post("/api/v1/voicemail", json={"extension_id": ext["id"]}).json()
    ctx = _context(admin)
    user = login(
        TestClient(app, base_url="http://veyra.test"), "summer@example.org", ADMIN_PASSWORD
    )
    base = f"/api/v1/me/voicemail/{box['id']}"
    spool = helper / ctx / "1005"
    r = user.put(base + "/greetings/absence", files={"file": ("away.wav", _wav(2.0), "audio/wav")})
    assert r.status_code == 200, r.text
    assert (spool / "absence.wav").exists() and not (spool / "temp.wav").exists()

    # The last day before the first is refused.
    r = user.put(base + "/absence", json={"starts_on": "2026-08-10", "ends_on": "2026-06-01"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "ends_on"
    # On from today, messages refused: temp is the absence copy, the flag is set.
    r = user.put(base + "/absence", json={"enabled": True, "refuse_messages": True})
    assert r.status_code == 200, r.text
    assert r.json()["active"] and r.json()["applied"]
    assert (spool / "temp.wav").read_bytes() == (spool / "absence.wav").read_bytes()
    assert adapter.store[f"veyra/vmabs/{ctx}"]["1005"] == "refuse"
    # Messages taken again: the flag goes, the greeting stays.
    r = user.put(base + "/absence", json={"refuse_messages": False})
    assert "1005" not in adapter.store.get(f"veyra/vmabs/{ctx}", {})
    assert (spool / "temp.wav").exists()

    # A past last day: the worker removes the copy and turns the absence off.
    with session_scope() as db:
        row = db.get(VoicemailBox, box["id"])
        row.absence_ends_on = date(2026, 1, 31)
        db.commit()
        assert vmsvc.absence_sweep(
            db, app.state.settings, adapter, now=datetime(2026, 2, 2, 12, tzinfo=UTC)
        )
        row = db.get(VoicemailBox, box["id"])
        assert row.absence_state == "off" and row.absence_enabled is False
    assert not (spool / "temp.wav").exists() and (spool / "absence.wav").exists()
    assert user.get(base + "/absence").json()["enabled"] is False


def test_bulk_absence_and_a_future_start(admin, app, helper):  # noqa: F811
    app.state.telephony = FakeAdapter()
    boxes = [
        admin.post("/api/v1/voicemail", json={"extension_id": _ext(admin, n)["id"]}).json()
        for n in ("1006", "1007")
    ]
    r = admin.put(
        "/api/v1/voicemail/absence",
        json={
            "box_ids": [b["id"] for b in boxes],
            "enabled": True,
            "starts_on": "2099-06-01",
            "ends_on": "2099-08-15",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"boxes": 2, "changed": 2}
    a = admin.get(f"/api/v1/voicemail/{boxes[0]['id']}/absence").json()
    assert a["enabled"] and not a["active"] and not a["applied"]
    # No absence recording: on its first day only the flag logic applies.
    with session_scope() as db:
        assert vmsvc.absence_sweep(
            db, app.state.settings, None, now=datetime(2099, 6, 1, 12, tzinfo=UTC)
        )
        assert db.get(VoicemailBox, boxes[1]["id"]).absence_state == "flag"


def test_after_hours_greeting_plays_while_the_condition_is_closed():
    from test_generator_voicemail_ivr import _box

    cond = {
        "key": "hours-1",
        "name": "Office hours",
        "organization": "example",
        "timezone": "America/Chicago",
        "ranges": [{"days": ["mon", "tue", "wed", "thu", "fri"], "start": "07:30", "end": "16:00"}],
        "holidays": [],
    }
    snap = _snapshot(voicemail_boxes=[_box("1002", after_hours="hours-1")], time_conditions=[cond])
    d = _files(snap)["extensions.conf"].content
    spool = "/var/spool/asterisk/voicemail/veyra/1002"
    steps = (
        " same => n,Gosub(veyra-tcopen-hours-1,s,1)\n"
        f" same => n,Set(VEYRA_AH=$[!0${{VEYRA_OPEN}} & ${{STAT(e,{spool}/afterhours.wav)}}"
        f" & !${{STAT(e,{spool}/temp.wav)}}])\n"
        f" same => n,ExecIf(${{VEYRA_AH}}?Playback({spool}/afterhours))\n"
        " same => n,VoiceMail(1002@veyra,${IF(${VEYRA_AH}?:u)})"
    )
    assert steps in d
    # The busy greeting stays as it is.
    assert " same => n,VoiceMail(1002@veyra,b)" in d
    ctx = d.split("[veyra-tcopen-hours-1]")[1].split("\n[")[0]
    assert "/tc/example/hours-1)}" in ctx
    assert "GotoIfTime(07:30-16:00,mon-fri,*,*,America/Chicago?open)" in ctx
    assert " same => n(open),Set(VEYRA_OPEN=1)" in ctx
    # A box without a condition is untouched.
    plain = _files(_snapshot(time_conditions=[cond]))["extensions.conf"].content
    assert "veyra-tcopen-" not in plain


def test_after_hours_condition_in_the_box_api(admin):
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    cond = admin.post(
        "/api/v1/routing/time-conditions",
        json={
            "organization_id": org,
            "name": "Office hours",
            "ranges": [{"days": ["mon"], "start": "08:00", "end": "16:00"}],
        },
    )
    assert cond.status_code == 201, cond.text
    box = admin.post(
        "/api/v1/voicemail",
        json={
            "extension_id": _ext(admin, "1008")["id"],
            "after_hours_time_condition_id": cond.json()["id"],
        },
    ).json()
    assert box["after_hours_time_condition_id"] == cond.json()["id"]
    r = admin.patch(
        f"/api/v1/voicemail/{box['id']}",
        json={"after_hours_time_condition_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 422
    r = admin.patch(f"/api/v1/voicemail/{box['id']}", json={"after_hours_time_condition_id": None})
    assert r.json()["after_hours_time_condition_id"] is None
    assert vmsvc.GREETING_LABELS["afterhours"] == "After hours"
