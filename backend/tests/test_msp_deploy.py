# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organization administrators apply their own changes, and one
organization's broken data does not stop the others
(docs/MULTI_TENANCY_MSP.md §7)."""

from conftest import org_user, two_organizations
from test_api_routing import _fake

from veyra.core.db import session_scope
from veyra.core.models import Extension

APPLY = "/api/v1/telephony/apply"
ENGINE = "/api/v1/telephony/engine"


def _deploy(deployer):
    with session_scope() as db:
        deployer.run_once(db)


def test_organization_administrators_apply_when_idle_and_not_too_often(admin, app, tmp_path):
    adapter, deployer, _ = _fake(app, tmp_path)
    adapter.calls = []  # when idle: nothing to wait for
    a, b = two_organizations(admin)
    alice = org_user(admin, app, "admin@a.local", "org_admin", a.id)
    r = alice.post(APPLY, json={"mode": "now"})
    assert r.status_code == 202, r.text
    assert r.json()["revision"]["deploy_mode"] == "when_idle"
    _deploy(deployer)
    events = admin.get("/api/v1/audit", params={"q": "telephony.config_apply"}).json()["items"]
    assert events[0]["organization_id"] == a.id
    r = alice.post(APPLY, json={})
    assert r.status_code == 429 and r.json()["code"] == "apply_rate_limited"
    # Never for another organization.
    assert alice.post(APPLY, json={"organization_id": b.id}).status_code == 403
    # The platform is not limited.
    r = admin.post(APPLY, json={})
    assert r.status_code == 202, r.text


def test_a_single_organization_keeps_platform_only_deploys(admin, app, tmp_path):
    _fake(app, tmp_path)
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    alice = org_user(admin, app, "admin@one.local", "org_admin", org)
    assert alice.post(APPLY, json={}).status_code == 403


def test_request_only_mode(admin, app, tmp_path):
    _fake(app, tmp_path)
    a, _ = two_organizations(admin)
    r = admin.put("/api/v1/system/multi-tenancy/org-apply", json={"mode": "request"})
    assert r.status_code == 200 and r.json()["org_apply"] == "request"
    alice = org_user(admin, app, "admin@a.local", "org_admin", a.id)
    r = alice.post(APPLY, json={})
    assert r.status_code == 202 and r.json()["requested"] and r.json()["revision"] is None
    assert alice.get(ENGINE).json()["org_apply"] == "request"
    requests = admin.get(ENGINE).json()["apply_requests"]
    assert [x["organization_id"] for x in requests] == [a.id]
    assert admin.post(APPLY, json={}).status_code == 202
    assert admin.get(ENGINE).json()["apply_requests"] == []


def test_each_organization_sees_its_own_pending_change(admin, app, tmp_path):
    _fake(app, tmp_path)
    a, b = two_organizations(admin)
    alice = org_user(admin, app, "admin@a.local", "org_admin", a.id)
    alice.patch(f"/api/v1/extensions/{a.extensions['1001']['id']}", json={"display_name": "Desk"})
    mine = alice.get(ENGINE).json()["organization_pending"]
    assert {p["organization_id"] for p in mine} == {a.id}
    every = {p["organization_id"] for p in admin.get(ENGINE).json()["organization_pending"]}
    assert {a.id, b.id} <= every


def test_one_organizations_broken_data_is_held_back(admin, app, tmp_path):
    _, deployer, cfg = _fake(app, tmp_path)
    a, b = two_organizations(admin)
    assert admin.post(APPLY, json={}).status_code == 202
    _deploy(deployer)
    # Beta's data breaks generation (written past the API's checks) ...
    with session_scope() as db:
        db.get(Extension, b.extensions["1002"]["id"]).caller_id_number = "bad;value"
    # ... while Alpha adds an extension.
    admin.post(
        "/api/v1/extensions",
        json={"organization_id": a.id, "number": "1003", "display_name": "New"},
    )
    r = admin.post(APPLY, json={})
    assert r.status_code == 202, r.text
    assert r.json()["applied"] and r.json()["held_back"] == ["beta"]
    _deploy(deployer)
    endpoints = (cfg / "pjsip.endpoints.conf").read_text()
    assert f"[{a.slug}-1003]" in endpoints and "[beta-1002]" in endpoints
    bob = org_user(admin, app, "admin@b.local", "org_admin", b.id)
    held = bob.get(ENGINE).json()["held_back"]
    assert [h["organization_id"] for h in held] == [b.id] and "bad;value" in held[0]["error"]
    alice = org_user(admin, app, "admin@a.local", "org_admin", a.id)
    assert alice.get(ENGINE).json()["held_back"] == []
    # Fixed: the note goes.
    with session_scope() as db:
        db.get(Extension, b.extensions["1002"]["id"]).caller_id_number = None
    r = admin.post(APPLY, json={})
    assert r.status_code == 202 and r.json()["held_back"] == []
    assert admin.get(ENGINE).json()["held_back"] == []


def test_a_shared_error_still_stops_everyone(admin, app, tmp_path):
    _, deployer, _ = _fake(app, tmp_path)
    two_organizations(admin)
    assert admin.post(APPLY, json={}).status_code == 202
    _deploy(deployer)
    with session_scope() as db:
        from veyra.core.models import SipTrunk

        db.add(
            SipTrunk(
                name="Broken",
                slug="broken slug",
                auth_mode="ip",
                host="198.51.100.9",
                default_caller_id="bad;value",
                match_addresses=["198.51.100.9"],
            )
        )
    r = admin.post(APPLY, json={})
    assert r.status_code == 202 and r.json()["revision"]["state"] == "failed"
