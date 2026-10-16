# SPDX-License-Identifier: AGPL-3.0-or-later
from conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    complete_setup,
    csrf_headers,
    enable_multi_tenancy,
    login,
)

from veyra.core import bootstrap
from veyra.core.db import session_scope


def test_setup_status_before_and_after(client):
    s = client.get("/api/v1/setup/status").json()
    assert s["setup_required"] is True and s["token_issued"] is False
    assert any(not step["available"] for step in s["steps"])
    complete_setup(client)
    assert client.get("/api/v1/setup/status").json()["setup_required"] is False


def _setup_body(token: str) -> dict:
    return {
        "setup_token": token,
        "installation_name": "X",
        "administrator": {
            "email": "a@b.local",
            "display_name": "A",
            "password": "long enough password",
        },
        "organization": {"name": "Org", "slug": "org", "timezone": "UTC"},
    }


def test_setup_requires_valid_token(client):
    r = client.post("/api/v1/setup/initialize", json=_setup_body("guess"))
    assert r.status_code == 403 and r.json()["code"] == "invalid_setup_token"
    with session_scope() as db:
        bootstrap.create_setup_token(db)
    assert client.post("/api/v1/setup/initialize", json=_setup_body("wrong")).status_code == 403


def test_setup_only_once(client):
    complete_setup(client)
    with session_scope() as db:
        assert not bootstrap.setup_required(db)
        token = bootstrap.create_setup_token(db)
    r = client.post("/api/v1/setup/initialize", json=_setup_body(token))
    assert r.status_code == 409


def test_setup_enforces_password_policy(client):
    with session_scope() as db:
        token = bootstrap.create_setup_token(db)
    body = _setup_body(token)
    body["administrator"]["password"] = "short"
    r = client.post("/api/v1/setup/initialize", json=body)
    assert r.status_code == 422 and r.json()["code"] == "password_policy"


def test_login_logout_flow(admin):
    admin.post("/api/v1/auth/logout")
    assert admin.get("/api/v1/auth/session").status_code == 401
    login(admin, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert admin.get("/api/v1/auth/session").status_code == 200


def test_login_failure_is_generic_and_audited(admin):
    admin.cookies.clear()
    r1 = admin.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong password!"}
    )
    r2 = admin.post(
        "/api/v1/auth/login", json={"email": "nobody@x.local", "password": "whatever123"}
    )
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"]
    login(admin, ADMIN_EMAIL, ADMIN_PASSWORD)
    events = admin.get("/api/v1/audit", params={"q": "auth.login", "outcome": "failure"}).json()
    assert events["total"] >= 2


def test_account_lockout(client, settings, monkeypatch):
    import veyra.api.v1.auth as auth_mod
    from veyra.core.security.ratelimit import SlidingWindowLimiter

    complete_setup(client)
    client.cookies.clear()
    roomy = SlidingWindowLimiter(1000, 60)  # isolate account lockout from per-IP limiting
    monkeypatch.setattr(auth_mod, "_limiter", lambda _settings: roomy)
    for _ in range(settings.account_lockout_threshold):
        client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "bad password"})
    r = client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 401  # locked even with the right password


def test_ip_rate_limit(client):
    import veyra.api.v1.auth as auth_mod

    auth_mod._ip_limiter = None
    codes = [
        client.post(
            "/api/v1/auth/login", json={"email": "x@y.local", "password": "nope nope"}
        ).status_code
        for _ in range(12)
    ]
    assert 429 in codes
    auth_mod._ip_limiter = None


def test_csrf_required_for_mutations(admin):
    token = admin.headers.pop("X-CSRF-Token")
    enable_multi_tenancy()
    r = admin.post("/api/v1/organizations", json={"name": "N", "slug": "n"})
    assert r.status_code == 403 and r.json()["code"] == "csrf_failed"
    r = admin.post(
        "/api/v1/organizations", json={"name": "N", "slug": "n"}, headers={"X-CSRF-Token": "forged"}
    )
    assert r.status_code == 403
    admin.headers["X-CSRF-Token"] = token
    assert admin.post("/api/v1/organizations", json={"name": "N", "slug": "n"}).status_code == 201


def test_cookies_are_httponly_and_strict(client):
    with session_scope() as db:
        token = bootstrap.create_setup_token(db)
    r = client.post("/api/v1/setup/initialize", json=_setup_body(token))
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("__Host-veyra_session="))
    assert "HttpOnly" in session and "SameSite=strict" in session


def test_password_change_revokes_other_sessions(admin, app):
    from fastapi.testclient import TestClient

    other = TestClient(app, base_url="http://veyra.test")
    login(other, ADMIN_EMAIL, ADMIN_PASSWORD)
    r = admin.post(
        "/api/v1/auth/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "an even better password"},
    )
    assert r.status_code == 200
    assert admin.get("/api/v1/auth/session").status_code == 200
    assert other.get("/api/v1/auth/session").status_code == 401


def test_problem_details_format(admin):
    r = admin.get("/api/v1/organizations/not-a-uuid")
    assert r.status_code == 422
    body = r.json()
    assert r.headers["content-type"].startswith("application/problem+json")
    assert body["code"] == "validation_failed" and body["errors"] and body["request_id"]
    assert r.headers["x-request-id"] == body["request_id"]
    assert csrf_headers(admin)
