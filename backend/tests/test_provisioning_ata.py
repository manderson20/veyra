# SPDX-License-Identifier: AGPL-3.0-or-later
"""Grandstream ATAs (issue #37, docs/PROVISIONING_BREADTH.md §4.4): one
extension per FXS port, the fax mode of each port from its extension, the
ATA's own star codes off, and the HT81x's shared profiles."""

import xml.etree.ElementTree as ET

DEVICES = "/api/v1/devices"
PROFILES = "/api/v1/device-profiles"
EXT = "/api/v1/extensions"


def _post(admin, url, body):
    r = admin.post(url, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _p(xml: str) -> dict[str, str]:
    root = ET.fromstring(xml)  # noqa: S314 (Veyra's own output)
    assert root.tag == "gs_provision"
    return {el.tag[1:]: el.text or "" for el in root.find("config")}


def _setup(admin, template_key, values=None):
    o = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    admin.patch(f"/api/v1/organizations/{o}", json={"timezone": "America/Chicago"})
    exts = [
        _post(
            admin,
            EXT,
            {
                "organization_id": o,
                "number": "2001",
                "display_name": "Elevator",
                "hotline_target": "0",
                "hotline_delay": 2,
            },
        ),
        _post(
            admin,
            EXT,
            {"organization_id": o, "number": "2002", "display_name": "Office fax", "fax_t38": True},
        ),
        _post(admin, EXT, {"organization_id": o, "number": "2003", "display_name": "Door phone"}),
    ]
    admin.post("/api/v1/voicemail", json={"extension_id": exts[2]["id"], "pin": "1234"})
    profile = _post(
        admin,
        PROFILES,
        {
            "organization_id": o,
            "name": "ATAs",
            "template_key": template_key,
            "values": values or {},
        },
    )
    return o, exts, profile


def _device(admin, o, exts, profile, mac, model):
    d = _post(
        admin,
        DEVICES,
        {
            "organization_id": o,
            "mac_address": mac,
            "manufacturer": "Grandstream",
            "model": model,
            "profile_id": profile["id"],
            "primary_extension_id": exts[0]["id"],
            "lines": [e["id"] for e in exts[1:]],
        },
    )
    out = admin.get(f"{DEVICES}/{d['id']}/preview").json()
    assert out["error"] is None, out
    (f,) = out["files"]
    assert f["filename"] == f"cfg{mac.replace(':', '').lower()}.xml"
    return out, f["content"]


def test_ht802_ports_fax_and_star_codes(admin):
    o, exts, profile = _setup(admin, "grandstream.ata", {"registration_expires": 600})
    out, xml = _device(admin, o, exts, profile, "C0:74:AD:11:22:33", "HT802")
    assert out["template_key"] == "grandstream.ht80x" and out["warnings"] == []
    p = _p(xml)
    # Port 1: the elevator phone, a hotline to 0 after 2 s, pass-through fax.
    assert p["271"] == "1" and p["35"] == p["36"] and p["35"].endswith("2001")
    assert p["3"] == "Elevator" and p["71"] == "0" and p["4045"] == "2"
    assert p["228"] == "1" and p["191"] == "0" and p["32"] == "10" and p["99"] == "0"
    assert [p[n] for n in ("57", "58", "59")] == ["0", "8", "9"]
    # Port 2: the fax machine (T.38) extension.
    assert p["401"] == "1" and p["735"].endswith("2002") and p["703"] == "Office fax"
    assert p["710"] == "0" and p["4417"] == "1" and p["751"] == "0" and p["771"] == ""
    assert p["709"] == "0"  # no mailbox on the fax line
    # The HT802 has two ports: the third line is noted, not configured.
    assert "Line 3 (2003) is not used: the HT802 has 2 ports" in xml
    # Provisioning: HTTPS, the device credential, daily; time as a POSIX rule.
    assert p["212"] == "2" and p["22296"] == "2" and p["4428"] == "1" and p["1360"]
    assert p["64"] == "customize" and p["246"] == "MTZ+6MDT+5,M3.2.0,M11.1.0"
    assert p["238"] == "2"


def test_fax_mode_variable_and_star_codes(admin):
    o, exts, profile = _setup(
        admin, "grandstream.ht80x", {"fax_mode": "passthrough", "local_call_features": True}
    )
    _, xml = _device(admin, o, exts[:2], profile, "C0:74:AD:11:22:34", "HT802V2")
    p = _p(xml)
    assert p["228"] == "1" and p["710"] == "1" and p["191"] == "1" and p["751"] == "1"
    r = admin.patch(f"{PROFILES}/{profile['id']}", json={"values": {"fax_mode": "t38"}})
    assert r.status_code == 200, r.text
    devices = admin.get(DEVICES).json()["items"]
    p = _p(admin.get(f"{DEVICES}/{devices[0]['id']}/preview").json()["files"][0]["content"])
    assert p["228"] == "0" and p["710"] == "0"


def test_ht814_shares_profiles(admin):
    o, exts, profile = _setup(admin, "grandstream.ata")
    out, xml = _device(admin, o, exts, profile, "C0:74:AD:55:66:77", "HT814")
    assert out["template_key"] == "grandstream.ht81x"
    p = _p(xml)
    # Profile 1 (pass-through) and profile 2 (T.38) on the same server.
    assert p["271"] == "1" and p["228"] == "1" and p["401"] == "1" and p["710"] == "0"
    assert p["47"] == p["747"] and p["4045"] == "2" and p["99"] == "1"  # 2003 has a mailbox
    # Ports 1-3 with their own credentials; the fax port on profile 2.
    assert p["4060"].endswith("2001") and p["4180"] == "Elevator" and p["4210"] == "0"
    assert [p[str(4150 + i)] for i in range(3)] == ["0", "1", "0"]
    assert [p[str(4595 + i)] for i in range(4)] == ["1", "1", "1", "0"]
    assert "4064" not in p  # past the HT814's four ports
    # Without a fax machine (T.38) port, profile 2 is off.
    _, xml = _device(admin, o, [exts[0], exts[2]], profile, "C0:74:AD:55:66:78", "HT812")
    p = _p(xml)
    assert p["401"] == "0" and "710" not in p and p["4151"] == "0"


def test_ata_template_previews_without_a_device(admin):
    r = admin.post(
        "/api/v1/provisioning/templates/grandstream.ht81x/preview",
        json={
            "model": "HT818",
            "mac": "c074ad000001",
            "values": {
                "sip_server": "pbx.example.org",
                "extension_number": "1001",
                "sip_username": "example-1001",
                "sip_password": "secret",
            },
        },
    )
    assert r.status_code == 200, r.text
    p = _p(r.json()["files"][0]["content"])
    assert p["4060"] == "example-1001" and p["4595"] == "1" and p["4602"] == "0"
