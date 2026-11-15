# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organization onboarding (docs/MULTI_TENANCY_MSP.md §10): the organization
is created with its numbers, and each step reports done or to do."""

from conftest import enable_multi_tenancy, give_main_number, org_body, org_user

ORGS = "/api/v1/organizations"


def _steps(client, org_id):
    r = client.get(f"{ORGS}/{org_id}/onboarding")
    assert r.status_code == 200, r.text
    return {s["key"]: s for s in r.json()["steps"]}, r.json()


def test_create_needs_numbers_with_multi_tenancy(admin):
    give_main_number(admin)
    enable_multi_tenancy()
    r = admin.post(ORGS, json={"name": "Gamma", "slug": "gamma"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "main_number"
    # A main number outside the numbers given is refused, and nothing is created.
    body = org_body("Gamma", "gamma")
    r = admin.post(ORGS, json={**body, "emergency_caller_id_number": "8165550000"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "emergency_caller_id_number"
    assert not [o for o in admin.get(ORGS).json()["items"] if o["slug"] == "gamma"]
    # Another organization's number is refused.
    r = admin.post(ORGS, json={**body, "numbers": [{"first": "5735550100"}]})
    assert r.status_code == 409 and r.json()["code"] == "number_assigned"
    r = admin.post(ORGS, json=body)
    assert r.status_code == 201, r.text
    org = r.json()
    assert org["main_number"] == body["main_number"]
    assert org["emergency_caller_id_number"] == body["main_number"]
    nums = admin.get(f"{ORGS}/{org['id']}/numbers").json()
    assert [n["first"] for n in nums] == [body["main_number"]]


def test_first_organization_without_multi_tenancy_needs_no_numbers(admin):
    # The setup's organization is active; deactivate it to stand in for a
    # fresh installation's first organization.
    first = admin.get(ORGS).json()["items"][0]
    assert admin.patch(f"{ORGS}/{first['id']}", json={"is_active": False}).status_code == 200
    r = admin.post(ORGS, json={"name": "Solo", "slug": "solo"})
    assert r.status_code == 201, r.text


def test_steps_report_done_and_left(admin, app):
    give_main_number(admin)
    enable_multi_tenancy()
    org = admin.post(ORGS, json=org_body("Delta", "delta")).json()
    steps, out = _steps(admin, org["id"])
    assert steps["organization"]["done"]
    assert not steps["administrator"]["done"]
    assert not steps["phones"]["done"]
    assert not steps["emergency"]["done"]
    assert steps["limits"]["optional"] and not steps["limits"]["done"]
    assert "First administrator" in out["left"] and "Limits" not in out["left"]

    org_user(admin, app, "it@delta.local", "org_admin", org["id"])
    rot = admin.post(f"{ORGS}/{org['id']}/provisioning-credential/rotate")
    assert rot.status_code == 200, rot.text
    admin.put(f"{ORGS}/{org['id']}/limits", json={"max_outside_calls": 4})
    steps, _ = _steps(admin, org["id"])
    assert steps["administrator"]["done"] and "it@delta.local" in steps["administrator"]["detail"]
    assert steps["phones"]["done"]
    assert steps["limits"]["done"] and "4" in steps["limits"]["detail"]


def test_check_lists_what_is_left_and_scope(admin, app):
    give_main_number(admin)
    enable_multi_tenancy()
    org = admin.post(ORGS, json=org_body("Eps", "eps")).json()
    r = admin.post(f"{ORGS}/{org['id']}/onboarding/check")
    assert r.status_code == 200, r.text
    out = r.json()
    assert {c["name"] for c in out["checks"]} >= {"namespaces", "main_numbers", "isolation"}
    assert out["emergency"][0]["emergency_number"] == org["emergency_caller_id_number"]
    assert not out["ok"] and "Emergency" in out["left"]
    # Another organization's administrator cannot see it.
    first = next(o for o in admin.get(ORGS).json()["items"] if o["id"] != org["id"])
    other = org_user(admin, app, "it@first.local", "org_admin", first["id"])
    assert other.get(f"{ORGS}/{org['id']}/onboarding").status_code == 404
    assert other.post(f"{ORGS}/{org['id']}/onboarding/check").status_code == 403
