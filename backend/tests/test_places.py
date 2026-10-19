# SPDX-License-Identifier: AGPL-3.0-or-later
"""Buildings, departments and the site/building/department of an extension (#126)."""

from conftest import enable_multi_tenancy


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]["id"]


def _site(admin, org, name="Main Campus"):
    r = admin.post("/api/v1/sites", json={"organization_id": org, "name": name, "street": "1 Main"})
    assert r.status_code == 201, r.text
    return r.json()


def test_buildings_and_departments_crud(admin):
    org = _org(admin)
    site = _site(admin, org)
    r = admin.post(f"/api/v1/sites/{site['id']}/buildings", json={"name": " Gym "})
    assert r.status_code == 201, r.text
    gym = r.json()
    assert gym["name"] == "Gym" and gym["site_name"] == "Main Campus"
    assert gym["has_own_address"] is False
    dup = admin.post(f"/api/v1/sites/{site['id']}/buildings", json={"name": "Gym"})
    assert dup.status_code == 409 and dup.json()["code"] == "name_in_use"
    r = admin.patch(
        f"/api/v1/buildings/{gym['id']}", json={"street": "2 Field Rd", "country": "us"}
    )
    assert r.json()["has_own_address"] is True and r.json()["country"] == "US"
    assert [b["name"] for b in admin.get(f"/api/v1/sites/{site['id']}/buildings").json()] == ["Gym"]
    assert len(admin.get("/api/v1/buildings", params={"organization_id": org}).json()) == 1

    d = admin.post("/api/v1/departments", json={"organization_id": org, "name": "Office"})
    assert d.status_code == 201, d.text
    dept = d.json()
    r = admin.patch(f"/api/v1/departments/{dept['id']}", json={"site_id": site["id"]})
    assert r.json()["site_name"] == "Main Campus"

    # A site with buildings cannot be deleted; an unused building can.
    assert admin.delete(f"/api/v1/sites/{site['id']}").status_code == 409
    ext = admin.post(
        "/api/v1/extensions",
        json={
            "organization_id": org,
            "number": "1001",
            "display_name": "Coach",
            "building_id": gym["id"],
            "department_id": dept["id"],
        },
    ).json()
    assert ext["site_id"] == site["id"] and ext["building_name"] == "Gym"
    assert ext["department_name"] == "Office"
    busy = admin.delete(f"/api/v1/buildings/{gym['id']}")
    assert busy.status_code == 409 and busy.json()["code"] == "building_in_use"
    assert admin.get(f"/api/v1/sites/{site['id']}").json()["extensions"] == 1
    assert admin.delete(f"/api/v1/departments/{dept['id']}").status_code == 204
    assert admin.get(f"/api/v1/extensions/{ext['id']}").json()["department_id"] is None
    events = admin.get("/api/v1/audit", params={"q": "building."}).json()
    assert events["total"] >= 2


def test_extension_site_and_building_rules(admin):
    org = _org(admin)
    a = _site(admin, org, "North")
    b = _site(admin, org, "South")
    hall = admin.post(f"/api/v1/sites/{a['id']}/buildings", json={"name": "Hall"}).json()
    ext = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org, "number": "1002", "display_name": "Desk", "site_id": b["id"]},
    ).json()
    assert ext["site_id"] == b["id"] and ext["site_name"] == "South"
    # A building at another site than the one given is refused.
    r = admin.patch(
        f"/api/v1/extensions/{ext['id']}", json={"site_id": b["id"], "building_id": hall["id"]}
    )
    assert r.status_code == 422
    # A building alone moves the extension to its site.
    r = admin.patch(f"/api/v1/extensions/{ext['id']}", json={"building_id": hall["id"]})
    assert r.status_code == 200 and r.json()["site_id"] == a["id"]
    # Moving to another site drops the building.
    r = admin.patch(f"/api/v1/extensions/{ext['id']}", json={"site_id": b["id"]})
    assert r.json()["site_id"] == b["id"] and r.json()["building_id"] is None
    r = admin.patch(f"/api/v1/extensions/{ext['id']}", json={"site_id": None})
    assert r.json()["site_id"] is None

    enable_multi_tenancy()
    other = admin.post("/api/v1/organizations", json={"name": "Beta", "slug": "beta"}).json()["id"]
    elsewhere = _site(admin, other, "Beta HQ")
    r = admin.patch(f"/api/v1/extensions/{ext['id']}", json={"site_id": elsewhere["id"]})
    assert r.status_code == 422
    dept = admin.post("/api/v1/departments", json={"organization_id": other, "name": "X"}).json()
    r = admin.patch(f"/api/v1/extensions/{ext['id']}", json={"department_id": dept["id"]})
    assert r.status_code == 422
