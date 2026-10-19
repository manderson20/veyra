# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Algo family (docs/PROVISIONING_BREADTH.md §4): one template for every
current Algo SIP endpoint; algom<MAC>.conf with its md5 checksum, which must
match the file the device downloads."""

import base64
import hashlib

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


def test_algo_speaker_listens_to_zones_and_checksum_matches(admin, app):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    o = org["id"]
    ext = _post(admin, EXT, {"organization_id": o, "number": "2801", "display_name": "Gym horn"})
    zones = [
        _post(
            admin,
            ZONES,
            {
                "organization_id": o,
                "name": name,
                "multicast_address": addr,
                "multicast_port": 5004,
                "poly_group": group,
                **({"kind": "emergency"} if group == 25 else {}),
            },
        )
        for name, addr, group in (
            ("Gym", "239.1.2.20", 4),
            ("Building B", "239.1.2.21", 5),
            ("All call", "239.1.2.99", 25),
        )
    ]
    profile = _post(
        admin,
        PROFILES,
        {
            "organization_id": o,
            "name": "Algo speakers, building B",
            "template_key": "algo.sip",
            "values": {"multicast_format": "both", "algo_timezone": "US/Central", "vlan_id": 30},
            "paging": [{"zone_id": z["id"], "subscribed": True, "transmit": False} for z in zones],
        },
    )
    device = _post(
        admin,
        DEVICES,
        {
            "organization_id": o,
            "mac_address": "00:22:EE:11:22:33",
            "manufacturer": "Algo",
            "model": "8186",
            "profile_id": profile["id"],
            "primary_extension_id": ext["id"],
        },
    )
    out = admin.get(f"{DEVICES}/{device['id']}/preview").json()
    assert out["error"] is None and out["template_key"] == "algo.sip", out
    names = [f["filename"] for f in out["files"]]
    assert names == ["algom0022EE112233.conf", "algom0022EE112233.md5"]
    conf = out["files"][0]["content"]
    for line in (
        "sip.transp = udp",
        "sip.u1.user = ",
        "sip.u1.dname = Gym horn",
        "mcast.mode = 2",
        "mcast.polycom.mode = 3",
        "mcast.zone1 = 239.1.2.20:5004",
        "mcast.zone2 = 239.1.2.21:5004",
        "mcast.zone9 = 239.1.2.99:5004",
        "mcast.polycom.groups = 4,5,25",
        "admin.timezone = US/Central",
        "net.vlan.id = 30",
        "prov.download.method = https",
        "prov.download.cfgpath = provisioning",
        "prov.server.static = dev-0022ee112233:",
    ):
        assert line in conf, line

    # Served to the device: the checksum matches the file it downloads.
    cred = admin.post(f"/api/v1/organizations/{o}/provisioning-credential/rotate").json()
    phone = TestClient(app, base_url="https://veyra.test")
    auth = _basic(cred["username"], cred["password"])
    r = phone.get("/provisioning/algom0022EE112233.conf", headers=auth)
    assert r.status_code == 200, r.text
    md5 = phone.get("/provisioning/algom0022EE112233.md5", headers=auth)
    assert md5.status_code == 200
    assert (
        md5.text
        == f"{hashlib.md5(r.content, usedforsecurity=False).hexdigest()}  algom0022EE112233.conf\n"
    )
    assert "sip.u1.pwd = ********" not in r.text
