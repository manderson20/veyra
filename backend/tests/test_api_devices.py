# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 9 API: sites, paging zones, device profiles, devices, firmware
images and the enrollment credential (docs/DEVICE_PROVISIONING.md)."""

import io

from conftest import ADMIN_PASSWORD, login
from fastapi.testclient import TestClient
from test_api_rbac import make_org, make_user

SITES = "/api/v1/sites"
ZONES = "/api/v1/paging-zones"
PROFILES = "/api/v1/device-profiles"
DEVICES = "/api/v1/devices"
FIRMWARE = "/api/v1/provisioning/firmware"
EXT = "/api/v1/extensions"


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _ext(admin, org_id, number, name="Front Office"):
    r = admin.post(EXT, json={"organization_id": org_id, "number": number, "display_name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _zone(admin, org_id, name="Building A", group=1, **over):
    r = admin.post(
        ZONES,
        json={
            "organization_id": org_id,
            "name": name,
            "multicast_address": "239.1.2.10",
            "multicast_port": 5004,
            "poly_group": group,
            **over,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _profile(admin, org_id, name="VVX, Building A", template="poly.vvx.base", **over):
    r = admin.post(
        PROFILES,
        json={"organization_id": org_id, "name": name, "template_key": template, **over},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_sites_crud_and_emergency_default(admin):
    org = _org(admin)
    r = admin.post(
        SITES,
        json={
            "organization_id": org["id"],
            "name": "Main Campus",
            "timezone": "America/Chicago",
            "country": "us",
            "emergency_caller_id_number": " 5735550100 ",
        },
    )
    assert r.status_code == 201, r.text
    site = r.json()
    assert site["slug"] == "main-campus" and site["country"] == "US"
    assert site["emergency_caller_id_number"] == "5735550100" and site["extensions"] == 0
    r = admin.post(SITES, json={"organization_id": org["id"], "name": "Main Campus"})
    assert r.status_code == 409 and r.json()["code"] == "name_in_use"
    r = admin.post(SITES, json={"organization_id": org["id"], "name": "x", "timezone": "Mars/Base"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "timezone"
    r = admin.patch(f"{SITES}/{site['id']}", json={"emergency_caller_id_number": "12-3"})
    assert r.status_code == 422
    r = admin.patch(f"{SITES}/{site['id']}", json={"city": "Springfield", "timezone": ""})
    assert r.status_code == 200 and r.json()["city"] == "Springfield"
    assert r.json()["timezone"] is None
    assert admin.get(SITES, params={"q": "spring"}).json()["total"] == 1
    assert admin.delete(f"{SITES}/{site['id']}").status_code == 204
    assert admin.get(f"{SITES}/{site['id']}").status_code == 404


def test_paging_zone_validation_uniqueness_and_in_use(admin):
    org = _org(admin)
    zone = _zone(admin, org["id"])
    assert zone["slug"] == "building-a" and zone["poly_address"] == "224.0.1.116"
    assert zone["poly_port"] == 5001 and zone["kind"] == "normal" and zone["problems"] == []
    r = admin.post(
        ZONES,
        json={
            "organization_id": org["id"],
            "name": "Bad",
            "multicast_address": "10.0.0.1",
            "multicast_port": 5004,
            "poly_group": 2,
        },
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "multicast_address"
    r = admin.post(
        ZONES,
        json={
            "organization_id": org["id"],
            "name": "Dup group",
            "multicast_address": "239.1.2.11",
            "multicast_port": 5004,
            "poly_group": 1,
        },
    )
    assert r.status_code == 409 and r.json()["code"] == "poly_group_in_use"
    other = _zone(admin, org["id"], "Building B", 25, kind="emergency", poly_port=5003)
    listing = admin.get(ZONES).json()["items"]
    assert [z["poly_group"] for z in listing] == [1, 25]
    # Poly phones listen on one address and port: differing zones are flagged.
    assert any("different Poly paging" in p for p in listing[0]["problems"])
    r = admin.patch(f"{ZONES}/{other['id']}", json={"poly_port": 5001, "poly_group": 3})
    assert r.status_code == 200
    assert any("group 25" in p for p in r.json()["problems"])  # emergency kind, group 3
    profile = _profile(admin, org["id"], paging=[{"zone_id": zone["id"], "role": "default"}])
    assert profile["paging"][0]["zone_name"] == "Building A"
    r = admin.delete(f"{ZONES}/{zone['id']}")
    assert r.status_code == 409 and r.json()["code"] == "zone_in_use"
    assert admin.get(f"{ZONES}/{zone['id']}").json()["profiles"][0]["name"] == profile["name"]
    assert admin.delete(f"{ZONES}/{other['id']}").status_code == 204


def test_device_profile_resolves_family_values_keys_and_paging(admin):
    org = _org(admin)
    zone = _zone(admin, org["id"])
    r = admin.post(
        PROFILES,
        json={"organization_id": org["id"], "name": "x", "template_key": "poly.vvx.nope"},
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "template_key"
    r = admin.post(
        PROFILES,
        json={
            "organization_id": org["id"],
            "name": "x",
            "template_key": "poly.vvx.base",
            "values": {"sip_transport": "SCTP"},
        },
    )
    assert r.status_code == 422 and "sip_transport" in r.json()["errors"][0]["message"]
    r = admin.post(
        PROFILES,
        json={
            "organization_id": org["id"],
            "name": "x",
            "template_key": "poly.vvx.base",
            "values": {"sip_password": "no"},
        },
    )
    assert r.status_code == 422
    r = admin.post(
        PROFILES,
        json={
            "organization_id": org["id"],
            "name": "x",
            "template_key": "poly.vvx.base",
            "keys": [{"type": "page", "value": "nowhere"}],
        },
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "keys"
    profile = _profile(
        admin,
        org["id"],
        values={"sip_transport": "TCPOnly", "registration_expires": "600", "ntp_server": ""},
        keys=[
            {"type": "line", "value": "1"},
            {"type": "blf", "label": "Front", "value": "1001"},
            {"type": "page", "value": "building-a"},
        ],
        paging=[{"zone_id": zone["id"], "role": "default", "transmit": True}],
    )
    # An abstract family resolves to the model templates underneath it.
    assert profile["template_abstract"] is True and profile["manufacturer"] == "Poly"
    assert profile["models"] == {"VVX 411": "poly.vvx.411", "VVX 450": "poly.vvx.450"}
    assert profile["values"] == {"sip_transport": "TCPOnly", "registration_expires": 600}
    assert profile["keys"][1]["label"] == "Front" and profile["paging"][0]["poly_group"] == 1
    r = admin.patch(f"{PROFILES}/{profile['id']}", json={"template_key": "poly.vvx.411"})
    assert r.status_code == 200 and r.json()["models"] == {"VVX 411": "poly.vvx.411"}
    r = admin.patch(
        f"{PROFILES}/{profile['id']}",
        json={"paging": [{"zone_id": zone["id"], "role": "default"}, {"zone_id": zone["id"]}]},
    )
    assert r.status_code == 422 and "twice" in r.json()["errors"][0]["message"]
    r = admin.post(
        PROFILES,
        json={
            "organization_id": org["id"],
            "name": profile["name"],
            "template_key": "poly.vvx.base",
        },
    )
    assert r.status_code == 409 and r.json()["code"] == "name_in_use"


def test_devices_register_resolve_template_status_and_unregistered(admin, app):
    org = _org(admin)
    ext = _ext(admin, org["id"], "1001")
    other = _ext(admin, org["id"], "1002", "Library")
    profile = _profile(admin, org["id"])
    r = admin.post(
        DEVICES,
        json={
            "organization_id": org["id"],
            "mac_address": "00:04:F2:AB:CD:EF",
            "manufacturer": "Poly",
            "model": "VVX 411",
            "label": "Room 112",
            "profile_id": profile["id"],
            "primary_extension_id": ext["id"],
            "lines": [other["id"]],
        },
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["mac_address"] == "0004f2abcdef" and d["mac_display"] == "00:04:f2:ab:cd:ef"
    assert d["template_key"] == "poly.vvx.411" and d["status"] == "never"
    assert d["extension"]["number"] == "1001" and d["lines"][0]["number"] == "1002"
    assert d["credential_user"] == "dev-0004f2abcdef" and d["problems"] == []
    assert d["firmware_state"] == "none"
    # Duplicate MAC, unknown model under the family, foreign extension.
    r = admin.post(
        DEVICES,
        json={
            "organization_id": org["id"],
            "mac_address": "0004f2abcdef",
            "manufacturer": "Poly",
            "model": "VVX 411",
        },
    )
    assert r.status_code == 409 and r.json()["code"] == "mac_in_use"
    r = admin.patch(f"{DEVICES}/{d['id']}", json={"model": "VVX 999"})
    assert r.status_code == 200 and r.json()["template_key"] is None
    assert any("supports model VVX 999" in p for p in r.json()["problems"])
    assert admin.patch(f"{DEVICES}/{d['id']}", json={"model": "VVX 411"}).json()["problems"] == []
    r = admin.patch(f"{DEVICES}/{d['id']}", json={"lines": [ext["id"]]})
    assert r.status_code == 422 and "twice" in r.json()["errors"][0]["message"]
    r = admin.patch(f"{DEVICES}/{d['id']}", json={"values": {"sip_transport": "TLS"}})
    assert r.status_code == 200 and r.json()["values"] == {"sip_transport": "TLS"}
    r = admin.patch(f"{DEVICES}/{d['id']}", json={"keys": [{"type": "speed_dial", "value": "9"}]})
    assert r.status_code == 200 and r.json()["keys"][0]["type"] == "speed_dial"
    assert admin.get(DEVICES, params={"q": "04:f2:ab"}).json()["total"] == 1
    assert admin.get(DEVICES, params={"q": "1001"}).json()["total"] == 1
    assert admin.get(DEVICES, params={"extension_id": other["id"]}).json()["total"] == 1
    assert admin.get(DEVICES, params={"q": "zzz"}).json()["total"] == 0
    # Profiles in use cannot be deleted; deleting the extension clears line 1.
    r = admin.delete(f"{PROFILES}/{profile['id']}")
    assert r.status_code == 409 and r.json()["code"] == "profile_in_use"
    assert admin.delete(f"{EXT}/{ext['id']}").status_code == 204
    d2 = admin.get(f"{DEVICES}/{d['id']}").json()
    assert d2["extension"] is None and "No extension" in d2["problems"][0]
    assert admin.get(f"{DEVICES}/unregistered").json() == []
    assert admin.delete(f"{DEVICES}/{d['id']}").status_code == 204
    assert admin.delete(f"{PROFILES}/{profile['id']}").status_code == 204
    audit = admin.get("/api/v1/audit", params={"q": "device"}).json()
    assert any(e["action"] == "device.create" for e in audit["items"])


def test_firmware_upload_assign_and_delete(admin):
    org = _org(admin)
    files = {
        "file": ("sip.ld", io.BytesIO(b"\x00firmware-bytes" * 100), "application/octet-stream")
    }
    r = admin.post(
        FIRMWARE,
        data={"manufacturer": "Poly", "version": "6.4.5.1234", "models": "VVX 411, VVX 450"},
        files=files,
    )
    assert r.status_code == 201, r.text
    fw = r.json()
    assert fw["models"] == ["VVX 411", "VVX 450"] and fw["size"] == 1500
    assert fw["url"].endswith(f"/{fw['id']}/sip.ld") and len(fw["sha256"]) == 64
    r = admin.post(
        FIRMWARE,
        data={"manufacturer": "Poly", "version": "6.4.5.1234"},
        files={"file": ("sip.ld", io.BytesIO(b"x"), "application/octet-stream")},
    )
    assert r.status_code == 409 and r.json()["code"] == "firmware_exists"
    r = admin.post(
        FIRMWARE,
        data={"manufacturer": "Poly", "version": "1"},
        files={"file": ("../evil.ld", io.BytesIO(b"x"), "application/octet-stream")},
    )
    assert r.status_code in (201, 422)  # the path is reduced to its last segment
    profile = _profile(admin, org["id"], firmware_image_id=fw["id"])
    assert profile["firmware"]["version"] == "6.4.5.1234"
    r = admin.post(
        PROFILES,
        json={
            "organization_id": org["id"],
            "name": "Yealink",
            "template_key": "poly.vvx.base",
            "firmware_image_id": fw["id"],
        },
    )
    assert r.status_code == 201  # same manufacturer
    second = r.json()["id"]
    r = admin.delete(f"{FIRMWARE}/{fw['id']}")
    assert r.status_code == 409 and r.json()["code"] == "firmware_in_use"
    assert admin.get(FIRMWARE).json()["items"][0]["profiles"] == 2
    admin.delete(f"{PROFILES}/{profile['id']}")
    r = admin.patch(f"{PROFILES}/{second}", json={"firmware_image_id": None})
    assert r.status_code == 200 and r.json()["firmware"] is None
    assert admin.delete(f"{FIRMWARE}/{fw['id']}").status_code == 204


def test_enrollment_credential_rotation_and_scoping(admin, app):
    org = _org(admin)
    r = admin.get(f"/api/v1/organizations/{org['id']}/provisioning-credential")
    assert r.status_code == 200 and r.json()["username"] is None
    assert r.json()["url"].endswith("/provisioning/")
    r = admin.post(f"/api/v1/organizations/{org['id']}/provisioning-credential/rotate")
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["username"] == f"veyra-{org['slug']}" and len(first["password"]) == 24
    r = admin.post(f"/api/v1/organizations/{org['id']}/provisioning-credential/rotate")
    assert r.json()["password"] != first["password"]
    assert (
        "password"
        not in admin.get(f"/api/v1/organizations/{org['id']}/provisioning-credential").json()
    )
    # A technician of another organization sees nothing of this one.
    other = make_org(admin, "other")
    make_user(admin, "tech@example.org", other, role="technician")
    tech = login(TestClient(app, base_url="http://veyra.test"), "tech@example.org", ADMIN_PASSWORD)
    assert tech.get(f"/api/v1/organizations/{org['id']}/provisioning-credential").status_code == 403
    assert tech.get(DEVICES).json()["total"] == 0
    assert tech.get(PROFILES).json()["total"] == 0
    assert (
        tech.post(f"/api/v1/organizations/{other}/provisioning-credential/rotate").status_code
        == 200
    )
    zone = {
        "organization_id": other,
        "name": "z",
        "multicast_address": "239.1.1.1",
        "multicast_port": 5004,
        "poly_group": 1,
    }
    assert tech.post(ZONES, json=zone).status_code == 403  # technicians read paging zones only
