# SPDX-License-Identifier: AGPL-3.0-or-later
"""Feature codes and Do Not Disturb (docs/CALL_FEATURES.md §3.1, §3.2): the
code table and its validation, the generated dialplan, the state API, the
phone's UserEvent and the worker's sync with the engine."""

from __future__ import annotations

import pytest
from fake_adapter import FakeAdapter
from fastapi.testclient import TestClient

from veyra.configmgmt import service as configmgmt
from veyra.core.db import session_scope
from veyra.core.models import Extension, ExtensionState, SystemSetting
from veyra.telephony import extension_state, features
from veyra.telephony.asterisk import events, generator
from veyra.telephony.settings import SipSettings

# ------------------------------------------------------------------ codes


def test_feature_code_validation():
    assert features.validate({}) == {}
    out = features.validate({"dnd_on": {"code": " *70 ", "enabled": True}})
    assert out == {"dnd_on": {"code": "*70", "enabled": True}}
    for bad in ({"nope": {"code": "*1"}}, {"dnd_on": "x"}, {"dnd_on": {"code": "70"}}):
        with pytest.raises(features.FeatureCodeError):
            features.validate(bad)
    with pytest.raises(features.FeatureCodeError, match="already used"):
        features.validate({"dnd_on": {"code": "*97"}})
    with pytest.raises(features.FeatureCodeError, match="already used"):
        features.validate({"dnd_on": {"code": "**1"}})
    with pytest.raises(features.FeatureCodeError, match="also used by"):
        features.validate({"dnd_on": {"code": "*79"}})
    # A disabled code frees its number.
    features.validate({"dnd_on": {"code": "*79"}, "dnd_off": {"code": "*79", "enabled": False}})


def test_feature_codes_load_save_and_active(admin):
    with session_scope() as db:
        codes = {c["key"]: c for c in features.load(db)}
        assert codes["dnd_toggle"]["code"] == "*76" and codes["dnd_toggle"]["enabled"]
        assert features.active(db)["cf_on"] == "*72"
        features.save(
            db, {"dnd_on": {"code": "*70"}, "intercom": {"code": "*80", "enabled": False}}, None
        )
        assert db.get(SystemSetting, features.SETTINGS_KEY).value == {
            "dnd_on": {"code": "*70", "enabled": True},
            "intercom": {"code": "*80", "enabled": False},
        }
        active = features.active(db)
        assert active["dnd_on"] == "*70" and "intercom" not in active
        # Back to the default: the override disappears.
        features.save(db, {"dnd_on": {"code": "*78"}}, None)
        assert "dnd_on" not in db.get(SystemSetting, features.SETTINGS_KEY).value


def test_feature_codes_api(admin, app):
    r = admin.get("/api/v1/telephony/feature-codes").json()
    assert {c["key"] for c in r["codes"]} >= {"dnd_on", "cf_on", "intercom"}
    assert r["fixed"]["*97"] == "own voicemail"
    r = admin.put("/api/v1/telephony/feature-codes", json={"codes": {"dnd_on": {"code": "*43"}}})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "dnd_on"
    r = admin.put(
        "/api/v1/telephony/feature-codes",
        json={"codes": {"dnd_on": {"code": "*70"}, "dnd_off": {"code": "*71", "enabled": True}}},
    )
    assert r.status_code == 200, r.text
    by = {c["key"]: c for c in r.json()["codes"]}
    assert by["dnd_on"]["code"] == "*70" and by["dnd_on"]["default_code"] == "*78"
    with session_scope() as db:
        assert (configmgmt.pending_change(db) or {}).get("what") == "feature codes"
    actions = [e["action"] for e in admin.get("/api/v1/audit").json()["items"]]
    assert "telephony.feature_codes_update" in actions


# ------------------------------------------------------------------ generator


def _snapshot(**over):
    snap = {
        "installation": {"name": "Test"},
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
        "feature_codes": {"dnd_on": "*78", "dnd_off": "*79", "dnd_toggle": "*76"},
    }
    snap.update(over)
    return snap


def _section(text: str, name: str) -> str:
    start = text.index(f"[{name}]")
    end = text.find("\n[", start + 1)
    return text[start : end if end > 0 else len(text)]


def test_generator_renders_dnd_codes_check_and_hint():
    files = {f.path: f.content for f in generator.generate(_snapshot())}
    ep = files["pjsip.endpoints.conf"]
    assert "set_var=VEYRA_EXT=1001" in ep and "set_var=VEYRA_ORG=example" in ep
    d = files["extensions.conf"]
    feat = _section(d, "veyra-features")
    assert "exten => *78,1,NoOp(Veyra DND on for ${VEYRA_EXT})" in feat
    assert "Set(DB(veyra/ext/${VEYRA_ORG}/${VEYRA_EXT}/dnd)=1)" in feat
    assert "Set(DEVICE_STATE(Custom:veyra-dnd-${VEYRA_ORG}-${VEYRA_EXT})=INUSE)" in feat
    assert (
        "UserEvent(VeyraExtState,Org: ${VEYRA_ORG},Extension: ${VEYRA_EXT},Field: dnd,Value: 1)"
        in feat
    )
    assert "Playback(do-not-disturb&activated)" in feat
    assert "exten => *79,1," in feat and "Playback(do-not-disturb&de-activated)" in feat
    assert (
        "exten => *76,1," in feat
        and 'GotoIf($["${DB(veyra/ext/${VEYRA_ORG}/${VEYRA_EXT}/dnd)}"="1"]?off)' in feat
    )
    assert "Playback(feature-not-avail-line)" in feat  # a caller without VEYRA_EXT
    internal = _section(d, "veyra-internal")
    assert "exten => *761001,hint,Custom:veyra-dnd-example-1001" in internal
    assert 'GotoIf($["${DB(veyra/ext/example/1001/dnd)}"="1"]?dnd)' in internal
    assert "n(dnd),NoOp(Veyra: 1001 has Do Not Disturb on)" in internal and "Busy(10)" in internal
    assert internal.index("?dnd)") < internal.index("Dial(PJSIP/example-1001")
    # Codes off: no feature code, no hint, the check stays (the API can still set DND).
    files = {f.path: f.content for f in generator.generate(_snapshot(feature_codes={}))}
    d = files["extensions.conf"]
    assert "*78" not in d and "hint,Custom:" not in d and "veyra/ext/example/1001/dnd" in d
    with pytest.raises(generator.GenerationError, match="not valid"):
        generator.generate(_snapshot(feature_codes={"dnd_on": "78"}))
    with pytest.raises(generator.GenerationError, match="used by"):
        generator.generate(_snapshot(feature_codes={"dnd_on": "*78", "dnd_off": "*78"}))


# ------------------------------------------------------------------ state


