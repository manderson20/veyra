# SPDX-License-Identifier: AGPL-3.0-or-later
"""Limits per organization (docs/MULTI_TENANCY_MSP.md §8): outside calls,
extensions and devices; emergency calls are never counted or refused."""

from conftest import org_user, two_organizations

EXT = "/api/v1/extensions"


def _limits(org_id):
    return f"/api/v1/organizations/{org_id}/limits"


def test_extension_and_device_limits(admin, app):
    a, b = two_organizations(admin)
    r = admin.put(_limits(a.id), json={"max_extensions": 3, "max_devices": 1})
    assert r.status_code == 200 and r.json()["extensions"] == 2
    alice = org_user(admin, app, "admin@a.local", "org_admin", a.id)
    assert alice.get(_limits(a.id)).json()["max_extensions"] == 3
    assert alice.put(_limits(a.id), json={"max_extensions": 99}).status_code == 403
    assert alice.get(_limits(b.id)).status_code == 404
    new = {"organization_id": a.id, "display_name": "x"}
    assert alice.post(EXT, json={**new, "number": "1003"}).status_code == 201
    r = alice.post(EXT, json={**new, "number": "1004"})
    assert r.status_code == 409 and r.json()["code"] == "limit_reached"
    # Beta is not limited by Alpha's limit.
    assert (
        admin.post(EXT, json={**new, "organization_id": b.id, "number": "1004"}).status_code == 201
    )
    device = {"organization_id": a.id, "manufacturer": "Yealink", "model": "T46U"}
    assert (
        admin.post("/api/v1/devices", json={**device, "mac_address": "805ec0aa0101"}).status_code
        == 201
    )
    r = admin.post("/api/v1/devices", json={**device, "mac_address": "805ec0aa0102"})
    assert r.status_code == 409 and r.json()["code"] == "limit_reached"
    # Lowering below today's count is allowed; nothing new until it is under.
    r = admin.put(_limits(a.id), json={"max_extensions": 1})
    assert r.status_code == 200 and r.json()["extensions"] == 3


def test_outside_call_limit_in_the_dialplan():
    from test_generator_routing import _route
    from test_generator_routing import _trunk as _trunk_snap
    from test_multi_tenancy import _base, _files, _org_b

    snap = _org_b(_base())
    snap["installation"]["multi_tenancy_enabled"] = True
    snap["organizations"][1]["max_outside_calls"] = 4
    snap["trunks"] = [_trunk_snap()]
    snap["outbound_routes"] = [
        _route(),
        _route("e911", is_emergency=True, patterns=[{"prefix": "", "match": "911", "prepend": ""}]),
    ]
    snap["inbound_routes"] = [
        {
            "did": "5735550200",
            "trunk": None,
            "destination": {"type": "extension", "number": "1001"},
            "organization": "x",
            "organization_slug": "beta",
        },
        {
            "did": "5735550100",
            "trunk": None,
            "destination": {"type": "extension", "number": "1001"},
            "organization": "y",
            "organization_slug": "example",
        },
    ]
    snap["sites"] = [
        {
            "id": "s",
            "slug": "main",
            "name": "Main",
            "organization": "beta",
            "emergency_caller_id_number": "5735550299",
            "callback_minutes": 30,
            "responder": None,
        }
    ]
    dp = _files(snap)["extensions.conf"].content
    local = dp.split("[veyra-out-local]")[1].split("\n[")[0]
    assert "Set(GROUP(veyra_org)=${VEYRA_ORG})" in local
    assert '"${VEYRA_ORG}"="beta" & ${GROUP_COUNT(beta@veyra_org)} > 4]?orgbusy' in local
    assert "example@veyra_org" not in local
    e911 = dp.split("[veyra-out-e911]")[1].split("\n[")[0]
    assert "veyra_org" not in e911  # emergency calls are never counted
    trunk_ctx = dp.split("[veyra-from-trunk]")[1].split("\n[")[0]
    beta_did = trunk_ctx.split("exten => 5735550200,")[1].split("exten => ")[0]
    assert "GROUP_COUNT(beta@veyra_org)} > 4]?orgfull" in beta_did and "n(orgfull)" in beta_did
    example_did = trunk_ctx.split("exten => 5735550100,")[1].split("exten => ")[0]
    assert "veyra_org" not in example_did
    # The 911 callback to Beta's ELIN is never refused.
    elin = trunk_ctx.split("exten => 5735550299,")[1].split("exten => ")[0]
    assert "veyra_org" not in elin
    # No limit anywhere: nothing written.
    assert "veyra_org" not in _files(_base())["extensions.conf"].content
