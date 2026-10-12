import pytest
from sqlalchemy import text

from veyra.core.db import session_scope


def test_ping_is_public(client):
    assert client.get("/api/v1/system/ping").json() == {"status": "ok"}


def test_health_reports_real_components(admin):
    h = admin.get("/api/v1/system/health").json()
    assert h["components"]["database"]["status"] == "ok"
    assert h["components"]["telephony"]["details"]["state"] == "not_configured"
    assert h["active_calls"] is None and h["registrations"] is None  # not fabricated
    assert h["host"]["memory_total_bytes"] > 0
    assert h["cluster"]["automatic_failover"] is False


def test_system_info(admin):
    info = admin.get("/api/v1/system/info").json()
    assert info["name"] == "Test District" and info["deployment_mode"] == "standalone"


def test_ha_status_standalone(admin):
    s = admin.get("/api/v1/ha/status").json()
    assert s["ha_enabled"] is False and s["database_role"] == "primary"
    assert len(s["nodes"]) == 1 and s["nodes"][0]["role"] == "standalone"


def test_audit_log_is_append_only(admin):
    with pytest.raises(Exception, match="append-only"), session_scope() as db:
        db.execute(text("UPDATE audit_log SET action = 'tampered'"))
    with pytest.raises(Exception, match="append-only"), session_scope() as db:
        db.execute(text("DELETE FROM audit_log"))


def test_update_policies(admin):
    p = admin.get("/api/v1/updates/policies").json()
    comps = {i["component"]: i for i in p["items"]}
    assert comps["veyra_core"]["mode"] == "notify"
    assert comps["operating_system"]["mode"] == "manual"
    assert all(not i["auto_download"] for i in p["items"])
    r = admin.put(
        "/api/v1/updates/policies/veyra_core",
        json={"mode": "manual", "channel": "stable", "check_enabled": True},
    )
    assert r.status_code == 200 and r.json()["mode"] == "manual"
    r = admin.put(
        "/api/v1/updates/policies/veyra_core",
        json={
            "mode": "auto_install_window",
            "auto_install_categories": ["security"],
            "maintenance_window": {"days": ["sun"], "start": "02:00", "duration_minutes": 60},
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "not_available"


def test_update_check_without_source(admin):
    r = admin.post("/api/v1/updates/check")
    assert r.json()["outcome"] == "not_configured"
    assert admin.get("/api/v1/updates/checks/latest").json()["outcome"] == "not_configured"


def test_provisioning_api(admin):
    items = admin.get("/api/v1/provisioning/templates").json()["items"]
    assert {"poly.vvx.411", "poly.vvx.450", "poly.vvx.base"} <= {i["key"] for i in items}
    detail = admin.get("/api/v1/provisioning/templates/poly.vvx.411").json()
    assert detail["chain"] == ["poly.vvx.411", "poly.vvx.base"] and detail["validation"] == []
    r = admin.post(
        "/api/v1/provisioning/templates/poly.vvx.411/preview",
        json={
            "model": "VVX 411",
            "values": {
                "extension_number": "100",
                "sip_username": "u100",
                "sip_password": "TopSecret99",
                "sip_server": "pbx.local",
            },
        },
    )
    assert r.status_code == 200
    assert "TopSecret99" not in r.text and "********" in r.text

    exported = admin.get("/api/v1/provisioning/templates/poly.vvx.450/export").json()
    # importing over an official key is refused...
    r = admin.post("/api/v1/provisioning/templates/import", json={"document": exported})
    assert r.status_code == 422
    # ...but a local derivative with its own key is accepted
    exported["manifest"]["template"]["key"] = "district.vvx.450"
    exported["manifest"]["template"]["parent"] = "poly.vvx.base"
    assert (
        admin.post("/api/v1/provisioning/templates/validate", json={"document": exported}).json()[
            "valid"
        ]
        is True
    )
    r = admin.post("/api/v1/provisioning/templates/import", json={"document": exported})
    assert r.status_code == 201 and r.json()["source"] == "local"
    keys = {i["key"]: i for i in admin.get("/api/v1/provisioning/templates").json()["items"]}
    assert keys["district.vvx.450"]["source"] == "local"
