# SPDX-License-Identifier: AGPL-3.0-or-later
from conftest import ADMIN_PASSWORD, login
from fake_adapter import FakeAdapter
from fastapi.testclient import TestClient

from veyra.cli.main import main
from veyra.configmgmt import service
from veyra.core.db import session_scope
from veyra.core.security.crypto import load_installation_key


def _fake(app, tmp_path, state="running"):
    adapter = FakeAdapter(state)
    app.state.telephony = adapter
    cfg = tmp_path / "asterisk-veyra"
    cfg.mkdir(exist_ok=True)
    app.state.settings.asterisk_config_dir = cfg
    return adapter, service.Deployer(adapter, cfg, load_installation_key(app.state.settings))


def test_engine_status_without_engine(admin):
    e = admin.get("/api/v1/telephony/engine").json()
    assert e["engine"] == "none" and e["state"] == "not_configured"
    assert e["capabilities"] == ["health"] and e["deployed_revision"] is None
    r = admin.post("/api/v1/telephony/revisions")
    assert r.status_code == 409 and r.json()["code"] == "not_available"


def test_engine_status_with_engine(admin, app, tmp_path):
    _fake(app, tmp_path)
    e = admin.get("/api/v1/telephony/engine").json()
    assert e["state"] == "running" and e["version"] == "22.5.2"
    assert e["endpoints_total"] == 2 and e["endpoints_registered"] == 1
    assert e["active_channels"] == 1
    assert e["modules"] == [{"name": "res_pjsip.so", "status": "Running"}]
    assert e["config_dir"].endswith("asterisk-veyra")
    h = admin.get("/api/v1/system/health").json()
    assert h["active_calls"] == 1 and h["registrations"] == 1


def test_setup_status_reports_engine_state(client, app, tmp_path):
    _fake(app, tmp_path, state="unreachable")
    s = client.get("/api/v1/setup/status").json()
    assert s["telephony_engine"] == "asterisk" and s["telephony_state"] == "unreachable"
    assert "version" not in s
    step = next(x for x in s["steps"] if x["key"] == "telephony")
    assert step["available"] is True


def test_sip_settings_roundtrip_validation_and_audit(admin):
    s = admin.get("/api/v1/telephony/settings").json()
    assert s["settings"]["udp_port"] == 5060 and s["problems"] == []
    assert "opus" in s["codecs_available"]
    bad = {**s["settings"], "rtp_start": 5000, "rtp_end": 6000}
    r = admin.put("/api/v1/telephony/settings", json=bad)
    assert r.status_code == 422 and "RTP range" in r.json()["detail"]
    r = admin.put("/api/v1/telephony/settings", json={**s["settings"], "codecs": ["nope"]})
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    good = {**s["settings"], "codecs": ["opus", "ulaw"], "local_nets": ["172.16.0.0/16"]}
    r = admin.put("/api/v1/telephony/settings", json=good)
    assert r.status_code == 200 and r.json()["settings"]["codecs"] == ["opus", "ulaw"]
    assert admin.get("/api/v1/telephony/settings").json()["settings"]["local_nets"] == [
        "172.16.0.0/16"
    ]
    ev = admin.get("/api/v1/audit", params={"q": "telephony.settings_update"}).json()["items"]
    assert ev and ev[0]["details"]["changed"]["codecs"] == ["opus", "ulaw"]


