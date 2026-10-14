# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 8 generation: ring group and queue contexts, queues.conf,
pickup groups on endpoints, pickup feature codes, hints and the new
destination kinds (docs/RING_GROUPS_QUEUES.md)."""

import pytest

from veyra.telephony.asterisk import generator
from veyra.telephony.settings import SipSettings


def _ext(number, org="brookfield", **over):
    return {
        "endpoint_name": f"{org}-{number}",
        "number": number,
        "display_name": f"Phone {number}",
        "organization": org,
        "caller_id_name": None,
        "caller_id_number": None,
        "secret": "s3cret-value",
        "pickup_groups": [],
        **over,
    }


def _member(number, org="brookfield", **over):
    return {"endpoint_name": f"{org}-{number}", "number": number, "name": f"Phone {number}", **over}


def _group(slug="sales", **over):
    return {
        "slug": slug,
        "name": "Sales",
        "number": "2300",
        "organization": "brookfield",
        "strategy": "ringall",
        "ring_seconds": 20,
        "ring_busy_members": False,
        "caller_id_prefix": None,
        "members": [_member("1001"), _member("1002")],
        "failover": {"type": "voicemail", "number": "1002"},
        **over,
    }


def _queue(slug="support", **over):
    return {
        "slug": slug,
        "name": "Support",
        "number": "2400",
        "organization": "brookfield",
        "strategy": "rrmemory",
        "member_timeout": 15,
        "retry_seconds": 5,
        "wrapup_seconds": 10,
        "max_wait_seconds": 300,
        "max_callers": 0,
        "join_when_empty": False,
        "announce_position": True,
        "announce_frequency": 90,
        "announcement_prompt": "lines-busy",
        "periodic_prompt": "please-hold",
        "periodic_seconds": 60,
        "music": "default",
        "members": [_member("1001", penalty=0), _member("1002", penalty=1)],
        "failover": {"type": "extension", "number": "1001"},
        **over,
    }


def _snapshot(**over):
    snap = {
        "installation": {"name": "Test District"},
        "sip": SipSettings().model_dump(mode="json"),
        "smtp": {"enabled": False, "from_address": "pbx@example.org", "from_name": "Test PBX"},
        "organizations": [{"slug": "brookfield", "name": "Brookfield", "timezone": "UTC"}],
        "extensions": [
            _ext("1001", pickup_groups=["front"]),
            _ext("1002", pickup_groups=["front", "back"]),
        ],
        "voicemail_boxes": [
            {
                "number": "1002",
                "name": "Phone 1002",
                "organization": "brookfield",
                "timezone": "UTC",
                "pin": "1234",
                "email": None,
                "attach_audio": True,
                "delete_after_email": False,
                "ring_seconds": 20,
            }
        ],
        "ivr_menus": [],
        "ring_groups": [_group()],
        "queues": [_queue()],
    }
    snap.update(over)
    return snap


def _files(snap):
    return {f.path: f for f in generator.generate(snap, prompts_dir="/var/lib/veyra/prompts")}


def test_pickup_groups_hints_and_feature_codes():
    files = _files(_snapshot())
    ep = files["pjsip.endpoints.conf"].content
    assert "named_call_group=front\nnamed_pickup_group=front\n" in ep
    assert "named_call_group=back,front\nnamed_pickup_group=back,front\n" in ep
    dp = files["extensions.conf"].content
    assert "exten => *8,1,NoOp(Veyra group pickup by ${CALLERID(num)})\n same => n,Pickup()" in dp
    assert (
        "exten => **1001,1,NoOp(Veyra directed pickup of 1001 by ${CALLERID(num)})\n"
        ' same => n,GotoIf($["${VEYRA_ORG}"!="brookfield"]?denied)\n'
        " same => n,PickupChan(PJSIP/brookfield-1001,,p)\n"
        " same => n,Hangup()\n"
        " same => n(denied),Playback(pbx-invalid)" in dp
    )
    assert "exten => 1001,hint,PJSIP/brookfield-1001\n" in dp
    assert "exten => 2300,hint,PJSIP/brookfield-1001&PJSIP/brookfield-1002\n" in dp
    # an endpoint without groups carries no group keys
    plain = _files(_snapshot(extensions=[_ext("1001")], ring_groups=[], queues=[]))
    assert "named_call_group" not in plain["pjsip.endpoints.conf"].content
    assert generator.validate(list(files.values())) == []


def test_ring_group_ringall_skips_busy_members_and_fails_over():
    dp = _files(_snapshot())["extensions.conf"].content
    assert "exten => 2300,1,NoOp(Veyra ring group Sales)\n same => n,Goto(veyra-rg-sales,s,1)" in dp
    assert (
        "[veyra-rg-sales]\n"
        "exten => s,1,NoOp(Veyra ring group Sales (brookfield))\n"
        " same => n,Set(__VEYRA_GROUP_DEPTH=$[0${VEYRA_GROUP_DEPTH} + 1])\n"
        " same => n,GotoIf($[${VEYRA_GROUP_DEPTH} > 6]?toodeep)\n"
        " same => n,Set(VEYRA_DIAL=)\n"
        ' same => n,GotoIf($["${DEVICE_STATE(PJSIP/brookfield-1001)}" : "(INUSE|BUSY|RINGINUSE)"]?m2)\n'
        " same => n,Set(VEYRA_DIAL=${VEYRA_DIAL}&PJSIP/brookfield-1001)\n"
        ' same => n(m2),GotoIf($["${DEVICE_STATE(PJSIP/brookfield-1002)}" : "(INUSE|BUSY|RINGINUSE)"]?dial)\n'
        " same => n,Set(VEYRA_DIAL=${VEYRA_DIAL}&PJSIP/brookfield-1002)\n"
        ' same => n(dial),GotoIf($["${VEYRA_DIAL}"=""]?failover)\n'
        " same => n,Dial(${VEYRA_DIAL:1},20)\n"
        ' same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?done)\n'
        " same => n,Goto(failover)\n"
        " same => n(done),Hangup()\n"
        " same => n(failover),NoOp(Veyra ring group Sales: not answered)\n"
        " same => n,VoiceMail(1002@veyra,u)\n"
        " same => n,Hangup()\n"
        " same => n(toodeep),NoOp(Veyra: groups and queues point at each other in a loop)\n" in dp
    )


def test_ring_group_sequential_ring_busy_prefix_and_empty():
    group = _group(
        strategy="sequential",
        ring_busy_members=True,
        caller_id_prefix="Sales: ",
        ring_seconds=12,
        failover={"type": "hangup"},
    )
    dp = _files(_snapshot(ring_groups=[group]))["extensions.conf"].content
    assert (
        " same => n,Set(CALLERID(name)=Sales: ${CALLERID(name)})\n"
        " same => n,Dial(PJSIP/brookfield-1001,12)\n"
        ' same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?done)\n'
        " same => n(m2),Dial(PJSIP/brookfield-1002,12)\n"
        ' same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?done)\n'
        " same => n,Goto(failover)\n" in dp
    )
    assert "DEVICE_STATE" not in dp
    assert (
        " same => n(failover),NoOp(Veyra ring group Sales: not answered)\n same => n,Playback(vm-goodbye)"
        in dp
    )
    # sequential with the busy check uses the next member as the skip target
    seq = _files(_snapshot(ring_groups=[_group(strategy="sequential")]))["extensions.conf"].content
    assert '"(INUSE|BUSY|RINGINUSE)"]?m2)\n same => n,Dial(PJSIP/brookfield-1001,20)' in seq
    assert '"(INUSE|BUSY|RINGINUSE)"]?failover)\n same => n,Dial(PJSIP/brookfield-1002,20)' in seq
    # no members: straight to the failover, and no hint
    empty = _files(_snapshot(ring_groups=[_group(members=[])]))["extensions.conf"].content
    assert "exten => 2300,hint" not in empty
    assert "exten => s,1,NoOp(Veyra ring group Sales (brookfield))" in empty
    assert " same => n,Goto(failover)\n same => n(done),Hangup()" in empty


def test_queue_context_and_queues_conf():
    files = _files(_snapshot())
    dp = files["extensions.conf"].content
    assert (
        "exten => 2400,1,NoOp(Veyra queue Support)\n same => n,Goto(veyra-queue-support,s,1)" in dp
    )
    assert (
        "[veyra-queue-support]\n"
        "exten => s,1,NoOp(Veyra queue Support (brookfield))\n"
        " same => n,Set(__VEYRA_GROUP_DEPTH=$[0${VEYRA_GROUP_DEPTH} + 1])\n"
        " same => n,GotoIf($[${VEYRA_GROUP_DEPTH} > 6]?toodeep)\n"
        " same => n,Answer()\n"
        " same => n,Playback(/var/lib/veyra/prompts/brookfield/lines-busy)\n"
        " same => n,Queue(veyra-support,t,,,300)\n"
        " same => n,NoOp(Veyra queue Support left with ${QUEUESTATUS})\n"
        " same => n,Goto(failover)\n"
        " same => n(failover),NoOp(Veyra queue Support: not answered)\n"
        " same => n,Goto(veyra-internal,1001,1)\n" in dp
    )
    qc = files["queues.conf"]
    assert not qc.sensitive
    assert qc.content.startswith("; Managed by Veyra")
    assert (
        "[general]\npersistentmembers=no\nautofill=yes\nshared_lastcall=yes\nmonitor-type=\n"
        in qc.content
    )
    assert (
        "[veyra-support]\n"
        "; Support (brookfield)\n"
        "strategy=rrmemory\n"
        "timeout=15\n"
        "retry=5\n"
        "wrapuptime=10\n"
        "maxlen=0\n"
        "ringinuse=no\n"
        "joinempty=strict\n"
        "leavewhenempty=strict\n"
        "musicclass=default\n"
        "announce-position=yes\n"
        "announce-frequency=90\n"
        "announce-holdtime=no\n"
        "periodic-announce=/var/lib/veyra/prompts/brookfield/please-hold\n"
        "periodic-announce-frequency=60\n"
        "member => PJSIP/brookfield-1001,0,Phone 1001,PJSIP/brookfield-1001\n"
        "member => PJSIP/brookfield-1002,1,Phone 1002,PJSIP/brookfield-1002\n" in qc.content
    )
    assert generator.reload_scopes(["queues.conf"]) == ["app_queue.so"]
    assert generator.reload_scopes(["queues.conf", "extensions.conf"]) == [
        "pbx_config.so",
        "app_queue.so",
    ]
    assert generator.validate(list(files.values())) == []
    # ring instead of music, unlimited wait, callers may wait with no agent, no announcements
    q = _queue(
        music="ring",
        max_wait_seconds=0,
        join_when_empty=True,
        announce_position=False,
        announcement_prompt=None,
        periodic_prompt=None,
        members=[],
    )
    files = _files(_snapshot(queues=[q]))
    assert " same => n,Queue(veyra-support,tr,,,)\n" in files["extensions.conf"].content
    assert "Playback(/var" not in files["extensions.conf"].content.split("[veyra-queue-support]")[1]
    qc = files["queues.conf"].content
    assert "joinempty=yes\nleavewhenempty=no\n" in qc
    assert "announce-position=no\nannounce-frequency=0\n" in qc
    assert "periodic-announce" not in qc and "member =>" not in qc
    # a member whose extension is not deployed is left out
    q = _queue(members=[_member("1001"), _member("1009")])
    qc = _files(_snapshot(queues=[q]))["queues.conf"].content
    assert "brookfield-1001" in qc and "brookfield-1009" not in qc
    # without queues the file is still written with its header
    assert "[general]" in _files(_snapshot(queues=[]))["queues.conf"].content


def test_group_and_queue_destinations_and_direct_dial():
    menu = {
        "slug": "main",
        "name": "Main",
        "organization": "brookfield",
        "prompt": "welcome",
        "invalid_prompt": None,
        "timeout_seconds": 5,
        "max_retries": 3,
        "allow_direct_dial": True,
        "direct_dial": ["1001", "2300", "2400"],
        "timeout": {"type": "ring_group", "ring_group": "sales"},
        "invalid": {"type": "queue", "queue": "support"},
        "entries": [{"digit": "1", "type": "ring_group", "ring_group": "sales"}],
    }
    route = {
        "did": "5735550100",
        "trunk": None,
        "destination": {"type": "queue", "queue": "support"},
        "after_hours": None,
        "time_condition": None,
        "caller_id_prefix": None,
        "organization": "x",
    }
    dp = _files(_snapshot(ivr_menus=[menu], inbound_routes=[route]))["extensions.conf"].content
    assert "exten => 1,1,NoOp(Veyra IVR Main key 1)\n same => n,Goto(veyra-rg-sales,s,1)" in dp
    assert "exten => 2300,1,Goto(veyra-internal,2300,1)" in dp
    assert "exten => 2400,1,Goto(veyra-internal,2400,1)" in dp
    assert " same => n,Goto(veyra-queue-support,s,1)\n same => n,Hangup()" in dp
    # groups failing over to each other render plain Gotos; the depth guard stops loops
    g = _group(failover={"type": "queue", "queue": "support"})
    q = _queue(failover={"type": "ring_group", "ring_group": "sales"})
    dp = _files(_snapshot(ring_groups=[g], queues=[q]))["extensions.conf"].content
    assert dp.count("GotoIf($[${VEYRA_GROUP_DEPTH} > 6]?toodeep)") == 2


def test_group_values_are_validated():
    with pytest.raises(generator.GenerationError, match="used by a extension and a ring group"):
        _files(_snapshot(ring_groups=[_group(number="1001")]))
    with pytest.raises(generator.GenerationError, match="used by a ring group and a queue"):
        _files(_snapshot(queues=[_queue(number="2300")]))
    with pytest.raises(generator.GenerationError, match="unknown strategy"):
        _files(_snapshot(ring_groups=[_group(strategy="hunt")]))
    with pytest.raises(generator.GenerationError, match="ring time"):
        _files(_snapshot(ring_groups=[_group(ring_seconds=2)]))
    with pytest.raises(generator.GenerationError, match="duplicate ring group slug"):
        _files(_snapshot(ring_groups=[_group(), _group(number="2301")]))
    with pytest.raises(generator.GenerationError, match="unknown strategy"):
        _files(_snapshot(queues=[_queue(strategy="loudest")]))
    with pytest.raises(generator.GenerationError, match="unknown hold music"):
        _files(_snapshot(queues=[_queue(music="jazz")]))
    with pytest.raises(generator.GenerationError, match="maximum wait"):
        _files(_snapshot(queues=[_queue(max_wait_seconds=10)]))
    with pytest.raises(generator.GenerationError, match="penalty"):
        _files(_snapshot(queues=[_queue(members=[_member("1001", penalty=12)])]))
    with pytest.raises(generator.GenerationError, match="not a valid slug"):
        _files(_snapshot(extensions=[_ext("1001", pickup_groups=["Front Desk"])]))
    with pytest.raises(generator.GenerationError, match="not valid"):
        _files(_snapshot(ring_groups=[_group(number="23a0")]))
