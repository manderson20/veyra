# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Grandstream family (issue #36, docs/PROVISIONING_BREADTH.md §4.3): a
GRP2614, a GRP2602 and a GXP2170 render well-formed P-value XML from the
same facts as the Poly and Yealink families, and a phone fetches it with
its credential."""

import base64
import xml.etree.ElementTree as ET

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


def _p(xml: str) -> dict[str, str]:
    root = ET.fromstring(xml)  # noqa: S314 (Veyra's own output)
    assert root.tag == "gs_provision" and root.find("config").get("version") == "1"
    return {el.tag[1:]: el.text or "" for el in root.find("config")}


def _setup(admin):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    o = org["id"]
    admin.patch(f"/api/v1/organizations/{o}", json={"timezone": "America/Chicago"})
    ext = _post(
        admin,
        EXT,
        {
            "organization_id": o,
            "number": "1001",
            "display_name": "Front Office",
            "hotline_target": "1009",
            "hotline_delay": 3,
        },
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
            "name": "Grandstream desk phones",
            "template_key": "grandstream.base",
            "values": {"sip_transport": "TCPOnly", "vlan_id": 20, "registration_expires": 600},
            "keys": [
                {"type": "line", "value": "1"},
                {"type": "blf", "value": "1002"},
                {"type": "speed_dial", "value": "5735550100", "label": "District office"},
                {"type": "transfer", "value": ""},
                {"type": "page", "value": zone["slug"]},
                {"type": "line", "value": "1"},
            ],
            "paging": [{"zone_id": zone["id"], "subscribed": True, "transmit": True}],
        },
    )
    return o, ext, profile


def _device(admin, o, ext, profile, mac, model):
    d = _post(
        admin,
        DEVICES,
        {
            "organization_id": o,
            "mac_address": mac,
            "manufacturer": "Grandstream",
            "model": model,
            "profile_id": profile["id"],
            "primary_extension_id": ext["id"],
        },
    )
    out = admin.get(f"{DEVICES}/{d['id']}/preview").json()
    assert out["error"] is None, out
    return d, out


def test_grp261x_renders_p_values(admin, app):
    o, ext, profile = _setup(admin)
    _, out = _device(admin, o, ext, profile, "00:0B:82:11:22:33", "GRP2614")
    assert out["template_key"] == "grandstream.grp261x"
    assert out["warnings"] == []
    (f,) = out["files"]
    assert f["filename"] == "cfg000b82112233.xml"
    p = _p(f["content"])
    expect = {
        "271": "1",  # account 1 active
        "270": "Front Office",
        "130": "1",  # TCP
        "32": "10",  # 600 s in minutes
        "33": "*97",
        "99": "1",
        "1347": "**",
        "298": "1",  # intercom auto-answer
        # Keys in order: line, BLF, speed dial, transfer, page.
        "1363": "31",
        "1364": "0",
        "1365": "1",
        "1468": "1002",
        "1367": "0",
        "1469": "District office",
        "1470": "5735550100",
        "1369": "8",
        "1371": "13",
        "1474": "239.1.2.10:5004",
        "1373": "31",  # a sixth key: a second line key, still on the GRP
        "22208": "1",
        "1568": "0",
        "1569": "239.1.2.10:5004",
        "1570": "Building A",
        "64": "customize",
        "246": "MTZ+6MDT+5,M3.2.0,M11.1.0",
        "144": "0",
        "212": "2",
        "1360": "dev-000b82112233",
        "4428": "1",
        "145": "0",
        "238": "2",  # no firmware assigned: no upgrades from Grandstream
        "8463": "0",
        "22174": "1",
        "51": "20",
        "330": "3",
        "71": "1009",
        "8388": "3",
    }
    for k, v in expect.items():
        assert p.get(k) == v, (k, p.get(k), v)
    assert p["237"].endswith("/provisioning") and "://" not in p["237"]
    assert p["331"].startswith("dev-000b82112233:") and p["331"].endswith(
        "/provisioning/directory/grandstream.xml"
    )
    assert p["34"] == "********" and p["1361"] == "********"  # previews mask secrets
    assert "26071" not in p  # GRP261x has no intercom mute on account 1


def test_gxp_fixed_keys_use_their_own_codes(admin):
    o, ext, profile = _setup(admin)
    _, out = _device(admin, o, ext, profile, "000b82aa0001", "GXP2130")
    assert out["template_key"] == "grandstream.gxp21xx"
    p = _p(out["files"][0]["content"])
    # GXP2130 has three fixed keys: line 0, BLF 11, speed dial 10; then the
    # dynamic keys take the GRP codes: transfer 8, page 13; a line key
    # beyond the fixed ones is empty (-1).
    assert [p["1363"], p["1365"], p["1367"], p["1369"], p["1371"], p["1373"]] == [
        "0", "11", "10", "8", "13", "-1",
    ]  # fmt: skip
    assert "22208" not in p  # GRP only
    assert p["26071"] == "0"


def test_grp260x_and_the_phone_fetches_its_file(admin, app):
    o, ext, profile = _setup(admin)
    d, out = _device(admin, o, ext, profile, "000b82bb0002", "GRP2602")
    assert out["template_key"] == "grandstream.grp260x"
    assert _p(out["files"][0]["content"])["26071"] == "0"
    cred = admin.post(f"/api/v1/organizations/{o}/provisioning-credential/rotate").json()
    phone = TestClient(app, base_url="https://veyra.test")
    headers = {
        **_basic(cred["username"], cred["password"]),
        "User-Agent": "Grandstream Model HW GRP2602 V1.0A SW 1.0.7.71 DevId 000b82bb0002",
    }
    r = phone.get("/provisioning/cfg000b82bb0002.xml", headers=headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    p = _p(r.text)
    assert p["34"] and p["34"] != "********"  # the real SIP password
    dev = admin.get(f"{DEVICES}/{d['id']}").json()
    assert dev["firmware_reported"] == "1.0.7.71"
    # Other Grandstream names get a 404, so the phone goes on to cfg<mac>.xml.
    assert phone.get("/provisioning/cfg000b82bb0002", headers=headers).status_code == 404
    assert phone.get("/provisioning/cfg.xml", headers=headers).status_code == 404


def test_grandstream_models_in_the_catalog(admin):
    makers = admin.get("/api/v1/provisioning/models").json()["manufacturers"]
    gs = {m for e in makers if e["name"] == "Grandstream" for m in e["models"]}
    for m in ("GRP2601", "GRP2604P", "GRP2612W", "GRP2616", "GRP2670", "GXP2135", "GXP2170"):
        assert m in gs, m


def test_posix_time_zones(admin):
    o, ext, profile = _setup(admin)
    d, _ = _device(admin, o, ext, profile, "000b82cc0003", "GRP2612")
    for tz, rule in (
        ("Europe/Berlin", "MTZ-1MDT-2,M3.5.0,M10.5.0/3"),
        ("Asia/Kolkata", "MTZ-5:30"),
        ("America/Phoenix", "MTZ+7"),
        ("UTC", "MTZ+0"),
    ):
        admin.patch(f"/api/v1/organizations/{o}", json={"timezone": tz})
        out = admin.get(f"{DEVICES}/{d['id']}/preview").json()
        assert _p(out["files"][0]["content"])["246"] == rule, tz


SAMPLE = {
    "sip_server": "pbx.example.org",
    "extension_number": "1001",
    "sip_username": "example-1001",
    "sip_password": "secret",
}


def test_template_previews_without_a_device(admin):
    """The template editor's preview renders sample facts; Yealink and
    Grandstream read the server's host and directory address from them."""
    for key, model in (
        ("grandstream.grp261x", "GRP2614"),
        ("grandstream.gxp21xx", "GXP2170"),
        ("yealink.t4x", "T46U"),
    ):
        r = admin.post(
            f"/api/v1/provisioning/templates/{key}/preview",
            json={
                "values": SAMPLE,
                "mac": "000b82000001",
                "model": model,
            },
        )
        assert r.status_code == 200, (key, r.text)
