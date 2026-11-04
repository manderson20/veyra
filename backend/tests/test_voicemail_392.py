# SPDX-License-Identifier: AGPL-3.0-or-later
"""Voicemail items of issue #392 (FreeSWITCH): extra recipients, per-box
quota, the alternate greeting and a spoken intro on a forward."""

from __future__ import annotations

import base64
import io
import wave

import pytest
from conftest import ADMIN_PASSWORD, login
from fake_adapter import FakeAdapter
from fastapi.testclient import TestClient
from test_api_voicemail_inbox import _context, _ext, _msg, _user, _wav, helper  # noqa: F401
from test_generator_voicemail_ivr import _box, _files, _snapshot

from veyra.telephony.asterisk.generator import GenerationError
from veyra.voicemail import service as vmsvc

# ------------------------------------------------------------------ generator


def test_extra_recipients_share_one_voicemail_call():
    snap = _snapshot(
        extensions=[*_snapshot()["extensions"]],
        voicemail_boxes=[
            _box("1001"),
            # 1003 is not a deployed box and drops out; 1002 itself too.
            _box("1002", copy_to=["1001", "1003", "1002", "1001"]),
        ],
    )
    d = _files(snap)["extensions.conf"].content
    assert "VoiceMail(1002@veyra&1001@veyra,${IF(${VEYRA_ALT}?:u)})" in d
    assert "VoiceMail(1001@veyra,${IF(${VEYRA_ALT}?:u)})" in d
    with pytest.raises(GenerationError, match="copy to"):
        _files(_snapshot(voicemail_boxes=[_box("1002", copy_to=["10;02"])]))


def test_quota_lands_on_the_box_line():
    vm = _files(
        _snapshot(voicemail_boxes=[_box("1002", max_messages=25, max_message_seconds=120)])
    )["voicemail.conf"].content
    assert "envelope=yes|maxmsg=25|maxsecs=120" in vm
    plain = _files(_snapshot())["voicemail.conf"].content
    assert "|maxmsg=" not in plain and "maxmsg=100" in plain  # the [general] default
    with pytest.raises(GenerationError, match="maxsecs"):
        _files(_snapshot(voicemail_boxes=[_box("1002", max_message_seconds=5)]))


def test_alternate_greeting_comes_before_after_hours_and_busy():
    d = _files(_snapshot())["extensions.conf"].content
    assert '"${DB(veyra/vmalt/veyra/1002)}"="on"' in d
    assert "VoiceMail(1002@veyra,${IF(${VEYRA_ALT}?:b)})" in d
    # Feature-code voicemail (no greeting flag) has no alternate step.
    assert "VEYRA_ALT" not in d.split("[veyra-vm-absent]")[1].split("\n[")[0]


# ------------------------------------------------------------------ joining


def test_join_wavs_puts_a_gap_between():
    joined, seconds = vmsvc.join_wavs(_wav(1.0), _wav(2.0))
    assert seconds == pytest.approx(3.0 + vmsvc.INTRO_GAP_SECONDS, abs=0.01)
    with wave.open(io.BytesIO(joined)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (8000, 1, 2)
    with pytest.raises(ValueError):
        vmsvc.join_wavs(_wav(1.0), _wav(1.0, 16000))


# ------------------------------------------------------------------ API


def test_copies_and_quota_through_the_api(admin, app, helper):  # noqa: F811
    a = _ext(admin, "1001")
    b = _ext(admin, "1002")
    box_a = admin.post("/api/v1/voicemail", json={"extension_id": a["id"]}).json()
    r = admin.post(
        "/api/v1/voicemail",
        json={"extension_id": b["id"], "copy_to_box_ids": [box_a["id"]], "max_messages": 5},
    )
    assert r.status_code == 201, r.text
    box_b = r.json()
    assert box_b["copy_to_box_ids"] == [box_a["id"]] and box_b["max_messages"] == 5
    r = admin.patch(f"/api/v1/voicemail/{box_b['id']}", json={"copy_to_box_ids": [box_b["id"]]})
    assert r.status_code == 422
    r = admin.patch(
        f"/api/v1/voicemail/{box_b['id']}",
        json={"max_messages": None, "max_message_seconds": 300},
    )
    assert r.status_code == 200, r.text
    assert r.json()["max_messages"] is None and r.json()["max_message_seconds"] == 300
    assert (
        admin.patch(f"/api/v1/voicemail/{box_b['id']}", json={"max_message_seconds": 5}).status_code
        == 422
    )
    # Deleting a recipient takes it off the lists that named it.
    assert admin.delete(f"/api/v1/voicemail/{box_a['id']}").status_code == 204
    assert admin.get(f"/api/v1/voicemail/{box_b['id']}").json()["copy_to_box_ids"] == []


def test_alternate_greeting_switch(admin, app, helper):  # noqa: F811
    adapter = FakeAdapter()
    app.state.telephony = adapter
    uid = _user(admin, "alt@example.org")
    ext = _ext(admin, "1005", uid)
    box = admin.post("/api/v1/voicemail", json={"extension_id": ext["id"]}).json()
    ctx = _context(admin)
    user = login(TestClient(app, base_url="http://veyra.test"), "alt@example.org", ADMIN_PASSWORD)
    base = f"/api/v1/me/voicemail/{box['id']}"
    assert user.get(base + "/alternate").json() == {"enabled": False, "recorded": False}
    r = user.put(base + "/alternate", json={"enabled": True})
    assert r.status_code == 409 and r.json()["code"] == "greeting_missing"
    r = user.put(base + "/greetings/alternate", files={"file": ("a.wav", _wav(1.0), "audio/wav")})
    assert r.status_code == 200, r.text
    r = user.put(base + "/alternate", json={"enabled": True})
    assert r.status_code == 200 and r.json() == {"enabled": True, "recorded": True}
    assert adapter.store[f"veyra/vmalt/{ctx}"]["1005"] == "on"
    r = admin.put(f"/api/v1/voicemail/{box['id']}/alternate", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert "1005" not in adapter.store.get(f"veyra/vmalt/{ctx}", {})
    assert admin.get(f"/api/v1/voicemail/{box['id']}").json()["alternate_greeting"] is False


def test_forward_with_intro_and_quota(admin, app, helper):  # noqa: F811
    a = _ext(admin, "1001")
    b = _ext(admin, "1002")
    src = admin.post("/api/v1/voicemail", json={"extension_id": a["id"]}).json()
    dst = admin.post("/api/v1/voicemail", json={"extension_id": b["id"], "max_messages": 1}).json()
    ctx = _context(admin)
    inbox = helper / ctx / "1001" / "INBOX"
    _msg(inbox, 0, ctx, "1001")
    (inbox / "msg0000.wav").write_bytes(_wav(2.0))
    intro = base64.b64encode(_wav(1.0)).decode()
    url = f"/api/v1/voicemail/{src['id']}/messages/0/forward"
    r = admin.post(url, json={"box_id": dst["id"], "intro": intro, "intro_filename": "i.wav"})
    assert r.status_code == 200, r.text
    copied = helper / ctx / "1002" / "INBOX"
    with wave.open(str(copied / "msg0000.wav")) as w:
        assert w.getnframes() / w.getframerate() == pytest.approx(3.4, abs=0.01)
    txt = (copied / "msg0000.txt").read_text()
    assert "duration=3\n" in txt and "forwarded_by=" in txt
    # The target holds one message at most.
    r = admin.post(url, json={"box_id": dst["id"]})
    assert r.status_code >= 400 and "full" in r.text
    r = admin.post(url, json={"box_id": src["id"], "intro": "not base64!"})
    assert r.status_code == 422
