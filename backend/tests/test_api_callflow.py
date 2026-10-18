# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 19 API: announcements, conference rooms, the directory, and the
new destination kinds everywhere a destination is stored (docs/CALL_FEATURES.md
§4.1-§4.3)."""

from fake_adapter import FakeAdapter
from test_api_ivr import _ext, _org, _upload

from veyra.configmgmt import service
from veyra.core.db import session_scope
from veyra.core.security.crypto import load_installation_key

ANN = "/api/v1/announcements"
CONF = "/api/v1/conferences"
INBOUND = "/api/v1/routing/inbound"
IVR = "/api/v1/ivr"
RG = "/api/v1/ring-groups"


def _fake(app, tmp_path):
    adapter = FakeAdapter(prompts_dir=app.state.settings.prompts_dir)
    app.state.telephony = adapter
    cfg = tmp_path / "asterisk-veyra"
    cfg.mkdir(exist_ok=True)
    app.state.settings.asterisk_config_dir = cfg
    return adapter, service.Deployer(adapter, cfg, load_installation_key(app.state.settings)), cfg


def test_announcement_crud_destinations_and_uses(admin, app):
    org = _org(admin)
    ext = _ext(admin, org["id"], "3001")
    prompt = _upload(admin, org["id"], "Closed Today")
    # Minimal create: hangs up afterwards and is flagged until a prompt is set.
    r = admin.post(ANN, json={"organization_id": org["id"], "name": "Closed notice"})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["slug"] == "closed-notice" and a["context"] == "veyra-ann-closed-notice"
    assert a["destination"]["type"] == "hangup" and a["in_use_by"] == 0
    assert any("No prompt" in p for p in a["problems"])
    # Full update: prompt, keys, destination to an extension.
    r = admin.patch(
        f"{ANN}/{a['id']}",
        json={
            "prompt_id": prompt["id"],
            "allow_skip": True,
            "repeat_key": "9",
            "destination": {"type": "extension", "extension_id": ext["id"]},
        },
    )
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["prompt_name"] == "Closed Today" and a["allow_skip"] and a["repeat_key"] == "9"
    assert a["destination"]["label"].startswith("3001") and a["problems"] == []
    # The prompt counts the announcement as a use.
    p = admin.get(f"/api/v1/prompts/{prompt['id']}").json()
    assert p["in_use_by"] == 1
    # Validation: bad repeat key, self reference, prompt of another organization.
    assert admin.patch(f"{ANN}/{a['id']}", json={"repeat_key": "A"}).status_code == 422
    r = admin.patch(
        f"{ANN}/{a['id']}",
        json={"destination": {"type": "announcement", "announcement_id": a["id"]}},
    )
    assert r.status_code == 422 and "itself" in r.text
    r = admin.post(
        ANN,
        json={
            "organization_id": org["id"],
            "name": "Foreign",
            "prompt_id": "00000000-0000-0000-0000-000000000001",
        },
    )
    assert r.status_code == 422 and "prompt not found" in r.text
    # A second announcement continues to the first; the first is then in use
    # and cannot be deleted; a route may point at either.
    r = admin.post(
        ANN,
        json={
            "organization_id": org["id"],
            "name": "Disclaimer",
            "prompt_id": prompt["id"],
            "destination": {"type": "announcement", "announcement_id": a["id"]},
        },
    )
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["destination"]["label"] == "Announcement: Closed notice"
    assert admin.get(f"{ANN}/{a['id']}").json()["in_use_by"] == 1
    r = admin.delete(f"{ANN}/{a['id']}")
    assert r.status_code == 409 and "announcement Disclaimer" in r.text
    r = admin.post(
        INBOUND,
        json={
            "organization_id": org["id"],
            "did": "5735550101",
            "destination_type": "announcement",
            "destination_announcement_id": b["id"],
        },
    )
    assert r.status_code == 201, r.text
    route = r.json()
    assert (
        route["destination"]["type"] == "announcement"
        and route["destination_announcement_id"] == b["id"]
    )
    assert admin.get(f"{ANN}/{b['id']}").json()["in_use_by"] == 1
    # Directory destination needs no target; a disabled announcement is refused.
    r = admin.patch(f"{INBOUND}/{route['id']}", json={"destination_type": "directory"})
    assert r.status_code == 200, r.text
    assert r.json()["destination"]["label"] == "Dial-by-name directory"
    admin.patch(f"{ANN}/{b['id']}", json={"is_enabled": False})
    r = admin.patch(
        f"{INBOUND}/{route['id']}",
        json={"destination_type": "announcement", "destination_announcement_id": b["id"]},
    )
    assert r.status_code == 422 and "disabled" in r.text
    # Delete the chain once nothing points at it.
    assert admin.delete(f"{ANN}/{b['id']}").status_code == 204
    assert admin.delete(f"{ANN}/{a['id']}").status_code == 204
    assert admin.get(ANN).json()["total"] == 0


def test_conference_room_crud_pins_numbers_and_destination(admin, app):
    org = _org(admin)
    ext = _ext(admin, org["id"], "3002")
    r = admin.post(
        CONF, json={"organization_id": org["id"], "name": "Board room", "number": "3500"}
    )
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["slug"] == "board-room" and c["context"] == "veyra-conf-board-room"
    assert not c["has_user_pin"] and not c["has_admin_pin"] and c["max_participants"] == 0
    # The number space is shared with extensions and other rooms.
    r = admin.post(CONF, json={"organization_id": org["id"], "name": "Clash", "number": "3002"})
    assert r.status_code == 409 and r.json()["code"] == "number_in_use"
    r = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "3500", "display_name": "Clash"},
    )
    assert r.status_code == 409, r.text
    # PINs: format, difference, write-only; wait_for_admin without an admin PIN is flagged.
    assert admin.patch(f"{CONF}/{c['id']}", json={"user_pin": "12"}).status_code == 422
    r = admin.patch(f"{CONF}/{c['id']}", json={"user_pin": "1234", "admin_pin": "1234"})
    assert r.status_code == 422 and "differ" in r.text
    r = admin.patch(
        f"{CONF}/{c['id']}",
        json={
            "user_pin": "1234",
            "admin_pin": "9876",
            "wait_for_admin": True,
            "max_participants": 12,
            "record": True,
        },
    )
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["has_user_pin"] and c["has_admin_pin"] and c["problems"] == []
    assert "user_pin" not in c and "admin_pin" not in c
    # Changing one PIN to the other's value is caught against the stored PIN.
    r = admin.patch(f"{CONF}/{c['id']}", json={"user_pin": "9876"})
    assert r.status_code == 422 and "differ" in r.text
    r = admin.patch(f"{CONF}/{c['id']}", json={"admin_pin": None})
    assert r.status_code == 200 and not r.json()["has_admin_pin"]
    assert any("administrator PIN" in p for p in r.json()["problems"])
    # As a destination from an IVR key and a ring group failover; then in use.
    menu = admin.post(IVR, json={"organization_id": org["id"], "name": "Main"}).json()
    r = admin.patch(
        f"{IVR}/{menu['id']}",
        json={
            "entries": [
                {"digit": "5", "destination": {"type": "conference", "conference_id": c["id"]}}
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["entries"][0]["destination"]["label"] == "Conference: Board room (3500)"
    r = admin.post(
        RG,
        json={
            "organization_id": org["id"],
            "name": "Sales",
            "number": "3600",
            "members": [ext["id"]],
            "failover": {"type": "conference", "conference_id": c["id"]},
        },
    )
    assert r.status_code == 201, r.text
    assert admin.get(f"{CONF}/{c['id']}").json()["in_use_by"] == 2
    r = admin.delete(f"{CONF}/{c['id']}")
    assert r.status_code == 409 and r.json()["code"] == "conference_in_use"
    # Search by number; the list is scoped.
    assert admin.get(CONF, params={"q": "3500"}).json()["total"] == 1
    assert admin.get(CONF, params={"q": "nothing"}).json()["total"] == 0


def test_callflow_objects_deploy(admin, app, tmp_path):
    org = _org(admin)
    _ext(admin, org["id"], "3003")
    prompt = _upload(admin, org["id"], "Welcome Note")
    room = admin.post(
        CONF,
        json={
            "organization_id": org["id"],
            "name": "Staff room",
            "number": "3501",
            "user_pin": "2468",
            "admin_pin": "1357",
            "record": True,
        },
    ).json()
    ann = admin.post(
        ANN,
        json={
            "organization_id": org["id"],
            "name": "Welcome",
            "prompt_id": prompt["id"],
            "allow_skip": True,
            "destination": {"type": "conference", "conference_id": room["id"]},
        },
    ).json()
    admin.post(
        INBOUND,
        json={
            "organization_id": org["id"],
            "did": "5735550102",
            "destination_type": "announcement",
            "destination_announcement_id": ann["id"],
        },
    )
    admin.post(
        INBOUND,
        json={"organization_id": org["id"], "did": "5735550103", "destination_type": "directory"},
    )
    adapter, deployer, cfg = _fake(app, tmp_path)
    r = admin.post("/api/v1/telephony/apply", json={})
    assert r.status_code in (200, 202), r.text
    with session_scope() as db:
        deployer.run_once(db)
    dialplan = (cfg / "extensions.conf").read_text()
    confbridge = (cfg / "confbridge.conf").read_text()
    assert "[veyra-ann-welcome]" in dialplan and "Background(" in dialplan
    assert "Goto(veyra-conf-staff-room,s,1)" in dialplan
    assert 'GotoIf($["${VEYRA_PIN}"="1357"]?admin)' in dialplan
    assert 'GotoIf($["${VEYRA_PIN}"="2468"]?join)' in dialplan
    assert "exten => 3501,hint,confbridge:veyra-conf-staff-room" in dialplan
    assert "Goto(veyra-directory,s,1)" in dialplan and "[veyra-directory]" in dialplan
    assert "[veyra-conf-staff-room-bridge]" in confbridge and "record_conference=yes" in confbridge
    assert "app_confbridge.so" in adapter.reloads and "pbx_config.so" in adapter.reloads


LOTS = "/api/v1/parking-lots"


def test_parking_lot_crud_and_number_space(admin, app, tmp_path):
    org = _org(admin)
    ext = _ext(admin, org["id"], "3010")
    r = admin.post(
        LOTS,
        json={
            "organization_id": org["id"],
            "name": "Front office",
            "park_exten": "7000",
            "slot_first": 7001,
            "slot_last": 7004,
        },
    )
    assert r.status_code == 201, r.text
    lot = r.json()
    assert lot["slug"] == "front-office" and lot["slots"] == ["7001", "7002", "7003", "7004"]
    assert lot["timeout"]["type"] == "hangup" and lot["problems"] == []
    # Numbers of the lot are taken for everything else in the organization.
    r = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "7002", "display_name": "Clash"},
    )
    assert r.status_code == 409 and "parking lot" in r.text
    r = admin.post(
        "/api/v1/conferences", json={"organization_id": org["id"], "name": "Room", "number": "7000"}
    )
    assert r.status_code == 409 and "parking lot" in r.text
    # ... and the lot cannot take an extension's number or overlap another lot.
    r = admin.post(
        LOTS,
        json={
            "organization_id": org["id"],
            "name": "Clash",
            "park_exten": "3010",
            "slot_first": 7081,
            "slot_last": 7082,
        },
    )
    assert r.status_code == 409 and r.json()["code"] == "number_in_use"
    r = admin.post(
        LOTS,
        json={
            "organization_id": org["id"],
            "name": "Overlap",
            "park_exten": "7080",
            "slot_first": 7003,
            "slot_last": 7006,
        },
    )
    assert r.status_code == 409 and "parking lot" in r.text
    # Shape rules: park extension inside the slots, reversed range, too many slots.
    assert (
        admin.post(
            LOTS,
            json={
                "organization_id": org["id"],
                "name": "Bad",
                "park_exten": "7092",
                "slot_first": 7090,
                "slot_last": 7095,
            },
        ).status_code
        == 422
    )
    assert (
        admin.post(
            LOTS,
            json={
                "organization_id": org["id"],
                "name": "Bad",
                "park_exten": "7090",
                "slot_first": 7095,
                "slot_last": 7091,
            },
        ).status_code
        == 422
    )
    assert (
        admin.post(
            LOTS,
            json={
                "organization_id": org["id"],
                "name": "Bad",
                "park_exten": "7100",
                "slot_first": 7101,
                "slot_last": 7199,
            },
        ).status_code
        == 422
    )
    # Growing the lot over its own numbers is fine; destination and timeouts update.
    r = admin.patch(
        f"{LOTS}/{lot['id']}",
        json={
            "slot_last": 7009,
            "timeout_seconds": 60,
            "timeout": {"type": "extension", "extension_id": ext["id"]},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["slots"][-1] == "7009" and r.json()["timeout"]["label"].startswith("3010")
    # Deployment writes res_parking.conf and the timeout context.
    adapter, deployer, cfg = _fake(app, tmp_path)
    r = admin.post("/api/v1/telephony/apply", json={})
    assert r.status_code in (200, 202), r.text
    with session_scope() as db:
        deployer.run_once(db)
    conf = (cfg / "res_parking.conf").read_text()
    assert (
        "[veyra-park-front-office]" in conf
        and "parkpos=7001-7009" in conf
        and "parkingtime=60" in conf
    )
    dp = (cfg / "extensions.conf").read_text()
    assert "include => veyra-park-front-office" in dp and "[veyra-park-front-office-timeout]" in dp
    assert "res_parking.so" in adapter.reloads
    assert admin.delete(f"{LOTS}/{lot['id']}").status_code == 204
    # The numbers are free again.
    r = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "7002", "display_name": "Fine"},
    )
    assert r.status_code == 201, r.text