def test_state_api_writes_engine_and_lists_dnd(admin, app):
    adapter = FakeAdapter()
    app.state.telephony = adapter
    org = admin.get("/api/v1/organizations").json()["items"][0]
    ext = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1001", "display_name": "Front"},
    ).json()
    assert ext["dnd"] is False
    st = admin.get(f"/api/v1/extensions/{ext['id']}/state").json()
    assert st["dnd"] is False and st["ring_seconds"] == 30 and st["updated_at"] is None
    r = admin.put(f"/api/v1/extensions/{ext['id']}/state", json={"dnd": True})
    assert r.status_code == 200 and r.json()["dnd"] is True and r.json()["updated_by"] == "admin"
    assert adapter.state_calls == [(org["slug"], "1001", "dnd", "1")]
    assert admin.get(f"/api/v1/extensions/{ext['id']}").json()["dnd"] is True
    assert admin.get("/api/v1/extensions").json()["items"][0]["dnd"] is True
    # Unchanged values write nothing; Do Not Disturb needs no deployment, the ring time does.
    admin.put(f"/api/v1/extensions/{ext['id']}/state", json={"dnd": True})
    assert len(adapter.state_calls) == 1
    with session_scope() as db:
        configmgmt.clear_changed(db)
        db.commit()
    admin.put(f"/api/v1/extensions/{ext['id']}/state", json={"dnd": False})
    admin.put(f"/api/v1/extensions/{ext['id']}/state", json={"dnd": True})
    with session_scope() as db:
        assert configmgmt.pending_change(db) is None
    r = admin.put(f"/api/v1/extensions/{ext['id']}/state", json={"ring_seconds": 45})
    assert r.status_code == 200 and r.json()["ring_seconds"] == 45
    with session_scope() as db:
        assert (configmgmt.pending_change(db) or {}).get("what") == "extension.state_update 1001"
    assert (
        admin.put(f"/api/v1/extensions/{ext['id']}/state", json={"ring_seconds": 2}).status_code
        == 422
    )
    r = admin.put(f"/api/v1/extensions/{ext['id']}/state", json={"dnd": False})
    assert r.json()["dnd"] is False and adapter.state_calls[-1] == (
        org["slug"],
        "1001",
        "dnd",
        None,
    )
    actions = [e["action"] for e in admin.get("/api/v1/audit").json()["items"]]
    assert "extension.state_update" in actions


def test_phone_userevent_updates_the_row(admin, app):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    ext = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1001", "display_name": "Front"},
    ).json()
    event = {
        "type": "ChannelUserevent",
        "eventname": "VeyraExtState",
        "userevent": {"Org": org["slug"], "Extension": "1001", "Field": "dnd", "Value": "1"},
    }
    assert events.is_extstate_event(event) and not events.is_emergency_event(event)
    with session_scope() as db:
        row = extension_state.handle_userevent(db, event["userevent"])
        assert row is not None and row.dnd is True and row.updated_by == "phone"
        # Unknown extension or organization: ignored.
        assert (
            extension_state.handle_userevent(db, {**event["userevent"], "Extension": "9"}) is None
        )
        assert extension_state.handle_userevent(db, {**event["userevent"], "Org": "x"}) is None
        assert (
            extension_state.handle_userevent(db, {**event["userevent"], "Value": "0"}).dnd is False
        )
    assert admin.get(f"/api/v1/extensions/{ext['id']}/state").json()["updated_by"] == "phone"


def test_sync_makes_the_engine_follow_the_rows(admin, app):
    adapter = FakeAdapter()
    org = admin.get("/api/v1/organizations").json()["items"][0]
    a = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1001", "display_name": "A"},
    ).json()
    admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1002", "display_name": "B"},
    )
    with session_scope() as db:
        ext = db.get(Extension, a["id"])
        extension_state.apply(db, ext, {"dnd": True, "cf_busy": "1002"}, by="admin")  # no engine
        # The engine has a stale key for a phone that is not on DND, and one for a removed phone.
        adapter.states = {
            (org["slug"], "1002"): {"dnd": "1"},
            (org["slug"], "1999"): {"cf_always": "5"},
        }
        fixed = extension_state.sync(db, adapter)
        assert fixed == 4
        assert adapter.states == {(org["slug"], "1001"): {"dnd": "1", "cf_busy": "1002"}}
        assert extension_state.sync(db, adapter) == 0
        assert db.get(ExtensionState, ext.id).dnd is True


def test_extension_state_goes_with_the_extension(admin):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    ext = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1001", "display_name": "A"},
    ).json()
    admin.put(f"/api/v1/extensions/{ext['id']}/state", json={"dnd": True})
    assert admin.delete(f"/api/v1/extensions/{ext['id']}").status_code == 204
    with session_scope() as db:
        assert db.query(ExtensionState).count() == 0


def test_state_is_scoped(admin, app):
    from conftest import ADMIN_PASSWORD, login
    from test_api_rbac import make_org, make_user

    org = admin.get("/api/v1/organizations").json()["items"][0]
    ext = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1001", "display_name": "A"},
    ).json()
    other = make_org(admin, "other")
    make_user(admin, "orgadmin@other.local", other, "org_admin")
    oa = login(
        TestClient(app, base_url="http://veyra.test"), "orgadmin@other.local", ADMIN_PASSWORD
    )
    assert oa.get(f"/api/v1/extensions/{ext['id']}/state").status_code == 404
    assert oa.put(f"/api/v1/extensions/{ext['id']}/state", json={"dnd": True}).status_code == 404


# ------------------------------------------------------------------ forwarding (§3.3)


