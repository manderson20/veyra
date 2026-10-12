# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extensions: CRUD with tenant scoping, the numbering plan, SIP secrets
encrypted at rest, generated configuration and encrypted revision artifacts."""

import json

from conftest import ADMIN_PASSWORD, csrf_headers, login, make_settings
from fake_adapter import FakeAdapter
from fastapi.testclient import TestClient
from sqlalchemy import text

from veyra.cli.main import main
from veyra.configmgmt import service
from veyra.core import bootstrap
from veyra.core.db import session_scope
from veyra.core.models import ConfigRevision, Extension
from veyra.core.security.crypto import load_installation_key
from veyra.telephony.snapshot import build_snapshot

EXT = "/api/v1/extensions"


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _create(admin, org_id, number, name="Front Office", **extra):
    r = admin.post(
        EXT, json={"organization_id": org_id, "number": number, "display_name": name, **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _fake(app, tmp_path):
    adapter = FakeAdapter()
    app.state.telephony = adapter
    cfg = tmp_path / "asterisk-veyra"
    cfg.mkdir(exist_ok=True)
    app.state.settings.asterisk_config_dir = cfg
    return adapter, service.Deployer(adapter, cfg, load_installation_key(app.state.settings)), cfg


def test_create_read_update_delete_and_audit(admin):
    org = _org(admin)
    assert admin.get(f"{EXT}/next-number").json()["number"] == "1000"
    ext = _create(admin, org["id"], "1001", caller_id_name="Front Office")
    assert ext["endpoint_name"] == f"{org['slug']}-1001"
    assert ext["organization_name"] == org["name"] and ext["sip_secret_set"]
    assert ext["sip_secret_changed_at"] and ext["is_enabled"] and ext["user_id"] is None
    assert not {"secret", "sip_secret", "sip_secret_ciphertext"} & set(ext)
    assert admin.get(f"{EXT}/next-number").json()["number"] == "1000"
    assert admin.get(f"{EXT}/next-number", params={"after": "1001"}).json()["number"] == "1002"

    listing = admin.get(EXT, params={"q": "front"}).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == ext["id"]
    assert admin.get(EXT, params={"q": "1001"}).json()["total"] == 1
    assert admin.get(EXT, params={"organization_id": org["id"]}).json()["total"] == 1
    assert admin.get(f"{EXT}/{ext['id']}").json()["number"] == "1001"

    me = admin.get("/api/v1/auth/session").json()["user"]["id"]
    r = admin.patch(
        f"{EXT}/{ext['id']}",
        json={"display_name": "Reception", "user_id": me, "caller_id_number": "+15551234567"},
    )
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["display_name"] == "Reception" and got["user_id"] == me
    assert got["user_email"] == "admin@district.local" and got["caller_id_number"] == "+15551234567"
    # renumbering renames the endpoint
    r = admin.patch(f"{EXT}/{ext['id']}", json={"number": "1005"})
    assert r.status_code == 200 and r.json()["endpoint_name"] == f"{org['slug']}-1005"
    r = admin.patch(f"{EXT}/{ext['id']}", json={"is_enabled": False})
    assert r.json()["is_enabled"] is False

    assert admin.delete(f"{EXT}/{ext['id']}").status_code == 204
    assert admin.get(f"{EXT}/{ext['id']}").status_code == 404
    actions = [
        e["action"] for e in admin.get("/api/v1/audit", params={"q": "extension."}).json()["items"]
    ]
    assert {"extension.create", "extension.update", "extension.delete"} <= set(actions)
    created = next(
        e
        for e in admin.get("/api/v1/audit", params={"q": "extension.create"}).json()["items"]
        if e["action"] == "extension.create"
    )
    assert created["details"]["number"] == "1001" and created["target_type"] == "extension"


def test_numbering_plan_is_enforced(admin):
    org = _org(admin)
    plan = admin.get("/api/v1/telephony/numbering").json()
    assert plan["plan"]["extension_length"] == 4 and plan["problems"] == []
    for number, fragment in (
        ("100", "have 4 digits"),
        ("8000", "from 1000 to 7999"),
        ("12x4", "digits only"),
    ):
        r = admin.post(
            EXT, json={"organization_id": org["id"], "number": number, "display_name": "x"}
        )
        assert r.status_code == 422, r.text
        assert fragment in r.json()["detail"] and r.json()["errors"][0]["field"] == "number"

    # change the plan: 3 digits from 200 to 299, 9 reserved
    r = admin.put(
        "/api/v1/telephony/numbering",
        json={
            "extension_length": 3,
            "first_extension": "200",
            "last_extension": "299",
            "reserved_prefixes": ["29"],
        },
    )
    assert r.status_code == 200, r.text
    assert admin.get(f"{EXT}/next-number").json()["number"] == "200"
    r = admin.post(EXT, json={"organization_id": org["id"], "number": "290", "display_name": "x"})
    assert r.status_code == 422 and "reserved" in r.json()["detail"]
    _create(admin, org["id"], "200")
    r = admin.post(EXT, json={"organization_id": org["id"], "number": "200", "display_name": "y"})
    assert r.status_code == 409 and r.json()["code"] == "number_in_use"
    assert admin.get(f"{EXT}/next-number").json()["number"] == "201"
    # an unusable plan is refused
    r = admin.put(
        "/api/v1/telephony/numbering",
        json={"extension_length": 3, "first_extension": "300", "last_extension": "200"},
    )
    assert r.status_code == 422 and "lower than the first" in r.json()["detail"]
    r = admin.put("/api/v1/telephony/numbering", json={"extension_length": 9})
    assert r.status_code == 422
    ev = admin.get("/api/v1/audit", params={"q": "telephony.numbering_update"}).json()["items"]
    assert ev and ev[0]["details"]["changed"]["extension_length"] == 3


def test_numbers_are_unique_across_organizations(admin):
    a = _org(admin)["id"]
    r = admin.post("/api/v1/organizations", json={"name": "Other", "slug": "other"})
    b = r.json()["id"]
    _create(admin, a, "1001")
    r = admin.post(EXT, json={"organization_id": b, "number": "1001", "display_name": "dup"})
    assert r.status_code == 409 and r.json()["code"] == "number_in_use"
    _create(admin, b, "1002")
    # renumbering onto a used number is refused too
    listing = admin.get(EXT, params={"organization_id": b}).json()["items"]
    r = admin.patch(f"{EXT}/{listing[0]['id']}", json={"number": "1001"})
    assert r.status_code == 409
    # inactive organizations cannot get new extensions
    admin.patch(f"/api/v1/organizations/{b}", json={"is_active": False})
    r = admin.post(EXT, json={"organization_id": b, "number": "1003", "display_name": "x"})
    assert r.status_code == 409 and r.json()["code"] == "organization_inactive"


def test_user_assignment_must_match_the_organization(admin):
    a = _org(admin)["id"]
    b = admin.post("/api/v1/organizations", json={"name": "Beta", "slug": "beta"}).json()["id"]
    r = admin.post(
        "/api/v1/users",
        json={
            "email": "b@beta.local",
            "display_name": "B",
            "password": ADMIN_PASSWORD,
            "home_organization_id": b,
        },
    )
    other_user = r.json()["id"]
    r = admin.post(
        EXT,
        json={"organization_id": a, "number": "1001", "display_name": "x", "user_id": other_user},
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "user_id"
    r = admin.post(
        EXT,
        json={
            "organization_id": a,
            "number": "1001",
            "display_name": "x",
            "user_id": "00000000-0000-0000-0000-000000000001",
        },
    )
    assert r.status_code == 422 and "does not exist" in r.json()["detail"]
    ext = _create(admin, b, "1002", user_id=other_user)
    assert ext["user_display_name"] == "B"
    r = admin.patch(f"{EXT}/{ext['id']}", json={"user_id": None})
    assert r.status_code == 200 and r.json()["user_id"] is None


def test_caller_id_validation(admin):
    a = _org(admin)["id"]
    r = admin.post(
        EXT,
        json={"organization_id": a, "number": "1001", "display_name": "x", "caller_id_name": "a;b"},
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "caller_id_name"
    r = admin.post(
        EXT,
        json={
            "organization_id": a,
            "number": "1001",
            "display_name": "x",
            "caller_id_number": "1a",
        },
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "caller_id_number"
    ext = _create(admin, a, "1001", caller_id_name="  Main Office (East)  ", caller_id_number=" ")
    assert ext["caller_id_name"] == "Main Office (East)" and ext["caller_id_number"] is None


def test_sip_secret_is_encrypted_at_rest_revealed_only_on_request_and_rotatable(admin, app):
    a = _org(admin)["id"]
    ext = _create(admin, a, "1001")
    with session_scope() as db:
        row = db.get(Extension, ext["id"])
        assert row.sip_secret_ciphertext.startswith("v1:")
        raw = db.execute(
            text("SELECT sip_secret_ciphertext FROM extensions WHERE id = :id"), {"id": row.id}
        ).scalar_one()
    creds = admin.get(f"{EXT}/{ext['id']}/sip-credentials").json()
    assert creds["username"] == ext["endpoint_name"] and len(creds["secret"]) == 24
    assert creds["secret"].isalnum() and creds["secret"] not in raw
    assert creds["udp_port"] == 5060 and creds["tcp_port"] == 5060 and creds["tls_port"] is None
    rotated = admin.post(f"{EXT}/{ext['id']}/sip-credentials/rotate").json()
    assert rotated["secret"] != creds["secret"] and rotated["rotated_at"] >= creds["rotated_at"]
    assert admin.get(f"{EXT}/{ext['id']}/sip-credentials").json()["secret"] == rotated["secret"]
    events = admin.get("/api/v1/audit", params={"q": "extension.secret"}).json()["items"]
    assert {e["action"] for e in events} == {"extension.secret_reveal", "extension.secret_rotate"}
    assert all("secret" not in json.dumps(e["details"]) for e in events)

    # the key is bound to the extension id: a copied ciphertext does not decrypt
    other = _create(admin, a, "1002")
    with session_scope() as db:
        db.get(Extension, other["id"]).sip_secret_ciphertext = row.sip_secret_ciphertext
    r = admin.get(f"{EXT}/{other['id']}/sip-credentials")
    assert r.status_code == 503 and r.json()["code"] == "secret_unreadable"

    # without the key nothing can be stored or shown
    app.state.settings.installation_key_file = app.state.settings.config_dir / "missing.key"
    r = admin.post(EXT, json={"organization_id": a, "number": "1003", "display_name": "x"})
    assert r.status_code == 503 and r.json()["code"] == "installation_key_missing"
    assert admin.get(f"{EXT}/{ext['id']}/sip-credentials").status_code == 503
    assert admin.get("/api/v1/telephony/engine").json()["installation_key_present"] is False


def test_org_admin_is_confined_and_technician_cannot_write(admin, app):
    a = _org(admin)["id"]
    b = admin.post("/api/v1/organizations", json={"name": "Beta", "slug": "beta"}).json()["id"]
    _create(admin, a, "1001", name="Alpha phone")
    ext_b = _create(admin, b, "2001", name="Beta phone")
    for email, role in (("orgadmin@beta.local", "org_admin"), ("tech@beta.local", "technician")):
        r = admin.post(
            "/api/v1/users",
            json={
                "email": email,
                "display_name": email,
                "password": ADMIN_PASSWORD,
                "home_organization_id": b,
                "require_password_change": False,
            },
        )
        uid = r.json()["id"]
        admin.post(
            f"/api/v1/users/{uid}/roles",
            json={"role_key": role, "scope_type": "organization", "organization_id": b},
        )
    c = login(TestClient(app, base_url="http://veyra.test"), "orgadmin@beta.local", ADMIN_PASSWORD)
    items = c.get(EXT).json()["items"]
    assert [i["number"] for i in items] == ["2001"]
    assert c.get(f"{EXT}/{ext_b['id']}").status_code == 200
    alpha = admin.get(EXT, params={"q": "Alpha"}).json()["items"][0]
    assert c.get(f"{EXT}/{alpha['id']}").status_code == 404
    assert c.get(f"{EXT}/{alpha['id']}/sip-credentials").status_code == 404
    r = c.post(EXT, json={"organization_id": a, "number": "1002", "display_name": "x"})
    assert r.status_code == 403
    r = c.post(EXT, json={"organization_id": b, "number": "2002", "display_name": "x"})
    assert r.status_code == 201
    assert c.get("/api/v1/telephony/numbering").status_code == 200
    assert c.put("/api/v1/telephony/numbering", json={}).status_code == 403
    # search is scoped too
    hits = c.get("/api/v1/search", params={"q": "phone"}).json()["results"]
    assert [h["title"] for h in hits if h["type"] == "extension"] == ["2001 Beta phone"]
    assert hits[0]["href"].startswith("/extensions/view/?id=")

    t = login(TestClient(app, base_url="http://veyra.test"), "tech@beta.local", ADMIN_PASSWORD)
    assert t.get(EXT).status_code == 200
    assert t.get(f"{EXT}/{ext_b['id']}/sip-credentials").status_code == 403
    assert t.patch(f"{EXT}/{ext_b['id']}", json={"display_name": "x"}).status_code == 403
    assert t.delete(f"{EXT}/{ext_b['id']}").status_code == 403


def test_generated_configuration_and_encrypted_revision_artifacts(admin, app, tmp_path):
    adapter, deployer, cfg = _fake(app, tmp_path)
    a = _org(admin)["id"]
    ext = _create(admin, a, "1001", caller_id_name="Front Office")
    disabled = _create(admin, a, "1002", is_enabled=False)
    secret = admin.get(f"{EXT}/{ext['id']}/sip-credentials").json()["secret"]
    engine = admin.get("/api/v1/telephony/engine").json()
    assert engine["changes_pending"] is True and engine["installation_key_present"] is True

    key = load_installation_key(app.state.settings)
    with session_scope() as db:
        snap = build_snapshot(db, key)
        assert [e["number"] for e in snap["extensions"]] == ["1001"]
        assert snap["extensions"][0]["secret"] == secret

    rev = admin.post("/api/v1/telephony/revisions").json()
    assert rev["state"] == "validated", rev
    ep = next(f for f in rev["files"] if f["path"] == "pjsip.endpoints.conf")
    assert ep["sensitive"] and ep["content"] is None
    assert rev["diff"]["pjsip.endpoints.conf"] == {"changed": True, "diff": None, "sensitive": True}
    dial = next(f for f in rev["files"] if f["path"] == "extensions.conf")
    assert "Dial(PJSIP/brookfield-1001,30)" in dial["content"]
    assert "1002" not in dial["content"]
    with session_scope() as db:
        row = db.get(ConfigRevision, rev["id"])
        stored = json.dumps(row.artifacts)
        assert secret not in stored
        files = {f["path"]: f for f in row.artifacts["files"]}
        assert "ciphertext" in files["pjsip.endpoints.conf"]
        assert "content" not in files["pjsip.endpoints.conf"]
        assert "content" in files["extensions.conf"]
    assert admin.post(f"/api/v1/telephony/revisions/{rev['id']}/deploy").status_code == 202
    with session_scope() as db:
        deployer.run_once(db)
    written = (cfg / "pjsip.endpoints.conf").read_text()
    assert f"password={secret}" in written and "[brookfield-1001](veyra-endpoint)" in written
    assert admin.get("/api/v1/telephony/engine").json()["changes_pending"] is False

    # a save that does not change the files still raises the flag (like
    # "Apply Config"); applying clears it without deploying anything
    admin.patch(f"{EXT}/{ext['id']}", json={"display_name": "Front Desk"})
    e = admin.get("/api/v1/telephony/engine").json()
    assert e["changes_pending"] is True and e["pending_by"] == "admin@district.local"
    out = admin.post("/api/v1/telephony/apply").json()
    assert out["applied"] is False and out["unchanged"] is True
    assert admin.get("/api/v1/telephony/engine").json()["changes_pending"] is False
    # enabling the second extension makes changes pending again; only the
    # changed files are reported, and the sensitive one stays hidden
    admin.patch(f"{EXT}/{disabled['id']}", json={"is_enabled": True})
    assert admin.get("/api/v1/telephony/engine").json()["changes_pending"] is True
    rev2 = admin.post("/api/v1/telephony/revisions").json()
    assert set(rev2["diff"]) == {"pjsip.endpoints.conf", "extensions.conf"}
    assert rev2["diff"]["pjsip.endpoints.conf"]["diff"] is None
    assert "+exten => 1002" in rev2["diff"]["extensions.conf"]["diff"]

    # a deployer without the key fails the revision cleanly and restores the files
    blind = service.Deployer(adapter, cfg, None)
    admin.post(f"/api/v1/telephony/revisions/{rev2['id']}/deploy")
    with session_scope() as db:
        blind.run_once(db)
        failed = db.get(ConfigRevision, rev2["id"])
        assert failed.state == "failed" and "installation key" in failed.validation_errors[0]
    assert (cfg / "pjsip.endpoints.conf").read_text() == written


def test_apply_generates_and_deploys_in_one_step(admin, app, tmp_path):
    adapter, deployer, cfg = _fake(app, tmp_path)
    a = _org(admin)["id"]
    _create(admin, a, "1001")
    r = admin.post("/api/v1/telephony/apply")
    assert r.status_code == 202, r.text
    out = r.json()
    assert out["applied"] is True and out["unchanged"] is False
    assert out["revision"]["state"] == "deploying" and out["revision"]["files"] == []
    # a second apply while the first is queued is refused
    assert admin.post("/api/v1/telephony/apply").json()["code"] == "deployment_in_progress"
    with session_scope() as db:
        deployer.run_once(db)
    assert admin.get("/api/v1/telephony/engine").json()["changes_pending"] is False
    assert "[brookfield-1001](veyra-endpoint)" in (cfg / "pjsip.endpoints.conf").read_text()
    # nothing changed: the revision is discarded rather than queued
    out = admin.post("/api/v1/telephony/apply").json()
    assert out["applied"] is False and out["unchanged"] is True
    assert out["revision"]["state"] == "superseded"
    assert admin.get("/api/v1/telephony/engine").json()["pending_revision"] is None
    # a generation problem comes back as a failed revision, nothing queued
    with session_scope() as db:
        from veyra.telephony.settings import SipSettings, save_sip_settings

        save_sip_settings(db, SipSettings(rtp_start=5000, rtp_end=6000))
    out = admin.post("/api/v1/telephony/apply").json()
    assert out["applied"] is False and out["revision"]["state"] == "failed"
    assert "RTP range" in out["revision"]["validation_errors"][0]
    events = admin.get("/api/v1/audit", params={"q": "telephony.config_apply"}).json()["items"]
    assert [e["outcome"] for e in events[:3]] == ["failure", "success", "success"]
    # engine down and no deploy permission
    adapter.state = "stopped"
    assert admin.post("/api/v1/telephony/apply").json()["code"] == "engine_not_running"


def test_session_reports_the_running_version(admin):
    s = admin.get("/api/v1/auth/session").json()
    from veyra.version import __version__

    assert s["version"] == __version__ and "release" in s


def test_generation_fails_clearly_when_a_secret_cannot_be_read(admin, app, tmp_path):
    _fake(app, tmp_path)
    a = _org(admin)["id"]
    ext = _create(admin, a, "1001")
    with session_scope() as db:
        db.get(Extension, ext["id"]).sip_secret_ciphertext = "v1:garbage"
    rev = admin.post("/api/v1/telephony/revisions").json()
    assert rev["state"] == "failed"
    assert "SIP secret of extension 1001 cannot be read" in rev["validation_errors"][0]
    app.state.settings.installation_key_file = app.state.settings.config_dir / "missing.key"
    rev = admin.post("/api/v1/telephony/revisions").json()
    assert rev["state"] == "failed" and "installation key" in rev["validation_errors"][0]


def test_setup_wizard_accepts_a_numbering_plan(client):
    steps = {s["key"]: s for s in client.get("/api/v1/setup/status").json()["steps"]}
    assert steps["numbering"]["available"] is True
    with session_scope() as db:
        token = bootstrap.create_setup_token(db)
    body = {
        "setup_token": token,
        "installation_name": "Test District",
        "administrator": {
            "email": "admin@district.local",
            "display_name": "Admin",
            "password": ADMIN_PASSWORD,
        },
        "organization": {"name": "Brookfield Schools", "slug": "brookfield", "timezone": "UTC"},
        "numbering": {"extension_length": 3, "first_extension": "300", "last_extension": "100"},
    }
    r = client.post("/api/v1/setup/initialize", json=body)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "numbering"
    body["numbering"] = {
        "extension_length": 3,
        "first_extension": "100",
        "last_extension": "199",
        "reserved_prefixes": ["0", "9"],
    }
    r = client.post("/api/v1/setup/initialize", json=body)
    assert r.status_code == 200, r.text
    client.headers.update(csrf_headers(client))
    plan = client.get("/api/v1/telephony/numbering").json()["plan"]
    assert plan["extension_length"] == 3 and plan["reserved_prefixes"] == ["0", "9"]
    assert client.get(f"{EXT}/next-number").json()["number"] == "100"


def test_cli_installation_key_commands(tmp_path, capsys, monkeypatch, database_url):
    from veyra.core import config

    path = tmp_path / "k" / "installation.key"
    monkeypatch.setenv("VEYRA_INSTALLATION_KEY_FILE", str(path))
    monkeypatch.setenv("VEYRA_DATABASE_URL", database_url)
    config.get_settings.cache_clear()
    try:
        assert main(["installation-key", "check"]) == 1
        assert "missing" in capsys.readouterr().out
        assert main(["installation-key", "generate"]) == 0
        out = capsys.readouterr().out
        assert "fingerprint" in out and "Back it up" in out
        assert main(["installation-key", "check", "--json"]) == 0
        info = json.loads(capsys.readouterr().out)
        assert info["present"] and len(info["fingerprint"]) == 16
        assert main(["installation-key", "generate"]) == 1
        assert "already exists" in capsys.readouterr().err
        assert main(["installation-key", "generate", "--force"]) == 0
        capsys.readouterr()
        assert main(["installation-key", "check", "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["fingerprint"] != info["fingerprint"]
    finally:
        config.get_settings.cache_clear()
    # the settings helper used by the fixtures also creates a key
    s = make_settings(database_url, tmp_path / "s")
    assert s.installation_key_path.exists()
