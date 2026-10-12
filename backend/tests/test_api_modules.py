from conftest import make_settings
from sqlalchemy import inspect

from veyra.core.db import get_engine

MOD = "veyra.example-notes"
NOTES = "/api/v1/ext/example-notes/notes"


def install_and_enable(admin):
    assert admin.post(f"/api/v1/modules/{MOD}/install").status_code == 200
    assert admin.post(f"/api/v1/modules/{MOD}/enable").status_code == 200


def test_module_listed_as_available(admin):
    items = {m["module_id"]: m for m in admin.get("/api/v1/modules").json()["items"]}
    m = items[MOD]
    assert m["state"] == "available" and m["available_version"] == "0.1.0"
    assert m["signature_verified"] is False and m["trust_level"] == "unsigned"


def test_full_lifecycle(admin):
    install_and_enable(admin)
    assert "mod_example_notes_note" in inspect(get_engine()).get_table_names()

    r = admin.post(NOTES, json={"title": "Fire drill", "body": "Tuesday 10:00"})
    assert r.status_code == 201, r.text
    listing = admin.get(NOTES).json()
    assert listing["total"] == 1 and listing["items"][0]["title"] == "Fire drill"

    ext = admin.get("/api/v1/modules/ui-extensions").json()
    assert ext[0]["module_id"] == MOD and ext[0]["views"][0]["id"] == "notes"
    assert ext[0]["api_base"] == "/api/v1/ext/example-notes"

    detail = admin.get(f"/api/v1/modules/{MOD}").json()
    assert detail["state"] == "enabled" and detail["health"]["status"] == "ok"

    health = admin.get("/api/v1/system/health").json()["components"]["modules"]
    assert health["details"]["modules"][0]["health"] == "ok"

    # disabling hides the API but keeps the data
    assert admin.post(f"/api/v1/modules/{MOD}/disable").status_code == 200
    assert admin.get(NOTES).status_code == 404
    assert admin.get("/api/v1/modules/ui-extensions").json() == []
    assert admin.post(f"/api/v1/modules/{MOD}/enable").status_code == 200
    assert admin.get(NOTES).json()["total"] == 1

    # uninstall without purge keeps tables and data
    admin.post(f"/api/v1/modules/{MOD}/disable")
    assert admin.post(f"/api/v1/modules/{MOD}/uninstall", json={}).status_code == 200
    assert "mod_example_notes_note" in inspect(get_engine()).get_table_names()
    assert admin.get(f"/api/v1/modules/{MOD}").json()["state"] == "removed"

    # purge requires typed confirmation, then drops the module's tables
    r = admin.post(f"/api/v1/modules/{MOD}/uninstall", json={"purge_data": True})
    assert r.status_code == 422
    r = admin.post(
        f"/api/v1/modules/{MOD}/uninstall", json={"purge_data": True, "confirm_module_id": MOD}
    )
    assert r.status_code == 200
    assert "mod_example_notes_note" not in inspect(get_engine()).get_table_names()

    actions = [
        e["action"] for e in admin.get("/api/v1/audit", params={"q": "module."}).json()["items"]
    ]
    assert {"module.install", "module.enable", "module.disable", "module.uninstall"} <= set(actions)


def test_cannot_uninstall_enabled_module(admin):
    install_and_enable(admin)
    r = admin.post(f"/api/v1/modules/{MOD}/uninstall", json={})
    assert r.status_code == 409


def test_module_permissions_granted_to_roles(admin):
    install_and_enable(admin)
    perms = admin.get("/api/v1/auth/session").json()["permissions"]
    assert "example_notes.read" in perms


def test_unsigned_module_refused_in_production(database_url, tmp_path, db_ready):
    from conftest import complete_setup, csrf_headers
    from fastapi.testclient import TestClient

    from veyra.main import create_app

    settings = make_settings(
        database_url, tmp_path, environment="production", allow_unsigned_modules=True
    )
    with TestClient(create_app(settings), base_url="http://veyra.test") as c:
        complete_setup(c)
        c.headers.update(csrf_headers(c))
        r = c.post(f"/api/v1/modules/{MOD}/install")
        assert r.status_code == 409
        assert "verification failed" in r.json()["errors"][0]["message"]
