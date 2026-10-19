# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Yealink family and the phone directory (docs/PROVISIONING_BREADTH.md
§4, §5): a T46U renders lines, keys, paging, DST and provisioning from the
same facts as the Poly family; the directory serves every format to a phone
with its credential."""

import base64

from fastapi.testclient import TestClient

DEVICES = "/api/v1/devices"
PROFILES = "/api/v1/device-profiles"
ZONES = "/api/v1/paging-zones"
EXT = "/api/v1/extensions"


def _post(admin, url, body):
    r = admin.post(url, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _basic(user, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def test_yealink_renders_and_directory_is_served(admin, app):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    o = org["id"]
    admin.patch(f"/api/v1/organizations/{o}", json={"timezone": "America/Chicago"})
    ext = _post(
        admin, EXT, {"organization_id": o, "number": "1001", "display_name": "Front Office"}
    )
    _post(admin, EXT, {"organization_id": o, "number": "1002", "display_name": "Library & Media"})
    admin.post("/api/v1/voicemail", json={"extension_id": ext["id"], "pin": "1234"})
    zone = _post(
        admin,
        ZONES,
        {
            "organization_id": o,
            "name": "Building A",
            "multicast_address": "239.1.2.10",
            "multicast_port": 5004,
            "poly_group": 3,
        },
    )
    profile = _post(
        admin,
        PROFILES,
        {
            "organization_id": o,
            "name": "Yealink desk phones",
            "template_key": "yealink.base",
            "values": {"sip_transport": "TCPOnly", "vlan_id": 20},
            "keys": [
                {"type": "line", "value": "1"},
                {"type": "blf", "value": "1002"},
                {"type": "speed_dial", "value": "5735550100", "label": "District office"},
                {"type": "transfer", "value": ""},
                {"type": "page", "value": zone["slug"]},
            ],
            "paging": [{"zone_id": zone["id"], "subscribed": True, "transmit": True}],
        },
    )
    device = _post(
        admin,
        DEVICES,
        {
            "organization_id": o,
            "mac_address": "80:5E:C0:11:22:33",
            "manufacturer": "Yealink",
            "model": "T46U",
            "profile_id": profile["id"],
            "primary_extension_id": ext["id"],
        },
    )
    r = admin.get(f"{DEVICES}/{device['id']}/preview")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["error"] is None and out["template_key"] == "yealink.t4x", out
    assert out["warnings"] == []  # Yealink has a transfer key
    (f,) = out["files"]
    assert f["filename"] == "805ec0112233.cfg"
    cfg = f["content"]
    assert cfg.startswith("#!version:1.0.0.1")
    for line in (
        "account.1.enable = 1",
        "account.1.user_name = ",
        "account.1.sip_server.1.transport_type = 1",
        "account.1.subscribe_mwi = 1",
        "voice_mail.number.1 = *97",
        "linekey.1.type = 15",
        "linekey.2.type = 16",
        "linekey.2.value = 1002",
        "linekey.3.type = 13",
        "linekey.3.label = District office",
        "linekey.4.type = 3",
        "linekey.5.type = 24",
        "linekey.5.value = 239.1.2.10:5004",
        "multicast.listen_address.1.ip_address = 239.1.2.10:5004",
        "local_time.time_zone = -6",
        "local_time.summer_time = 1",
        "local_time.start_time = 3/2/7/2",
        "static.network.vlan.internet_port_vid = 20",
        "remote_phonebook.data.1.url = ",
        "auto_provision.server.username = dev-805ec0112233",
    ):
        assert line in cfg, line
    assert "account.1.password = ********" in cfg  # previews mask secrets

    # The directory, with the organization credential, in each format.
    cred = admin.post(f"/api/v1/organizations/{o}/provisioning-credential/rotate").json()
    phone = TestClient(app, base_url="https://veyra.test")
    auth = _basic(cred["username"], cred["password"])
    assert phone.get("/provisioning/directory/yealink.xml").status_code == 401
    assert phone.get("/provisioning/directory/other.xml", headers=auth).status_code == 404
    r = phone.get("/provisioning/directory/yealink.xml", headers=auth)
    assert r.status_code == 200 and "<YealinkIPPhoneBook>" in r.text
    assert 'Name="Library &amp; Media" Phone1="1002"' in r.text
    r = phone.get("/provisioning/directory/poly.xml", headers=auth)
    assert "<fn>Front Office</fn><ct>1001</ct>" in r.text
    r = phone.get("/provisioning/directory/grandstream.xml", headers=auth)
    assert "<phonenumber>1002</phonenumber>" in r.text
    r = phone.get("/provisioning/directory/contacts.csv", headers=auth)
    assert r.text.splitlines()[0] == "name,number" and "Front Office,1001" in r.text


def test_yealink_lineup_and_conference_phone(admin, app):
    """Every current Yealink SIP model resolves to a family; a conference
    phone renders its line without line keys."""
    makers = admin.get("/api/v1/provisioning/models").json()["manufacturers"]
    yealink = {m for e in makers if e["name"] == "Yealink" for m in e["models"]}
    for m in (
        "T30",
        "T34W",
        "T42U",
        "T44W",
        "T58W Pro",
        "VP59",
        "T73U",
        "T77U",
        "T85W",
        "T88",
        "CP925",
        "CP965",
    ):
        assert m in yealink, m
    org = admin.get("/api/v1/organizations").json()["items"][0]
    o = org["id"]
    ext = _post(admin, EXT, {"organization_id": o, "number": "1009", "display_name": "Board room"})
    profile = _post(
        admin,
        PROFILES,
        {
            "organization_id": o,
            "name": "Yealink rooms",
            "template_key": "yealink.base",
            "keys": [{"type": "blf", "value": "1009"}],
        },
    )
    device = _post(
        admin,
        DEVICES,
        {
            "organization_id": o,
            "mac_address": "805ec0aa0001",
            "manufacturer": "Yealink",
            "model": "CP965",
            "profile_id": profile["id"],
            "primary_extension_id": ext["id"],
        },
    )
    out = admin.get(f"{DEVICES}/{device['id']}/preview").json()
    assert out["error"] is None and out["template_key"] == "yealink.cp", out
    cfg = out["files"][0]["content"]
    assert "account.1.enable = 1" in cfg and "linekey." not in cfg


def test_poly_edge_ccx_and_poly_directory(admin, app):
    makers = admin.get("/api/v1/provisioning/models").json()["manufacturers"]
    poly = {m for e in makers if e["name"] == "Poly" for m in e["models"]}
    for m in ("Edge E100", "Edge E550", "CCX 350", "CCX 700", "VVX 411"):
        assert m in poly, m
    org = admin.get("/api/v1/organizations").json()["items"][0]
    o = org["id"]
    ext = _post(admin, EXT, {"organization_id": o, "number": "1010", "display_name": "Counselor"})
    zone = _post(
        admin,
        ZONES,
        {
            "organization_id": o,
            "name": "Office",
            "multicast_address": "239.1.2.30",
            "multicast_port": 5004,
            "poly_group": 6,
        },
    )
    profile = _post(
        admin,
        PROFILES,
        {
            "organization_id": o,
            "name": "Poly media phones",
            "template_key": "poly.vvx.base",
            "paging": [{"zone_id": zone["id"], "subscribed": True, "transmit": True}],
        },
    )
    out = {}
    for mac, model in (("0004f2c00001", "CCX 505"), ("0004f2e00001", "Edge E450")):
        d = _post(
            admin,
            DEVICES,
            {
                "organization_id": o,
                "mac_address": mac,
                "manufacturer": "Poly",
                "model": model,
                "profile_id": profile["id"],
                "primary_extension_id": ext["id"],
            },
        )
        p = admin.get(f"{DEVICES}/{d['id']}/preview").json()
        assert p["error"] is None, p
        out[model] = (p["template_key"], "\n".join(f["content"] for f in p["files"]))
    assert out["CCX 505"][0] == "poly.ccx" and "ptt." not in out["CCX 505"][1]
    assert out["Edge E450"][0] == "poly.edge.e" and "ptt." in out["Edge E450"][1]
    cred = admin.post(f"/api/v1/organizations/{o}/provisioning-credential/rotate").json()
    phone = TestClient(app, base_url="https://veyra.test")
    r = phone.get(
        "/provisioning/0004f2c00001-directory.xml",
        headers=_basic(cred["username"], cred["password"]),
    )
    assert r.status_code == 200 and "<fn>Counselor</fn><ct>1010</ct>" in r.text


def test_device_export_for_redirect_portals(admin):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    profile = _post(
        admin,
        PROFILES,
        {"organization_id": org["id"], "name": "Export", "template_key": "yealink.base"},
    )
    _post(
        admin,
        DEVICES,
        {
            "organization_id": org["id"],
            "mac_address": "805ec0bb0002",
            "manufacturer": "Yealink",
            "model": "T54W",
            "label": "Room 9",
            "profile_id": profile["id"],
        },
    )
    r = admin.get(f"{DEVICES}/export.csv", params={"manufacturer": "yealink"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.splitlines()
    assert lines[0] == "mac,mac_colon,manufacturer,model,label,provisioning_url"
    assert any(
        row.startswith("805EC0BB0002,80:5E:C0:BB:00:02,Yealink,T54W,Room 9,http") for row in lines
    )
    assert "Poly" not in r.text