def test_generator_renders_forward_codes_and_dialplan():
    snap = _snapshot(
        feature_codes={"cf_on": "*72", "cf_off": "*73", "cfb_on": "*90", "cfu_off": "*53"}
    )
    snap["extensions"][0]["ring_seconds"] = 45
    snap["extensions"][0]["outbound_caller_id_number"] = "5735550123"
    files = {f.path: f.content for f in generator.generate(snap)}
    d = files["extensions.conf"]
    feat = _section(d, "veyra-features")
    key = "veyra/ext/${VEYRA_ORG}/${VEYRA_EXT}"
    # *72 alone asks for the number; _*72. takes it from the dialled digits.
    assert "exten => *72,1,NoOp(Veyra forward cf_always for ${VEYRA_EXT})" in feat
    assert "Read(VEYRA_NUM,call-fwd-unconditional&vm-enter-num-to-call,20,,2,10)" in feat
    assert "exten => _*72.,1," in feat and "Set(VEYRA_NUM=${EXTEN:3})" in feat
    assert 'GotoIf($[${REGEX("^\\+?[0-9]{2,20}$" ${VEYRA_NUM})}]?store:bad)' in feat
    assert f"n(store),Set(DB({key}/cf_always)=${{VEYRA_NUM}})" in feat
    assert "Playback(call-fwd-unconditional&activated)" in feat
    assert "n(bad),Playback(pbx-invalid)" in feat
    assert "Field: cf_always,Value: ${VEYRA_NUM}" in feat
    assert "exten => *73,1," in feat and f"DB_DELETE({key}/cf_always)" in feat
    assert "Field: cf_always,Value: )" in feat
    assert "Playback(call-fwd-unconditional&de-activated)" in feat
    assert "exten => *90,1," in feat and "exten => _*90.,1," in feat and "call-fwd-on-busy" in feat
    assert "exten => *53,1," in feat
    assert "exten => *52,1," not in feat and "exten => *91,1," not in feat
    # The forwarding lamp follows all three keys.
    lamp = f'DEVICE_STATE(Custom:veyra-cf-${{VEYRA_ORG}}-${{VEYRA_EXT}})=${{IF($["${{DB({key}'
    assert lamp + "/cf_always)}" in feat
    internal = _section(d, "veyra-internal")
    assert "exten => *721001,hint,Custom:veyra-cf-example-1001" in internal
    assert "Set(VEYRA_CF=${DB(veyra/ext/example/1001/cf_always)})" in internal
    assert "Dial(PJSIP/example-1001,45,${VEYRA_XFER})" in internal  # the state's ring time
    assert "Set(VEYRA_CF=${DB(veyra/ext/example/1001/cf_no_answer)})" in internal
    assert "n(busy),Set(VEYRA_CF=${DB(veyra/ext/example/1001/cf_busy)})" in internal
    assert "n(forward),NoOp(Veyra: 1001 forwards to ${VEYRA_CF})" in internal
    assert "GotoIf($[0${VEYRA_FWD} >= 3]?toomany)" in internal
    assert "Set(__VEYRA_HOPS=0)" in internal and "Set(__VEYRA_OUT_CID=5735550123)" in internal
    assert "Dial(Local/${VEYRA_CF}@veyra-internal/n,60)" in internal
    dial = internal.index("Dial(PJSIP/example-1001")
    assert (
        internal.index("/dnd)")
        < internal.index("cf_always")
        < dial
        < internal.index("cf_no_answer")
    )
    snap["extensions"][0]["ring_seconds"] = 3
    with pytest.raises(generator.GenerationError, match="ring time"):
        generator.generate(snap)


