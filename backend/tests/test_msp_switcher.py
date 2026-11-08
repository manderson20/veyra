# SPDX-License-Identifier: AGPL-3.0-or-later
"""Working in one organization (docs/MULTI_TENANCY_MSP.md §10a): the
X-Veyra-Organization header narrows a request to one organization, even for a
platform administrator, and roles can be granted per client."""

from conftest import org_body, org_user, two_organizations

H = "X-Veyra-Organization"
EXT = "/api/v1/extensions"


def _in(org_id):
    return {H: org_id}


def test_one_organization_has_no_switcher(admin):
    r = admin.get("/api/v1/me/organizations")
    assert r.status_code == 200
    assert r.json()["switcher"] is False and r.json()["system"] is True


def test_platform_admin_working_in_one_organization(admin):
    a, b = two_organizations(admin)
    me = admin.get("/api/v1/me/organizations").json()
    assert me["switcher"] and me["system"]
    assert {o["id"] for o in me["organizations"]} == {a.id, b.id}
    # The switcher's own list is not narrowed.
    assert (
        len(admin.get("/api/v1/me/organizations", headers=_in(a.id)).json()["organizations"]) == 2
    )

    # Lists show only the organization being worked in.
    items = admin.get(EXT, headers=_in(a.id)).json()["items"]
    assert items and {e["organization_id"] for e in items} == {a.id}
    orgs = admin.get("/api/v1/organizations", headers=_in(a.id)).json()["items"]
    assert [o["id"] for o in orgs] == [a.id]
    # B's extension cannot be changed from A.
    b_ext = b.extensions["1001"]["id"]
    r = admin.patch(f"{EXT}/{b_ext}", json={"display_name": "x"}, headers=_in(a.id))
    assert r.status_code in (403, 404)
    r = admin.post(
        EXT,
        json={"organization_id": b.id, "number": "1777", "display_name": "x"},
        headers=_in(a.id),
    )
    assert r.status_code in (403, 404)
    # Platform-only pages are under System, not in an organization.
    assert admin.get("/api/v1/system/multi-tenancy", headers=_in(a.id)).status_code == 403
    session = admin.get("/api/v1/auth/session", headers=_in(a.id)).json()
    assert session["is_platform_admin"] is False
    assert "system.settings.write" not in session["permissions"]
    assert "extensions.write" in session["permissions"]
    # Without the header: today's behaviour.
    assert admin.get("/api/v1/system/multi-tenancy").status_code == 200
    assert admin.patch(f"{EXT}/{b_ext}", json={"display_name": "B one"}).status_code == 200


def test_technician_in_some_clients(admin, app):
    a, b = two_organizations(admin)
    c = admin.post("/api/v1/organizations", json=org_body("Gamma", "gamma")).json()
    tech = org_user(admin, app, "tech@msp.local", "technician", a.id)
    uid = next(
        u["id"]
        for u in admin.get("/api/v1/users").json()["items"]
        if u["email"] == "tech@msp.local"
    )
    url = f"/api/v1/users/{uid}/roles/technician/organizations"
    r = admin.put(url, json={"organization_ids": [a.id, c["id"]]})
    assert r.status_code == 200, r.text
    assert {x["organization_id"] for x in r.json()} == {a.id, c["id"]}

    me = tech.get("/api/v1/me/organizations").json()
    assert {o["id"] for o in me["organizations"]} == {a.id, c["id"]}
    assert me["system"] is False and me["switcher"] is True
    r = tech.get(EXT, headers=_in(b.id))
    assert r.status_code == 403 and r.json()["code"] == "organization_not_available"
    assert tech.get(f"{EXT}/{b.extensions['1001']['id']}", headers=_in(a.id)).status_code in (
        403,
        404,
    )
    assert tech.get(EXT, headers=_in(c["id"])).status_code == 200
    # A link carries the short name.
    assert tech.get(EXT, headers=_in("gamma")).status_code == 200

    # Removing a client ends the access at once.
    r = admin.put(url, json={"organization_ids": [a.id]})
    assert {x["organization_id"] for x in r.json()} == {a.id}
    assert tech.get(EXT, headers=_in(c["id"])).status_code == 403


def test_org_admin_grants_only_in_own_organization(admin, app):
    a, b = two_organizations(admin)
    alice = org_user(admin, app, "admin@a.local", "org_admin", a.id)
    org_user(admin, app, "helper@a.local", "read_only", a.id)
    uid = next(
        u["id"]
        for u in alice.get("/api/v1/users").json()["items"]
        if u["email"] == "helper@a.local"
    )
    url = f"/api/v1/users/{uid}/roles/technician/organizations"
    assert alice.put(url, json={"organization_ids": [b.id]}).status_code == 404
    r = alice.put(url, json={"organization_ids": [a.id]})
    assert r.status_code == 200, r.text
    # Platform-wide is never granted this way.
    url = f"/api/v1/users/{uid}/roles/platform_admin/organizations"
    assert admin.put(url, json={"organization_ids": [a.id]}).status_code == 403


def test_bad_header_is_refused(admin):
    r = admin.get(EXT, headers={H: "no-such-org"})
    assert r.status_code == 403
    r = admin.get(EXT, headers={H: "00000000-0000-0000-0000-000000000001"})
    assert r.status_code == 403
