# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 19 generation: announcement, conference and directory contexts,
confbridge.conf, the new destination kinds and the shared number space
(docs/CALL_FEATURES.md §4.1-§4.3)."""

import pytest

from veyra.telephony.asterisk import generator
from veyra.telephony.settings import SipSettings


def _snapshot(**over):
    snap = {
        "installation": {"name": "Veyra"},
        "sip": SipSettings().model_dump(mode="json"),
        "organizations": [
            {
                "slug": "example",
                "name": "Example",
                "namespace": "",
                "is_active": True,
                "timezone": "UTC",
            }
        ],
        "extensions": [
            {
                "endpoint_name": "example-1001",
                "number": "1001",
                "display_name": "Phone 1001",
                "organization": "example",
                "secret": "s3cret-value",
                "max_contacts": 1,
            }
        ],
        "voicemail_boxes": [],
        "announcements": [],
        "conference_rooms": [],
        "inbound_routes": [],
        "trunks": [],
        "ring_groups": [],
        "queues": [],
        "ivr_menus": [],
        "hold_music": [],
        "recording": [],
        "paging": {},
        "sites": [],
        "feature_codes": {},
        "numbering": {"extension_length": 4},
        "classes_of_service": [],
        "time_conditions": [],
        "outbound_routes": [],
    }
    snap.update(over)
    return snap


def _room(slug="board", number="2500", **over):
    r = {
        "slug": slug,
        "name": slug.title(),
        "number": number,
        "organization": "example",
        "user_pin": None,
        "admin_pin": None,
        "max_participants": 0,
        "record": False,
        "announce_join_leave": True,
        "music_on_hold_alone": True,
        "wait_for_admin": False,
        "hold_music": None,
    }
    r.update(over)
    return r


def _ann(slug="closed", **over):
    a = {
        "slug": slug,
        "name": slug.title(),
        "organization": "example",
        "prompt": slug,
        "allow_skip": False,
        "repeat_key": None,
        "destination": {"type": "hangup"},
    }
    a.update(over)
    return a


def _files(snap):
    return {f.path: f.content for f in generator.generate(snap)}


def _context(text, name):
    start = text.index(f"[{name}]")
    end = text.find("\n[", start + 1)
    return text[start : end if end > 0 else len(text)]


def test_announcement_contexts_plain_skippable_and_without_prompt():
    files = _files(
        _snapshot(
            announcements=[
                _ann("plain", destination={"type": "extension", "number": "1001"}),
                _ann("skip", allow_skip=True, repeat_key="9", destination={"type": "directory"}),
                _ann("rep", repeat_key="5"),
                _ann("bare", prompt=None),
            ]
        )
    )
    dp = files["extensions.conf"]
    plain = _context(dp, "veyra-ann-plain")
    assert "Playback(/var/lib/veyra/prompts/example/plain)" in plain
    assert "Goto(veyra-internal,1001,1)" in plain and "Background(" not in plain
    assert "VEYRA_ANN_DEPTH" in plain  # loop guard
    skip = _context(dp, "veyra-ann-skip")
    assert "Background(/var/lib/veyra/prompts/example/skip)" in skip and "WaitExten(1)" in skip
    assert "exten => 9,1,Goto(s,play)" in skip and "exten => _[0-9*#],1,Goto(s,next)" in skip
    assert "Goto(veyra-directory,s,1)" in skip and "exten => i,1,Goto(s,next)" in skip
    rep = _context(dp, "veyra-ann-rep")  # repeat only: a wrong key replays, never skips
    assert "exten => 5,1,Goto(s,play)" in rep and "exten => i,1,Goto(s,play)" in rep
    assert "_[0-9*#]" not in rep
    bare = _context(dp, "veyra-ann-bare")
    assert "Congestion(5)" in bare and "Playback(" not in bare
    assert generator.validate(generator.generate(_snapshot(announcements=[_ann()]))) == []


def test_announcement_rejects_bad_repeat_key_and_duplicate_slug():
    with pytest.raises(generator.GenerationError, match="repeat key"):
        _files(_snapshot(announcements=[_ann(repeat_key="A")]))
    with pytest.raises(generator.GenerationError, match="duplicate announcement"):
        _files(_snapshot(announcements=[_ann(), _ann()]))


def test_directory_context_uses_the_voicemail_context_of_the_namespace():
    dp = _files(_snapshot())["extensions.conf"]
    directory = _context(dp, "veyra-directory")
    assert "Directory(veyra,veyra-internal,ebc(veyra/directory.conf))" in directory
    assert "exten => o,1,Playback(vm-goodbye)" in directory


def test_directory_names_and_operator():
    """Custom directory names and the operator on 0 (#135)."""
    snap = _snapshot()
    snap["organizations"][0]["directory_operator"] = "1000"
    snap["organizations"][0]["directory_entries"] = [
        {"name": "Front office", "number": "2000"},
        {"name": "Nurse", "number": "1003"},
    ]
    snap["voicemail_boxes"] = [
        {
            "number": "1001",
            "name": "Pat Example",
            "organization": snap["organizations"][0]["slug"],
            "timezone": "UTC",
            "pin": "1234",
            "email": None,
            "attach_audio": True,
            "delete_after_email": False,
            "ring_seconds": 20,
        }
    ]
    files = _files(snap)
    conf = files["directory.conf"]
    assert "[veyra]" in conf and "1001 => ,Pat Example" in conf
    assert "2000 => ,Front office" in conf and "1003 => ,Nurse" in conf
    assert "1234" not in conf  # no PINs in the directory file
    directory = _context(files["extensions.conf"], "veyra-directory")
    assert "exten => o,1,Goto(veyra-internal,1000,1)" in directory
    snap["organizations"][0]["directory_entries"] = [{"name": "", "number": "2000"}]
    with pytest.raises(generator.GenerationError, match="directory name"):
        _files(snap)


def test_conference_pin_variants_and_confbridge_file():
    files = _files(
        _snapshot(
            conference_rooms=[
                _room("open", "2500"),
                _room(
                    "both",
                    "2501",
                    user_pin="1234",
                    admin_pin="9876",
                    max_participants=8,
                    record=True,
                    wait_for_admin=True,
                ),
                _room(
                    "admin",
                    "2502",
                    admin_pin="4321",
                    announce_join_leave=False,
                    music_on_hold_alone=False,
                ),
            ]
        )
    )
    dp, cb = files["extensions.conf"], files["confbridge.conf"]
    open_ctx = _context(dp, "veyra-conf-open")
    assert "Read(" not in open_ctx
    assert (
        "ConfBridge(veyra-conf-open,veyra-conf-open-bridge,${VEYRA_CONF_PROFILE},veyra-conf-open-menu)"
        in open_ctx
    )
    both = _context(dp, "veyra-conf-both")
    assert "Read(VEYRA_PIN,conf-getpin,10,,1,10)" in both
    assert 'GotoIf($["${VEYRA_PIN}"="9876"]?admin)' in both
    assert 'GotoIf($["${VEYRA_PIN}"="1234"]?join)' in both
    assert "GotoIf($[${VEYRA_CONF_TRIES} >= 3]?bye)" in both
    assert "Set(VEYRA_CONF_PROFILE=veyra-conf-both-admin)" in both
    admin = _context(dp, "veyra-conf-admin")
    # Only an administrator PIN: # alone joins as a participant.
    assert 'GotoIf($["${VEYRA_PIN}"=""]?join)' in admin
    # Dialable numbers with a lamp in the phone context.
    internal = _context(dp, "veyra-internal")
    assert "exten => 2500,hint,confbridge:veyra-conf-open" in internal
    assert "exten => 2501,1,NoOp(Veyra conference Both)" in internal
    assert "Goto(veyra-conf-both,s,1)" in internal
    # confbridge.conf
    bridge = _context(cb, "veyra-conf-both-bridge")
    assert "max_members=8" in bridge and "record_conference=yes" in bridge
    assert "record_file=/var/lib/veyra/recordings/conferences/example--both" in bridge
    assert "record_file_timestamp=yes" in bridge
    user = _context(cb, "veyra-conf-both-user")
    assert "wait_marked=yes" in user and "announce_join_leave=yes" in user
    admin_profile = _context(cb, "veyra-conf-admin-admin")
    assert "admin=yes" in admin_profile and "marked=yes" in admin_profile
    assert (
        "announce_join_leave=no" in admin_profile and "music_on_hold_when_empty=no" in admin_profile
    )
    assert "*1=toggle_mute" in _context(cb, "veyra-conf-open-menu")
    assert "; max_members: no limit" in _context(cb, "veyra-conf-open-bridge")
    assert generator.validate(generator.generate(_snapshot(conference_rooms=[_room()]))) == []
    assert "app_confbridge.so" in generator.reload_scopes(["confbridge.conf"])


def test_conference_validation():
    with pytest.raises(generator.GenerationError, match="PIN must be"):
        _files(_snapshot(conference_rooms=[_room(user_pin="12")]))
    with pytest.raises(generator.GenerationError, match="same"):
        _files(_snapshot(conference_rooms=[_room(user_pin="1234", admin_pin="1234")]))
    with pytest.raises(
        generator.GenerationError, match="used by a extension and a conference room"
    ):
        _files(_snapshot(conference_rooms=[_room(number="1001")]))
    with pytest.raises(generator.GenerationError, match="participant limit"):
        _files(_snapshot(conference_rooms=[_room(max_participants=1000)]))
    with pytest.raises(generator.GenerationError, match="duplicate conference"):
        _files(_snapshot(conference_rooms=[_room(), _room(number="2509")]))


def test_destinations_render_for_routes_and_groups():
    snap = _snapshot(
        announcements=[_ann("notice", destination={"type": "conference", "conference": "board"})],
        conference_rooms=[_room()],
        inbound_routes=[
            {
                "did": "5735550100",
                "trunk": None,
                "destination": {"type": "announcement", "announcement": "notice"},
                "after_hours": None,
                "time_condition": None,
                "caller_id_prefix": None,
                "organization": "x",
                "organization_slug": "example",
            },
            {
                "did": "5735550101",
                "trunk": None,
                "destination": {"type": "directory"},
                "after_hours": None,
                "time_condition": None,
                "caller_id_prefix": None,
                "organization": "x",
                "organization_slug": "example",
            },
            {
                "did": "5735550102",
                "trunk": None,
                "destination": {"type": "missing"},
                "after_hours": None,
                "time_condition": None,
                "caller_id_prefix": None,
                "organization": "x",
                "organization_slug": "example",
            },
        ],
    )
    dp = _files(snap)["extensions.conf"]
    assert "Goto(veyra-ann-notice,s,1)" in dp
    assert "Goto(veyra-conf-board,s,1)" in _context(dp, "veyra-ann-notice")
    assert "Goto(veyra-directory,s,1)" in dp
    assert "the destination no longer exists" in dp


def _flow(slug="night", index=1, **over):
    f = {
        "slug": slug,
        "name": slug.title(),
        "organization": "example",
        "code_index": index,
        "pin": None,
        "override": False,
        "normal": {"type": "extension", "number": "1001"},
        "override_destination": {"type": "directory"},
    }
    f.update(over)
    return f


def _tc(key="tc-1", index=2, **over):
    c = {
        "key": key,
        "name": "Office hours",
        "organization": "example",
        "timezone": "UTC",
        "ranges": [{"days": ["mon", "tue"], "start": "08:00", "end": "17:00"}],
        "holidays": ["12-25"],
        "code_index": index,
        "pin": None,
        "override": None,
    }
    c.update(over)
    return c


CODES = {"callflow_toggle_prefix": "*28", "tc_override_prefix": "*27"}


def test_call_flow_context_codes_and_hints():
    dp = _files(_snapshot(call_flows=[_flow(pin="1234")], feature_codes=CODES))["extensions.conf"]
    flow = _context(dp, "veyra-flow-night")
    assert 'GotoIf($["${DB(veyra/switch/flow/example/night)}"="1"]?override)' in flow
    assert "Goto(veyra-internal,1001,1)" in flow and "Goto(veyra-directory,s,1)" in flow
    features = _context(dp, "veyra-features")
    code = features[features.index("exten => *281,1") :]
    assert (
        "Read(VEYRA_PIN,agent-pass,10,,1,10)" in code
        and 'GotoIf($["${VEYRA_PIN}"="1234"]?ok)' in code
    )
    assert "Set(DB(veyra/switch/flow/example/night)=1)" in code
    assert "Set(DEVICE_STATE(Custom:veyra-flow-example-night)=INUSE)" in code
    assert "UserEvent(VeyraSwitch,Kind: flow,Org: example,Key: night,Value: 1)" in code
    assert "Set(VEYRA_DEL=${DB_DELETE(veyra/switch/flow/example/night)})" in code
    assert 'GotoIf($["${VEYRA_ORG}"!="example"]?nophone)' in code
    assert "exten => *281,hint,Custom:veyra-flow-example-night" in _context(dp, "veyra-internal")
    # No toggle prefix: no code, no hint, the routing context stays.
    dp2 = _files(_snapshot(call_flows=[_flow()], feature_codes={}))["extensions.conf"]
    assert "exten => *281" not in dp2 and "[veyra-flow-night]" in dp2


def test_call_flow_validation():
    with pytest.raises(generator.GenerationError, match="share the code index"):
        _files(_snapshot(call_flows=[_flow("a", 1), _flow("b", 1)], feature_codes=CODES))
    with pytest.raises(generator.GenerationError, match="out of range"):
        _files(_snapshot(call_flows=[_flow(index=100)], feature_codes=CODES))
    with pytest.raises(generator.GenerationError, match="PIN must be"):
        _files(_snapshot(call_flows=[_flow(pin="12")], feature_codes=CODES))


def test_time_condition_override_code_and_route_check():
    route = {
        "did": "5735550100",
        "trunk": None,
        "destination": {"type": "extension", "number": "1001"},
        "after_hours": {"type": "directory"},
        "time_condition": "tc-1",
        "caller_id_prefix": None,
        "organization": "x",
        "organization_slug": "example",
    }
    dp = _files(_snapshot(time_conditions=[_tc()], inbound_routes=[route], feature_codes=CODES))[
        "extensions.conf"
    ]
    features = _context(dp, "veyra-features")
    code = features[features.index("exten => *272,1") :]
    assert 'GotoIf($["${DB(veyra/switch/tc/example/tc-1)}"!=""]?clear)' in code
    assert "GotoIfTime(*,*,25,dec,UTC?isclosed)" in code
    assert "GotoIfTime(08:00-17:00,mon-tue,*,*,UTC?isopen)" in code
    assert "Set(DB(veyra/switch/tc/example/tc-1)=open)" in code
    assert "Set(DB(veyra/switch/tc/example/tc-1)=closed)" in code
    assert "UserEvent(VeyraSwitch,Kind: tc,Org: example,Key: tc-1,Value: )" in code
    assert "exten => *272,hint,Custom:veyra-tc-example-tc-1" in _context(dp, "veyra-internal")
    # The route consults the override before the schedule.
    body = dp.split("exten => 5735550100,1,")[1].split("\nexten =>")[0]
    assert "Set(VEYRA_TC=${DB(veyra/switch/tc/example/tc-1)})" in body
    assert body.index('"${VEYRA_TC}"="open"]?open') < body.index("GotoIfTime(")
    # A condition without a code gets neither code nor hint.
    dp2 = _files(
        _snapshot(
            time_conditions=[_tc(code_index=None)], inbound_routes=[route], feature_codes=CODES
        )
    )["extensions.conf"]
    assert "exten => *27" not in dp2
    with pytest.raises(generator.GenerationError, match="share the code index"):
        _files(
            _snapshot(time_conditions=[_tc("a", 2), _tc("b", 2, name="Other")], feature_codes=CODES)
        )


def _lot(slug="main", **over):
    lot = {
        "slug": slug,
        "name": slug.title(),
        "organization": "example",
        "park_exten": "70",
        "slot_first": 71,
        "slot_last": 79,
        "timeout_seconds": 45,
        "return_ring_seconds": 20,
        "courtesy_tone": True,
        "timeout": {"type": "extension", "number": "1001"},
    }
    lot.update(over)
    return lot


def test_parking_lot_conf_contexts_and_numbers():
    files = _files(_snapshot(parking_lots=[_lot()]))
    conf = files["res_parking.conf"]
    lot = _context(conf, "veyra-park-main")
    for line in (
        "context=veyra-park-main",
        "parkext=70",
        "parkpos=71-79",
        "parkingtime=45",
        "comebacktoorigin=no",
        "comebackcontext=veyra-park-main-timeout",
        "comebackdialtime=20",
        "courtesytone=beep",
        "parkext_exclusive=yes",
    ):
        assert line in lot
    dp = files["extensions.conf"]
    assert "include => veyra-park-main" in _context(dp, "veyra-internal")
    timeout = _context(dp, "veyra-park-main-timeout")
    assert "Dial(${PARKER},20)" in timeout and "Goto(veyra-internal,1001,1)" in timeout
    assert 'GotoIf($["${PARKER_FLAT}"=""]?gone)' in timeout
    assert "res_parking.so" in generator.reload_scopes(["res_parking.conf"])
    assert generator.validate(generator.generate(_snapshot(parking_lots=[_lot()]))) == []
    # No courtesy tone: the key is left empty.
    conf2 = _files(_snapshot(parking_lots=[_lot(courtesy_tone=False)]))["res_parking.conf"]
    assert "courtesytone=\n" in conf2


def test_parking_lot_validation():
    with pytest.raises(generator.GenerationError, match="used by a extension and parking lot"):
        _files(_snapshot(parking_lots=[_lot(park_exten="1001")]))
    with pytest.raises(generator.GenerationError, match="not a range"):
        _files(_snapshot(parking_lots=[_lot(slot_first=79, slot_last=71)]))
    with pytest.raises(generator.GenerationError, match="not a range"):
        _files(_snapshot(parking_lots=[_lot(slot_first=100, slot_last=200)]))
    with pytest.raises(generator.GenerationError, match="inside the slots"):
        _files(_snapshot(parking_lots=[_lot(park_exten="75")]))
    with pytest.raises(generator.GenerationError, match="timeout"):
        _files(_snapshot(parking_lots=[_lot(timeout_seconds=5)]))
    # Two lots may not overlap, and a conference room may not sit in a lot.
    with pytest.raises(generator.GenerationError, match="parking lot"):
        _files(
            _snapshot(
                parking_lots=[_lot(), _lot("second", park_exten="80", slot_first=75, slot_last=85)]
            )
        )
    with pytest.raises(
        generator.GenerationError, match="used by a conference room and parking lot"
    ):
        _files(
            _snapshot(
                parking_lots=[_lot(park_exten="2500")], conference_rooms=[_room(number="2500")]
            )
        )
