# SPDX-License-Identifier: AGPL-3.0-or-later
from conftest import ADMIN_PASSWORD, login


def make_org(admin, slug):
    r = admin.post("/api/v1/organizations", json={"name": slug.title(), "slug": slug})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_user(admin, email, org_id, role=None, scope="organization"):
    r = admin.post(
        "/api/v1/users",
        json={
            "email": email,
            "display_name": email.split("@")[0],
            "password": ADMIN_PASSWORD,
            "home_organization_id": org_id,
            "require_password_change": False,
        },
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    if role:
        r = admin.post(
            f"/api/v1/users/{uid}/roles",
            json={"role_key": role, "scope_type": scope, "organization_id": org_id},
        )
        assert r.status_code == 201, r.text
    return uid


def test_org_admin_is_confined_to_their_organization(admin, app):
    from fastapi.testclient import TestClient

    a, b = make_org(admin, "alpha"), make_org(admin, "beta")
    make_user(admin, "orgadmin@alpha.local", a, "org_admin")
    make_user(admin, "someone@beta.local", b)
    c = login(TestClient(app, base_url="http://veyra.test"), "orgadmin@alpha.local", ADMIN_PASSWORD)

    orgs = c.get("/api/v1/organizations").json()
    assert [o["slug"] for o in orgs["items"]] == ["alpha"]
    assert c.get(f"/api/v1/organizations/{b}").status_code == 404
    emails = [u["email"] for u in c.get("/api/v1/users").json()["items"]]
    assert "someone@beta.local" not in emails and "orgadmin@alpha.local" in emails

    # cannot create users in another org, cannot create organizations
    r = c.post(
        "/api/v1/users",
        json={
            "email": "x@beta.local",
            "display_name": "x",
            "password": ADMIN_PASSWORD,
            "home_organization_id": b,
        },
    )
    assert r.status_code == 403
    assert c.post("/api/v1/organizations", json={"name": "G", "slug": "g"}).status_code == 403

    # cannot escalate to platform scope
    me = next(
        u for u in c.get("/api/v1/users").json()["items"] if u["email"].startswith("orgadmin")
    )
    r = c.post(
        f"/api/v1/users/{me['id']}/roles",
        json={"role_key": "platform_admin", "scope_type": "platform"},
    )
    assert r.status_code == 403

    # platform-only areas are denied
    assert c.post("/api/v1/modules/veyra.example-notes/install").status_code == 403
    assert c.put("/api/v1/updates/policies/veyra_core", json={"mode": "manual"}).status_code == 403


def test_read_only_user_cannot_write_and_denial_is_audited(admin, app):
    from fastapi.testclient import TestClient

    a = make_org(admin, "gamma")
    make_user(admin, "viewer@gamma.local", a, "read_only")
    c = login(TestClient(app, base_url="http://veyra.test"), "viewer@gamma.local", ADMIN_PASSWORD)
    assert c.get("/api/v1/users").status_code == 200
    r = c.post(
        "/api/v1/users",
        json={
            "email": "n@gamma.local",
            "display_name": "n",
            "password": ADMIN_PASSWORD,
            "home_organization_id": a,
        },
    )
    assert r.status_code == 403
    denied = admin.get("/api/v1/audit", params={"outcome": "denied"}).json()["items"]
    assert any(e["action"] == "permission.denied:users.write" for e in denied)


def test_user_without_roles_sees_nothing(admin, app):
    from fastapi.testclient import TestClient

    a = make_org(admin, "delta")
    make_user(admin, "nobody@delta.local", a)
    c = login(TestClient(app, base_url="http://veyra.test"), "nobody@delta.local", ADMIN_PASSWORD)
    s = c.get("/api/v1/auth/session").json()
    assert s["permissions"] == [] and not s["is_platform_admin"]
    for path in (
        "/api/v1/organizations",
        "/api/v1/users",
        "/api/v1/audit",
        "/api/v1/system/health",
        "/api/v1/modules",
    ):
        assert c.get(path).status_code == 403, path


def test_deactivated_user_is_signed_out(admin, app):
    from fastapi.testclient import TestClient

    a = make_org(admin, "eps")
    uid = make_user(admin, "temp@eps.local", a, "read_only")
    c = login(TestClient(app, base_url="http://veyra.test"), "temp@eps.local", ADMIN_PASSWORD)
    assert admin.patch(f"/api/v1/users/{uid}", json={"is_active": False}).status_code == 200
    assert c.get("/api/v1/auth/session").status_code == 401


def test_last_platform_admin_cannot_be_removed(admin):
    me = admin.get("/api/v1/auth/session").json()["user"]["id"]
    assignment = admin.get(f"/api/v1/users/{me}/roles").json()[0]
    r = admin.delete(f"/api/v1/users/{me}/roles/{assignment['id']}")
    assert r.status_code == 409


def test_search_respects_scope(admin):
    make_org(admin, "zeta")
    results = admin.get("/api/v1/search", params={"q": "zet"}).json()["results"]
    assert any(r["type"] == "organization" for r in results)
