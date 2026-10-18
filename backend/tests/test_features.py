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
    assert "Dial(PJSIP/example-1001,45)" in internal  # the state's ring time
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