def test_forward_api_and_phone_event(admin, app):
    adapter = FakeAdapter()
    app.state.telephony = adapter
    org = admin.get("/api/v1/organizations").json()["items"][0]
    ext = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1001", "display_name": "Front"},
    ).json()
    url = f"/api/v1/extensions/{ext['id']}/state"
    r = admin.put(url, json={"cf_always": "573-555-0100", "cf_busy": "1002"})
    assert r.status_code == 200, r.text
    assert r.json()["cf_always"] == "5735550100" and r.json()["cf_busy"] == "1002"
    assert adapter.states[(org["slug"], "1001")] == {"cf_always": "5735550100", "cf_busy": "1002"}
    r = admin.put(url, json={"cf_no_answer": "1a"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "cf_no_answer"
    r = admin.put(url, json={"cf_always": ""})
    assert r.json()["cf_always"] is None
    assert adapter.state_calls[-1] == (org["slug"], "1001", "cf_always", None)
    # No deployment for forwards.
    with session_scope() as db:
        configmgmt.clear_changed(db)
        db.commit()
    admin.put(url, json={"cf_busy": "1003"})
    with session_scope() as db:
        assert configmgmt.pending_change(db) is None
        # The phone sets and clears a forward; a bad value is ignored.
        base = {"Org": org["slug"], "Extension": "1001", "Field": "cf_no_answer"}
        row = extension_state.handle_userevent(db, {**base, "Value": "15735550199"})
        assert row is not None and row.cf_no_answer == "15735550199"
        assert row.updated_by == "phone"
        row = extension_state.handle_userevent(db, {**base, "Value": ""})
        assert row is not None and row.cf_no_answer is None
        assert extension_state.handle_userevent(db, {**base, "Value": "x"}) is None
    st = admin.get(url).json()
    assert st["cf_busy"] == "1003" and st["cf_no_answer"] is None and st["updated_by"] == "phone"


# ------------------------------------------------------------------ find me / follow me (§3.4)


def test_generator_renders_follow_me():
    snap = _snapshot(feature_codes={"fmfm_toggle": "*21"})
    snap["extensions"].append(
        {
            "endpoint_name": "example-1002",
            "number": "1002",
            "display_name": "Back",
            "organization": "example",
            "secret": "s",
        }
    )
    snap["extensions"][0]["outbound_caller_id_number"] = "5735550123"
    snap["extensions"][0]["follow_me"] = {
        "strategy": "ringall",
        "initial_ring_seconds": 10,
        "confirm_calls": True,
        "caller_id_mode": "extension",
        "members": [
            {"type": "extension", "target": "1002", "endpoint": "example-1002", "ring_seconds": 20},
            {"type": "extension", "target": "1009", "endpoint": None, "ring_seconds": 20},
            {"type": "external", "target": "5735550100", "ring_seconds": 30},
        ],
        "no_answer_destination": "1002",
    }
    files = {f.path: f.content for f in generator.generate(snap)}
    d = files["extensions.conf"]
    feat = _section(d, "veyra-features")
    assert "exten => *21,1,NoOp(Veyra follow me toggle for ${VEYRA_EXT})" in feat
    assert "Set(DB(veyra/ext/${VEYRA_ORG}/${VEYRA_EXT}/fmfm)=1)" in feat
    assert "DEVICE_STATE(Custom:veyra-fm-${VEYRA_ORG}-${VEYRA_EXT})=INUSE" in feat
    assert "Field: fmfm,Value: 1" in feat and "Playback(followme/status&activated)" in feat
    internal = _section(d, "veyra-internal")
    assert "exten => *211001,hint,Custom:veyra-fm-example-1001" in internal
    assert "exten => *211002,hint" not in internal  # no follow-me configured
    assert 'GotoIf($["${DB(veyra/ext/example/1001/fmfm)}"="1"]?fm)' in internal
    assert (
        internal.index("cf_always")
        < internal.index('"1"]?fm)')
        < internal.index("Dial(PJSIP/example-1001,30,${VEYRA_XFER})")
    )
    assert "n(fm),NoOp(Veyra: 1001 follow me, ringall)" in internal
    assert "Dial(PJSIP/example-1001,10)" in internal  # desk first
    assert "Set(__VEYRA_FM_OPTS=U(veyra-fm-confirm^s))" in internal
    assert "Set(__VEYRA_OUT_CID=5735550123)" in internal
    assert "Dial(PJSIP/example-1002&Local/5735550100@veyra-fm-out/n,30)" in internal
    assert "example-1009" not in internal
    assert 'GotoIf($["${DIALSTATUS}"="ANSWER"]?fmdone)' in internal
    assert "Goto(veyra-internal,1002,1)" in internal and "n(fmdone),Hangup()" in internal
    assert "n(noanswer),Set(VEYRA_CF=" in internal
    out = _section(d, "veyra-fm-out")
    assert "Dial(Local/${EXTEN}@veyra-internal/n,60,${VEYRA_FM_OPTS})" in out
    assert "Set(__VEYRA_HOPS=0)" in out
    confirm = _section(d, "veyra-fm-confirm")
    assert "Read(VEYRA_OK,followme/options,1,,1,6)" in confirm
    assert "Set(GOSUB_RESULT=CONTINUE)" in confirm and "n(ok),Return()" in confirm
    # Sequential, caller's number, no destination: one Dial per leg and the own no-answer path.
    fm = snap["extensions"][0]["follow_me"]
    fm.update(
        strategy="sequential",
        caller_id_mode="caller",
        no_answer_destination=None,
        initial_ring_seconds=0,
        confirm_calls=False,
    )
    internal = _section(
        {f.path: f.content for f in generator.generate(snap)}["extensions.conf"], "veyra-internal"
    )
    assert (
        "Dial(PJSIP/example-1002,20)" in internal
        and "Dial(Local/5735550100@veyra-fm-out/n,30)" in internal
    )
    assert (
        "Set(__VEYRA_OUT_CID=${CALLERID(num)})" in internal and "Set(__VEYRA_FM_OPTS=)" in internal
    )
    assert "Goto(noanswer)" in internal and "Dial(PJSIP/example-1001,10)" not in internal
    # No usable members: no branch, no hint; bad values are refused.
    fm["members"] = [{"type": "extension", "target": "1009", "endpoint": None, "ring_seconds": 20}]
    internal = _section(
        {f.path: f.content for f in generator.generate(snap)}["extensions.conf"], "veyra-internal"
    )
    assert "?fm)" not in internal and "*211001" not in internal
    fm["members"] = [{"type": "external", "target": "55 1", "ring_seconds": 20}]
    with pytest.raises(generator.GenerationError, match="follow-me number"):
        generator.generate(snap)
    fm["members"] = [{"type": "external", "target": "5735550100", "ring_seconds": 2}]
    with pytest.raises(generator.GenerationError, match="ring time"):
        generator.generate(snap)


def test_follow_me_api_and_toggle(admin, app):
    adapter = FakeAdapter()
    app.state.telephony = adapter
    org = admin.get("/api/v1/organizations").json()["items"][0]
    a = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1001", "display_name": "A"},
    ).json()
    admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1002", "display_name": "B"},
    )
    url = f"/api/v1/extensions/{a['id']}/follow-me"
    assert admin.get(url).json() == {
        "enabled": False,
        "strategy": "ringall",
        "initial_ring_seconds": 0,
        "confirm_calls": False,
        "caller_id_mode": "caller",
        "members": [],
        "no_answer_destination": None,
        "updated_at": None,
        "updated_by": None,
    }
    body = {
        "strategy": "sequential",
        "initial_ring_seconds": 10,
        "confirm_calls": True,
        "caller_id_mode": "extension",
        "members": [
            {"type": "extension", "target": "1002", "ring_seconds": 15},
            {"type": "external", "target": "573-555-0100", "ring_seconds": 30},
        ],
        "no_answer_destination": "1002",
    }
    r = admin.put(url, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["members"][1]["target"] == "5735550100" and r.json()["enabled"] is False
    for bad, field in (
        ({"members": [{"type": "extension", "target": "1001"}]}, "members.1"),
        ({"members": [{"type": "extension", "target": "1999"}]}, "members.1"),
        ({"members": [{"type": "external", "target": "x"}]}, "members.1"),
        (
            {
                "members": [
                    {"type": "external", "target": "55"},
                    {"type": "external", "target": "55"},
                ]
            },
            "members.2",
        ),
        ({"no_answer_destination": "1001"}, "no_answer_destination"),
        ({"no_answer_destination": "1999"}, "no_answer_destination"),
    ):
        r = admin.put(url, json={**body, **bad})
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == field, r.text
    with session_scope() as db:
        assert (configmgmt.pending_change(db) or {}).get(
            "what"
        ) == "extension.follow_me_update 1001"
        from veyra.core.security.crypto import load_installation_key
        from veyra.telephony.snapshot import build_snapshot

        snap = build_snapshot(db, load_installation_key(app.state.settings))
    fm = next(e for e in snap["extensions"] if e["number"] == "1001")["follow_me"]
    assert (
        fm["members"][0]["endpoint"] == "example-1002"
        and fm["members"][1]["target"] == "5735550100"
    )
    assert fm["strategy"] == "sequential" and fm["no_answer_destination"] == "1002"
    # On and off through the state, at once.
    r = admin.put(f"/api/v1/extensions/{a['id']}/state", json={"fmfm_enabled": True})
    assert r.status_code == 200 and r.json()["fmfm_enabled"] is True
    assert adapter.state_calls[-1] == (org["slug"], "1001", "fmfm", "1")
    assert admin.get(url).json()["enabled"] is True
    with session_scope() as db:
        row = extension_state.handle_userevent(
            db, {"Org": org["slug"], "Extension": "1001", "Field": "fmfm", "Value": "0"}
        )
        assert row is not None and row.fmfm_enabled is False
    assert admin.get(url).json()["enabled"] is False
    # Removing the extension removes the follow-me.
    assert admin.delete(f"/api/v1/extensions/{a['id']}").status_code == 204
    with session_scope() as db:
        from veyra.core.models import FollowMe

        assert db.query(FollowMe).count() == 0


# ------------------------------------------------------------------ intercom (§3.6)


def test_generator_renders_intercom():
    snap = _snapshot(feature_codes={"intercom": "*80"})
    snap["extensions"][0]["intercom"] = "allow"
    snap["extensions"].append(
        {
            "endpoint_name": "example-1002",
            "number": "1002",
            "display_name": "Quiet",
            "organization": "example",
            "secret": "s",
            "intercom": "deny",
        }
    )
    d = {f.path: f.content for f in generator.generate(snap)}["extensions.conf"]
    feat = _section(d, "veyra-features")
    assert "exten => _*80.,1,NoOp(Veyra intercom from ${VEYRA_EXT} to ${EXTEN:3})" in feat
    assert "Goto(veyra-intercom,${EXTEN:3},1)" in feat
    ic = _section(d, "veyra-intercom")
    assert "exten => 1001,1,NoOp(Veyra intercom to 1001)" in ic
    assert 'GotoIf($["${DB(veyra/ext/example/1001/dnd)}"="1"]?dnd)' in ic
    assert "Dial(PJSIP/example-1001,20,b(veyra-intercom-hdr^s^1))" in ic
    assert "exten => 1002,1,NoOp(Veyra: intercom to 1002 is not allowed)" in ic
    assert "Dial(PJSIP/example-1002" not in ic
    assert "exten => _X.,1,Answer()" in ic and "Playback(pbx-invalid)" in ic
    hdr = _section(d, "veyra-intercom-hdr")
    assert "Set(PJSIP_HEADER(add,Alert-Info)=<http://www.notuse.com>;info=alert-autoanswer)" in hdr
    assert "Set(PJSIP_HEADER(add,Call-Info)=<sip:veyra>;answer-after=0)" in hdr
    # Without the code there is no intercom context at all.
    d = {f.path: f.content for f in generator.generate(_snapshot(feature_codes={}))}[
        "extensions.conf"
    ]
    assert "[veyra-intercom]" not in d and "veyra-intercom-hdr" not in d


def test_intercom_setting_api_and_snapshot(admin, app):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    ext = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1001", "display_name": "A"},
    ).json()
    assert ext["intercom"] == "default"
    r = admin.patch(f"/api/v1/extensions/{ext['id']}", json={"intercom": "maybe"})
    assert r.status_code == 422
    deny = admin.post(
        "/api/v1/extensions",
        json={
            "organization_id": org["id"],
            "number": "1002",
            "display_name": "B",
            "intercom": "deny",
        },
    ).json()
    assert deny["intercom"] == "deny"
    from veyra.core.security.crypto import load_installation_key
    from veyra.telephony.snapshot import build_snapshot

    with session_scope() as db:
        by = {
            e["number"]: e["intercom"]
            for e in build_snapshot(db, load_installation_key(app.state.settings))["extensions"]
        }
    assert by == {"1001": "allow", "1002": "deny"}  # the organization's default is allow
    r = admin.patch(f"/api/v1/organizations/{org['id']}", json={"intercom_default": "deny"})
    assert r.status_code == 200 and r.json()["intercom_default"] == "deny"
    with session_scope() as db:
        assert (configmgmt.pending_change(db) or {}).get("what", "").startswith("intercom default")
        by = {
            e["number"]: e["intercom"]
            for e in build_snapshot(db, load_installation_key(app.state.settings))["extensions"]
        }
    assert by == {"1001": "deny", "1002": "deny"}
    assert (
        admin.patch(
            f"/api/v1/organizations/{org['id']}", json={"intercom_default": "x"}
        ).status_code
        == 422
    )


