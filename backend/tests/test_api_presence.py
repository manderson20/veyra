# SPDX-License-Identifier: AGPL-3.0-or-later
"""Presence (docs/USER_PORTAL.md §7): a user's state with automatic actions,
shown to colleagues in the directory."""

from conftest import ADMIN_PASSWORD, login
from fake_adapter import FakeAdapter
from fastapi.testclient import TestClient

from veyra.telephony.adapter import ActiveCall, EndpointStatus


def _user(admin, email):
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    r = admin.post(
        "/api/v1/users",
        json={
            "email": email,
            "display_name": email.split("@")[0].title(),
            "password": ADMIN_PASSWORD,
            "home_organization_id": org,
            "require_password_change": False,
        },
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = admin.post(
        f"/api/v1/users/{uid}/roles",
        json={"role_key": "standard_user", "scope_type": "organization", "organization_id": org},
    )
    assert r.status_code in (200, 201), r.text
    return uid, org


def test_presence_rules_and_directory(admin, app):
    adapter = FakeAdapter()
    app.state.telephony = adapter
    uid, org = _user(admin, "pat@example.org")
    r = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org, "number": "1001", "display_name": "Pat", "user_id": uid},
    )
    ext = r.json()
    adapter.endpoints = [EndpointStatus(ext["endpoint_name"], True)]
    adapter.calls = [ActiveCall("ch1", "1001", "1002", "Up", 12, endpoint=ext["endpoint_name"])]
    pat = login(TestClient(app, base_url="http://veyra.test"), "pat@example.org", ADMIN_PASSWORD)
    base = f"/api/v1/me/extensions/{ext['id']}/presence"

    r = pat.get(base)
    assert r.status_code == 200 and r.json()["state"] == "available"
    assert [s["key"] for s in r.json()["states"]][:2] == ["available", "away"]
    # Rules: in a meeting → DND on; out → forward to the office; available → both off.
    prefs = pat.get("/api/v1/me/preferences").json()
    assert prefs["portal"] == {"presence_rules": {}}
    r = pat.put(
        "/api/v1/me/preferences",
        json={
            "companion": prefs["companion"],
            "portal": {
                "presence_rules": {
                    "meeting": {"dnd": True},
                    "out": {"dnd": False, "cf_always": "1002"},
                    "available": {"dnd": False, "cf_always": ""},
                }
            },
        },
    )
    assert r.status_code == 200, r.text
    r = pat.put("/api/v1/me/preferences", json={"portal": {"presence_rules": {"nap": {}}}})
    assert r.status_code == 422

    r = pat.put(base, json={"state": "meeting", "message": "Back at 3"})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "meeting" and r.json()["message"] == "Back at 3"
    applied = r.json()["applied"]
    assert applied == {"presence": "meeting", "presence_message": "Back at 3", "dnd": True}
    state = pat.get(f"/api/v1/me/extensions/{ext['id']}/state").json()
    assert state["dnd"] is True and state["presence"] == "meeting"
    assert adapter.states[("example", "1001")]["dnd"] == "1"  # the engine followed at once
    r = pat.put(base, json={"state": "out"})
    assert r.json()["applied"]["cf_always"] == "1002" and r.json()["applied"]["dnd"] is False
    r = pat.put(base, json={"state": "available"})
    state = pat.get(f"/api/v1/me/extensions/{ext['id']}/state").json()
    assert state["dnd"] is False and state["cf_always"] is None and state["presence"] == "available"
    assert pat.put(base, json={"state": "sleeping"}).status_code == 422

    # Colleagues see the presence, the registration and the call in the directory.
    pat.put(base, json={"state": "lunch", "message": "Until 1"})
    entries = pat.get("/api/v1/directory").json()["results"]
    me = next(e for e in entries if e["number"] == "1001")
    assert me["presence"] == "lunch" and me["presence_message"] == "Until 1"
    assert me["registered"] is True and me["on_call"] is True
    r = admin.get("/api/v1/audit", params={"action": "extension.presence_update"})
    events = r.json()["items"]
    assert events and events[0]["details"]["self_service"] is True
