# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 7 API: voicemail boxes, own-box PIN change, SMTP settings, and
the deployed voicemail.conf."""

from conftest import ADMIN_PASSWORD, login
from fake_adapter import FakeAdapter
from fastapi.testclient import TestClient

from veyra.configmgmt import service
from veyra.core import mail
from veyra.core.db import session_scope
from veyra.core.security.crypto import load_installation_key

VM = "/api/v1/voicemail"
SMTP = "/api/v1/system/smtp"


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _ext(admin, org_id, number, name="Front Office", **extra):
    r = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org_id, "number": number, "display_name": name, **extra},
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


def _me(admin):
    return admin.get("/api/v1/auth/session").json()["user"]


def test_box_crud_pin_handling_and_audit(admin, app, tmp_path):
    _fake(app, tmp_path)
    org = _org(admin)
    me = _me(admin)
    ext = _ext(admin, org["id"], "1001", user_id=me["id"])
    r = admin.post(VM, json={"extension_id": ext["id"]})
    assert r.status_code == 201, r.text
    box = r.json()
    assert len(box["pin"]) == 6 and box["pin"].isdigit()
    assert box["email"] == me["email"]  # defaults to the user's address
    assert box["ring_seconds"] == 20 and box["attach_audio"] and not box["delete_after_email"]
    assert box["extension_number"] == "1001" and box["user_display_name"] == me["display_name"]
    assert box["email_delivery_enabled"] is False and box["in_use_by"] == 0
    # the PIN is never returned again, nor stored in the audit log
    got = admin.get(f"{VM}/{box['id']}").json()
    assert "pin" not in got and "pin_ciphertext" not in got
    events = admin.get("/api/v1/audit", params={"action": "voicemail.create"}).json()["items"]
    assert events and events[0]["details"]["generated"] is True
    assert box["pin"] not in str(events)
    # one box per extension
    assert admin.post(VM, json={"extension_id": ext["id"]}).json()["code"] == "box_exists"
    # explicit PIN and validation
    ext2 = _ext(admin, org["id"], "1002", "Library")
    assert admin.post(VM, json={"extension_id": ext2["id"], "pin": "12"}).status_code == 422
    assert admin.post(VM, json={"extension_id": ext2["id"], "email": "nope"}).status_code == 422
    r = admin.post(
        VM, json={"extension_id": ext2["id"], "pin": "4321", "email": "", "ring_seconds": 15}
    )
    assert r.status_code == 201 and r.json()["pin"] == "4321" and r.json()["email"] is None
    box2 = r.json()
    r = admin.post(VM, json={"extension_id": ext2["id"], "delete_after_email": True, "email": ""})
    assert r.status_code in (409, 422)
    # list, filters, search
    listing = admin.get(VM).json()
    assert listing["total"] == 2 and [b["extension_number"] for b in listing["items"]] == [
        "1001",
        "1002",
    ]
    assert admin.get(VM, params={"extension_id": ext2["id"]}).json()["total"] == 1
    assert admin.get(VM, params={"q": "libr"}).json()["total"] == 1
    # patch: PIN change audited without the value; delete_after_email needs an address
    r = admin.patch(
        f"{VM}/{box2['id']}", json={"pin": "999999", "ring_seconds": 40, "is_enabled": False}
    )
    assert r.status_code == 200 and r.json()["ring_seconds"] == 40 and not r.json()["is_enabled"]
    ev = admin.get("/api/v1/audit", params={"action": "voicemail.update"}).json()["items"][0]
    assert ev["details"]["code_changed"] is True and "999999" not in str(ev)
    r = admin.patch(f"{VM}/{box2['id']}", json={"delete_after_email": True})
    assert r.status_code == 422
    r = admin.patch(
        f"{VM}/{box2['id']}", json={"delete_after_email": True, "email": "lib@example.org"}
    )
    assert r.status_code == 200 and r.json()["delete_after_email"]
    # reset returns a fresh PIN once
    new = admin.post(f"{VM}/{box['id']}/reset-pin").json()["pin"]
    assert len(new) == 6 and new.isdigit()
    assert admin.get("/api/v1/telephony/engine").json()["changes_pending"] is True
    # delete
    assert admin.delete(f"{VM}/{box2['id']}").status_code == 204
    assert admin.get(f"{VM}/{box2['id']}").status_code == 404
    # deleting the extension removes its box
    admin.delete(f"/api/v1/extensions/{ext['id']}")
    assert admin.get(VM).json()["total"] == 0


def test_own_voicemail_and_pin_change(admin, app):
    org = _org(admin)
    me = _me(admin)
    mine = _ext(admin, org["id"], "1001", "Mine", user_id=me["id"])
    other = _ext(admin, org["id"], "1002", "Other")
    box_mine = admin.post(VM, json={"extension_id": mine["id"]}).json()
    box_other = admin.post(VM, json={"extension_id": other["id"]}).json()
    rows = admin.get("/api/v1/me/voicemail").json()
    assert [r["extension_number"] for r in rows] == ["1001"]
    assert rows[0]["id"] == box_mine["id"] and "pin" not in rows[0]
    assert (
        admin.post(f"/api/v1/me/voicemail/{box_mine['id']}/pin", json={"pin": "2468"}).status_code
        == 204
    )
    assert (
        admin.post(f"/api/v1/me/voicemail/{box_mine['id']}/pin", json={"pin": "12"}).status_code
        == 422
    )
    assert (
        admin.post(f"/api/v1/me/voicemail/{box_other['id']}/pin", json={"pin": "2468"}).status_code
        == 404
    )
    # a standard user sees only their own box and cannot administer boxes
    r = admin.post(
        "/api/v1/users",
        json={
            "email": "teacher@district.local",
            "display_name": "Teacher",
            "password": ADMIN_PASSWORD,
            "home_organization_id": org["id"],
            "require_password_change": False,
        },
    )
    uid = r.json()["id"]
    admin.patch(f"/api/v1/extensions/{other['id']}", json={"user_id": uid})
    c = login(
        TestClient(app, base_url="http://veyra.test"), "teacher@district.local", ADMIN_PASSWORD
    )
    assert [r["extension_number"] for r in c.get("/api/v1/me/voicemail").json()] == ["1002"]
    assert (
        c.post(f"/api/v1/me/voicemail/{box_other['id']}/pin", json={"pin": "1357"}).status_code
        == 204
    )
    assert c.get(VM).status_code == 403
    assert c.post(VM, json={"extension_id": other["id"]}).status_code == 403


def test_box_in_use_cannot_be_deleted_and_scoping(admin, app):
    a = _org(admin)["id"]
    b = admin.post("/api/v1/organizations", json={"name": "Beta", "slug": "beta"}).json()["id"]
    ext_a = _ext(admin, a, "1001", "Alpha")
    ext_b = _ext(admin, b, "2001", "Beta")
    box_a = admin.post(VM, json={"extension_id": ext_a["id"]}).json()
    route = admin.post(
        "/api/v1/routing/inbound",
        json={
            "organization_id": a,
            "did": "5735550100",
            "destination_type": "voicemail",
            "destination_extension_id": ext_a["id"],
        },
    )
    assert route.status_code == 201, route.text
    assert route.json()["destination"]["type"] == "voicemail"
    assert route.json()["destination"]["label"].startswith("Voicemail of 1001")
    assert admin.get(f"{VM}/{box_a['id']}").json()["in_use_by"] == 1
    r = admin.delete(f"{VM}/{box_a['id']}")
    assert r.status_code == 409 and r.json()["code"] == "voicemail_in_use"
    # a route may not point at the voicemail of an extension without a box
    r = admin.post(
        "/api/v1/routing/inbound",
        json={
            "organization_id": b,
            "did": "5735550101",
            "destination_type": "voicemail",
            "destination_extension_id": ext_b["id"],
        },
    )
    assert r.status_code == 422 and "no voicemail box" in r.text
    # organization administrators see and manage only their own boxes
    r = admin.post(
        "/api/v1/users",
        json={
            "email": "orgadmin@beta.local",
            "display_name": "Beta admin",
            "password": ADMIN_PASSWORD,
            "home_organization_id": b,
            "require_password_change": False,
        },
    )
    uid = r.json()["id"]
    admin.post(
        f"/api/v1/users/{uid}/roles",
        json={"role_key": "org_admin", "scope_type": "organization", "organization_id": b},
    )
    c = login(TestClient(app, base_url="http://veyra.test"), "orgadmin@beta.local", ADMIN_PASSWORD)
    assert c.get(VM).json()["items"] == []
    assert c.get(f"{VM}/{box_a['id']}").status_code == 404
    assert c.post(VM, json={"extension_id": ext_a["id"]}).status_code == 403
    assert c.post(VM, json={"extension_id": ext_b["id"]}).status_code == 201


def test_smtp_settings_and_test_message(admin, app, tmp_path, monkeypatch):
    _fake(app, tmp_path)
    s = admin.get(SMTP).json()
    assert (
        s["enabled"] is False
        and s["has_password"] is False
        and s["queue"]
        == {
            "waiting": 0,
            "failed": 0,
        }
    )
    assert s["effective_from_address"].startswith("veyra@") and s["effective_from_name"]
    # problems block saving
    r = admin.put(SMTP, json={"enabled": True, "host": ""})
    assert r.status_code == 422 and "host name" in r.text
    r = admin.put(SMTP, json={"enabled": True, "host": "relay.example.org", "security": "none"})
    assert r.status_code == 422 and "loopback" in r.text
    r = admin.put(
        SMTP,
        json={
            "enabled": True,
            "host": "smtp.example.org",
            "username": "mailer",
            "password": "pa55",
            "from_address": "pbx@example.org",
            "from_name": "District PBX",
        },
    )
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["has_password"] and "password" not in s and s["effective_from_name"] == "District PBX"
    assert admin.get("/api/v1/telephony/engine").json()["changes_pending"] is True
    ev = admin.get("/api/v1/audit", params={"action": "smtp.update"}).json()["items"][0]
    assert ev["details"]["changed"]["password_ciphertext"] == "[REDACTED]" or "pa55" not in str(ev)
    # omitting the password keeps it; an empty one removes it
    assert admin.put(SMTP, json={**s, "port": 2525}).json()["has_password"] is True
    assert (
        admin.put(SMTP, json={**s, "username": None, "password": ""}).json()["has_password"]
        is False
    )
    # test message: success and failure are both reported and audited
    sent = []

    def fake_send(settings, key, msg, **kw):
        sent.append(msg)
        return [msg["To"]]

    monkeypatch.setattr(mail, "send", fake_send)
    r = admin.post(f"{SMTP}/test")
    assert r.status_code == 200 and r.json()["ok"] and sent[0]["Subject"].startswith("District PBX")
    assert sent[0]["From"] == "District PBX <pbx@example.org>"

    def failing(settings, key, msg, **kw):
        raise mail.MailError("could not send through smtp.example.org:2525: refused")

    monkeypatch.setattr(mail, "send", failing)
    r = admin.post(f"{SMTP}/test")
    assert r.status_code == 200 and not r.json()["ok"] and "refused" in r.json()["message"]
    tests = admin.get("/api/v1/audit", params={"action": "smtp.test"}).json()["items"]
    assert [t["outcome"] for t in tests[:2]] == ["failure", "success"]
    # settings endpoints need the platform settings permission
    org = _org(admin)
    r = admin.post(
        "/api/v1/users",
        json={
            "email": "orgadmin@district.local",
            "display_name": "Org admin",
            "password": ADMIN_PASSWORD,
            "home_organization_id": org["id"],
            "require_password_change": False,
        },
    )
    uid = r.json()["id"]
    admin.post(
        f"/api/v1/users/{uid}/roles",
        json={"role_key": "org_admin", "scope_type": "organization", "organization_id": org["id"]},
    )
    c = login(
        TestClient(admin.app, base_url="http://veyra.test"),
        "orgadmin@district.local",
        ADMIN_PASSWORD,
    )
    assert c.get(SMTP).status_code == 403


def test_voicemail_reaches_the_generated_configuration(admin, app, tmp_path):
    adapter, deployer, cfg = _fake(app, tmp_path)
    org = _org(admin)
    ext = _ext(admin, org["id"], "1001", "Front Office")
    box = admin.post(
        VM, json={"extension_id": ext["id"], "pin": "1234", "email": "fo@example.org"}
    ).json()
    admin.put(
        SMTP,
        json={"enabled": True, "host": "smtp.example.org", "from_address": "pbx@example.org"},
    )
    r = admin.post("/api/v1/telephony/apply", json={})
    assert r.status_code in (200, 202), r.text
    with session_scope() as db:
        deployer.run_once(db)
    vm = (cfg / "voicemail.conf").read_text()
    assert "1001 => 1234,Front Office,fo@example.org,,attach=yes|delete=no|tz=example" in vm
    assert "serveremail=pbx@example.org" in vm
    assert f"mailcmd={app.state.settings.mailqueue_command}" in vm
    assert "example=America/Chicago|" in vm
    ep = (cfg / "pjsip.endpoints.conf").read_text()
    assert ep.count("mailboxes=1001@veyra") == 2
    dp = (cfg / "extensions.conf").read_text()
    assert "Dial(PJSIP/example-1001,20)" in dp and "VoiceMail(1001@veyra,u)" in dp
    assert "app_voicemail.so" in adapter.reloads
    assert admin.get("/api/v1/telephony/engine").json()["changes_pending"] is False
    # the PIN never appears in a revision's readable artifacts
    revs = admin.get("/api/v1/telephony/revisions").json()["items"]
    rev = admin.get(f"/api/v1/telephony/revisions/{revs[0]['id']}").json()
    assert "1234," not in str(rev)
    # a disabled box leaves the engine configuration at the next deployment
    admin.patch(f"{VM}/{box['id']}", json={"is_enabled": False})
    admin.post("/api/v1/telephony/apply", json={})
    with session_scope() as db:
        deployer.run_once(db)
    assert "1001 =>" not in (cfg / "voicemail.conf").read_text()
    assert "mailboxes=" not in (cfg / "pjsip.endpoints.conf").read_text()
