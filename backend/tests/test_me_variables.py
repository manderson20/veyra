# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /me/provisioning/variables (issue #130): the user's non-sensitive
variables (nearest scope) and the enabled feature codes."""

from conftest import ADMIN_PASSWORD, login
from fastapi.testclient import TestClient
from test_api_mfa import _make_user


def test_my_variables_and_codes(admin, app):
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    uid = _make_user(admin, "pat@example.org")
    r = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org, "number": "1001", "display_name": "Pat", "user_id": uid},
    )
    assert r.status_code == 201, r.text
    for body in (
        {"scope": "organization", "scope_id": org, "name": "all_call", "value": "7000"},
        {
            "scope": "organization",
            "scope_id": org,
            "name": "admin_pw",
            "value": "x",
            "sensitive": True,
        },
    ):
        assert admin.post("/api/v1/provisioning/variables", json=body).status_code == 201
    user = login(TestClient(app, base_url="http://veyra.test"), "pat@example.org", ADMIN_PASSWORD)
    out = user.get("/api/v1/me/provisioning/variables").json()
    assert out["variables"] == {"all_call": "7000"}
    codes = {c["key"]: c["code"] for c in out["feature_codes"]}
    assert codes["dnd_toggle"] == "*76" and codes["park_pickup"] == "*85"