# ------------------------------------------------------------------ voicemail (§3.7)


def test_generator_direct_voicemail_and_operator():
    from veyra.telephony.asterisk.generator import generate

    snap = _snapshot(feature_codes={"vm_direct": "*", "cf_on": "*72"})
    snap["extensions"].append(
        {
            "endpoint_name": "example-1002",
            "number": "1002",
            "display_name": "Back",
            "organization": "example",
            "secret": "s",
        }
    )
    box = {
        "number": "1001",
        "name": "Front",
        "organization": "example",
        "timezone": "UTC",
        "pin": "1234",
        "email": None,
        "attach_audio": True,
        "delete_after_email": False,
        "ring_seconds": 20,
        "operator_extension": "1002",
    }
    snap["voicemail_boxes"] = [box, {**box, "number": "1002", "operator_extension": None}]
    files = {f.path: f.content for f in generate(snap)}
    d = files["extensions.conf"]
    feat = _section(d, "veyra-features")
    assert "exten => *1001,1,NoOp(Veyra direct to voicemail 1001)" in feat
    # The unavailable greeting plays (u); VoiceMail plays no greeting without it.
    assert "VoiceMail(1001@veyra,u)" in feat and "exten => *1002,1," in feat
    vmx = _section(d, "veyra-vmx-1001")
    assert "exten => o,1,NoOp(Veyra: voicemail 1001 operator)" in vmx
    assert "Goto(veyra-internal,1002,1)" in vmx and "exten => a,1,VoiceMailMain(1001@veyra)" in vmx
    assert "[veyra-vmx-1002]" not in d
    vm = files["voicemail.conf"]
    assert (
        "1001 => 1234,Front,,,attach=yes|delete=no|tz=example|saycid=yes|envelope=yes"
        "|operator=yes|exitcontext=veyra-vmx-1001" in vm
    )
    assert "1002 => 1234,Front,,,attach=yes|delete=no|tz=example|saycid=yes|envelope=yes\n" in vm
    # The code off: no direct entries; a bad operator is refused.
    d = {f.path: f.content for f in generate({**snap, "feature_codes": {}})}["extensions.conf"]
    assert "direct to voicemail" not in d
    snap["voicemail_boxes"][0]["operator_extension"] = "1a"
    with pytest.raises(generator.GenerationError, match="operator"):
        generate(snap)


