# SPDX-License-Identifier: AGPL-3.0-or-later
"""User-set phone keys in the slots a profile leaves open, administrator keys
locked (docs/USER_PORTAL.md §8)."""

from conftest import ADMIN_PASSWORD, login
from fastapi.testclient import TestClient

from veyra.provisioning import facts
from veyra.telephony.asterisk import cli


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


def test_user_keys_in_open_slots_locked_elsewhere(admin, app, monkeypatch):
    uid, org = _user(admin, "pat@example.org")
    mine = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org, "number": "1001", "display_name": "Pat", "user_id": uid},
    ).json()
    admin.post(
        "/api/v1/extensions",
        json={"organization_id": org, "number": "1002", "display_name": "Office"},
    )
    templates = admin.get("/api/v1/provisioning/templates").json()
    template_key = next(
        t["key"]
        for t in (templates if isinstance(templates, list) else templates["items"])
        if "vvx" in t["key"]
    )
    # Profile: line 1, the all-call key (locked), two open slots.
    r = admin.post(
        "/api/v1/device-profiles",
        json={
            "organization_id": org,
            "name": "Classroom",
            "template_key": template_key,
            "keys": [
                {"type": "line", "value": "1"},
                {"type": "speed_dial", "label": "ALL CALL", "value": "*700"},
                {"type": "user"},
                {"type": "user"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    profile = r.json()
    r = admin.post(
        "/api/v1/devices",
        json={
            "organization_id": org,
            "mac_address": "0004f2aabbcc",
            "manufacturer": "Poly",
            "model": "VVX 450",
            "profile_id": profile["id"],
            "primary_extension_id": mine["id"],
        },
    )
    assert r.status_code == 201, r.text
    device = r.json()

    pat = login(TestClient(app, base_url="http://veyra.test"), "pat@example.org", ADMIN_PASSWORD)
    phones = pat.get("/api/v1/me/devices").json()
    assert len(phones) == 1 and phones[0]["user_slots"] == 2
    slots = phones[0]["slots"]
    assert [s["kind"] for s in slots] == ["locked", "locked", "user", "user"]
    assert slots[1]["label"] == "ALL CALL" and slots[2]["type"] is None

    sent = []
    monkeypatch.setattr(
        cli, "send_notify", lambda action, ep: sent.append((action, ep)) or (True, "ok")
    )
    app.state.telephony = object()  # an engine is present: the phone is told to resync
    contact = pat.post(
        "/api/v1/me/contacts",
        json={"name": "Bus Garage", "numbers": [{"label": "work", "number": "5735550199"}]},
    ).json()
    r = pat.put(
        f"/api/v1/me/devices/{device['id']}/keys",
        json={
            "keys": {
                "3": {"type": "blf", "value": "1002", "label": "Office"},
                "4": {"type": "speed_dial", "value": "5735550199", "contact_id": contact["id"]},
            }
        },
    )
    assert r.status_code == 200, r.text
    slots = r.json()["slots"]
    assert slots[2] == {
        "index": 3,
        "kind": "user",
        "type": "blf",
        "label": "Office",
        "value": "1002",
    }
    assert slots[3]["label"] == "Bus Garage" and slots[3]["value"] == "5735550199"
    assert sent == [("check_config", mine["endpoint_name"])]
    # Locked slots and unknown BLF targets are refused.
    r = pat.put(
        f"/api/v1/me/devices/{device['id']}/keys",
        json={"keys": {"2": {"type": "speed_dial", "value": "1"}}},
    )
    assert r.status_code == 422 and r.json()["code"] == "slot_locked"
    r = pat.put(
        f"/api/v1/me/devices/{device['id']}/keys",
        json={"keys": {"3": {"type": "blf", "value": "9999"}}},
    )
    assert r.status_code == 422
    # The administrator sees the user's keys on the device; the rendered key list carries both.
    d = admin.get(f"/api/v1/devices/{device['id']}").json()
    assert d["user_keys"]["3"]["value"] == "1002" and d["keys"] is None
    merged = facts.merge_user_keys(profile["keys"], d["user_keys"])
    assert [k["type"] for k in merged] == ["line", "speed_dial", "blf", "speed_dial"]
    assert merged[1]["value"] == "*700" and merged[3]["label"] == "Bus Garage"
    # Emptying a slot: the key disappears; the locked ones stay.
    r = pat.put(f"/api/v1/me/devices/{device['id']}/keys", json={"keys": {"3": None}})
    assert r.status_code == 200 and r.json()["slots"][2]["type"] is None
    assert r.json()["slots"][1]["value"] == "*700"
    # Another user has no phones here.
    _user(admin, "sam@example.org")
    sam = login(TestClient(app, base_url="http://veyra.test"), "sam@example.org", ADMIN_PASSWORD)
    assert sam.get("/api/v1/me/devices").json() == []
    assert sam.put(f"/api/v1/me/devices/{device['id']}/keys", json={"keys": {}}).status_code == 404
    events = [
        e
        for e in admin.get("/api/v1/audit", params={"q": "device.user_keys"}).json()["items"]
        if e["action"] == "device.user_keys"
    ]
    assert events and events[0]["details"].get("self_service") is True, events[0]
