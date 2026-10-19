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
