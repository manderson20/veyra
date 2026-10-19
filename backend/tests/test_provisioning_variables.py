# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provisioning variables (docs/PROVISIONING_BREADTH.md §2): scopes and
precedence, ``$name`` key references resolved per phone, variables filling
template variables, the preview's warnings, re-provisioning on change and the
in-use refusal."""

from veyra.provisioning.variables import VarsView, check_name, reference

VARS = "/api/v1/provisioning/variables"
DEVICES = "/api/v1/devices"
PROFILES = "/api/v1/device-profiles"
ZONES = "/api/v1/paging-zones"
SITES = "/api/v1/sites"
EXT = "/api/v1/extensions"


def test_names_references_and_missing_tracking():
    assert check_name("all_call") == "all_call"
    for bad in ("All", "1x", "lines", "vars", "sip_password", "a-b"):
        try:
            check_name(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    assert reference("$all_call") == "all_call" and reference("all_call") is None
    v = VarsView({"a": "1"})
    assert v["a"] == "1" and v["b"] == "" and v.b == "" and v.missing == {"b"}


def _post(admin, url, body):
    r = admin.post(url, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _setup(admin):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    o = org["id"]
    ext1 = _post(admin, EXT, {"organization_id": o, "number": "1001", "display_name": "Room 1"})
    ext2 = _post(admin, EXT, {"organization_id": o, "number": "1002", "display_name": "Room 2"})
    for name, group in (("Building A", 3), ("Building B", 4)):
        _post(
            admin,
            ZONES,
            {
                "organization_id": o,
                "name": name,
                "multicast_address": f"239.1.2.{group}",
                "multicast_port": 5004,
                "poly_group": group,
            },
        )
    site_a = _post(admin, SITES, {"organization_id": o, "name": "North"})
    site_b = _post(admin, SITES, {"organization_id": o, "name": "South"})
    profile = _post(
        admin,
        PROFILES,
        {
            "organization_id": o,
            "name": "VVX, every building",
            "template_key": "poly.vvx.base",
            "keys": [{"type": "line", "value": "1"}, {"type": "page", "value": "$all_call"}],
        },
    )
    devices = []
    for mac, site, ext in (
        ("0004f2000001", site_a, ext1),
        ("0004f2000002", site_b, ext2),
    ):
        devices.append(
            _post(
                admin,
                DEVICES,
                {
                    "organization_id": o,
                    "mac_address": mac,
                    "manufacturer": "Poly",
                    "model": "VVX 411",
                    "profile_id": profile["id"],
                    "primary_extension_id": ext["id"],
                    "site_id": site["id"],
                },
            )
        )
    return org, site_a, site_b, profile, devices


def _preview(admin, device):
    r = admin.get(f"{DEVICES}/{device['id']}/preview")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["error"] is None, out
    return "\n".join(f["content"] for f in out["files"]), out["warnings"]


def test_scopes_precedence_keys_reprovision_and_in_use(admin, app):
    notified: list[str] = []
    app.state.notify_phone = lambda action, endpoint: (notified.append(endpoint), (True, ""))[1]
    org, site_a, site_b, profile, (d1, d2) = _setup(admin)
    o = org["id"]

    # Nothing defined yet: the page key renders nothing and the preview warns.
    content, warnings = _preview(admin, d1)
    assert 'category="Paging"' not in content
    assert warnings == ["variable all_call is not defined"]

    # One key on one profile, a different zone per building.
    a = _post(
        admin,
        VARS,
        {"scope": "site", "scope_id": site_a["id"], "name": "all_call", "value": "building-a"},
    )
    assert a["affected_devices"] == 1 and a["scope_name"] == "North"
    _post(
        admin,
        VARS,
        {"scope": "site", "scope_id": site_b["id"], "name": "all_call", "value": "building-b"},
    )
    content, warnings = _preview(admin, d1)
    assert 'category="Paging" lineKey.2.index="3"' in content and warnings == []
    content, _ = _preview(admin, d2)
    assert 'category="Paging" lineKey.2.index="4"' in content

    # An organization value fills the template's own variable of that name.
    org_var = _post(
        admin,
        VARS,
        {"scope": "organization", "scope_id": o, "name": "sip_transport", "value": "TCPOnly"},
    )
    assert org_var["affected_devices"] == 2
    content, _ = _preview(admin, d2)
    assert 'transport="TCPOnly"' in content

    # The profile scope wins over the site; the phone's resolved set shows the scopes.
    prof_var = _post(
        admin,
        VARS,
        {"scope": "profile", "scope_id": profile["id"], "name": "all_call", "value": "building-b"},
    )
    content, _ = _preview(admin, d1)
    assert 'category="Paging" lineKey.2.index="4"' in content
    resolved = {v["name"]: v for v in admin.get(f"{DEVICES}/{d1['id']}/variables").json()}
    assert (
        resolved["all_call"]["scope"] == "profile"
        and resolved["sip_transport"]["scope"] == "organization"
    )
    assert admin.delete(f"{VARS}/{prof_var['id']}").status_code == 204
    content, _ = _preview(admin, d1)
    assert 'category="Paging" lineKey.2.index="3"' in content

    # A value change re-provisions the phones it reaches; a description alone does not.
    notified.clear()
    r = admin.patch(f"{VARS}/{a['id']}", json={"value": "building-b"})
    assert r.status_code == 200 and r.json()["affected_devices"] == 1 and len(notified) == 1
    r = admin.patch(f"{VARS}/{a['id']}", json={"description": "North building all-call"})
    assert r.json()["affected_devices"] == 0 and len(notified) == 1

    # Validation and conflicts.
    r = admin.post(
        VARS, json={"scope": "site", "scope_id": site_a["id"], "name": "all_call", "value": "x"}
    )
    assert r.status_code == 409 and r.json()["code"] == "variable_exists"
    r = admin.post(
        VARS, json={"scope": "organization", "scope_id": o, "name": "lines", "value": "x"}
    )
    assert r.status_code == 422
    r = admin.post(VARS, json={"scope": "installation", "scope_id": o, "name": "x", "value": "y"})
    assert r.status_code == 422
    inst = _post(
        admin,
        VARS,
        {"scope": "installation", "name": "ntp_pool", "value": "pool.ntp.org", "sensitive": True},
    )
    listed = admin.get(VARS, params={"organization_id": o}).json()
    assert any(v["source"] == "core" and v["name"] == "sip_server" for v in listed)
    assert {v["name"] for v in listed if v["source"] == "defined"} >= {
        "all_call",
        "sip_transport",
        "ntp_pool",
    }

    # Still referenced by the profile's keys: refused; after the key changes it goes.
    r = admin.delete(f"{VARS}/{a['id']}")
    assert r.status_code == 409 and r.json()["code"] == "variable_in_use"
    r = admin.patch(f"{PROFILES}/{profile['id']}", json={"keys": [{"type": "line", "value": "1"}]})
    assert r.status_code == 200, r.text
    assert admin.delete(f"{VARS}/{a['id']}").status_code == 204
    assert admin.delete(f"{VARS}/{inst['id']}").status_code == 204
    actions = {
        e["action"]
        for e in admin.get(
            "/api/v1/audit", params={"q": "provisioning.variable", "limit": 100}
        ).json()["items"]
    }
    assert {
        "provisioning.variable_create",
        "provisioning.variable_update",
        "provisioning.variable_delete",
    } <= actions
