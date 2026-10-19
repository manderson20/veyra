# SPDX-License-Identifier: AGPL-3.0-or-later
"""Portal canvas layouts and administrator templates (docs/USER_PORTAL.md §10)."""

import uuid

from conftest import ADMIN_PASSWORD, login
from fastapi.testclient import TestClient

from veyra.core.db import session_scope
from veyra.core.models import Building, Site

T = "/api/v1/portal-templates"
L = "/api/v1/me/portal/layout"


def _user(admin, email):
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    r = admin.post(
        "/api/v1/users",
        json={
            "email": email,
            "display_name": email.split("@")[0].title(),
            "password": ADMIN_PASSWORD,
            "home_organization_id": org,
            "require_password_change": False,
        },
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = admin.post(
        f"/api/v1/users/{uid}/roles",
        json={"role_key": "standard_user", "scope_type": "organization", "organization_id": org},
    )
    assert r.status_code in (200, 201), r.text
    return uid, org


def _layout(*keys, tab="home"):
    return {
        "version": 1,
        "tabs": [
            {
                "id": tab,
                "name": tab.title(),
                "widgets": [
                    {"key": k, "instance": "default", "x": 0, "y": i * 4, "w": 6, "h": 4}
                    for i, k in enumerate(keys)
                ],
            }
        ],
    }


def test_templates_resolve_by_scope_and_lock_widgets(admin, app):
    uid, org = _user(admin, "pat@example.org")
    # Buildings have no API of their own yet (docs/USER_PORTAL.md §10): a row.
    with session_scope() as db:
        site = Site(organization_id=uuid.UUID(org), name="North campus", slug="north")
        db.add(site)
        db.flush()
        building = Building(organization_id=uuid.UUID(org), site_id=site.id, name="North")
        db.add(building)
        db.flush()
        b = {"id": str(building.id)}
    ext = admin.post(
        "/api/v1/extensions",
        json={
            "organization_id": org,
            "number": "1001",
            "display_name": "Pat",
            "user_id": uid,
            "building_id": b["id"],
        },
    )
    assert ext.status_code == 201, ext.text
    pat = login(TestClient(app, base_url="http://veyra.test"), "pat@example.org", ADMIN_PASSWORD)

    # Nothing yet: the interface's default applies.
    assert pat.get(L).json() == {
        "layout": None,
        "source": "default",
        "template_id": None,
        "template_name": None,
        "locked_widgets": [],
    }
    # Organization template, then a building one with a locked announcement: the building wins.
    r = admin.post(
        T, json={"organization_id": org, "name": "Everyone", "layout": _layout("phone", "calls")}
    )
    assert r.status_code == 201, r.text
    org_t = r.json()
    r = admin.post(
        T,
        json={
            "organization_id": org,
            "name": "North building",
            "scope": "building",
            "scope_ref": b["id"],
            "layout": _layout("announce", "phone"),
            "locked_widgets": ["announce"],
        },
    )
    assert r.status_code == 201, r.text
    north = r.json()
    assert north["scope_label"] == "North"
    out = pat.get(L).json()
    assert out["source"] == "template" and out["template_name"] == "North building"
    assert out["locked_widgets"] == ["announce"]
    assert [w["key"] for w in out["layout"]["tabs"][0]["widgets"]] == ["announce", "phone"]
    # A role template outranks the building's.
    r = admin.post(
        T,
        json={
            "organization_id": org,
            "name": "Staff",
            "scope": "role",
            "scope_ref": "standard_user",
            "layout": _layout("phone"),
            "priority": 5,
        },
    )
    assert r.status_code == 201, r.text
    staff = r.json()
    assert pat.get(L).json()["template_name"] == "Staff"
    admin.patch(f"{T}/{staff['id']}", json={"is_enabled": False})
    assert pat.get(L).json()["template_name"] == "North building"
    # Bad scopes are refused.
    r = admin.post(
        T,
        json={"organization_id": org, "name": "x", "scope": "building", "layout": _layout("phone")},
    )
    assert r.status_code == 422
    r = admin.post(
        T,
        json={
            "organization_id": org,
            "name": "x",
            "scope": "role",
            "scope_ref": "nope",
            "layout": _layout("phone"),
        },
    )
    assert r.status_code == 422
    r = admin.post(
        T, json={"organization_id": org, "name": "x", "layout": {"version": 1, "tabs": []}}
    )
    assert r.status_code == 422

    # The user saves their own layout: it wins, but the locked widget must stay.
    r = pat.put(L, json={"layout": _layout("phone", "contacts")})
    assert r.status_code == 422 and r.json()["code"] == "widget_locked"
    r = pat.put(L, json={"layout": _layout("phone", "contacts", "announce", tab="mine")})
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "user" and r.json()["layout"]["tabs"][0]["id"] == "mine"
    assert pat.get("/api/v1/me/preferences").json()["portal"]["layout"]["tabs"][0]["id"] == "mine"
    # Widgets running past the grid are refused.
    bad = _layout("phone")
    bad["tabs"][0]["widgets"][0]["x"] = 8
    assert pat.put(L, json={"layout": bad}).status_code == 422
    # Reset returns to the template; push from the administrator does the same for everyone.
    assert pat.post(f"{L}/reset").json()["source"] == "template"
    pat.put(L, json={"layout": _layout("phone", "announce")})
    r = admin.post(f"{T}/{north['id']}/push")
    assert r.status_code == 200 and r.json()["reset"] == 1
    assert pat.get(L).json()["source"] == "template"
    # Templates are listed and deletable; the user cannot touch them.
    assert {t["name"] for t in admin.get(T).json()} >= {"Everyone", "North building", "Staff"}
    assert pat.get(T).status_code == 403
    assert admin.delete(f"{T}/{org_t['id']}").status_code == 204
