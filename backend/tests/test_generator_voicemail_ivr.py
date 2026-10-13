# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 7 generation: voicemail.conf, MWI, extension dialplan with a
box, feature codes, IVR contexts and typed destinations."""

import pytest

from veyra.telephony.asterisk import generator
from veyra.telephony.settings import SipSettings


def _ext(number, org="example", **over):
    return {
        "endpoint_name": f"{org}-{number}",
        "number": number,
        "display_name": f"Phone {number}",
        "organization": org,
        "caller_id_name": None,
        "caller_id_number": None,
        "secret": "s3cret-value",
        **over,
    }


def _box(number, **over):
    return {
        "number": number,
        "name": f"Phone {number}",
        "organization": "example",
        "timezone": "America/Chicago",
        "pin": "123456",
        "email": f"user{number}@example.org",
        "attach_audio": True,
        "delete_after_email": False,
        "ring_seconds": 25,
        **over,
    }


def _menu(slug="main-menu", **over):
    return {
        "slug": slug,
        "name": "Main menu",
        "organization": "example",
        "prompt": "welcome",
        "invalid_prompt": None,
        "timeout_seconds": 6,
        "max_retries": 2,
        "allow_direct_dial": True,
        "direct_dial": ["1001", "1002"],
        "timeout": {"type": "extension", "number": "1001"},
        "invalid": {"type": "hangup"},
        "entries": [
            {"digit": "1", "type": "extension", "number": "1001"},
            {"digit": "2", "type": "voicemail", "number": "1002"},
            {"digit": "3", "type": "ivr", "ivr": "after-hours"},
            {"digit": "0", "type": "missing"},
        ],
        **over,
    }


def _snapshot(**over):
    snap = {
        "installation": {"name": "Test District"},
        "sip": SipSettings().model_dump(mode="json"),
        "smtp": {"enabled": True, "from_address": "pbx@example.org", "from_name": "Test PBX"},
        "organizations": [{"slug": "example", "name": "Example", "timezone": "UTC"}],
        "extensions": [_ext("1001"), _ext("1002")],
        "voicemail_boxes": [_box("1002")],
        "ivr_menus": [],
    }
    snap.update(over)
    return snap


def _files(snap):
    return {f.path: f for f in generator.generate(snap, prompts_dir="/var/lib/veyra/prompts")}


def test_voicemail_conf_is_rendered_sensitive_and_valid():
    files = _files(_snapshot())
    vm = files["voicemail.conf"]
    assert vm.sensitive
    assert "[general]" in vm.content and "serveremail=pbx@example.org" in vm.content
    assert "fromstring=Test PBX" in vm.content
    assert "mailcmd=/opt/veyra/current/installer/bin/veyra-mailqueue" in vm.content
    assert "example=America/Chicago|'vm-received' Q 'digits/at' IMp" in vm.content
    assert (
        "1002 => 123456,Phone 1002,user1002@example.org,,"
        "attach=yes|delete=no|tz=example|saycid=yes|envelope=yes" in vm.content
    )
    assert generator.validate(list(files.values())) == []
    assert generator.MANAGED_FILES[-1] == "voicemail.conf"
    assert generator.reload_scopes(["voicemail.conf"]) == ["app_voicemail.so"]
    # without any box the file still exists, carries no PIN and is not sensitive
    empty = _files(_snapshot(voicemail_boxes=[]))["voicemail.conf"]
    assert "[veyra]" in empty.content and not empty.sensitive


def test_email_is_left_out_when_delivery_is_disabled():
    snap = _snapshot(
        smtp={"enabled": False, "from_address": "x@example.org", "from_name": "X"},
        voicemail_boxes=[_box("1002", delete_after_email=True)],
    )
    vm = _files(snap)["voicemail.conf"].content
    assert "1002 => 123456,Phone 1002,,,attach=yes|delete=no|" in vm
    # with delivery on, delete_after_email reaches the engine
    on = _files(_snapshot(voicemail_boxes=[_box("1002", delete_after_email=True)]))
    assert "|delete=yes|" in on["voicemail.conf"].content


def test_mwi_and_voicemail_dialplan_for_extensions_with_a_box():
    files = _files(_snapshot())
    ep = files["pjsip.endpoints.conf"].content
    # only the extension with a box subscribes to a mailbox, on endpoint and AOR
    assert ep.count("mailboxes=1002@veyra") == 2
    assert "mailboxes=1001@veyra" not in ep
    assert "mwi_subscribe_replaces_unsolicited=yes" in ep
    dp = files["extensions.conf"].content
    assert (
        "exten => 1001,1,NoOp(Veyra extension 1001)\n"
        " same => n,Dial(PJSIP/example-1001,30)\n"
        " same => n,Hangup()" in dp
    )
    assert (
        "exten => 1002,1,NoOp(Veyra extension 1002)\n"
        " same => n,Dial(PJSIP/example-1002,25)\n"
        ' same => n,GotoIf($["${DIALSTATUS}"="BUSY"]?busy)\n'
        " same => n,VoiceMail(1002@veyra,u)\n"
        " same => n,Hangup()\n"
        " same => n(busy),VoiceMail(1002@veyra,b)\n"
        " same => n,Hangup()" in dp
    )
    # feature codes
    assert "exten => *97,1," in dp and "VoiceMailMain(${CALLERID(num)}@veyra)" in dp
    assert "exten => *98,1," in dp and "VoiceMailMain(@veyra)" in dp
    assert "exten => *95,1," in dp
    assert (
        "Set(VEYRA_REC=/var/lib/veyra/prompts/${VEYRA_ORG}/incoming/rec-${CALLERID(num)}-${EPOCH})"
        in dp
    )
    assert "Record(${VEYRA_REC}.wav,5,300,k)" in dp
    assert "Read(VEYRA_CHOICE,vm-review,1,,1,5)" in dp


def test_box_of_an_unknown_extension_is_skipped_and_bad_values_rejected():
    files = _files(_snapshot(voicemail_boxes=[_box("1002"), _box("4444")]))
    assert "4444 =>" not in files["voicemail.conf"].content
    with pytest.raises(generator.GenerationError, match="PIN"):
        _files(_snapshot(voicemail_boxes=[_box("1002", pin="12")]))
    with pytest.raises(generator.GenerationError, match="more than one"):
        _files(_snapshot(voicemail_boxes=[_box("1002"), _box("1002")]))
    with pytest.raises(generator.GenerationError, match="ring time"):
        _files(_snapshot(voicemail_boxes=[_box("1002", ring_seconds=2)]))
    with pytest.raises(generator.GenerationError, match="email"):
        _files(_snapshot(voicemail_boxes=[_box("1002", email="not an address")]))
    with pytest.raises(generator.GenerationError, match="path"):
        generator.generate(_snapshot(), prompts_dir="relative/dir")


def test_ivr_context_keys_direct_dial_and_fallbacks():
    files = _files(_snapshot(ivr_menus=[_menu(), _menu("after-hours", name="After hours")]))
    dp = files["extensions.conf"].content
    assert "[veyra-ivr-main-menu]" in dp and "[veyra-ivr-after-hours]" in dp
    body = dp.split("[veyra-ivr-main-menu]")[1].split("[veyra-ivr-after-hours]")[0]
    assert "GotoIf($[${VEYRA_IVR_DEPTH} > 8]?toodeep)" in body
    assert " same => n(menu),Background(/var/lib/veyra/prompts/example/welcome)" in body
    # The timeout handler must be reached explicitly: WaitExten continues with
    # the next priority when one exists instead of going to 't'.
    assert " same => n,WaitExten(6)\n same => n,Goto(t,1)\n" in body
    assert (
        "exten => 1,1,NoOp(Veyra IVR Main menu key 1)\n same => n,Goto(veyra-internal,1001,1)"
        in body
    )
    assert (
        "exten => 2,1,NoOp(Veyra IVR Main menu key 2)\n same => n,VoiceMail(1002@veyra,u)" in body
    )
    assert (
        "exten => 3,1,NoOp(Veyra IVR Main menu key 3)\n same => n,Goto(veyra-ivr-after-hours,s,1)"
        in body
    )
    # a missing target answers with congestion instead of breaking the menu
    assert (
        "exten => 0,1,NoOp(Veyra IVR Main menu key 0)\n"
        " same => n,NoOp(Veyra: the destination no longer exists)\n"
        " same => n,Congestion(5)" in body
    )
    # direct dialling renders the organization's extensions explicitly
    assert "exten => 1001,1,Goto(veyra-internal,1001,1)" in body
    assert "exten => 1002,1,Goto(veyra-internal,1002,1)" in body
    # invalid and timeout handlers retry twice then fall back
    assert "exten => i,1,Set(VEYRA_IVR_TRIES=$[${VEYRA_IVR_TRIES} + 1])" in body
    assert "GotoIf($[${VEYRA_IVR_TRIES} >= 2]?giveup)" in body
    assert " same => n,Playback(pbx-invalid)\n same => n,Goto(s,menu)" in body
    # a timeout replays the menu without the invalid prompt
    t_handler = body.split("exten => t,1,")[1]
    assert (
        t_handler.startswith("Set(VEYRA_IVR_TRIES=")
        and "Playback(pbx-invalid)\n same => n,Goto(s,menu)" not in t_handler
    )
    assert "no key pressed 2 times)\n same => n,Goto(veyra-internal,1001,1)" in body
    assert "invalid key 2 times)\n same => n,Playback(vm-goodbye)\n same => n,Hangup()" in body
    assert generator.validate(list(files.values())) == []


def test_ivr_without_prompt_is_congestion_and_custom_invalid_prompt_is_used():
    files = _files(
        _snapshot(
            ivr_menus=[
                _menu(prompt=None),
                _menu("other", invalid_prompt="try-again", allow_direct_dial=False),
            ]
        )
    )
    dp = files["extensions.conf"].content
    main = dp.split("[veyra-ivr-main-menu]")[1].split("[veyra-ivr-other]")[0]
    assert "no prompt, menu not deployable" in main and "Congestion(5)" in main
    other = dp.split("[veyra-ivr-other]")[1]
    assert "Playback(/var/lib/veyra/prompts/example/try-again)" in other
    assert "exten => 1001,1,Goto" not in other  # direct dialling off


def test_ivr_values_are_validated():
    with pytest.raises(generator.GenerationError, match="duplicate IVR"):
        _files(_snapshot(ivr_menus=[_menu(), _menu()]))
    with pytest.raises(generator.GenerationError, match="slug"):
        _files(_snapshot(ivr_menus=[_menu("Bad Slug!")]))
    with pytest.raises(generator.GenerationError, match="key"):
        _files(_snapshot(ivr_menus=[_menu(entries=[{"digit": "x", "type": "hangup"}])]))
    with pytest.raises(generator.GenerationError, match="prompt slug"):
        _files(_snapshot(ivr_menus=[_menu(prompt="../etc")]))


def test_inbound_routes_accept_typed_destinations():
    snap = _snapshot(
        ivr_menus=[_menu()],
        trunks=[],
        inbound_routes=[
            {
                "did": "5735550100",
                "trunk": None,
                "destination": {"type": "ivr", "ivr": "main-menu"},
            },
            {
                "did": "5735550101",
                "trunk": None,
                "destination": {"type": "voicemail", "number": "1002"},
            },
            {"did": "5735550102", "trunk": None, "destination": {"type": "missing"}},
            {"did": "5735550103", "trunk": None, "destination": "1001"},  # Milestone 6 form
        ],
    )
    dp = _files(snap)["extensions.conf"].content
    assert "exten => 5735550100,1," in dp and "Goto(veyra-ivr-main-menu,s,1)" in dp
    assert "VoiceMail(1002@veyra,u)" in dp.split("exten => 5735550101,1,")[1].split("exten =>")[0]
    assert "Congestion(5)" in dp.split("exten => 5735550102,1,")[1].split("exten =>")[0]
    assert (
        "Goto(veyra-internal,1001,1)" in dp.split("exten => 5735550103,1,")[1].split("exten =>")[0]
    )
