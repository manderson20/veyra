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
        "organizations": [{"slug": "example", "name": "Example", "timezone": "UTC"}],
        "extensions": [
            {
                "endpoint_name": "example-1001",
                "number": "1001",
                "display_name": "Front Office",
                "organization": "example",
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
    assert "set_var=VEYRA_ORG=example" in files["pjsip.endpoints.conf"].content


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
    # Trunk default, unless the extension carries an outbound caller ID (§3.5).
    assert 'ExecIf($["${VEYRA_OUT_CID}"=""]?Set(CALLERID(num)=5735550100))' in local_ctx
    assert 'ExecIf($["${VEYRA_OUT_CID}"!=""]?Set(CALLERID(num)=${VEYRA_OUT_CID}))' in local_ctx
    assert "Dial(PJSIP/${VEYRA_DIAL}@trunk-carrier,60,${VEYRA_XFER_OUT})" in local_ctx
    assert "Dial(PJSIP/${VEYRA_DIAL}@trunk-backup,60,${VEYRA_XFER_OUT})" in local_ctx
    assert '"${DIALSTATUS}"="CHANUNAVAIL" | "${DIALSTATUS}"="CONGESTION"]?t2' in local_ctx
    assert "Playback(all-circuits-busy)" in local_ctx and "Hangup(21)" in local_ctx
    em = _section(d, "veyra-out-emergency")
    assert "exten => 911,1," in em and "Log(WARNING,Veyra EMERGENCY call" in em
    # The extension's emergency caller ID wins; the route override applies without one.
    assert 'ExecIf($["${VEYRA_EMERGENCY_CID}"!=""]?Set(CALLERID(num)=${VEYRA_EMERGENCY_CID}))' in em
    guard = '$["${VEYRA_EMERGENCY_CID}"="" & "${VEYRA_OUT_CID}"=""]'
    assert f"ExecIf({guard}?Set(CALLERID(num)=5735550199))" in em
    assert em.index('VEYRA_EMERGENCY_CID}"!=') < em.index("Dial(PJSIP/")
    assert "Dial(PJSIP/${VEYRA_DIAL}@trunk-carrier,120,${VEYRA_XFER_OUT})" in em
    assert "loop" not in em and "GROUP_COUNT" not in em


def test_outbound_caller_id_precedence_and_endpoint_variables():
    """docs/CALL_FEATURES.md §3.5: emergency → forced route → extension → route → trunk."""
    snap = _snapshot(
        outbound_routes=[
            _route("plain"),
            _route("routed", caller_id_number="5735550150"),
            _route("forced", caller_id_number="5735550160", caller_id_force=True),
            _route(
                "emergency",
                is_emergency=True,
                patterns=[{"prefix": "", "match": "911", "prepend": ""}],
                caller_id_number="5735550199",
                caller_id_force=True,
            ),
        ]
    )
    snap["extensions"][0]["outbound_caller_id_number"] = "5735550123"
    snap["extensions"][0]["outbound_caller_id_name"] = "Front Office"
    files = _files(snap)
    ep = files["pjsip.endpoints.conf"].content
    assert "set_var=VEYRA_OUT_CID=5735550123" in ep
    assert "set_var=VEYRA_OUT_CID_NAME=Front Office" in ep
    d = files["extensions.conf"].content
    plain = _section(d, "veyra-out-plain")
    # Extension first, then the trunk default; the name only with the extension's number.
    assert 'ExecIf($["${VEYRA_OUT_CID}"!=""]?Set(CALLERID(num)=${VEYRA_OUT_CID}))' in plain
    assert (
        'ExecIf($["${VEYRA_OUT_CID}"!="" & "${VEYRA_OUT_CID_NAME}"!=""]'
        "?Set(CALLERID(name)=${VEYRA_OUT_CID_NAME}))" in plain
    )
    assert 'ExecIf($["${VEYRA_OUT_CID}"=""]?Set(CALLERID(num)=5735550100))' in plain
    assert plain.index('VEYRA_OUT_CID}"!=') < plain.index("Dial(PJSIP/")
    routed = _section(d, "veyra-out-routed")
    assert 'ExecIf($["${VEYRA_OUT_CID}"=""]?Set(CALLERID(num)=5735550150))' in routed
    assert "5735550100" not in routed
    forced = _section(d, "veyra-out-forced")
    assert " same => n,Set(CALLERID(num)=5735550160)" in forced
    assert "VEYRA_OUT_CID" not in forced
    em = _section(d, "veyra-out-emergency")
    assert 'ExecIf($["${VEYRA_EMERGENCY_CID}"!=""]?Set(CALLERID(num)=${VEYRA_EMERGENCY_CID}))' in em
    assert 'ExecIf($["${VEYRA_EMERGENCY_CID}"=""]?Set(CALLERID(num)=5735550199))' in em
    assert "VEYRA_OUT_CID" not in em
    # No trunk default and no route number: the extension's number or nothing.
    snap = _snapshot(trunks=[_trunk(default_caller_id=None)], outbound_routes=[_route("bare")])
    bare = _section(_files(snap)["extensions.conf"].content, "veyra-out-bare")
    assert 'ExecIf($["${VEYRA_OUT_CID}"!=""]?Set(CALLERID(num)=${VEYRA_OUT_CID}))' in bare
    assert 'ExecIf($["${VEYRA_OUT_CID}"=""]' not in bare
    snap = _snapshot()
    snap["extensions"][0]["outbound_caller_id_number"] = "573-555"
    with pytest.raises(generator.GenerationError, match="outbound caller ID"):
        generator.generate(snap)


def test_extension_emergency_caller_id_is_an_endpoint_variable():
    snap = _snapshot()
    snap["extensions"][0]["emergency_caller_id_number"] = "5735550123"
    files = _files(snap)
    assert "set_var=VEYRA_EMERGENCY_CID=5735550123" in files["pjsip.endpoints.conf"].content
    assert "VEYRA_EMERGENCY_CID" not in _files(_snapshot())["pjsip.endpoints.conf"].content
    snap["extensions"][0]["emergency_caller_id_number"] = "573-555"
    with pytest.raises(generator.GenerationError, match="emergency caller ID"):
        generator.generate(snap)


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


def test_shared_extensions_get_more_contacts_and_the_notify_file_is_managed():
    snap = _snapshot()
    snap["extensions"][0]["max_contacts"] = 2
    files = _files(snap)
    ep = files["pjsip.endpoints.conf"].content
    assert "[example-1001](veyra-aor)\nmax_contacts=2\n" in ep
    plain = _files(_snapshot())["pjsip.endpoints.conf"].content
    assert "max_contacts" not in plain.split("[example-1001](veyra-aor)")[1]
    notify = files["pjsip_notify.conf"]
    assert not notify.sensitive and generator.FILE_NOTIFY in generator.MANAGED_FILES
    assert generator.RELOAD_SCOPES[generator.FILE_NOTIFY] == "res_pjsip_notify.so"
    assert "[veyra-check-config]\nEvent=>check-sync;reboot=false" in notify.content
    assert "[veyra-reboot]\nEvent=>check-sync;reboot=true" in notify.content
    snap["extensions"][0]["max_contacts"] = 99
    with pytest.raises(generator.GenerationError, match="max_contacts"):
        generator.generate(snap)


def test_holiday_forms_validate_match_and_generate():
    from datetime import date

    given = ["12-25", "12-21..01-02", "2026-11-27", "2026-12-21..2027-01-02", "4-THU-11"]
    given += ["last-mon-05", "2026-12-24..2026-12-24", "12-25"]
    hs = routing.check_holidays(given)
    assert hs == [
        "12-21..01-02",
        "12-25",
        "2026-11-27",
        "2026-12-21..2027-01-02",
        "2026-12-24",
        "4-thu-11",
        "last-mon-05",
    ]
    for bad in ["13-01", "02-30", "2026-02-29", "2027-01-02..2026-12-21", "last-mon-02"]:
        with pytest.raises(ValueError):
            routing.check_holidays([bad])
    for bad in ["5-mon-01", "xmas", "2026/12/25"]:
        with pytest.raises(ValueError):
            routing.check_holidays([bad])

    m = routing.holiday_matches
    assert m("4-thu-11", date(2026, 11, 26)) and not m("4-thu-11", date(2026, 11, 19))
    assert m("last-mon-05", date(2026, 5, 25)) and not m("last-mon-05", date(2026, 5, 18))
    assert m("1-mon-09", date(2026, 9, 7)) and not m("1-mon-09", date(2026, 9, 14))
    assert m("12-21..01-02", date(2027, 1, 1)) and m("12-21..01-02", date(2026, 12, 21))
    assert not m("12-21..01-02", date(2027, 1, 3))
    assert m("2026-11-27", date(2026, 11, 27)) and not m("2026-11-27", date(2027, 11, 27))
    assert m("2026-12-21..2027-01-02", date(2027, 1, 2))
    assert not m("2026-12-21..2027-01-02", date(2027, 12, 22))

    apps = routing.holiday_apps(["12-21..01-02", "03-30..04-02", "4-thu-11"], "UTC", "closed")
    assert apps == [
        "GotoIfTime(*,*,21-31,dec,UTC?closed)",
        "GotoIfTime(*,*,1-2,jan,UTC?closed)",
        "GotoIfTime(*,*,30-31,mar,UTC?closed)",
        "GotoIfTime(*,*,1-2,apr,UTC?closed)",
        "GotoIfTime(*,thu,22-28,nov,UTC?closed)",
    ]
    # A range across several whole months lists each month.
    assert routing.holiday_apps(["06-10..08-20"], "UTC", "x")[1] == "GotoIfTime(*,*,*,jul,UTC?x)"
    once = routing.holiday_apps(["2026-12-21..2027-01-02"], "America/Chicago", "closed")
    assert once == [
        "GotoIf($[${STRFTIME(${EPOCH},America/Chicago,%Y%m%d)} >= 20261221"
        " & ${STRFTIME(${EPOCH},America/Chicago,%Y%m%d)} <= 20270102]?closed)"
    ]


def test_holiday_sql_matches_python(app):
    from datetime import date, timedelta

    from sqlalchemy import DateTime, Integer, cast, func, literal, select

    from veyra.core.db import session_scope
    from veyra.reporting.builder import _holiday

    hs = ["12-25", "12-21..01-02", "03-30..04-02", "2026-11-27", "2026-12-21..2027-01-02"]
    hs += ["4-thu-11", "last-mon-05", "1-mon-09"]
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(0, 400, 3)]
    days += [date(2026, 11, 26), date(2026, 5, 25), date(2026, 9, 7), date(2027, 1, 2)]
    with session_scope() as db:
        for d in days:
            local = cast(literal(f"{d.isoformat()} 10:00:00"), DateTime)
            weekday = cast(func.extract("isodow", local), Integer)
            for h in hs:
                got = db.scalar(select(_holiday(h, local, weekday)))
                assert bool(got) == routing.holiday_matches(h, d), (h, d)
