# SPDX-License-Identifier: AGPL-3.0-or-later
"""Personal contacts and speed dials (docs/USER_PORTAL.md §6)."""

from conftest import ADMIN_PASSWORD, login
from fastapi.testclient import TestClient

ME = "/api/v1/me/contacts"


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
    return uid


def test_contacts_crud_search_speed_dials_import_export(admin, app):
    _user(admin, "pat@example.org")
    _user(admin, "sam@example.org")
    pat = login(TestClient(app, base_url="http://veyra.test"), "pat@example.org", ADMIN_PASSWORD)
    sam = login(TestClient(app, base_url="http://veyra.test"), "sam@example.org", ADMIN_PASSWORD)

    r = pat.post(
        ME,
        json={
            "name": "Front Office",
            "company": "Example Schools",
            "numbers": [
                {"label": "work", "number": "(573) 555-0100"},
                {"label": "mobile", "number": "+1 573 555 0101"},
            ],
            "email": "Office@Example.org",
            "favourite": True,
            "speed_dial": 1,
        },
    )
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["numbers"][0]["number"] == "5735550100" and c["numbers"][1]["number"] == "+15735550101"
    assert c["email"] == "office@example.org" and c["speed_dial"] == 1 and c["favourite"]
    # A contact needs a number or an email; numbers are checked; slot 1 is taken.
    assert pat.post(ME, json={"name": "Nobody"}).status_code == 422
    assert pat.post(ME, json={"name": "Bad", "numbers": [{"number": "abc"}]}).status_code == 422
    r = pat.post(ME, json={"name": "Dup", "numbers": [{"number": "1002"}], "speed_dial": 1})
    assert r.status_code == 409 and r.json()["code"] == "speed_dial_in_use"
    r = pat.post(ME, json={"name": "Bus Garage", "numbers": [{"number": "1002"}], "speed_dial": 2})
    assert r.status_code == 201
    garage = r.json()
    # Listing: favourites first, then by name; search by name, company and digits.
    names = [x["name"] for x in pat.get(ME).json()]
    assert names == ["Front Office", "Bus Garage"]
    assert [x["name"] for x in pat.get(ME, params={"q": "garage"}).json()] == ["Bus Garage"]
    assert [x["name"] for x in pat.get(ME, params={"q": "555-0101"}).json()] == ["Front Office"]
    assert [x["name"] for x in pat.get(ME, params={"favourite": "true"}).json()] == ["Front Office"]
    # Sam sees nothing of Pat's.
    assert sam.get(ME).json() == []
    assert sam.get(f"{ME}/{garage['id']}").status_code == 404
    assert sam.delete(f"{ME}/{garage['id']}").status_code == 404
    # Patch: move the speed dial, clear the company; last number cannot be removed without an email.
    r = pat.patch(f"{ME}/{garage['id']}", json={"speed_dial": 5, "company": "  "})
    assert r.status_code == 200 and r.json()["speed_dial"] == 5 and r.json()["company"] is None
    assert pat.patch(f"{ME}/{garage['id']}", json={"numbers": []}).status_code == 422
    assert pat.patch(f"{ME}/{garage['id']}", json={"speed_dial": 1}).status_code == 409
    # Export then import back (replace): the same two contacts, slots kept.
    r = pat.get(f"{ME}/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    text = r.text
    assert "Front Office" in text and "work:5735550100 mobile:+15735550101" in text
    r = pat.post(f"{ME}/import", json={"text": text, "replace": True})
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 2 and r.json()["updated"] == 0 and r.json()["skipped"] == []
    after = {x["name"]: x for x in pat.get(ME).json()}
    assert after["Front Office"]["speed_dial"] == 1 and after["Bus Garage"]["speed_dial"] == 5
    assert after["Front Office"]["numbers"][1] == {"label": "mobile", "number": "+15735550101"}
    # Plain "name, company, number" lines update by name and skip unusable ones.
    r = pat.post(
        f"{ME}/import",
        json={"text": "Bus Garage,District,5735550199\nNo Number,,\nnew person,,1003\n"},
    )
    assert r.json()["added"] == 1 and r.json()["updated"] == 1 and len(r.json()["skipped"]) == 1
    assert {x["name"]: x for x in pat.get(ME).json()}["Bus Garage"]["numbers"][0][
        "number"
    ] == "5735550199"
    # Delete, audited as self-service.
    garage_now = {x["name"]: x for x in pat.get(ME).json()}["Bus Garage"]
    assert pat.delete(f"{ME}/{garage_now['id']}").status_code == 204
    events = [
        e
        for e in admin.get("/api/v1/audit", params={"q": "contact.create"}).json()["items"]
        if e["action"] == "contact.create"
    ]
    assert events and events[0]["details"]["self_service"] is True
