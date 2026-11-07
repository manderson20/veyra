# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration checks on save (docs/CONFIG_VERIFICATION.md §4, §5, §6): an
enforced error stops a Base File Edit until it is overridden with a reason;
the override is listed, audited and revocable; advisory and off modes; the
override permission; the read-only check of unsaved changes."""

from conftest import ADMIN_PASSWORD, login
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from test_config_precheck import _strict_yealink

from veyra.core.db import session_scope
from veyra.core.models import AuditEvent, Device, Role, RolePermission

PROFILES = "/api/v1/device-profiles"
BAD = {
    "file": "{mac}.cfg",
    "parameter": "account.1.sip_server.1.transport_type",
    "value": "4",
    "models": ["T46U"],
}


def _setup(admin, app, tmp_path):
    app.state.capabilities = _strict_yealink(tmp_path)
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    r = admin.post(
        PROFILES,
        json={"organization_id": org, "name": "Desk", "template_key": "yealink.t4x"},
    )
    assert r.status_code == 201, r.text
    return org, r.json()


def test_enforced_error_needs_an_override(admin, app, tmp_path):
    _org, profile = _setup(admin, app, tmp_path)
    check = profile["config_check"]
    assert check["mode"] == "enforce" and check["level"] == "installation"
    assert check["counts"]["error"] == 0
    assert check["targets"] and check["targets"][0]["how"] == "oldest"
    pid = profile["id"]

    r = admin.put(f"{PROFILES}/{pid}/base-edits", json={"edits": [BAD]})
    assert r.status_code == 422, r.text
    problem = r.json()
    assert problem["code"] == "config_findings"
    errors = [f for f in problem["errors"] if f["severity"] == "error"]
    assert [(f["rule"], f["parameter"], f["value"]) for f in errors] == [
        ("enum.1", "account.1.sip_server.1.transport_type", "4")
    ]
    assert errors[0]["accepts"] == "0 UDP, 1 TCP, 2 TLS, 3 DNS-NAPTR"
    assert admin.get(f"{PROFILES}/{pid}").json()["base_edits"] == []  # nothing saved

    fp = errors[0]["fingerprint"]
    ack = {"fingerprint": fp, "reason": "Vendor support confirmed", "checker_wrong": True}
    r = admin.put(f"{PROFILES}/{pid}/base-edits", json={"edits": [BAD], "acknowledge": [ack]})
    assert r.status_code == 200, r.text
    check = r.json()["config_check"]
    assert check["counts"]["overridden"] == 1 and check["counts"]["error"] == 0
    over = next(f for f in check["findings"] if f["fingerprint"] == fp)["override"]
    assert over["reason"] == "Vendor support confirmed" and over["checker_wrong"]

    listed = admin.get("/api/v1/provisioning/check-overrides?checker_wrong=true").json()
    assert [o["parameter"] for o in listed["items"]] == ["account.1.sip_server.1.transport_type"]
    with session_scope() as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "provisioning.check.override")
        ).all()
        assert len(events) == 1 and events[0].details["reason"] == "Vendor support confirmed"

    # Later saves keep the override.
    r = admin.patch(f"{PROFILES}/{pid}", json={"description": "Building A"})
    assert r.status_code == 200, r.text

    # Revoked, the finding is open again.
    oid = listed["items"][0]["id"]
    assert admin.post(f"/api/v1/provisioning/check-overrides/{oid}/revoke").status_code == 200
    r = admin.patch(f"{PROFILES}/{pid}", json={"description": "Building B"})
    assert r.status_code == 422 and r.json()["code"] == "config_findings"

    # A different value is a different finding.
    other = {**BAD, "value": "9"}
    r = admin.put(f"{PROFILES}/{pid}/base-edits", json={"edits": [other], "acknowledge": [ack]})
    assert r.status_code == 422


def test_modes(admin, app, tmp_path):
    org, profile = _setup(admin, app, tmp_path)
    pid = profile["id"]
    r = admin.put(
        "/api/v1/provisioning/check-mode",
        json={"scope": "profile", "scope_id": pid, "mode": "advisory"},
    )
    assert r.status_code == 200 and r.json()["effective"] == "advisory"
    r = admin.put(f"{PROFILES}/{pid}/base-edits", json={"edits": [BAD]})
    assert r.status_code == 200, r.text
    check = r.json()["config_check"]
    assert check["mode"] == "advisory" and check["counts"]["error"] == 1
    with session_scope() as db:
        assert db.scalars(select(Device)).all() == []
    # Off at the organization does not override the profile's own mode...
    r = admin.put(
        "/api/v1/provisioning/check-mode",
        json={"scope": "organization", "scope_id": org, "mode": "off"},
    )
    assert r.status_code == 200 and r.json()["level"] == "organization"
    mode = admin.get(f"/api/v1/provisioning/check-mode?profile_id={pid}").json()
    assert (mode["effective"], mode["level"]) == ("advisory", "profile")
    # ...until the profile follows the organization again.
    r = admin.patch(f"{PROFILES}/{pid}", json={"config_check_mode": None, "description": "x"})
    assert r.status_code == 200, r.text
    assert r.json()["config_check"]["mode"] == "off"
    assert r.json()["config_check"]["findings"] == []
    with session_scope() as db:
        assert db.scalars(
            select(AuditEvent).where(AuditEvent.action == "provisioning.check.mode")
        ).all()


def test_override_needs_the_permission(admin, app, tmp_path):
    from test_api_rbac import make_user

    org, profile = _setup(admin, app, tmp_path)
    pid = profile["id"]
    fp = admin.put(f"{PROFILES}/{pid}/base-edits", json={"edits": [BAD]}).json()["errors"]
    fp = next(f for f in fp if f["severity"] == "error")["fingerprint"]
    with session_scope() as db:
        role = db.scalar(select(Role).where(Role.key == "org_admin"))
        assert role is not None
        db.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role.id,
                RolePermission.permission_key == "provisioning.check.override",
            )
        )
    make_user(admin, "tech@district.local", org, "org_admin")
    c = login(TestClient(app, base_url="http://veyra.test"), "tech@district.local", ADMIN_PASSWORD)
    ack = {"fingerprint": fp, "reason": "I am sure of it"}
    r = c.put(f"{PROFILES}/{pid}/base-edits", json={"edits": [BAD], "acknowledge": [ack]})
    assert r.status_code == 403, r.text
    # Without an acknowledgement the check still stops the save.
    r = c.put(f"{PROFILES}/{pid}/base-edits", json={"edits": [BAD]})
    assert r.status_code == 422


def test_verify_unsaved_changes(admin, app, tmp_path):
    org, profile = _setup(admin, app, tmp_path)
    pid = profile["id"]
    r = admin.post("/api/v1/provisioning/verify", json={"profile_id": pid, "base_edits": [BAD]})
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["error"] == 1
    assert admin.get(f"{PROFILES}/{pid}").json()["base_edits"] == []
    r = admin.post(
        "/api/v1/provisioning/verify",
        json={"organization_id": org, "template_key": "yealink.t4x"},
    )
    # The strict test pack warns about long labels, but nothing is refused.
    assert r.status_code == 200 and r.json()["counts"]["error"] == 0


def _fp(response):
    return next(f for f in response.json()["errors"] if f["severity"] == "error")["fingerprint"]


def test_device_inherits_profile_overrides(admin, app, tmp_path):
    org, profile = _setup(admin, app, tmp_path)
    pid = profile["id"]
    fp = _fp(admin.put(f"{PROFILES}/{pid}/base-edits", json={"edits": [BAD]}))
    ack = [{"fingerprint": fp, "reason": "Known to work on our phones"}]
    r = admin.put(f"{PROFILES}/{pid}/base-edits", json={"edits": [BAD], "acknowledge": ack})
    assert r.status_code == 200, r.text
    r = admin.post(
        "/api/v1/devices",
        json={
            "organization_id": org,
            "mac_address": "80:5E:C0:11:22:44",
            "manufacturer": "Yealink",
            "model": "T46U",
            "profile_id": pid,
        },
    )
    assert r.status_code == 201, r.text
    device = r.json()
    assert device["config_check"]["counts"]["overridden"] == 1
    assert device["config_check_summary"]["overridden"] == 1
    assert device["config_check_summary"]["open_errors"] == 0
    # A phone on another release is a new finding the profile's override does not cover.
    r = admin.patch(f"/api/v1/devices/{device['id']}", json={"label": "Room 104"})
    assert r.status_code == 200 and r.json()["config_check"] is None  # nothing checked changed


def test_variable_change_checks_the_templates_it_reaches(admin, app, tmp_path):
    org, profile = _setup(admin, app, tmp_path)
    pid = profile["id"]
    r = admin.post(
        "/api/v1/provisioning/variables",
        json={
            "scope": "organization",
            "scope_id": org,
            "name": "district_office",
            "value": "5550100",
        },
    )
    assert r.status_code == 201, r.text
    var = r.json()
    assert var["config_check"]["profiles"] == 1
    r = admin.patch(
        f"{PROFILES}/{pid}",
        json={"keys": [{"type": "speed_dial", "value": "$district_office", "label": "Office"}]},
    )
    assert r.status_code == 200, r.text
    # The speed dial's number is written into a setting of at most 99 characters.
    r = admin.patch(f"/api/v1/provisioning/variables/{var['id']}", json={"value": "5" * 120})
    assert r.status_code == 422, r.text
    errors = [f for f in r.json()["errors"] if f["severity"] == "error"]
    assert errors and errors[0]["profile_name"] == "Desk"
    assert errors[0]["parameter"].startswith("linekey.")
    # One finding per model the template serves; the dialog acknowledges them all.
    assert len({f["model"] for f in errors}) == 6
    ack = [{"fingerprint": f["fingerprint"], "reason": "Phone takes long numbers"} for f in errors]
    r = admin.patch(
        f"/api/v1/provisioning/variables/{var['id']}",
        json={"value": "5" * 120, "acknowledge": ack},
    )
    assert r.status_code == 200, r.text


def test_local_template_save_is_checked(admin, app, tmp_path):
    org, _profile = _setup(admin, app, tmp_path)
    r = admin.post(
        "/api/v1/provisioning/templates/yealink.t4x/customize",
        json={"key": "local.t4x-test", "name": "Our T4x", "organization_id": org},
    )
    assert r.status_code == 201, r.text
    doc = admin.get("/api/v1/provisioning/templates/local.t4x-test/export").json()
    sources = dict(doc["sources"])
    sources["phone.cfg.j2"] = sources["phone.cfg.j2"].replace(
        "{% endblock %}", "account.1.sip_server.1.transport_type = 7\n{% endblock %}"
    )
    tpl = doc
    body = {"manifest": tpl["manifest"], "sources": sources}
    r = admin.put("/api/v1/provisioning/templates/local.t4x-test", json=body)
    assert r.status_code == 422, r.text
    ack = [
        {"fingerprint": f["fingerprint"], "reason": "Testing a new transport"}
        for f in r.json()["errors"]
        if f["severity"] == "error"
    ]
    r = admin.put(
        "/api/v1/provisioning/templates/local.t4x-test", json={**body, "acknowledge": ack}
    )
    assert r.status_code == 200, r.text
    assert r.json()["config_check"]["counts"]["overridden"] >= 1
