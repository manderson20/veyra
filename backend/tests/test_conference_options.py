# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conference options of issue #392: count announcement, silent listener,
end on silence, calls placed when a room starts, record at N members."""

import pytest
from test_api_callflow import CONF
from test_api_ivr import _ext, _org
from test_generator_callflow import _context, _files, _room, _snapshot

from veyra.telephony.asterisk import generator
from veyra.telephony.conference_watch import ConferenceWatch, Rule

ROOM = "veyra-conf-board"

# ----------------------------------------------------------------- generated


def test_count_announcement_and_listener_profiles():
    room = _room(announce_count=True, announce_count_above=3, user_pin="1111", listener_pin="2222")
    files = _files(_snapshot(conference_rooms=[room]))
    conf = files["confbridge.conf"]
    user = _context(conf, "veyra-conf-board-user")
    assert "announce_user_count=yes" in user and "announce_user_count_all=3" in user
    listener = _context(conf, "veyra-conf-board-user-listener")
    assert "startmuted=yes" in listener and "quiet=yes" in listener
    assert "announce_join_leave=no" in listener and "announce_user_count" not in listener
    dp = _context(files["extensions.conf"], ROOM)
    assert '"${VEYRA_PIN}"="2222"]?listener)' in dp
    assert "n(listener),Set(VEYRA_CONF_PROFILE=veyra-conf-board-user-listener)" in dp
    # 0: on every join.
    conf = _files(_snapshot(conference_rooms=[_room(announce_count_above=0)]))["confbridge.conf"]
    assert "announce_user_count_all=yes" in conf


def test_listener_pin_must_differ():
    with pytest.raises(generator.GenerationError, match="listener PIN"):
        _files(_snapshot(conference_rooms=[_room(user_pin="1111", listener_pin="1111")]))


def test_outcall_and_silence_dialplan():
    room = _room(
        user_pin="1111",
        end_on_silence_seconds=300,
        auto_outcall=[{"number": "1001", "local": True}, {"number": "5735550100", "local": False}],
    )
    dp = _context(_files(_snapshot(conference_rooms=[room]))["extensions.conf"], ROOM)
    lines = dp.splitlines()
    join = next(i for i, x in enumerate(lines) if "n(join)" in x)
    bridge = next(i for i, x in enumerate(lines) if "ConfBridge(" in x)
    # A PIN caller passes through the start checks before entering.
    assert join < bridge and "(join)" not in lines[bridge]
    block = "\n".join(lines[join:bridge])
    assert '"${VEYRA_CONF_INVITED}"="1"]?enter)' in block
    assert "CONFBRIDGE_INFO(parties,veyra-conf-board)" in block
    assert (
        "Originate(Local/1001@veyra-internal/n,exten,veyra-conf-board,s,1,45,"
        "ac(2500)n(Board)v(VEYRA_CONF_INVITED=1^__VEYRA_ORG=example))"
    ) in block
    assert "Originate(Local/5735550100@veyra-outbound/n," in block
    assert "Set(TALK_DETECT(set)=)" in block


def test_unset_options_leave_the_room_as_before():
    dp = _context(_files(_snapshot(conference_rooms=[_room()]))["extensions.conf"], ROOM)
    assert "n(join),ConfBridge(" in dp
    assert "TALK_DETECT" not in dp and "Originate" not in dp


# ----------------------------------------------------------------- watcher


def _ev(kind, channel, bridge=ROOM, name=None):
    e = {"type": kind, "channel": {"id": channel, "name": name or f"PJSIP/{channel}-1"}}
    if "Bridge" in kind:
        e["bridge"] = {"name": bridge}
    return e


def test_watch_records_at_n_members_once():
    w = ConferenceWatch()
    w.set_rules({ROOM: Rule(record_at=3)})
    assert w.handle(_ev("ChannelEnteredBridge", "a"), 0) == []
    # The recorder is not a member.
    assert w.handle(_ev("ChannelEnteredBridge", "r", name="CBRec/x-1"), 1) == []
    assert w.handle(_ev("ChannelEnteredBridge", "b"), 1) == []
    assert w.handle(_ev("ChannelEnteredBridge", "c"), 2) == [(ROOM, "record_start")]
    assert w.handle(_ev("ChannelEnteredBridge", "d"), 3) == []
    # Another room's bridge is not watched.
    assert w.handle(_ev("ChannelEnteredBridge", "z", bridge="other"), 3) == []


def test_watch_ends_a_quiet_room_once():
    w = ConferenceWatch()
    w.set_rules({ROOM: Rule(silence_seconds=60)})
    w.handle(_ev("ChannelEnteredBridge", "a"), 0)
    w.handle(_ev("ChannelEnteredBridge", "b"), 10)
    w.handle(_ev("ChannelTalkingStarted", "a"), 20)
    assert w.tick(200) == []  # someone is talking
    w.handle(_ev("ChannelTalkingFinished", "a"), 210)
    assert w.tick(260) == []
    assert w.tick(270) == [(ROOM, "end")]
    assert w.tick(300) == []
    # Everyone left: the next conference starts afresh.
    w.handle(_ev("ChannelLeftBridge", "a"), 301)
    w.handle(_ev("ChannelLeftBridge", "b"), 301)
    assert ROOM not in w.rooms
    w.handle(_ev("ChannelEnteredBridge", "c"), 400)
    assert w.tick(470) == [(ROOM, "end")]


def test_watch_reset_forgets_rooms():
    w = ConferenceWatch()
    w.set_rules({ROOM: Rule(silence_seconds=60)})
    w.handle(_ev("ChannelEnteredBridge", "a"), 0)
    w.reset()
    assert w.tick(1000) == []


# ----------------------------------------------------------------- API


def test_api_options_validation_and_rules(admin, app):
    from veyra.core.db import session_scope
    from veyra.telephony.conference_watch import load_rules

    org = _org(admin)
    _ext(admin, org["id"], "3002")
    body = {
        "organization_id": org["id"],
        "name": "Board",
        "number": "3500",
        "user_pin": "1111",
        "listener_pin": "2222",
        "announce_count": True,
        "announce_count_above": 2,
        "end_on_silence_seconds": 600,
        "auto_outcall": ["3002", "(573) 555-0100"],
        "record_at_members": 3,
        "max_participants": 10,
    }
    r = admin.post(CONF, json=body)
    assert r.status_code == 201, r.text
    room = r.json()
    assert room["has_listener_pin"] and room["auto_outcall"] == ["3002", "5735550100"]
    assert room["record_at_members"] == 3 and room["end_on_silence_seconds"] == 600
    with session_scope() as db:
        assert load_rules(db) == {"veyra-conf-board": Rule(record_at=3, silence_seconds=600)}

    url = f"{CONF}/{room['id']}"
    # The listener PIN must differ from the stored user PIN.
    r = admin.patch(url, json={"listener_pin": "1111"})
    assert r.status_code == 422 and "listener" in r.text
    r = admin.patch(url, json={"record_at_members": 20})
    assert r.status_code == 422, r.text
    r = admin.patch(url, json={"end_on_silence_seconds": 10})
    assert r.status_code == 422, r.text
    r = admin.patch(url, json={"listener_pin": None, "record": True})
    assert r.status_code == 200, r.text
    assert not r.json()["has_listener_pin"]
    assert any("recording at a number" in p for p in r.json()["problems"])


def test_api_refuses_an_emergency_number_to_call(admin, app):
    org = _org(admin)
    r = admin.post(
        CONF,
        json={
            "organization_id": org["id"],
            "name": "Drill",
            "number": "3501",
            "auto_outcall": ["911"],
        },
    )
    assert r.status_code == 422 and "emergency" in r.text, r.text
