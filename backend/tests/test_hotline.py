# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hotline and warm-line phones (issue #168): an extension's hotline number
reaches the Yealink and Poly templates; a bad number is refused."""

from test_provisioning_yealink import DEVICES, EXT, PROFILES, _post


def _device(admin, o, ext_id, mac, maker, model, template):
    profile = _post(
        admin,
        PROFILES,
        {"organization_id": o, "name": f"{maker} {model}", "template_key": template},
    )
    d = _post(
        admin,
        DEVICES,
        {
            "organization_id": o,
            "mac_address": mac,
            "manufacturer": maker,
            "model": model,
            "profile_id": profile["id"],
            "primary_extension_id": ext_id,
        },
    )
    p = admin.get(f"{DEVICES}/{d['id']}/preview").json()
    assert p["error"] is None, p
    return "\n".join(f["content"] for f in p["files"])


def test_hotline_reaches_the_templates(admin):
    o = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    r = admin.post(
        EXT,
        json={
            "organization_id": o,
            "number": "1020",
            "display_name": "Elevator 1",
            "hotline_target": "1000",
            "hotline_delay": 3,
        },
    )
    assert r.status_code == 201, r.text
    ext = r.json()
    assert ext["hotline_target"] == "1000" and ext["hotline_delay"] == 3
    cfg = _device(admin, o, ext["id"], "805ec0aa0001", "Yealink", "T46U", "yealink.base")
    assert "features.hotline_number = 1000" in cfg and "features.hotline_delay = 3" in cfg
    cfg = _device(admin, o, ext["id"], "0004f2aa0001", "Poly", "VVX 411", "poly.vvx.base")
    assert 'call.autoOffHook.1.enabled="1"' in cfg and 'call.autoOffHook.1.contact="1000"' in cfg
    # Cleared: the Yealink setting is emptied, Poly renders nothing.
    r = admin.patch(f"{EXT}/{ext['id']}", json={"hotline_target": ""})
    assert r.status_code == 200 and r.json()["hotline_target"] is None
    assert admin.patch(f"{EXT}/{ext['id']}", json={"hotline_target": "12ab"}).status_code == 422
    assert admin.patch(f"{EXT}/{ext['id']}", json={"hotline_delay": 11}).status_code == 422