def test_revision_flow_through_the_api(admin, app, tmp_path):
    adapter, deployer = _fake(app, tmp_path)
    r = admin.post("/api/v1/telephony/revisions")
    assert r.status_code == 201, r.text
    rev = r.json()
    assert rev["state"] == "validated" and rev["sequence"] >= 1 and rev["can_deploy"]
    assert {f["path"] for f in rev["files"]} == set(adapter.managed_files())
    assert all(f["content"] for f in rev["files"])  # nothing sensitive yet
    assert set(rev["diff"]) == set(adapter.managed_files())
    assert rev["unchanged"] is False

    r = admin.post(f"/api/v1/telephony/revisions/{rev['id']}/deploy")
    assert r.status_code == 202 and r.json()["state"] == "deploying"
    assert admin.get("/api/v1/telephony/engine").json()["pending_revision"] == rev["sequence"]
    # a second deployment request while one is queued
    r2 = admin.post("/api/v1/telephony/revisions").json()
    r = admin.post(f"/api/v1/telephony/revisions/{r2['id']}/deploy")
    assert r.status_code == 409 and r.json()["code"] == "deployment_in_progress"

    with session_scope() as db:
        deployer.run_once(db)
    got = admin.get(f"/api/v1/telephony/revisions/{rev['id']}").json()
    assert got["state"] == "deployed" and got["deployed_at"] and got["diff"] == {}
    assert admin.get("/api/v1/telephony/engine").json()["deployed_revision"] == rev["sequence"]
    assert (tmp_path / "asterisk-veyra" / "extensions.conf").exists()

    # the duplicate revision is "no change"; discard it
    assert admin.get(f"/api/v1/telephony/revisions/{r2['id']}").json()["state"] == "validated"
    r = admin.post(f"/api/v1/telephony/revisions/{r2['id']}/discard")
    assert r.status_code == 200
    assert admin.get(f"/api/v1/telephony/revisions/{r2['id']}").json()["state"] == "superseded"

    listing = admin.get("/api/v1/telephony/revisions").json()
    assert (
        listing["total"] == 2 and listing["items"][0]["sequence"] > listing["items"][1]["sequence"]
    )
    assert listing["items"][0]["files"] == []  # list is metadata only

    # deploy refuses when the engine is down, and refuses wrong states
    adapter.state = "unreachable"
    r3 = admin.post("/api/v1/telephony/revisions").json()
    r = admin.post(f"/api/v1/telephony/revisions/{r3['id']}/deploy")
    assert r.status_code == 409 and r.json()["code"] == "engine_not_running"
    adapter.state = "running"
    r = admin.post(f"/api/v1/telephony/revisions/{rev['id']}/deploy")
    assert r.status_code == 409 and r.json()["code"] == "invalid_state"
    events = admin.get("/api/v1/audit", params={"q": "telephony.config"}).json()["items"]
    actions = {e["action"] for e in events}
    assert {
        "telephony.config_generate",
        "telephony.config_deploy_request",
        "telephony.config_deploy",
        "telephony.config_discard",
    } <= actions


def test_org_admin_sees_metadata_but_no_files(admin, app, tmp_path):
    _fake(app, tmp_path)
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    r = admin.post(
        "/api/v1/users",
        json={
            "email": "orgadmin@district.local",
            "display_name": "Org Admin",
            "password": ADMIN_PASSWORD,
            "home_organization_id": org,
            "require_password_change": False,
        },
    )
    uid = r.json()["id"]
    admin.post(
        f"/api/v1/users/{uid}/roles",
        json={"role_key": "org_admin", "scope_type": "organization", "organization_id": org},
    )
    rev = admin.post("/api/v1/telephony/revisions").json()
    c = login(
        TestClient(app, base_url="http://veyra.test"), "orgadmin@district.local", ADMIN_PASSWORD
    )
    assert c.get("/api/v1/telephony/engine").status_code == 200  # config.read at org scope
    got = c.get(f"/api/v1/telephony/revisions/{rev['id']}").json()
    assert got["sequence"] == rev["sequence"] and got["files"] == [] and got["diff"] is None
    assert (
        c.post("/api/v1/telephony/revisions").status_code == 403
    )  # config.deploy is platform-only
    assert c.get("/api/v1/telephony/settings").status_code == 403
    assert c.put("/api/v1/telephony/settings", json={}).status_code == 403


def test_cli_config_commands(admin, app, tmp_path, capsys, monkeypatch):
    adapter, deployer = _fake(app, tmp_path)
    import veyra.telephony as telephony_pkg

    monkeypatch.setattr(telephony_pkg, "get_adapter", lambda _s: adapter)
    assert main(["config", "generate", "--deploy"]) == 0
    out = capsys.readouterr().out
    assert "revision #" in out and "deploying" in out and "queued" in out
    with session_scope() as db:
        deployer.run_once(db)
    assert main(["config", "status"]) == 0
    out = capsys.readouterr().out
    assert "deployed revision: " in out and "deployed" in out
    assert main(["config", "status", "--json"]) == 0
    assert '"deployed"' in capsys.readouterr().out
    assert main(["config", "generate"]) == 0
    assert "no change" in capsys.readouterr().out
    assert main(["config", "deploy", "999"]) == 1
    assert "no revision" in capsys.readouterr().err
