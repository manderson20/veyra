# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call rules from the Metaswitch comparison (docs/research/pbx-comparison):
*67, *69, *70 and anonymous call rejection (#163), forward when the phone is
unreachable (#165), Do Not Disturb exceptions (#170) and the trunk channels
kept for emergency calls (#171)."""

from __future__ import annotations

import uuid

import pytest
from fake_adapter import FakeAdapter
from test_emergency import _site_and_ext
from test_features import _section
from test_features import _snapshot as _ext_snapshot
from test_generator_routing import _files, _route, _trunk
from test_generator_routing import _snapshot as _route_snapshot

from veyra.core.db import session_scope
from veyra.core.models import Site
from veyra.emergency import service
from veyra.telephony import extension_state, features
from veyra.telephony.asterisk import generator

CODES = {"cid_block": "*67", "call_return": "*69", "cw_off_once": "*70"}
CODES_ACR = {"acr_on": "*77", "acr_off": "*87"}


def _dialplan(**over):
    return {f.path: f.content for f in generator.generate(_ext_snapshot(**over))}["extensions.conf"]


# ------------------------------------------------------------------ feature codes


def test_new_codes_are_defaults_and_do_not_collide():
    assert {k: features.DEFAULT_CODES[k] for k in (*CODES, *CODES_ACR)} == {**CODES, **CODES_ACR}
    assert features.validate({}) == {}  # every default unique, none fixed


def test_call_codes_place_the_call_without_answering_first():
    d = _dialplan(feature_codes={**CODES, **CODES_ACR})
    feat = _section(d, "veyra-features")
    calls = _section(d, "veyra-call-codes")
    # Codes before a number live after paging and parking in the search order,
    # so an exact page number such as *700 is never taken by _*70.
    internal = _section(d, "veyra-internal")
    assert (
        internal.index("include => veyra-paging")
        < internal.index("include => veyra-call-codes")
        < internal.index("include => veyra-outbound")
    )
    assert "_*67." not in feat and "_*70." not in feat
    block = calls.split("exten => _*67.,1,")[1].split("exten => ")[0]
    assert "Set(CALLERID(pres)=prohib)" in block
    assert "Goto(veyra-internal,${EXTEN:3},1)" in block
    assert "Answer()" not in block.split("n(nophone)")[0]
    ret = calls.split("exten => *69,1,")[1].split("exten => ")[0]
    assert "Set(VEYRA_NUM=${DB(veyra/lastcid/${VEYRA_ORG}/${VEYRA_EXT})})" in ret
    assert "Playback(vm-nonumber)" in ret
    assert '${REGEX("^\\+?1[2-9][0-9]{9}$" ${VEYRA_NUM})}' in ret
    assert "Set(VEYRA_NUM=${VEYRA_NUM:-10})" in ret
    assert "Goto(veyra-internal,${VEYRA_NUM},1)" in ret
    cw = calls.split("exten => _*70.,1,")[1].split("exten => ")[0]
    assert "Set(DB(veyra/ext/${VEYRA_ORG}/${VEYRA_EXT}/nocw_call)=${UNIQUEID})" in cw
    assert (
        "Set(CHANNEL(hangup_handler_push)=veyra-cw-clear,s,1"
        "(${VEYRA_ORG},${VEYRA_EXT},${UNIQUEID}))" in cw
    )
    clear = _section(d, "veyra-cw-clear")
    assert '"${DB(veyra/ext/${ARG1}/${ARG2}/nocw_call)}"!="${ARG3}"]?done)' in clear
    assert "DB_DELETE(veyra/ext/${ARG1}/${ARG2}/nocw_call)" in clear
    # *77 / *87 switch the engine's copy and tell the API.
    assert (
        "exten => *77,1," in feat and "Set(DB(veyra/ext/${VEYRA_ORG}/${VEYRA_EXT}/acr)=1)" in feat
    )
    assert "Field: acr,Value: 1" in feat and "exten => *87,1," in feat
    # Codes off: nothing rendered, the context stays (empty).
    d = _dialplan(feature_codes={})
    assert "_*67." not in d and "exten => *69," not in d and "[veyra-call-codes]" in d


def test_extension_dialplan_applies_the_rules_in_order():
    internal = _section(_dialplan(), "veyra-internal")
    key = "veyra/ext/example/1001"
    order = [
        f'"${{DB({key}/acr)}}"="1" & "${{VEYRA_DID}}"!=""]?acr)',
        f'"${{DB({key}/dnd)}}"="1"]?dndallow)',
        f"n(ring),Set(VEYRA_CF=${{DB({key}/cf_always)}})",
        f"${{DB({key}/nocw)}}${{DB({key}/nocw_call)}}",
        "${DEVICE_STATE(PJSIP/example-1001)}",
        "Dial(PJSIP/example-1001,30,",
        '"${DIALSTATUS}"!="CHANUNAVAIL"]?noanswer)',
        f"Set(VEYRA_CF=${{DB({key}/cf_unavailable)}})",
        f"n(noanswer),Set(VEYRA_CF=${{DB({key}/cf_no_answer)}})",
    ]
    positions = [internal.index(s) for s in order]
    assert positions == sorted(positions)
    # Anonymous: the carrier's words for it, or a withheld presentation.
    assert '"${TOLOWER(${CALLERID(num)})}"="anonymous"' in internal
    assert '${REGEX("^prohib" ${CALLERID(pres)})}]?refuse)' in internal
    assert "Playback(privacy-unident)" in internal
    # DND exceptions: ten digits for a North American caller, "-<n>-" lookup.
    assert 'ExecIf($[${LEN(${VEYRA_DA})} = 11 & "${VEYRA_DA:0:1}"="1"]' in internal
    assert f'REGEX("-${{VEYRA_DA}}-" ${{DB({key}/dnd_allow)}})}}?ring:dnd)' in internal


def test_forward_lamp_includes_the_offline_forward():
    d = _dialplan(feature_codes={"cf_on": "*72", "cf_off": "*73"})
    assert "${DB(veyra/ext/${VEYRA_ORG}/${VEYRA_EXT}/cf_unavailable)}" in _section(
        d, "veyra-features"
    )


# ------------------------------------------------------------------ routes and trunks


def test_emergency_route_shows_the_number_and_trunk_keeps_a_channel():
    carrier = _trunk(max_channels=4, emergency_reserved_channels=1)
    local = _route()
    emergency = _route(
        "emergency", is_emergency=True, patterns=[{"prefix": "", "match": "911", "prepend": ""}]
    )
    files = _files(_route_snapshot(trunks=[carrier], outbound_routes=[local, emergency]))
    d = files["extensions.conf"].content
    assert "GotoIf($[${GROUP_COUNT(carrier@veyra_trunk)} > 3]?failed)" in _section(
        d, "veyra-out-local"
    )
    em = _section(d, "veyra-out-emergency")
    assert "Set(CALLERID(pres)=allowed_not_screened)" in em and "GROUP_COUNT" not in em
    assert "trust_id_outbound=yes" in files["pjsip.trunks.conf"].content
    # Reserve as large as the limit: no other call gets out on this trunk.
    files = _files(
        _route_snapshot(
            trunks=[_trunk(max_channels=2, emergency_reserved_channels=5)], outbound_routes=[local]
        )
    )
    assert "GROUP_COUNT(carrier@veyra_trunk)} > 0]" in files["extensions.conf"].content


def test_trunk_api_keeps_emergency_channels(admin):
    r = admin.post(
        "/api/v1/trunks",
        json={
            "name": "Carrier",
            "slug": "carrier",
            "auth_mode": "ip",
            "host": "198.51.100.7",
            "match_addresses": ["198.51.100.7"],
            "max_channels": 10,
        },
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["emergency_reserved_channels"] == 1
    r = admin.patch(f"/api/v1/trunks/{r.json()['id']}", json={"emergency_reserved_channels": 2})
    assert r.status_code == 200, r.text
    assert r.json()["emergency_reserved_channels"] == 2


def test_readiness_advises_on_the_emergency_channel(admin):
    _org_id, site, _ext = _site_and_ext(admin)
    with session_scope() as db:
        r = service.readiness(db, db.get(Site, uuid.UUID(site["id"])))
    reserve = {c["key"]: c for c in r["checks"]}["reserve"]
    assert reserve["advisory"] is True and reserve["ok"] is False
    # Advice never decides readiness.
    assert r["ready"] == all(c["ok"] for c in r["checks"] if not c["advisory"])


# ------------------------------------------------------------------ state and API


def test_dnd_allow_is_cleaned_and_matched_on_ten_digits():
    assert extension_state.dnd_key("+1 (573) 555-0100") == "5735550100"
    assert extension_state.dnd_key("1002") == "1002"
    assert extension_state.normalize_dnd_allow(["573-555-0100", "15735550100", " 1002 ", ""]) == [
        "5735550100",
        "1002",
    ]
    with pytest.raises(extension_state.StateError, match="at most"):
        extension_state.normalize_dnd_allow([str(1000 + i) for i in range(21)])
    with pytest.raises(extension_state.StateError):
        extension_state.normalize_dnd_allow(["12ab"])


def test_state_api_writes_the_new_rules_to_the_engine(admin, app):
    adapter = FakeAdapter()
    app.state.telephony = adapter
    org = admin.get("/api/v1/organizations").json()["items"][0]
    ext = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1001", "display_name": "Front"},
    ).json()
    url = f"/api/v1/extensions/{ext['id']}/state"
    r = admin.put(
        url,
        json={
            "cf_unavailable": "573 555 0100",
            "call_waiting_off": True,
            "anonymous_reject": True,
            "dnd_allow": ["+15735550111", "1002"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cf_unavailable"] == "5735550100" and body["call_waiting_off"] is True
    assert body["anonymous_reject"] is True and body["dnd_allow"] == ["+15735550111", "1002"]
    assert adapter.states[(org["slug"], "1001")] == {
        "cf_unavailable": "5735550100",
        "nocw": "1",
        "acr": "1",
        "dnd_allow": "-5735550111-1002-",
    }
    r = admin.put(url, json={"dnd_allow": [], "call_waiting_off": False})
    assert r.json()["dnd_allow"] == [] and r.json()["call_waiting_off"] is False
    assert "dnd_allow" not in adapter.states[(org["slug"], "1001")]
    r = admin.put(url, json={"dnd_allow": ["x1"]})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "dnd_allow"
    with session_scope() as db:
        # *77 / *87 from the phone; a phone never sends the exception list.
        base = {"Org": org["slug"], "Extension": "1001"}
        row = extension_state.handle_userevent(db, {**base, "Field": "acr", "Value": "0"})
        assert row is not None and row.anonymous_reject is False
        assert (
            extension_state.handle_userevent(db, {**base, "Field": "dnd_allow", "Value": "-1-"})
            is None
        )
        db.commit()
        # The worker's sync rewrites the engine from the rows.
        adapter.states.clear()
        assert extension_state.sync(db, adapter) == 1  # only the offline forward is left
    assert adapter.states[(org["slug"], "1001")]["cf_unavailable"] == "5735550100"


# ------------------------------------------------------------------ code sets (#164)


def test_every_code_set_is_valid_and_metaswitch_moves_the_collisions():
    for key in features.PRESETS:
        codes = features.preset_codes(key)
        assert set(codes) == set(features.BY_KEY)
        features.validate({k: {"code": v, "enabled": True} for k, v in codes.items()})
    ms = features.preset_codes("metaswitch")
    assert ms["cfu_on"] == "*92" and ms["cfu_off"] == "*93"
    assert ms["park_pickup"] != "*85" and ms["queue_count"] != "*47"
    assert features.preset_codes("veyra") == features.DEFAULT_CODES


def test_code_sets_api_and_saving_one(admin):
    r = admin.get("/api/v1/telephony/feature-codes/presets")
    assert r.status_code == 200, r.text
    sets = {p["key"]: p for p in r.json()}
    assert sets["metaswitch"]["notes"] and sets["veyra"]["codes"]["dnd_on"] == "*78"
    ms = sets["metaswitch"]["codes"]
    r = admin.put(
        "/api/v1/telephony/feature-codes",
        json={"codes": {k: {"code": v, "enabled": True} for k, v in ms.items()}},
    )
    assert r.status_code == 200, r.text
    by = {c["key"]: c["code"] for c in r.json()["codes"]}
    assert by["cfu_on"] == "*92" and by["park_pickup"] == "*88"


def test_organization_dnd_list_rings_through_every_phone(admin):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    r = admin.patch(
        f"/api/v1/organizations/{org['id']}",
        json={"dnd_allow": ["(573) 555-0199", "15735550199", "1000"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["dnd_allow"] == ["5735550199", "1000"]
    bad = admin.patch(f"/api/v1/organizations/{org['id']}", json={"dnd_allow": ["12ab"]})
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "dnd_allow"

    snap = _ext_snapshot()
    snap["extensions"][0]["dnd_allow_org"] = extension_state.dnd_list(["5735550199", "1000"])
    internal = _section(_files(snap)["extensions.conf"].content, "veyra-internal")
    org_line = 'GotoIf($["${VEYRA_DA}"!="" & ${REGEX("-${VEYRA_DA}-" -5735550199-1000-)}]?ring)'
    assert org_line in internal
    # Checked before the phone's own list.
    assert internal.index(org_line) < internal.index("n(dndlist)")
    snap["extensions"][0]["dnd_allow_org"] = "-1$(x)-"
    with pytest.raises(generator.GenerationError):
        _files(snap)