def test_voicemail_operator_api(admin):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    a = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1001", "display_name": "A"},
    ).json()
    admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1002", "display_name": "B"},
    )
    r = admin.post(
        "/api/v1/voicemail", json={"extension_id": a["id"], "operator_extension": "1999"}
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "operator_extension"
    r = admin.post(
        "/api/v1/voicemail", json={"extension_id": a["id"], "operator_extension": " 1002 "}
    )
    assert r.status_code == 201, r.text
    box = r.json()
    assert box["operator_extension"] == "1002"
    r = admin.patch(f"/api/v1/voicemail/{box['id']}", json={"operator_extension": ""})
    assert r.status_code == 200 and r.json()["operator_extension"] is None
    codes = {c["key"]: c for c in admin.get("/api/v1/telephony/feature-codes").json()["codes"]}
    assert codes["vm_direct"]["code"] == "*" and codes["vm_direct"]["takes_number"] is True


# ------------------------------------------------------------------ class of service (§3.8)


def test_generator_class_of_service_guards():
    from test_generator_routing import _route, _trunk

    snap = _snapshot(
        feature_codes={"dnd_on": "*78", "cf_on": "*72", "intercom": "*80", "vm_direct": "*"},
        trunks=[_trunk()],
        outbound_routes=[
            _route("local"),
            _route("long", patterns=[{"prefix": "9", "match": "1NXXNXXXXXX", "prepend": ""}]),
            _route(
                "emergency",
                is_emergency=True,
                patterns=[{"prefix": "", "match": "911", "prepend": ""}],
            ),
        ],
        numbering={"extension_length": 4},
        classes_of_service={},
    )
    snap["classes_of_service"] = [
        {
            "slug": "classroom",
            "name": "Classroom",
            "organization": "example",
            "allowed_routes": ["local"],
            "allowed_feature_codes": ["dnd_on"],
            "allow_external_forwards": False,
            "allow_external_follow_me": False,
            "allow_intercom": False,
            "max_outbound_calls": 2,
        },
        {
            "slug": "office",
            "name": "Office",
            "organization": "example",
            "allowed_routes": ["local", "long"],
            "allowed_feature_codes": None,
            "allow_external_forwards": True,
            "allow_external_follow_me": True,
            "allow_intercom": True,
            "max_outbound_calls": None,
        },
    ]
    snap["extensions"][0]["class_of_service"] = "classroom"
    snap["extensions"][0]["follow_me"] = {
        "strategy": "ringall",
        "members": [
            {"type": "external", "target": "5735550100", "ring_seconds": 20},
            {"type": "extension", "target": "1002", "endpoint": "example-1002", "ring_seconds": 20},
        ],
    }
    snap["voicemail_boxes"] = [
        {
            "number": "1001",
            "name": "A",
            "organization": "example",
            "timezone": "UTC",
            "pin": "1234",
            "email": None,
            "attach_audio": True,
            "delete_after_email": False,
            "ring_seconds": 20,
        }
    ]
    files = {f.path: f.content for f in generator.generate(snap)}
    assert "set_var=VEYRA_COS=classroom" in files["pjsip.endpoints.conf"]
    d = files["extensions.conf"]
    # Routes: "long" is denied to the classroom class, "local" to nobody; emergency never.
    long_ctx = _section(d, "veyra-out-long")
    assert 'GotoIf($[${REGEX("^(classroom)$" ${VEYRA_COS})}]?cosdenied)' in long_ctx
    assert "n(cosdenied),NoOp(Veyra: not allowed by the class of service)" in long_ctx
    local_ctx = _section(d, "veyra-out-local")
    assert "cosdenied" not in local_ctx
    # The call limit of the classroom class applies on every non-emergency route.
    assert "Set(GROUP(veyra_cos)=${VEYRA_COS})" in local_ctx
    assert (
        'GotoIf($["${VEYRA_COS}"="classroom" & ${GROUP_COUNT(classroom@veyra_cos)} > 2]?cosbusy)'
        in local_ctx
    )
    assert "n(cosbusy),NoOp(Veyra: the class of service has too many outside calls up)" in local_ctx
    em = _section(d, "veyra-out-emergency")
    assert "cos" not in em.lower().replace("noop(veyra emergency", "")
    # Feature codes: the classroom class may use dnd_on only.
    feat = _section(d, "veyra-features")
    dnd_block = feat[feat.index("exten => *78,1,") : feat.index("exten => *72,1,")]
    assert "cosdenied" not in dnd_block
    cf_block = feat[feat.index("exten => *72,1,") : feat.index("exten => _*72.,1,")]
    assert 'GotoIf($[${REGEX("^(classroom)$" ${VEYRA_COS})}]?cosdenied)' in cf_block
    assert (
        cf_block.index("?nophone)")
        < cf_block.index("?cosdenied)")
        < cf_block.index("Read(VEYRA_NUM")
    )
    ic_block = feat[feat.index("exten => _*80.,1,") : feat.index("exten => *1001,1,")]
    assert ic_block.count('GotoIf($[${REGEX("^(classroom)$" ${VEYRA_COS})}]?cosdenied)') == 2
    vm_block = feat[feat.index("exten => *1001,1,") :]
    assert 'GotoIf($[${REGEX("^(classroom)$" ${VEYRA_COS})}]?cosdenied)' in vm_block.split("\n")[1]
    # Forwards outside (longer than an extension) are denied to the classroom class.
    internal = _section(d, "veyra-internal")
    assert (
        'GotoIf($[${REGEX("^(classroom)$" ${VEYRA_COS})} & ${LEN(${VEYRA_CF})} > 4]?cosdenied)'
        in internal
    )
    # Follow-me of a classroom phone rings only the extension member.
    assert (
        "Dial(PJSIP/example-1002,20)" in internal
        and "veyra-fm-out" not in internal.split("n(fm)")[1].split("n(fmdone)")[0]
    )
    # In-call codes (issue #135): the classroom class may not transfer, so
    # its phone loses Dial T when calling and t when called.
    assert (
        'ExecIf(${REGEX("^(classroom)$" ${VEYRA_COS})}?Set(VEYRA_XFER=${REPLACE(VEYRA_XFER,T)}))'
        in internal
    )
    assert "Dial(PJSIP/example-1001,20,${REPLACE(VEYRA_XFER,t)})" in internal
    # The office class and a phone without a class are never denied.
    snap["extensions"][0]["class_of_service"] = None
    d2 = {f.path: f.content for f in generator.generate(snap)}["extensions.conf"]
    assert "Local/5735550100@veyra-fm-out/n" in d2
    # No classes at all: no guards anywhere.
    snap["classes_of_service"] = []
    d3 = {f.path: f.content for f in generator.generate(snap)}["extensions.conf"]
    assert "cosdenied" not in d3 and "veyra_cos" not in d3


def test_class_of_service_api(admin, app):
    from fastapi.testclient import TestClient

    org = admin.get("/api/v1/organizations").json()["items"][0]
    trunk = admin.post(
        "/api/v1/trunks",
        json={
            "name": "Carrier",
            "auth_mode": "registration",
            "host": "sip.carrier.example",
            "username": "acct1",
            "password": "Secr3t-pass",
        },
    ).json()
    route = admin.post(
        "/api/v1/routing/outbound",
        json={
            "name": "Local",
            "patterns": [{"prefix": "9", "match": "NXXNXXXXXX", "prepend": "1"}],
            "trunk_ids": [trunk["id"]],
        },
    ).json()
    emergency = admin.post(
        "/api/v1/routing/outbound",
        json={
            "name": "Emergency",
            "is_emergency": True,
            "patterns": [{"prefix": "", "match": "911", "prepend": ""}],
            "trunk_ids": [trunk["id"]],
        },
    ).json()
    r = admin.post(
        "/api/v1/classes-of-service",
        json={
            "organization_id": org["id"],
            "name": "Classroom",
            "allowed_outbound_route_ids": [route["id"], emergency["id"]],
            "allowed_feature_code_keys": ["dnd_on", "dnd_off"],
            "allow_external_forwards": False,
            "max_outbound_calls": 3,
        },
    )
    assert r.status_code == 201, r.text
    cls = r.json()
    assert cls["slug"] == "classroom" and [x["name"] for x in cls["allowed_outbound_routes"]] == [
        "Local"
    ]
    assert cls["allowed_feature_code_keys"] == ["dnd_on", "dnd_off"] and cls["extensions"] == 0
    r = admin.post(
        "/api/v1/classes-of-service",
        json={"organization_id": org["id"], "name": "Bad", "allowed_feature_code_keys": ["nope"]},
    )
    assert r.status_code == 422
    r = admin.post(
        "/api/v1/classes-of-service", json={"organization_id": org["id"], "name": "Classroom"}
    )
    assert r.status_code == 409
    # An extension joins the class; a class of another organization is refused.
    r = admin.post(
        "/api/v1/extensions",
        json={
            "organization_id": org["id"],
            "number": "1001",
            "display_name": "A",
            "class_of_service_id": cls["id"],
        },
    )
    assert r.status_code == 201, r.text
    ext = r.json()
    assert ext["class_of_service_id"] == cls["id"] and ext["class_of_service_name"] == "Classroom"
    assert admin.get(f"/api/v1/classes-of-service/{cls['id']}").json()["extensions"] == 1
    from test_api_rbac import make_org

    other = make_org(admin, "other")
    r = admin.post(
        "/api/v1/classes-of-service",
        json={"organization_id": other, "name": "Elsewhere"},
    ).json()
    r2 = admin.patch(f"/api/v1/extensions/{ext['id']}", json={"class_of_service_id": r["id"]})
    assert r2.status_code == 422 and r2.json()["errors"][0]["field"] == "class_of_service_id"
    # Patch: back to every feature code, no limit; snapshot carries the class.
    r = admin.patch(
        f"/api/v1/classes-of-service/{cls['id']}",
        json={"all_feature_codes": True, "no_call_limit": True},
    )
    assert r.status_code == 200 and r.json()["allowed_feature_code_keys"] is None
    assert r.json()["max_outbound_calls"] is None
    from veyra.core.security.crypto import load_installation_key
    from veyra.telephony.snapshot import build_snapshot

    with session_scope() as db:
        snap = build_snapshot(db, load_installation_key(app.state.settings))
        assert (configmgmt.pending_change(db) or {}).get("what") == "class of service classroom"
    assert snap["numbering"]["extension_length"] == 4
    assert snap["classes_of_service"][0]["allowed_routes"] == ["local"]
    assert snap["extensions"][0]["class_of_service"] == "classroom"
    # In use: cannot delete; moved out: can.
    assert admin.delete(f"/api/v1/classes-of-service/{cls['id']}").status_code == 409
    admin.patch(f"/api/v1/extensions/{ext['id']}", json={"class_of_service_id": None})
    assert admin.delete(f"/api/v1/classes-of-service/{cls['id']}").status_code == 204
    assert TestClient(app).get("/api/v1/classes-of-service").status_code in (401, 403)


# ------------------------------------------------------------- ring group outside members (§3.4)


def test_ring_group_outside_members_generate_local_legs():
    from test_generator_groups import _group
    from test_generator_groups import _snapshot as _group_snapshot

    snap = _group_snapshot(
        ring_groups=[
            _group(
                "front",
                strategy="ringall",
                external_members=["5735550100", "15735550101"],
                confirm_external=True,
            ),
            _group("seq", number="2301", strategy="sequential", external_members=["5735550102"]),
            _group("only", number="2302", members=[], external_members=["5735550103"]),
        ]
    )
    d = {f.path: f.content for f in generator.generate(snap)}["extensions.conf"]
    front = _section(d, "veyra-rg-front")
    assert "Set(__VEYRA_FM_OPTS=U(veyra-fm-confirm^s))" in front and "Set(__VEYRA_HOPS=0)" in front
    assert "Set(VEYRA_DIAL=${VEYRA_DIAL}&Local/5735550100@veyra-fm-out/n)" in front
    assert "Set(VEYRA_DIAL=${VEYRA_DIAL}&Local/15735550101@veyra-fm-out/n)" in front
    seq = _section(d, "veyra-rg-seq")
    assert (
        "Set(__VEYRA_FM_OPTS=)" in seq
        and "Dial(Local/5735550102@veyra-fm-out/n,20,${VEYRA_XFER}U(veyra-lastcid))" in seq
    )
    only = _section(d, "veyra-rg-only")
    assert "Goto(failover)" in only and "Local/5735550103@veyra-fm-out/n" in only
    assert only.index("Local/5735550103") < only.index("n(failover)")
    snap["ring_groups"][0]["external_members"] = ["55 1"]
    with pytest.raises(generator.GenerationError, match="outside number"):
        generator.generate(snap)


def test_ring_group_outside_members_api(admin):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    r = admin.post(
        "/api/v1/ring-groups",
        json={
            "organization_id": org["id"],
            "name": "Front",
            "number": "2300",
            "external_members": ["573-555-0100", "5735550100", " "],
            "confirm_external": True,
        },
    )
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["external_members"] == ["5735550100"] and g["confirm_external"] is True
    r = admin.patch(f"/api/v1/ring-groups/{g['id']}", json={"external_members": ["x"]})
    assert r.status_code == 422
    r = admin.patch(
        f"/api/v1/ring-groups/{g['id']}", json={"external_members": [], "confirm_external": False}
    )
    assert (
        r.status_code == 200
        and r.json()["external_members"] == []
        and r.json()["confirm_external"] is False
    )


# ------------------------------------------------------------------ my phone (own extension)


def test_user_manages_own_phone(admin, app):
    from conftest import ADMIN_PASSWORD, login
    from fastapi.testclient import TestClient
    from test_api_rbac import make_user

    adapter = FakeAdapter()
    app.state.telephony = adapter
    org = admin.get("/api/v1/organizations").json()["items"][0]
    uid = make_user(admin, "teacher@example.local", org["id"], "standard_user")
    mine = admin.post(
        "/api/v1/extensions",
        json={
            "organization_id": org["id"],
            "number": "1001",
            "display_name": "Mine",
            "user_id": uid,
        },
    ).json()
    other = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1002", "display_name": "Other"},
    ).json()
    me = login(
        TestClient(app, base_url="http://veyra.test"), "teacher@example.local", ADMIN_PASSWORD
    )
    assert [e["number"] for e in me.get("/api/v1/me/extensions").json()] == ["1001"]
    # The administrator's endpoints stay closed to a standard user; the own ones open.
    assert me.get(f"/api/v1/extensions/{mine['id']}/state").status_code == 403
    assert me.get(f"/api/v1/me/extensions/{other['id']}/state").status_code == 404
    r = me.put(f"/api/v1/me/extensions/{mine['id']}/state", json={"dnd": True, "cf_busy": "1002"})
    assert r.status_code == 200, r.text
    assert (
        r.json()["dnd"] is True
        and r.json()["cf_busy"] == "1002"
        and r.json()["updated_by"] == "user"
    )
    assert adapter.states[(org["slug"], "1001")] == {"dnd": "1", "cf_busy": "1002"}
    # The ring time is not the user's to change.
    r = me.put(f"/api/v1/me/extensions/{mine['id']}/state", json={"ring_seconds": 45})
    assert r.status_code == 200 and r.json()["ring_seconds"] == 30
    assert (
        me.put(f"/api/v1/me/extensions/{mine['id']}/state", json={"cf_always": "x"}).status_code
        == 422
    )
    # Follow-me legs and the switch.
    r = me.put(
        f"/api/v1/me/extensions/{mine['id']}/follow-me",
        json={"strategy": "ringall", "members": [{"type": "extension", "target": "1002"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["members"][0]["target"] == "1002"
    r = me.put(f"/api/v1/me/extensions/{mine['id']}/state", json={"fmfm_enabled": True})
    assert r.json()["fmfm_enabled"] is True
    assert me.get(f"/api/v1/me/extensions/{mine['id']}/follow-me").json()["enabled"] is True
    assert (
        me.put(f"/api/v1/me/extensions/{other['id']}/follow-me", json={"members": []}).status_code
        == 404
    )
    codes = me.get("/api/v1/me/feature-codes").json()
    assert {c["key"] for c in codes["codes"]} >= {"dnd_toggle", "cf_on"} and "*97" in codes["fixed"]
    # Administrators see the user's change and the pending deployment for the legs.
    assert admin.get(f"/api/v1/extensions/{mine['id']}/state").json()["updated_by"] == "user"
    with session_scope() as db:
        assert (configmgmt.pending_change(db) or {}).get("what") == "follow-me of 1001"
    actions = [
        (e["action"], (e.get("details") or {}).get("self_service"))
        for e in admin.get("/api/v1/audit", params={"limit": 20}).json()["items"]
    ]
    assert ("extension.state_update", True) in actions and (
        "extension.follow_me_update",
        True,
    ) in actions


def test_generator_voicemail_locater():
    """Keys 1 and 2 during the greeting (#131): VoiceMail takes d(<exit
    context>) and the exit context has the targets."""
    from test_generator_routing import _section, _snapshot

    from veyra.telephony.asterisk.generator import generate

    snap = _snapshot(feature_codes={"vm_direct": "*"})
    box = {
        "number": "1001",
        "name": "Front",
        "organization": "example",
        "timezone": "UTC",
        "pin": "1234",
        "email": None,
        "attach_audio": True,
        "delete_after_email": False,
        "ring_seconds": 20,
        "operator_extension": None,
        "locater_1": "followme",
        "locater_2": "7000",
        "follow_me": True,
    }
    snap["voicemail_boxes"] = [box]
    files = {f.path: f.content for f in generate(snap)}
    d = files["extensions.conf"]
    vmx = _section(d, "veyra-vmx-1001")
    assert "exten => 1,1,NoOp(Veyra: voicemail 1001 locater 1)" in vmx
    assert "Goto(veyra-internal,1001,fm)" in vmx and "Goto(veyra-internal,7000,1)" in vmx
    assert "exten => o," not in vmx  # no operator set
    assert "VoiceMail(1001@veyra,ud(veyra-vmx-1001))" in d
    assert "VoiceMail(1001@veyra,bd(veyra-vmx-1001))" in d
    assert "|operator=no|exitcontext=veyra-vmx-1001" in files["voicemail.conf"]
    # Follow me gone: key 1 is dropped, key 2 stays.
    box["follow_me"] = False
    d = {f.path: f.content for f in generate(snap)}["extensions.conf"]
    assert "locater 1" not in d and "locater 2" in d
    # No locater and no operator: plain VoiceMail, no exit context.
    box.update(locater_1=None, locater_2=None)
    d = {f.path: f.content for f in generate(snap)}["extensions.conf"]
    assert "[veyra-vmx-1001]" not in d and "VoiceMail(1001@veyra,u)" in d
    box["locater_2"] = "70a"
    with pytest.raises(generator.GenerationError, match="locater"):
        generate(snap)


def test_presence_hint_and_lamp(admin, app):
    """Presence keys (#132): one hint per extension, and the lamp follows."""
    from test_generator_routing import _snapshot

    from veyra.telephony.asterisk.generator import generate
    from veyra.telephony.extension_state import PRESENCE_LAMP

    snap = _snapshot(feature_codes={"presence_watch": "*36"})
    d = {f.path: f.content for f in generate(snap)}["extensions.conf"]
    assert "exten => *361001,hint,Custom:veyra-presence-example-1001" in d
    assert "exten => *361001,1,Goto(veyra-internal,1001,1)" in d
    assert (
        "Custom:veyra-presence"
        not in {f.path: f.content for f in generate({**snap, "feature_codes": {}})}[
            "extensions.conf"
        ]
    )

    adapter = FakeAdapter()
    app.state.telephony = adapter
    org = admin.get("/api/v1/organizations").json()["items"][0]
    me = admin.get("/api/v1/auth/session").json()["user"]
    ext = admin.post(
        "/api/v1/extensions",
        json={
            "organization_id": org["id"],
            "number": "1001",
            "display_name": "Me",
            "user_id": me["id"],
        },
    ).json()
    r = admin.put(f"/api/v1/me/extensions/{ext['id']}/presence", json={"state": "meeting"})
    assert r.status_code == 200, r.text
    assert adapter.presence_lamps[(org["slug"], "1001")] == PRESENCE_LAMP["meeting"] == "INUSE"
    admin.put(f"/api/v1/me/extensions/{ext['id']}/presence", json={"state": "out"})
    assert adapter.presence_lamps[(org["slug"], "1001")] == "UNAVAILABLE"


def test_record_toggle_class_guard():
    """Issue #135: a class without the record code hears an error tone."""
    snap = _snapshot(feature_codes={"record_toggle": "*1"})
    snap["classes_of_service"] = [
        {
            "slug": "classroom",
            "name": "Classroom",
            "organization": "example",
            "allowed_routes": [],
            "allowed_feature_codes": ["dnd_on"],
        },
    ]
    d = {f.path: f.content for f in generator.generate(snap)}["extensions.conf"]
    od = _section(d, "veyra-ondemand")
    assert 'GotoIf($[${REGEX("^(classroom)$" ${VEYRA_COS})}]?denied)' in od
    assert " same => n(denied),Playback(beeperr)" in od


def test_presence_code_dialplan():
    """*37<n> (issue #136): the phone tells the API which state."""
    snap = _snapshot(feature_codes={"presence_set": "*37"})
    d = {f.path: f.content for f in generator.generate(snap)}["extensions.conf"]
    feat = _section(d, "veyra-features")
    assert "exten => *37,1,Set(VEYRA_PRESENCE=1)" in feat
    assert "exten => _*37[1-6],1,Set(VEYRA_PRESENCE=${EXTEN:3})" in feat
    assert (
        "UserEvent(VeyraPresence,Org: ${VEYRA_ORG},Extension: ${VEYRA_EXT},"
        "State: ${VEYRA_PRESENCE})" in feat
    )


def test_presence_from_the_phone_applies_the_rules(admin, app):
    from conftest import ADMIN_PASSWORD, login
    from fastapi.testclient import TestClient
    from test_api_mfa import _make_user

    from veyra.core.db import session_scope
    from veyra.telephony import extension_state

    org = admin.get("/api/v1/organizations").json()["items"][0]
    uid = _make_user(admin, "pat@example.org")
    ext = admin.post(
        "/api/v1/extensions",
        json={
            "organization_id": org["id"],
            "number": "1001",
            "display_name": "Pat",
            "user_id": uid,
        },
    ).json()
    user = login(TestClient(app, base_url="http://veyra.test"), "pat@example.org", ADMIN_PASSWORD)
    r = user.put(
        "/api/v1/me/preferences", json={"portal": {"presence_rules": {"meeting": {"dnd": True}}}}
    )
    assert r.status_code == 200, r.text
    with session_scope() as db:
        out = extension_state.handle_presence_userevent(
            db, {"Org": org["slug"], "Extension": "1001", "State": "4"}
        )
    assert out is not None
    p = user.get(f"/api/v1/me/extensions/{ext['id']}/presence").json()
    assert p["state"] == "meeting"
    st = admin.get(f"/api/v1/extensions/{ext['id']}/state").json()
    assert st["dnd"] is True
    with session_scope() as db:
        assert (
            extension_state.handle_presence_userevent(
                db, {"Org": org["slug"], "Extension": "1001", "State": "9"}
            )
            is None
        )
