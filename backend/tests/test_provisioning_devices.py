# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 9: daylight-saving rules, device rendering with structured facts,
the phone-facing provisioning server (docs/DEVICE_PROVISIONING.md §3, §4)."""

import base64

from conftest import enable_multi_tenancy
from fastapi.testclient import TestClient

from veyra.provisioning.facts import dst_rules

PROV = "/provisioning"
DEVICES = "/api/v1/devices"
PROFILES = "/api/v1/device-profiles"
ZONES = "/api/v1/paging-zones"
EXT = "/api/v1/extensions"


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _basic(user, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def test_dst_rules_from_the_zone_database():
    us = dst_rules("America/Chicago", 2026)
    assert us["enabled"] and us["standard_offset"] == -6 * 3600
    assert (
        us["start"]["month"] == 3 and us["start"]["week"] == 2 and us["start"]["day_of_week"] == 1
    )
    assert (
        us["start"]["date"] == 8 and us["start"]["hour"] == 2 and not us["start"]["last_in_month"]
    )
    assert us["stop"]["month"] == 11 and us["stop"]["week"] == 1 and us["stop"]["hour"] == 2
    uk = dst_rules("Europe/London", 2026)
    assert uk["standard_offset"] == 0 and uk["start"]["last_in_month"] and uk["start"]["month"] == 3
    assert uk["start"]["hour"] == 1 and uk["stop"]["month"] == 10 and uk["stop"]["hour"] == 2
    au = dst_rules("Australia/Sydney", 2026)
    assert (
        au["standard_offset"] == 10 * 3600
        and au["start"]["month"] == 10
        and au["stop"]["month"] == 4
    )
    assert au["start"]["week"] == 1 and au["stop"]["week"] == 1
    assert (
        dst_rules("UTC")["enabled"] is False
        and dst_rules("Asia/Tokyo")["standard_offset"] == 9 * 3600
    )
    assert dst_rules("Mars/Olympus") == {
        "enabled": False,
        "standard_offset": 0,
        "start": None,
        "stop": None,
    }


def _setup(admin, app):
    org = _org(admin)
    admin.patch(f"/api/v1/organizations/{org['id']}", json={"timezone": "UTC"})
    ext = admin.post(
        EXT, json={"organization_id": org["id"], "number": "1001", "display_name": "Front Office"}
    ).json()
    other = admin.post(
        EXT, json={"organization_id": org["id"], "number": "1002", "display_name": "Library"}
    ).json()
    admin.post("/api/v1/voicemail", json={"extension_id": ext["id"], "pin": "1234"})
    rg = admin.post(
        "/api/v1/ring-groups",
        json={
            "organization_id": org["id"],
            "name": "Sales",
            "number": "2300",
            "members": [ext["id"]],
        },
    ).json()
    assert rg["number"] == "2300"
    zone = admin.post(
        ZONES,
        json={
            "organization_id": org["id"],
            "name": "Building A",
            "multicast_address": "239.1.2.10",
            "multicast_port": 5004,
            "poly_group": 3,
            "codec": "G.722",
        },
    ).json()
    emergency = admin.post(
        ZONES,
        json={
            "organization_id": org["id"],
            "name": "All call",
            "multicast_address": "239.1.2.99",
            "multicast_port": 5004,
            "poly_group": 25,
            "kind": "emergency",
        },
    ).json()
    profile = admin.post(
        PROFILES,
        json={
            "organization_id": org["id"],
            "name": "VVX, Building A",
            "template_key": "poly.vvx.base",
            "values": {"sip_transport": "TCPOnly", "polling_hour": 4, "vlan_id": 20},
            "keys": [
                {"type": "line", "value": "1"},
                {"type": "blf", "value": "1002"},
                {"type": "blf", "label": "Sales grp", "value": "2300"},
                {"type": "speed_dial", "label": "Office", "value": "15735550100"},
                {"type": "page", "value": "building-a"},
            ],
            "paging": [
                {"zone_id": zone["id"], "role": "default"},
                {"zone_id": emergency["id"], "transmit": False},
            ],
        },
    )
    assert profile.status_code == 201, profile.text
    device = admin.post(
        DEVICES,
        json={
            "organization_id": org["id"],
            "mac_address": "0004f2aabbcc",
            "manufacturer": "Poly",
            "model": "VVX 450",
            "label": "Room 112",
            "profile_id": profile.json()["id"],
            "primary_extension_id": ext["id"],
            "lines": [other["id"]],
        },
    )
    assert device.status_code == 201, device.text
    return org, ext, other, zone, profile.json(), device.json()


def test_device_preview_renders_lines_keys_paging_and_dst(admin, app):
    org, ext, other, _zone, _profile, device = _setup(admin, app)
    r = admin.get(f"{DEVICES}/{device['id']}/preview")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["template_key"] == "poly.vvx.450" and out["error"] is None
    names = {f["filename"] for f in out["files"]}
    assert names == {"0004f2aabbcc.cfg", "veyra-0004f2aabbcc.cfg"}
    cfg = next(f["content"] for f in out["files"] if f["filename"].startswith("veyra-"))
    master = next(f["content"] for f in out["files"] if f["filename"] == "0004f2aabbcc.cfg")
    assert 'APP_FILE_PATH=""' in master and 'CONFIG_FILES="veyra-0004f2aabbcc.cfg"' in master
    # Two registrations, secrets masked in previews.
    assert (
        f'reg.1.address="{ext["endpoint_name"]}"' in cfg
        and f'reg.2.address="{other["endpoint_name"]}"' in cfg
    )
    assert 'reg.1.auth.password="********"' in cfg and 'reg.1.server.1.transport="TCPOnly"' in cfg
    assert 'reg.1.label="Front Office"' in cfg and 'reg.2.label="Library"' in cfg
    # Voicemail indication for line 1 only (it has a box), calling back *97.
    assert (
        "msg.mwi.1.subscribe=" in cfg
        and "msg.mwi.2.subscribe" not in cfg
        and 'callBack="*97"' in cfg
    )
    # Keys: BLF labels resolve to the extension and ring group names; pickup prefix.
    assert 'call.directedCallPickupString="**"' in cfg
    assert (
        'attendant.resourceList.1.address="1002"' in cfg
        and 'attendant.resourceList.1.label="Library"' in cfg
    )
    assert 'attendant.resourceList.2.label="Sales grp"' in cfg
    assert 'lineKey.4.category="SpeedDial"' in cfg and 'action.string="15735550100$Tinvite$"' in cfg
    assert 'lineKey.5.category="Paging" lineKey.5.index="3"' in cfg
    # Paging: both groups, roles, codec from the zones, transmit flags.
    assert (
        'ptt.pageMode.enable="1"' in cfg
        and 'ptt.address="224.0.1.116"' in cfg
        and 'ptt.port="5001"' in cfg
    )
    assert 'ptt.pageMode.codec="G.722"' in cfg and 'ptt.pageMode.defaultGroup="3"' in cfg
    assert 'ptt.pageMode.emergencyGroup="25"' in cfg
    assert (
        'ptt.pageMode.group.3.label="Building A"' in cfg
        and 'ptt.pageMode.group.3.allowTransmit="1"' in cfg
    )
    assert (
        'ptt.pageMode.group.25.allowTransmit="0"' in cfg
        and 'ptt.pageMode.group.25.subscribed="1"' in cfg
    )
    # Time: the organization's zone (UTC in tests) gives no DST; VLAN and polling from values.
    assert (
        'tcpIpApp.sntp.daylightSavings.enable="0"' in cfg and 'tcpIpApp.sntp.gmtOffset="0"' in cfg
    )
    assert 'device.net.vlanId="20"' in cfg and 'prov.polling.time="04:00"' in cfg
    assert 'device.prov.user="dev-0004f2aabbcc"' in cfg and 'device.prov.password="********"' in cfg
    assert 'device.prov.serverType="HTTPS"' in cfg
    # A site time zone with DST turns the rules on.
    site = admin.post(
        "/api/v1/sites",
        json={"organization_id": org["id"], "name": "Main", "timezone": "America/Chicago"},
    ).json()
    admin.patch(f"{DEVICES}/{device['id']}", json={"site_id": site["id"]})
    cfg = next(
        f["content"]
        for f in admin.get(f"{DEVICES}/{device['id']}/preview").json()["files"]
        if f["filename"].startswith("veyra-")
    )
    assert 'daylightSavings.enable="1"' in cfg and 'gmtOffset="-21600"' in cfg
    assert (
        'daylightSavings.start.month="3"' in cfg
        and 'start.date="8"' in cfg
        and 'start.dayOfWeek="1"' in cfg
    )
    assert 'stop.month="11"' in cfg and 'stop.date="1"' in cfg
    # Without a profile nothing renders, with a clear reason.
    admin.patch(f"{DEVICES}/{device['id']}", json={"profile_id": None})
    out = admin.get(f"{DEVICES}/{device['id']}/preview").json()
    assert out["files"] == [] and out["error_code"] == "no_profile"


def test_provisioning_server_authenticates_logs_and_serves(admin, app):
    org, _ext, _other, _zone, _profile, device = _setup(admin, app)
    cred = admin.post(f"/api/v1/organizations/{org['id']}/provisioning-credential/rotate").json()
    anon = TestClient(app, base_url="https://veyra.test")  # a phone over HTTPS: no session, no CSRF
    ua = {"User-Agent": "PolycomVVX-VVX_450-UA/6.4.5.1234"}
    # No credentials, wrong credentials.
    r = anon.get(f"{PROV}/0004f2aabbcc.cfg", headers=ua)
    assert r.status_code == 401 and r.headers["WWW-Authenticate"].startswith("Basic")
    assert (
        anon.get(
            f"{PROV}/0004f2aabbcc.cfg", headers={**ua, **_basic(cred["username"], "nope")}
        ).status_code
        == 401
    )
    # The enrollment credential serves registered phones of its organization.
    org_auth = {**ua, **_basic(cred["username"], cred["password"])}
    r = anon.get(f"{PROV}/000000000000.cfg", headers=org_auth)
    assert r.status_code == 200 and "APPLICATION" in r.text
    r = anon.get(f"{PROV}/0004f2aabbcc.cfg", headers=org_auth)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert (
        'CONFIG_FILES="veyra-0004f2aabbcc.cfg"' in r.text
        and r.headers["cache-control"] == "no-store"
    )
    r = anon.get(f"{PROV}/veyra-0004f2aabbcc.cfg", headers=org_auth)
    assert r.status_code == 200
    assert 'reg.1.auth.password="********"' not in r.text and "reg.1.auth.password=" in r.text
    assert (
        'device.prov.user="dev-0004f2aabbcc"' in r.text
        and 'device.prov.password="********"' not in r.text
    )
    assert (
        'device.prov.serverName="https://' in r.text and '/provisioning/"' in r.text
    )  # client scheme
    device_password = r.text.split('device.prov.password="')[1].split('"')[0]
    # Unknown MAC with a valid credential: 404 and listed as unregistered.
    assert anon.get(f"{PROV}/0004f2ffffff.cfg", headers=org_auth).status_code == 404
    seen = admin.get(f"{DEVICES}/unregistered").json()
    assert seen[0]["mac_address"] == "0004f2ffffff" and seen[0]["model"] == "VVX 450"
    assert seen[0]["manufacturer"] == "Poly" and seen[0]["organization_id"] == org["id"]
    # Files the phone uploads are accepted and discarded; the device credential works alone.
    dev_auth = {**ua, **_basic("dev-0004f2aabbcc", device_password)}
    r = anon.put(f"{PROV}/0004f2aabbcc-app.log", content=b"log lines", headers=dev_auth)
    assert r.status_code == 200
    assert anon.get(f"{PROV}/veyra-0004f2aabbcc.cfg", headers=dev_auth).status_code == 200
    assert (
        anon.get(
            f"{PROV}/veyra-0004f2aabbcc.cfg", headers={**ua, **_basic("dev-0004f2aabbcc", "x")}
        ).status_code
        == 401
    )
    # The device credential cannot fetch another phone's files.
    assert anon.get(f"{PROV}/veyra-0004f2ffffff.cfg", headers=dev_auth).status_code == 404
    d = admin.get(f"{DEVICES}/{device['id']}").json()
    assert (
        d["status"] == "provisioned"
        and d["last_result"] == "ok"
        and d["firmware_reported"] == "6.4.5.1234"
    )
    assert d["last_user_agent"].startswith("PolycomVVX")
    # Disabled devices get 403; unknown file names of a known device 404; bad names 404.
    admin.patch(f"{DEVICES}/{device['id']}", json={"is_enabled": False})
    assert anon.get(f"{PROV}/veyra-0004f2aabbcc.cfg", headers=org_auth).status_code == 403
    assert admin.get(f"{DEVICES}/{device['id']}").json()["status"] == "error"
    admin.patch(f"{DEVICES}/{device['id']}", json={"is_enabled": True})
    # The phone's own directory file is the organization's directory (M21 §5).
    r = anon.get(f"{PROV}/0004f2aabbcc-directory.xml", headers=org_auth)
    assert r.status_code == 200 and "<directory>" in r.text
    assert anon.get(f"{PROV}/..%2Fetc%2Fpasswd", headers=org_auth).status_code == 404
    # Rotating the enrollment credential does not affect the provisioned phone.
    admin.post(f"/api/v1/organizations/{org['id']}/provisioning-credential/rotate")
    assert anon.get(f"{PROV}/veyra-0004f2aabbcc.cfg", headers=org_auth).status_code == 401
    assert anon.get(f"{PROV}/veyra-0004f2aabbcc.cfg", headers=dev_auth).status_code == 200
    # A technician of another organization's credential cannot reach this device.
    enable_multi_tenancy()
    other_org = admin.post("/api/v1/organizations", json={"name": "Other", "slug": "other"}).json()
    other_cred = admin.post(
        f"/api/v1/organizations/{other_org['id']}/provisioning-credential/rotate"
    ).json()
    r = anon.get(
        f"{PROV}/veyra-0004f2aabbcc.cfg",
        headers={**ua, **_basic(other_cred["username"], other_cred["password"])},
    )
    assert r.status_code == 401
    audit_rows = admin.get("/api/v1/audit", params={"q": "provisioning"}).json()["items"]
    assert any(e["action"] == "provisioning_credential.rotate" for e in audit_rows)


def test_snapshot_counts_phones_per_extension_and_site_emergency_default(admin, app):
    from veyra.core.db import session_scope
    from veyra.core.security.crypto import load_installation_key
    from veyra.telephony.snapshot import build_snapshot

    org, ext, other, _zone, profile, device = _setup(admin, app)
    site = admin.post(
        "/api/v1/sites",
        json={
            "organization_id": org["id"],
            "name": "Annex",
            "emergency_caller_id_number": "5735550199",
        },
    ).json()
    with session_scope() as db:
        from veyra.core.models import Extension

        row = db.get(Extension, other["id"])
        row.site_id = site["id"]
        db.commit()
    # A second phone carrying extension 1001 on line 2 → two contacts.
    r = admin.post(
        DEVICES,
        json={
            "organization_id": org["id"],
            "mac_address": "0004f2aabbdd",
            "manufacturer": "Poly",
            "model": "VVX 411",
            "profile_id": profile["id"],
            "primary_extension_id": other["id"],
            "lines": [ext["id"]],
        },
    )
    assert r.status_code == 201, r.text
    with session_scope() as db:
        snap = build_snapshot(db, load_installation_key(app.state.settings))
    by_number = {e["number"]: e for e in snap["extensions"]}
    assert by_number["1001"]["max_contacts"] == 2 and by_number["1002"]["max_contacts"] == 2
    assert by_number["1002"]["emergency_caller_id_number"] == "5735550199"  # site default
    assert by_number["1001"]["emergency_caller_id_number"] is None
    admin.patch(f"{EXT}/{other['id']}", json={"emergency_caller_id_number": "5735550123"})
    with session_scope() as db:
        snap = build_snapshot(db, load_installation_key(app.state.settings))
    assert {e["number"]: e for e in snap["extensions"]}["1002"][
        "emergency_caller_id_number"
    ] == "5735550123"
    # Reprovision: without Asterisk on the test host the request is refused cleanly and audited.
    r = admin.post(f"{DEVICES}/{device['id']}/reprovision", json={"action": "check_config"})
    assert r.status_code == 200 and r.json()["endpoint"] == ext["endpoint_name"]
    assert r.json()["sent"] in (True, False)
    assert any(
        e["action"] == "device.reprovision"
        for e in admin.get("/api/v1/audit", params={"q": "reprovision"}).json()["items"]
    )
