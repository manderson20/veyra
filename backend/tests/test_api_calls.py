# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 5: registration status, active calls, click-to-dial, deploy when idle."""

from datetime import timedelta

from conftest import ADMIN_PASSWORD, enable_multi_tenancy, login
from fake_adapter import FakeAdapter
from fastapi.testclient import TestClient

from veyra.cli.main import main
from veyra.configmgmt import service
from veyra.core.db import session_scope
from veyra.core.models import ConfigRevision
from veyra.core.security.crypto import load_installation_key
from veyra.telephony.adapter import ActiveCall, EndpointStatus, RecordingState
from veyra.telephony.asterisk.adapter import _age_seconds, _endpoint_of

EXT = "/api/v1/extensions"


def _fake(app, tmp_path, **deployer_kwargs):
    adapter = FakeAdapter()
    app.state.telephony = adapter
    cfg = tmp_path / "asterisk-veyra"
    cfg.mkdir(exist_ok=True)
    app.state.settings.asterisk_config_dir = cfg
    key = load_installation_key(app.state.settings)
    return adapter, service.Deployer(adapter, cfg, key, **deployer_kwargs), cfg


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _create(admin, org_id, number, name="Phone", **extra):
    r = admin.post(
        EXT, json={"organization_id": org_id, "number": number, "display_name": name, **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _user(admin, email, role, org_id):
    r = admin.post(
        "/api/v1/users",
        json={
            "email": email,
            "display_name": email.split("@")[0],
            "password": ADMIN_PASSWORD,
            "home_organization_id": org_id,
            "require_password_change": False,
        },
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = admin.post(
        f"/api/v1/users/{uid}/roles",
        json={"role_key": role, "scope_type": "organization", "organization_id": org_id},
    )
    assert r.status_code == 201, r.text
    return uid


def test_channel_parsing_helpers():
    from datetime import UTC, datetime

    assert _endpoint_of("PJSIP/example-1001-00000003") == "example-1001"
    assert _endpoint_of("Local/1001@veyra-internal-0000;1") is None
    now = datetime(2026, 10, 12, 20, 10, 0, tzinfo=UTC)
    assert _age_seconds("2026-10-12T20:07:31.123+0000", now) == 148
    assert _age_seconds("2026-10-12T20:07:31+00:00", now) == 149
    assert _age_seconds(None, now) == 0 and _age_seconds("garbage", now) == 0


def test_registration_status_in_extension_responses(admin, app, tmp_path):
    adapter, _, _ = _fake(app, tmp_path)
    org = _org(admin)
    a = _create(admin, org["id"], "1001", "Desk")
    b = _create(admin, org["id"], "1002", "Hall")
    adapter.endpoints = [
        EndpointStatus(a["endpoint_name"], True, contacts=["ch-1"]),
        EndpointStatus(b["endpoint_name"], False),
    ]
    items = {x["number"]: x for x in admin.get(EXT).json()["items"]}
    assert items["1001"]["registration"] == {"registered": True, "channels": 1, "contacts": []}
    assert items["1002"]["registration"] == {"registered": False, "channels": 0, "contacts": []}
    assert admin.get(f"{EXT}/{a['id']}").json()["registration"]["registered"] is True
    # engine down: no live data, the extension is still shown
    adapter.state = "unreachable"
    assert admin.get(f"{EXT}/{a['id']}").json()["registration"] is not None  # fake still answers
    app.state.telephony = __import__(
        "veyra.telephony.adapter", fromlist=["NullAdapter"]
    ).NullAdapter()
    assert admin.get(f"{EXT}/{a['id']}").json()["registration"] is None


def test_active_calls_are_scoped(admin, app, tmp_path):
    adapter, _, _ = _fake(app, tmp_path)
    a = _org(admin)["id"]
    enable_multi_tenancy()
    b = admin.post("/api/v1/organizations", json={"name": "Beta", "slug": "beta"}).json()["id"]
    ea = _create(admin, a, "1001", "Alpha desk")
    eb = _create(admin, b, "2001", "Beta desk")
    adapter.calls = [
        ActiveCall("c1", "1001", "1002", "Up", 30, endpoint=ea["endpoint_name"]),
        ActiveCall("c2", "2001", "*43", "Ring", 2, endpoint=eb["endpoint_name"]),
        ActiveCall("c3", None, None, "Down", 0, endpoint=None),
    ]
    out = admin.get("/api/v1/calls").json()
    assert out["available"] and [c["channel_id"] for c in out["calls"]] == ["c1", "c2", "c3"]
    assert out["calls"][0]["extension_name"] == "Alpha desk"
    _user(admin, "tech@beta.local", "technician", b)
    t = login(TestClient(app, base_url="http://veyra.test"), "tech@beta.local", ADMIN_PASSWORD)
    mine = t.get("/api/v1/calls").json()["calls"]
    assert [c["channel_id"] for c in mine] == ["c2"]
    assert admin.get("/api/v1/telephony/engine").json()["active_calls"] == 3
    adapter.state = "unreachable"
    assert admin.get("/api/v1/calls").json()["available"] is True  # the fake still lists


def test_click_to_dial(admin, app, tmp_path):
    adapter, _, _ = _fake(app, tmp_path)
    a = _org(admin)["id"]
    uid = _user(admin, "jo@district.local", "standard_user", a)
    mine = _create(admin, a, "1001", "Jo", user_id=uid)
    other = _create(admin, a, "1002", "Front")
    jo = login(TestClient(app, base_url="http://veyra.test"), "jo@district.local", ADMIN_PASSWORD)
    r = jo.post("/api/v1/calls/originate", json={"extension_id": mine["id"], "number": "1002"})
    assert r.status_code == 202, r.text
    assert r.json()["channel_id"] == "orig-1" and "ringing" in r.json()["message"]
    assert adapter.originated == [(mine["endpoint_name"], "1002", "veyra-internal")]
    # formatting is tolerated, letters are not
    r = jo.post(
        "/api/v1/calls/originate", json={"extension_id": mine["id"], "number": "(555) 123-4567"}
    )
    assert r.status_code == 202 and adapter.originated[-1][1] == "5551234567"
    r = jo.post("/api/v1/calls/originate", json={"extension_id": mine["id"], "number": "12a"})
    assert r.status_code == 422
    # not your phone, and no calls.read for a standard user
    r = jo.post("/api/v1/calls/originate", json={"extension_id": other["id"], "number": "1001"})
    assert r.status_code == 403
    assert jo.get("/api/v1/calls").status_code == 403
    # an administrator may dial from any phone in the organization
    r = admin.post("/api/v1/calls/originate", json={"extension_id": other["id"], "number": "1001"})
    assert r.status_code == 202
    r = admin.post("/api/v1/calls/originate", json={"extension_id": other["id"], "number": "1002"})
    assert r.status_code == 409 and r.json()["code"] == "same_number"
    admin.patch(f"{EXT}/{other['id']}", json={"is_enabled": False})
    r = admin.post("/api/v1/calls/originate", json={"extension_id": other["id"], "number": "1001"})
    assert r.status_code == 409 and r.json()["code"] == "extension_disabled"
    adapter.fail_originate = "ARI POST channels returned HTTP 500"
    r = admin.post("/api/v1/calls/originate", json={"extension_id": mine["id"], "number": "1002"})
    assert r.status_code == 409 and r.json()["code"] == "originate_failed"
    adapter.state = "stopped"
    adapter.fail_originate = None
    r = admin.post("/api/v1/calls/originate", json={"extension_id": mine["id"], "number": "1002"})
    assert r.status_code == 409 and r.json()["code"] == "engine_not_running"
    events = admin.get("/api/v1/audit", params={"q": "call.originate"}).json()["items"]
    assert len(events) >= 4 and {e["outcome"] for e in events} == {"success", "failure"}
    assert events[-1]["details"] == {
        "from": "1001",
        "to": "1002",
        "own_extension": True,
        "channel": "orig-1",
    }


def test_deploy_when_idle_waits_then_deploys(admin, app, tmp_path):
    adapter, deployer, cfg = _fake(app, tmp_path, idle_timeout=timedelta(minutes=10))
    a = _org(admin)["id"]
    _create(admin, a, "1001")
    # a call is up: a when-idle apply queues and the deployer holds back
    r = admin.post("/api/v1/telephony/apply", json={"mode": "when_idle"})
    assert r.status_code == 202, r.text
    rev = r.json()["revision"]
    assert rev["deploy_mode"] == "when_idle" and rev["deploy_requested_at"]
    e = admin.get("/api/v1/telephony/engine").json()
    assert e["pending_mode"] == "when_idle" and e["pending_active_calls"] == 1
    with session_scope() as db:
        assert deployer.run_once(db) is None
        assert deployer.waiting is not None and deployer.waiting[0] == 1
        assert db.get(ConfigRevision, rev["id"]).state == "deploying"
    assert not (cfg / "pjsip.endpoints.conf").exists()
    # the call ends: the next pass deploys and records the wait
    adapter.calls = []
    with session_scope() as db:
        done = deployer.run_once(db)
        assert done is not None and done.state == "deployed"
        assert any("deployed when idle" in line for line in done.validation_errors)
    assert deployer.waiting is None
    assert (cfg / "pjsip.endpoints.conf").exists()
    # timeout: with calls still up past the limit, the deployer goes ahead and says so
    adapter.calls = [ActiveCall("c1", "1001", "1002", "Up", 5)]
    admin.patch(f"{EXT}/{admin.get(EXT).json()['items'][0]['id']}", json={"caller_id_name": "X"})
    r = admin.post("/api/v1/telephony/apply", json={"mode": "when_idle"})
    rev2 = r.json()["revision"]
    with session_scope() as db:
        row = db.get(ConfigRevision, rev2["id"])
        row.deploy_requested_at = row.deploy_requested_at - timedelta(minutes=11)
    with session_scope() as db:
        done = deployer.run_once(db)
        assert done is not None and done.state == "deployed"
        assert any("idle timeout" in line for line in done.validation_errors)
    # "now" ignores calls entirely; an invalid mode is refused
    admin.patch(f"{EXT}/{admin.get(EXT).json()['items'][0]['id']}", json={"caller_id_name": "Y"})
    r = admin.post("/api/v1/telephony/apply", json={"mode": "now"})
    assert r.status_code == 202 and r.json()["revision"]["deploy_mode"] == "now"
    with session_scope() as db:
        assert deployer.run_once(db).state == "deployed"
    assert admin.post("/api/v1/telephony/apply", json={"mode": "later"}).status_code == 422


def test_cli_deploy_when_idle(admin, app, tmp_path, capsys, monkeypatch):
    adapter, deployer, _ = _fake(app, tmp_path)
    import veyra.telephony as telephony_pkg

    monkeypatch.setattr(telephony_pkg, "get_adapter", lambda _s: adapter)
    assert main(["config", "generate"]) == 0
    seq = int(capsys.readouterr().out.split("#")[1].split(":")[0])
    assert main(["config", "deploy", str(seq), "--when-idle"]) == 0
    assert "waits until no calls" in capsys.readouterr().out
    with session_scope() as db:
        assert deployer.run_once(db) is None  # the fake has a call up
    adapter.calls = []
    with session_scope() as db:
        assert deployer.run_once(db).state == "deployed"


def test_hang_up_a_call(admin, app, tmp_path):
    adapter, _, _ = _fake(app, tmp_path)
    a = _org(admin)["id"]
    enable_multi_tenancy()
    b = admin.post("/api/v1/organizations", json={"name": "Beta", "slug": "beta"}).json()["id"]
    ea = _create(admin, a, "1001", "Alpha desk")
    eb = _create(admin, b, "2001", "Beta desk")
    adapter.calls = [
        ActiveCall("1697.1", "1001", "1002", "Up", 30, endpoint=ea["endpoint_name"]),
        ActiveCall("1697.2", "2001", "*43", "Ring", 2, endpoint=eb["endpoint_name"]),
    ]
    _user(admin, "tech@beta.local", "technician", b)
    t = login(TestClient(app, base_url="http://veyra.test"), "tech@beta.local", ADMIN_PASSWORD)
    assert t.delete("/api/v1/calls/1697.1").status_code == 404  # another organization's call
    assert adapter.hung_up == []
    r = t.delete("/api/v1/calls/1697.2")
    assert r.status_code == 200 and "2001" in r.json()["message"]
    assert adapter.hung_up == ["1697.2"]
    assert admin.delete("/api/v1/calls/1697.2").status_code == 404  # gone
    assert admin.delete("/api/v1/calls/bad%2Fid").status_code == 404
    assert admin.delete("/api/v1/calls/1697.1").status_code == 200
    events = admin.get("/api/v1/audit", params={"q": "call.hangup"}).json()
    assert events["total"] == 2
    _user(admin, "ro@beta.local", "read_only", b)
    ro = login(TestClient(app, base_url="http://veyra.test"), "ro@beta.local", ADMIN_PASSWORD)
    assert ro.delete("/api/v1/calls/1697.2").status_code == 403


def test_record_a_call_from_the_web(admin, app, tmp_path):
    """Issue #135: start and stop recording a call in progress; audited."""
    adapter, _, _ = _fake(app, tmp_path)
    a = _org(admin)["id"]
    ea = _create(admin, a, "1001", "Alpha desk")
    adapter.calls = [ActiveCall("1697.1", "1001", "1002", "Up", 30, endpoint=ea["endpoint_name"])]
    r = admin.post("/api/v1/calls/1697.1/record", json={"action": "start"})
    assert r.status_code == 200 and r.json()["message"] == "Recording started.", r.text
    assert admin.post("/api/v1/calls/1697.1/record", json={"action": "start"}).status_code == 409
    assert admin.post("/api/v1/calls/1697.1/record", json={"action": "stop"}).status_code == 200
    assert admin.post("/api/v1/calls/9.9/record", json={"action": "start"}).status_code == 404
    assert admin.post("/api/v1/calls/1697.1/record", json={"action": "pause"}).status_code == 422
    events = admin.get("/api/v1/audit", params={"q": "call.record"}).json()
    assert events["total"] == 2


def test_active_calls_report_recordings(admin, app, tmp_path):
    """Issue #351: from the engine, so it survives a reload and covers policies."""
    fake = FakeAdapter()
    fake.calls = [
        ActiveCall("c1", "1001", "1002", "Up", 5, channel_name="PJSIP/a-1"),
        ActiveCall("c2", "1002", "1001", "Up", 5, channel_name="PJSIP/b-2"),
        ActiveCall("c3", "1003", "1004", "Up", 5, channel_name="PJSIP/c-3"),
    ]
    fake.recordings = {
        "c1": RecordingState(True, True),
        "c2": RecordingState(True, False),
    }
    app.state.telephony = fake
    out = {c["channel_id"]: c for c in admin.get("/api/v1/calls").json()["calls"]}
    assert out["c1"]["recording"] and out["c1"]["recording_stoppable"]
    assert out["c2"]["recording"] and not out["c2"]["recording_stoppable"]
    assert not out["c3"]["recording"]


def test_recording_states_from_the_engine(monkeypatch):
    """A policy's recording on one leg marks the other leg by its inherited
    reference; a finished recording (reference, nothing running) is not one."""
    from veyra.telephony.asterisk import adapter as ast

    monkeypatch.setattr(
        ast.cli,
        "run",
        lambda cmd, timeout=10.0: (True, "File: /x/1.wav" if cmd.endswith("PJSIP/a-1") else ""),
    )
    variables = {
        ("c1", "VEYRA_CALLREC"): "ref1",
        ("c1", "VEYRA_ONDEMAND_WEB"): "1",
        ("c2", "VEYRA_CALLREC"): "ref1",
        ("c3", "VEYRA_CALLREC"): "old",
    }

    class Ari:
        def get_variable(self, channel, name):
            return variables.get((channel, name), "")

    a = ast.AsteriskAdapter.__new__(ast.AsteriskAdapter)
    a.ari = Ari()
    calls = [
        ActiveCall(i, None, None, "Up", 1, channel_name=n)
        for i, n in (("c1", "PJSIP/a-1"), ("c2", "PJSIP/b-2"), ("c3", "PJSIP/c-3"))
    ]
    states = a.recording_states(calls)
    assert states["c1"] == RecordingState(True, True)
    assert states["c2"] == RecordingState(True, False)
    assert states["c3"] == RecordingState(False, False)
