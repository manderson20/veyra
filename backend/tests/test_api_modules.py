# SPDX-License-Identifier: AGPL-3.0-or-later
import uuid

import pytest
from conftest import REPO, make_settings
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

    # The view declares search (module API 1.3); the page sends q.
    assert admin.post(NOTES, json={"title": "Lunch menu", "body": "100% pizza"}).status_code == 201
    assert [n["title"] for n in admin.get(NOTES, params={"q": "drill"}).json()["items"]] == [
        "Fire drill"
    ]
    assert admin.get(NOTES, params={"q": "100%"}).json()["total"] == 1
    assert admin.get(NOTES, params={"q": "0%z"}).json()["total"] == 0
    assert admin.delete(
        f"{NOTES}/{admin.get(NOTES, params={'q': 'Lunch'}).json()['items'][0]['id']}"
    ).status_code in (200, 204)

    ext = admin.get("/api/v1/modules/ui-extensions").json()
    assert ext[0]["module_id"] == MOD and ext[0]["views"][0]["id"] == "notes"
    assert ext[0]["views"][0]["search"] is True and ext[0]["views"][0]["filters"] == []
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


def test_core_data_for_modules(app, admin):
    """#149: module API 1.3 read-only core data, without secrets."""
    import dataclasses

    from veyra.core.db import session_scope
    from veyra.core.events import EventBus
    from veyra.modules.context import ModuleContext
    from veyra.modules.manifest import load_manifest
    from veyra.sdk import ExtensionInfo

    org = admin.get("/api/v1/organizations").json()["items"][0]
    r = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "2101", "display_name": "Front desk"},
    )
    assert r.status_code == 201, r.text
    manifest = load_manifest(REPO / "modules" / "veyra-example-notes")
    ctx = ModuleContext(manifest, REPO, REPO, EventBus())
    org_id = uuid.UUID(org["id"])
    with session_scope() as db:
        assert org_id in {o.id for o in ctx.organizations(db)}
        exts = ctx.extensions(db, org_id)
        assert [e.number for e in exts] == ["2101"] and isinstance(exts[0], ExtensionInfo)
        assert ctx.extensions(db, org_id, number="9999") == []
        assert ctx.extension(db, exts[0].id) == exts[0]
        assert ctx.devices(db, org_id) == []
        fields = {f.name for f in dataclasses.fields(ExtensionInfo)}
        assert not any("secret" in f or "pin" in f for f in fields)
        with pytest.raises(dataclasses.FrozenInstanceError):
            exts[0].number = "1"  # type: ignore[misc]


def test_unmet_python_requirement_refuses_install(app):
    """#149: a module whose [runtime] requires is not met cannot be installed."""
    from veyra.core.db import session_scope
    from veyra.modules.manifest import Manifest, load_manifest

    data = load_manifest(REPO / "modules" / "veyra-example-notes").model_dump(mode="json")
    data["runtime"]["requires"] = ["surely-not-installed-lib>=1.0"]
    with session_scope() as db:
        problems = app.state.modules.compatibility_problems(db, Manifest.model_validate(data))
    assert any("surely-not-installed-lib" in p for p in problems)


def test_view_filter_keys_are_checked():
    """#149: filter keys cannot shadow q, limit or offset."""
    from veyra.modules.manifest import UiFilter

    assert UiFilter(key="status", label="Status", choices=["open"]).key == "status"
    for bad in ("q", "offset", "Status", "a-b"):
        with pytest.raises(ValueError):
            UiFilter(key=bad, label="X", choices=["a"])
