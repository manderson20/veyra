# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 6 generation: trunk sections, inbound and outbound contexts,
time conditions, loop detection and emergency routes (docs/TRUNKS_ROUTING.md)."""

import pytest

from veyra.telephony import routing
from veyra.telephony.asterisk import generator
from veyra.telephony.settings import SipSettings


def _trunk(slug="carrier", **over):
    t = {
        "slug": slug,
        "name": slug.title(),
        "auth_mode": "registration",
        "host": "sip.carrier.example",
        "port": 5060,
        "transport": "udp",
        "username": "acct1",
        "auth_username": None,
        "password": "pw-1",
        "from_user": None,
        "from_domain": None,
        "outbound_proxy": None,
        "match_addresses": ["203.0.113.0/24"],
        "codecs": None,
        "max_channels": None,
        "default_caller_id": "5735550100",
        "caller_id_header": "pai",
        "dtmf_mode": "rfc4733",
        "qualify_frequency": 60,
        "register_expiry": 3600,
    }
    t.update(over)
    return t


def _route(slug="local", **over):
    r = {
        "slug": slug,
        "name": slug.title(),
        "is_emergency": False,
        "patterns": [{"prefix": "9", "match": "NXXNXXXXXX", "prepend": "1"}],
        "trunks": ["carrier"],
        "caller_id_number": None,
    }
    r.update(over)
    return r


def _snapshot(**over):
    snap = {
        "installation": {"name": "Test District"},
        "sip": SipSettings().model_dump(mode="json"),
        "organizations": [{"slug": "brookfield", "name": "Brookfield", "timezone": "UTC"}],
        "extensions": [
            {
                "endpoint_name": "brookfield-1001",
                "number": "1001",
                "display_name": "Front Office",
                "organization": "brookfield",
                "secret": "s3cret",
            }
        ],
        "trunks": [_trunk()],
        "inbound_routes": [],
        "outbound_routes": [],
        "time_conditions": [],
    }
    snap.update(over)
    return snap


def _files(snap):
    files = {f.path: f for f in generator.generate(snap)}
    assert generator.validate(list(files.values())) == []
    return files


def _section(text, header):
    body = text.split(f"[{header}]\n", 1)[1]
    return body.split("\n[", 1)[0]


def test_registration_trunk_renders_every_section_and_is_sensitive():
    files = _files(_snapshot())
    trunks = files["pjsip.trunks.conf"]
    assert trunks.sensitive
    assert generator.FILE_TRUNKS in generator.MANAGED_FILES
    assert generator.RELOAD_SCOPES[generator.FILE_TRUNKS] == "res_pjsip.so"
    c = trunks.content
    assert c.count("[trunk-carrier]") == 5  # endpoint, aor, identify, auth, registration
    assert "context=veyra-from-trunk-carrier" in c
    assert "set_var=VEYRA_TRUNK=carrier" in c
    assert "outbound_auth=trunk-carrier" in c
    assert "contact=sip:sip.carrier.example:5060\nqualify_frequency=60" in c
    assert "match=203.0.113.0/24" in c
    assert "username=acct1\npassword=pw-1" in c
    assert "client_uri=sip:acct1@sip.carrier.example" in c and "line=yes" in c
    assert "send_pai=yes" in c and "send_rpid=no" in c
    # phones now carry their organization for later per-tenant routing
    assert "set_var=VEYRA_ORG=brookfield" in files["pjsip.endpoints.conf"].content


def test_ip_trunk_has_no_auth_and_defaults_match_to_host():
    t = _trunk(
        "backup",
        auth_mode="ip",
        host="198.51.100.7",
        transport="tcp",
        match_addresses=[],
        caller_id_header="rpid",
        qualify_frequency=0,
        outbound_proxy="proxy.example:5080",
        from_user="main",
        username=None,
        password=None,
    )
    files = _files(_snapshot(trunks=[t]))
    c = files["pjsip.trunks.conf"].content
    assert not files["pjsip.trunks.conf"].sensitive
    assert c.count("[trunk-backup]") == 3
    assert "type=registration" not in c and "type=auth" not in c
    assert "match=198.51.100.7" in c
    assert "contact=sip:198.51.100.7:5060\\;transport=tcp" in c
    assert "outbound_proxy=sip:proxy.example:5080\\;lr" in c
    assert "send_rpid=yes" in c and "from_user=main" in c


def test_no_trunks_still_produces_the_file_and_contexts():
    files = _files(_snapshot(trunks=[]))
    assert files["pjsip.trunks.conf"].content.startswith("; Managed by Veyra")
    d = files["extensions.conf"].content
    assert "[veyra-outbound]" in d and "[veyra-from-trunk]" in d


@pytest.mark.parametrize(
    "over, message",
    [
        ({"transport": "tls"}, "TLS transport is disabled"),
        ({"password": None}, "no user name or password"),
        ({"host": "bad host;x"}, "not a valid host"),
        ({"slug": "bad slug"}, "not a valid section name"),
        ({"codecs": ["ulaw", "bad codec"]}, "codec"),
        ({"dtmf_mode": "sms"}, "DTMF"),
    ],
)
def test_trunk_values_are_validated(over, message):
    with pytest.raises(generator.GenerationError, match=message):
        generator.generate(_snapshot(trunks=[_trunk(**over)]))


def test_duplicate_trunk_slug_is_rejected():
    with pytest.raises(generator.GenerationError, match="duplicate trunk slug"):
        generator.generate(_snapshot(trunks=[_trunk(), _trunk()]))


def test_outbound_routes_emergency_first_with_failover_and_loop_check():
    carrier = _trunk(max_channels=4)
    backup = _trunk("backup", auth_mode="ip", host="198.51.100.7", password=None, username=None)
    local = _route(
        patterns=[
            {"prefix": "9", "match": "NXXNXXXXXX", "prepend": "1"},
            {"prefix": "9", "match": "1NXXNXXXXXX", "prepend": ""},
        ],
        trunks=["carrier", "backup"],
    )
    emergency = _route(
        "emergency",
        is_emergency=True,
        patterns=[{"prefix": "", "match": "911", "prepend": ""}],
        caller_id_number="5735550199",
    )
    files = _files(_snapshot(trunks=[carrier, backup], outbound_routes=[local, emergency]))
    d = files["extensions.conf"].content
    internal = _section(d, "veyra-internal")
    assert internal.index("include => veyra-features") < internal.index("include => veyra-outbound")
    assert internal.index("include => veyra-outbound") < internal.index("include => veyra-invalid")
    outbound = _section(d, "veyra-outbound")
    assert outbound.index("veyra-out-emergency") < outbound.index("veyra-out-local")
    local_ctx = _section(d, "veyra-out-local")
    assert "exten => _9NXXNXXXXXX,1," in local_ctx and "exten => _91NXXNXXXXXX,1," in local_ctx
    assert "Set(VEYRA_DIAL=1${EXTEN:1})" in local_ctx and "Set(VEYRA_DIAL=${EXTEN:1})" in local_ctx
    assert "GotoIf($[0${VEYRA_HOPS} > 0]?loop)" in local_ctx
    assert "GotoIf($[${GROUP_COUNT(carrier@veyra_trunk)} > 4]?t2)" in local_ctx
    assert "Set(CALLERID(num)=5735550100)" in local_ctx  # trunk default
    assert "Dial(PJSIP/${VEYRA_DIAL}@trunk-carrier,60)" in local_ctx
    assert "Dial(PJSIP/${VEYRA_DIAL}@trunk-backup,60)" in local_ctx
    assert '"${DIALSTATUS}"="CHANUNAVAIL" | "${DIALSTATUS}"="CONGESTION"]?t2' in local_ctx
    assert "Playback(all-circuits-busy)" in local_ctx and "Hangup(21)" in local_ctx
    em = _section(d, "veyra-out-emergency")
    assert "exten => 911,1," in em and "Log(WARNING,Veyra EMERGENCY call" in em
    assert "Set(CALLERID(num)=5735550199)" in em  # route override
    assert "Dial(PJSIP/${VEYRA_DIAL}@trunk-carrier,120)" in em
    assert "loop" not in em and "GROUP_COUNT" not in em


def test_outbound_route_without_usable_trunks_fails_cleanly():
    files = _files(_snapshot(outbound_routes=[_route(trunks=["missing"])]))
    ctx = _section(files["extensions.conf"].content, "veyra-out-local")
    assert "Goto(failed)" in ctx and "Dial(" not in ctx


@pytest.mark.parametrize(
    "pattern",
    [
        {"prefix": "9", "match": "NXX;NXXXXXX", "prepend": ""},
        {"prefix": "a", "match": "NXX", "prepend": ""},
        {"prefix": "", "match": "N.X", "prepend": ""},
        {"prefix": "", "match": "NXX", "prepend": "x"},
    ],
)
def test_outbound_patterns_are_validated(pattern):
    with pytest.raises(generator.GenerationError, match="outbound route local"):
        generator.generate(_snapshot(outbound_routes=[_route(patterns=[pattern])]))


def test_inbound_routes_shared_restricted_aliases_and_time_conditions():
    backup = _trunk("backup", auth_mode="ip", host="198.51.100.7", password=None, username=None)
    tc = {
        "key": "tc1",
        "name": "Office hours",
        "timezone": "America/Chicago",
        "ranges": [
            {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "07:30", "end": "16:00"},
            {"days": ["mon", "wed", "sat"], "start": "18:00", "end": "20:00"},
        ],
        "holidays": ["12-25"],
    }
    routes = [
        {
            "did": "5735550100",
            "trunk": None,
            "destination": "1001",
            "after_hours": "1001",
            "time_condition": "tc1",
            "caller_id_prefix": "Main: ",
            "organization": "o",
        },
        {
            "did": "+15735550101",
            "trunk": "backup",
            "destination": "1001",
            "after_hours": None,
            "time_condition": None,
            "caller_id_prefix": None,
            "organization": "o",
        },
        {
            "did": "15735550100",  # an explicit alias form of the first DID: no automatic alias
            "trunk": "backup",
            "destination": None,
            "after_hours": None,
            "time_condition": None,
            "caller_id_prefix": None,
            "organization": "o",
        },
    ]
    files = _files(
        _snapshot(trunks=[_trunk(), backup], inbound_routes=routes, time_conditions=[tc])
    )
    d = files["extensions.conf"].content
    shared = _section(d, "veyra-from-trunk")
    assert "exten => 5735550100,1,NoOp(Veyra inbound 5735550100" in shared
    assert "Set(__VEYRA_HOPS=1)" in shared and "Set(__VEYRA_DID=5735550100)" in shared
    assert "Set(CALLERID(name)=Main: ${CALLERID(name)})" in shared
    assert "GotoIfTime(*,*,25,dec,America/Chicago?closed)" in shared
    assert "GotoIfTime(07:30-16:00,mon-fri,*,*,America/Chicago?open)" in shared
    assert "GotoIfTime(18:00-20:00,mon,*,*,America/Chicago?open)" in shared
    assert "GotoIfTime(18:00-20:00,wed,*,*,America/Chicago?open)" in shared
    assert "GotoIfTime(18:00-20:00,sat,*,*,America/Chicago?open)" in shared
    assert "n(closed),NoOp" in shared and "n(open),NoOp" in shared
    assert "exten => +15735550100,1,Goto(veyra-from-trunk,5735550100,1)" in shared
    # 15735550100 is claimed explicitly on the backup trunk: the shared alias still
    # exists for other trunks, and the backup context's own entry wins there.
    assert "exten => 15735550100,1,Goto(veyra-from-trunk,5735550100,1)" in shared
    backup_ctx = _section(d, "veyra-from-trunk-backup")
    assert backup_ctx.startswith(
        "include => veyra-from-trunk\ninclude => veyra-from-trunk-backup-fallback"
    )
    assert "exten => +15735550101,1," in backup_ctx
    assert "exten => 5735550101,1,Goto(veyra-from-trunk-backup,+15735550101,1)" in backup_ctx
    assert "exten => 15735550100,1,NoOp" in backup_ctx
    assert "this route has no destination" in backup_ctx and "Congestion(5)" in backup_ctx
    carrier_ctx = _section(d, "veyra-from-trunk-carrier")
    assert "exten => +15735550101" not in carrier_ctx
    fallback = _section(d, "veyra-from-trunk-carrier-fallback")
    assert "Hangup(1)" in fallback and "exten => s,1," in fallback
    # trunk endpoints enter their own context
    assert "context=veyra-from-trunk-backup" in files["pjsip.trunks.conf"].content


def test_catch_all_route_per_trunk_and_shared():
    backup = _trunk("backup", auth_mode="ip", host="198.51.100.7", password=None, username=None)
    any_shared = {
        "did": "any",
        "trunk": None,
        "destination": "1001",
        "after_hours": None,
        "time_condition": None,
        "caller_id_prefix": None,
        "organization": "o",
    }
    any_backup = {**any_shared, "trunk": "backup", "caller_id_prefix": "Backup: "}
    files = _files(_snapshot(trunks=[_trunk(), backup], inbound_routes=[any_shared, any_backup]))
    d = files["extensions.conf"].content
    carrier_fb = _section(d, "veyra-from-trunk-carrier-fallback")
    backup_fb = _section(d, "veyra-from-trunk-backup-fallback")
    assert ": any)" in carrier_fb and "Goto(veyra-internal,1001,1)" in carrier_fb
    assert "Backup:" not in carrier_fb and "Backup: " in backup_fb
    assert "exten => s,1,NoOp" in backup_fb


def test_duplicate_dids_are_rejected():
    r = {
        "did": "5735550100",
        "trunk": None,
        "destination": "1001",
        "after_hours": None,
        "time_condition": None,
        "caller_id_prefix": None,
        "organization": "o",
    }
    with pytest.raises(generator.GenerationError, match="routed more than once"):
        generator.generate(_snapshot(inbound_routes=[r, {**r, "did": "+15735550100"}]))


def test_route_on_a_disabled_trunk_waits_without_failing():
    r = {
        "did": "5735550100",
        "trunk": "gone",
        "destination": "1001",
        "after_hours": None,
        "time_condition": None,
        "caller_id_prefix": None,
        "organization": "o",
    }
    files = _files(_snapshot(inbound_routes=[r]))
    assert "5735550100" not in files["extensions.conf"].content


# ----------------------------------------------------------------- routing helpers


def test_routing_helpers():
    assert routing.slugify("Carrier A (main)!") == "carrier-a-main"
    assert routing.canonical_did("+15735550100") == "5735550100"
    assert routing.canonical_did("15735550100") == "5735550100"
    assert routing.canonical_did("5735550100") == "5735550100"
    assert routing.canonical_did("+442071234567") == "+442071234567"
    assert routing.did_aliases("5735550100") == ["15735550100", "+15735550100"]
    assert routing.did_aliases("+15735550100") == ["5735550100", "15735550100"]
    assert routing.did_aliases("+442071234567") == []
    assert routing.exten_for("9", "NXXNXXXXXX") == "_9NXXNXXXXXX"
    assert routing.exten_for("", "911") == "911"
    assert routing.check_pattern("9", "nxx[2-9]xxxxxx", "") == ("9", "NXX[2-9]XXXXXX", "")
    assert routing.day_spans(["mon", "tue", "wed", "fri", "sun"]) == ["mon-wed", "fri", "sun"]
    with pytest.raises(ValueError):
        routing.normalize_did("1")
    assert routing.normalize_did("(573) 555-0100") == "5735550100"
    with pytest.raises(ValueError, match="end must be after"):
        routing.check_ranges([{"days": ["mon"], "start": "10:00", "end": "09:00"}])
    with pytest.raises(ValueError, match="unknown time zone"):
        routing.check_timezone("Mars/Olympus")


def test_is_open_respects_zone_ranges_and_holidays():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ranges = [{"days": ["mon", "tue", "wed", "thu", "fri"], "start": "08:00", "end": "16:00"}]
    tz = "America/Chicago"
    monday_morning = datetime(2026, 10, 12, 9, 0, tzinfo=ZoneInfo(tz))
    assert routing.is_open(ranges, [], tz, monday_morning)
    # 15:30 UTC is 10:30 in Chicago: open; 22:30 UTC is 17:30: closed
    assert routing.is_open(ranges, [], tz, datetime(2026, 10, 12, 15, 30, tzinfo=ZoneInfo("UTC")))
    assert not routing.is_open(
        ranges, [], tz, datetime(2026, 10, 12, 22, 30, tzinfo=ZoneInfo("UTC"))
    )
    assert not routing.is_open(ranges, [], tz, datetime(2026, 10, 11, 9, 0, tzinfo=ZoneInfo(tz)))
    assert not routing.is_open(ranges, ["10-12"], tz, monday_morning)
