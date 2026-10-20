# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dial-by-name directory's own names and operator (#135)."""


def test_directory_names_and_operator(admin):
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    admin.post(
        "/api/v1/extensions",
        json={"organization_id": org, "number": "1003", "display_name": "Nurse"},
    )
    base = "/api/v1/name-directory"
    assert admin.get(base, params={"organization_id": org}).json() == {
        "organization_id": org,
        "operator_number": None,
        "entries": [],
    }
    r = admin.post(
        f"{base}/entries",
        json={"organization_id": org, "name": "  Nurse  office ", "number": "1003"},
    )
    assert r.status_code == 201, r.text
    entry = r.json()
    assert entry["name"] == "Nurse office"
    dup = admin.post(
        f"{base}/entries", json={"organization_id": org, "name": "Nurse office", "number": "1003"}
    )
    assert dup.status_code == 409
    for bad in ({"name": "Pat, Jo", "number": "1003"}, {"name": "Lab", "number": "9999"}):
        r = admin.post(f"{base}/entries", json={"organization_id": org, **bad})
        assert r.status_code == 422, bad
    r = admin.patch(f"{base}/entries/{entry['id']}", json={"name": "Health office"})
    assert r.status_code == 200 and r.json()["name"] == "Health office"
    r = admin.put(f"{base}/operator", json={"organization_id": org, "operator_number": "1003"})
    assert r.status_code == 200 and r.json()["operator_number"] == "1003"
    assert (
        admin.put(
            f"{base}/operator", json={"organization_id": org, "operator_number": "77"}
        ).status_code
        == 422
    )
    r = admin.put(f"{base}/operator", json={"organization_id": org, "operator_number": ""})
    assert r.json()["operator_number"] is None
    assert admin.delete(f"{base}/entries/{entry['id']}").status_code == 204
    assert admin.get(base, params={"organization_id": org}).json()["entries"] == []
