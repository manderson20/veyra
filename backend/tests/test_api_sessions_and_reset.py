"""Milestone 2: sessions, password reset links, forced password change,
unlock, fetch-metadata rejection and purging."""

from datetime import timedelta

from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, csrf_headers, login
from fastapi.testclient import TestClient
from sqlalchemy import select

from veyra.cli.main import main, purge_expired
from veyra.core.db import session_scope
from veyra.core.models import PasswordResetToken, User, UserSession
from veyra.core.models.base import utcnow

NEW_PASSWORD = "a completely different phrase"


def _second_client(app) -> TestClient:
    other = TestClient(app, base_url="http://veyra.test")
    other.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux) Firefox/144.0"
    return login(other, ADMIN_EMAIL, ADMIN_PASSWORD)


def _make_user(admin, email="jo@district.local", role=None):
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    r = admin.post(
        "/api/v1/users",
        json={
            "email": email,
            "display_name": "Jo Example",
            "password": ADMIN_PASSWORD,
            "home_organization_id": org,
        },
    )
    assert r.status_code == 201, r.text
    user = r.json()
    if role:
        r = admin.post(
            f"/api/v1/users/{user['id']}/roles",
            json={"role_key": role, "scope_type": "organization", "organization_id": org},
        )
        assert r.status_code == 201, r.text
    return user


# ----------------------------------------------------------------- own sessions


def test_list_and_revoke_own_sessions(admin, app):
    other = _second_client(app)
    sessions = admin.get("/api/v1/auth/sessions").json()
    assert len(sessions) == 2
    current = [s for s in sessions if s["is_current"]]
    assert len(current) == 1
    foreign = next(s for s in sessions if not s["is_current"])
    assert "Firefox" in foreign["user_agent"]

    # the current session cannot be revoked through this endpoint
    r = admin.delete(f"/api/v1/auth/sessions/{current[0]['id']}")
    assert r.status_code == 409 and r.json()["code"] == "current_session"

    assert admin.delete(f"/api/v1/auth/sessions/{foreign['id']}").status_code == 200
    assert other.get("/api/v1/auth/session").status_code == 401
    assert admin.delete(f"/api/v1/auth/sessions/{foreign['id']}").status_code == 404
    assert len(admin.get("/api/v1/auth/sessions").json()) == 1


def test_revoke_other_sessions(admin, app):
    others = [_second_client(app) for _ in range(2)]
    r = admin.post("/api/v1/auth/sessions/revoke-others")
    assert r.status_code == 200 and "2 other sessions" in r.json()["message"]
    assert all(o.get("/api/v1/auth/session").status_code == 401 for o in others)
    assert admin.get("/api/v1/auth/session").status_code == 200
    assert "No other" in admin.post("/api/v1/auth/sessions/revoke-others").json()["message"]


def test_users_cannot_see_each_others_sessions(admin, app):
    jo = _make_user(admin)
    jo_client = login(TestClient(app, base_url="http://veyra.test"), jo["email"], ADMIN_PASSWORD)
    # Jo must change the temporary password first; the auth endpoints still work.
    assert jo_client.get("/api/v1/auth/session").json()["must_change_password"] is True
    assert len(jo_client.get("/api/v1/auth/sessions").json()) == 1
    admin_session = admin.get("/api/v1/auth/sessions").json()[0]["id"]
    assert jo_client.delete(f"/api/v1/auth/sessions/{admin_session}").status_code == 404


# ----------------------------------------------------------------- admin session control


def test_admin_lists_and_revokes_user_sessions(admin, app):
    jo = _make_user(admin)
    jo_client = login(TestClient(app, base_url="http://veyra.test"), jo["email"], ADMIN_PASSWORD)
    rows = admin.get(f"/api/v1/users/{jo['id']}/sessions").json()
    assert len(rows) == 1 and rows[0]["is_current"] is False
    r = admin.delete(f"/api/v1/users/{jo['id']}/sessions")
    assert r.status_code == 200 and "1 session" in r.json()["message"]
    assert jo_client.get("/api/v1/auth/session").status_code == 401
    assert admin.get(f"/api/v1/users/{jo['id']}/sessions").json() == []


def test_org_admin_cannot_touch_platform_admin_sessions(admin, app):
    jo = _make_user(admin, role="org_admin")
    jo_client = login(TestClient(app, base_url="http://veyra.test"), jo["email"], ADMIN_PASSWORD)
    # clear the forced change so Jo can use the rest of the API
    jo_client.post(
        "/api/v1/auth/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": NEW_PASSWORD},
    )
    me = admin.get("/api/v1/auth/session").json()["user"]["id"]
    assert jo_client.get(f"/api/v1/users/{me}/sessions").status_code == 403
    assert jo_client.delete(f"/api/v1/users/{me}/sessions").status_code == 403
    assert jo_client.post(f"/api/v1/users/{me}/password-reset-link").status_code == 403
    assert jo_client.post(f"/api/v1/users/{me}/unlock").status_code == 403


# ----------------------------------------------------------------- forced password change


def test_admin_set_password_forces_change(admin, app):
    jo = _make_user(admin, role="read_only")
    jo_client = login(TestClient(app, base_url="http://veyra.test"), jo["email"], ADMIN_PASSWORD)
    r = jo_client.get("/api/v1/organizations")
    assert r.status_code == 403 and r.json()["code"] == "password_change_required"
    r = jo_client.post(
        "/api/v1/auth/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": ADMIN_PASSWORD},
    )
    assert r.status_code == 422 and r.json()["code"] == "password_policy"
    r = jo_client.post(
        "/api/v1/auth/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 200
    session = jo_client.get("/api/v1/auth/session").json()
    assert session["must_change_password"] is False
    assert session["user"]["password_changed_at"] is not None
    assert jo_client.get("/api/v1/organizations").status_code == 200

    # an administrator may hand out a permanent password explicitly
    r = admin.patch(
        f"/api/v1/users/{jo['id']}",
        json={"password": "another long passphrase", "require_password_change": False},
    )
    assert r.status_code == 200 and r.json()["must_change_password"] is False
    assert jo_client.get("/api/v1/auth/session").status_code == 401  # signed out everywhere


def test_admin_cannot_reset_own_password_via_user_api(admin):
    me = admin.get("/api/v1/auth/session").json()["user"]["id"]
    r = admin.patch(f"/api/v1/users/{me}", json={"password": NEW_PASSWORD})
    assert r.status_code == 409 and r.json()["code"] == "self_password_reset"
    r = admin.post(f"/api/v1/users/{me}/password-reset-link")
    assert r.status_code == 409


# ----------------------------------------------------------------- reset links


def test_password_reset_link_flow(admin, app):
    jo = _make_user(admin)
    jo_client = login(TestClient(app, base_url="http://veyra.test"), jo["email"], ADMIN_PASSWORD)
    r = admin.post(f"/api/v1/users/{jo['id']}/password-reset-link")
    assert r.status_code == 201, r.text
    link = r.json()
    assert link["path"] == f"/reset-password/?token={link['token']}"
    with session_scope() as db:
        rows = db.scalars(select(PasswordResetToken)).all()
        assert len(rows) == 1 and rows[0].token_hash != link["token"]

    anon = TestClient(app, base_url="http://veyra.test")
    info = anon.post("/api/v1/auth/password-reset/check", json={"token": link["token"]})
    assert info.status_code == 200 and info.json()["email"] == jo["email"]

    weak = anon.post(
        "/api/v1/auth/password-reset",
        json={"token": link["token"], "new_password": "jo example is my name"},
    )
    assert weak.status_code == 422 and weak.json()["code"] == "password_policy"

    ok = anon.post(
        "/api/v1/auth/password-reset", json={"token": link["token"], "new_password": NEW_PASSWORD}
    )
    assert ok.status_code == 200
    assert "veyra_session" not in ok.cookies  # the reset does not sign the user in
    assert jo_client.get("/api/v1/auth/session").status_code == 401  # old sessions revoked

    # single use
    again = anon.post(
        "/api/v1/auth/password-reset", json={"token": link["token"], "new_password": NEW_PASSWORD}
    )
    assert again.status_code == 404 and again.json()["code"] == "reset_token_invalid"

    fresh = login(TestClient(app, base_url="http://veyra.test"), jo["email"], NEW_PASSWORD)
    me = fresh.get("/api/v1/auth/session").json()
    assert me["must_change_password"] is False
    events = admin.get("/api/v1/audit", params={"q": "auth.password_reset"}).json()
    assert events["total"] >= 2  # one failure (reuse), one success


def test_reset_link_replaced_expired_and_generic(admin, app):
    jo = _make_user(admin)
    first = admin.post(f"/api/v1/users/{jo['id']}/password-reset-link").json()
    second = admin.post(f"/api/v1/users/{jo['id']}/password-reset-link").json()
    anon = TestClient(app, base_url="http://veyra.test")
    r = anon.post("/api/v1/auth/password-reset/check", json={"token": first["token"]})
    assert r.status_code == 404  # replaced
    assert anon.post("/api/v1/auth/password-reset/check", json={"token": "nope"}).status_code == 404
    with session_scope() as db:
        row = db.scalar(select(PasswordResetToken))
        row.expires_at = utcnow() - timedelta(minutes=1)
    r = anon.post("/api/v1/auth/password-reset/check", json={"token": second["token"]})
    assert r.status_code == 404 and r.json()["code"] == "reset_token_invalid"

    # a disabled account gets no link
    admin.patch(f"/api/v1/users/{jo['id']}", json={"is_active": False})
    assert admin.post(f"/api/v1/users/{jo['id']}/password-reset-link").status_code == 409


def test_reset_check_is_rate_limited(admin, app):
    import veyra.api.v1.auth as auth_mod

    auth_mod._reset_limiter = None
    anon = TestClient(app, base_url="http://veyra.test")
    codes = [
        anon.post("/api/v1/auth/password-reset/check", json={"token": "x"}).status_code
        for _ in range(12)
    ]
    assert 429 in codes
    auth_mod._reset_limiter = None


# ----------------------------------------------------------------- unlock


def test_unlock_clears_lockout(admin, settings, monkeypatch, app):
    import veyra.api.v1.auth as auth_mod
    from veyra.core.security.ratelimit import SlidingWindowLimiter

    jo = _make_user(admin)
    monkeypatch.setattr(auth_mod, "_limiter", lambda _s: SlidingWindowLimiter(1000, 60))
    anon = TestClient(app, base_url="http://veyra.test")
    for _ in range(settings.account_lockout_threshold):
        anon.post("/api/v1/auth/login", json={"email": jo["email"], "password": "bad password"})
    assert admin.get(f"/api/v1/users/{jo['id']}").json()["locked_until"] is not None
    r = anon.post("/api/v1/auth/login", json={"email": jo["email"], "password": ADMIN_PASSWORD})
    assert r.status_code == 401
    r = admin.post(f"/api/v1/users/{jo['id']}/unlock")
    assert r.status_code == 200 and r.json()["message"] == "Account unlocked."
    assert admin.get(f"/api/v1/users/{jo['id']}").json()["locked_until"] is None
    r = anon.post("/api/v1/auth/login", json={"email": jo["email"], "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    assert "not locked" in admin.post(f"/api/v1/users/{jo['id']}/unlock").json()["message"]


# ----------------------------------------------------------------- CLI


def test_cli_reset_password_and_unlock(admin, app, capsys):
    jo = _make_user(admin)
    with session_scope() as db:
        user = db.get(User, __import__("uuid").UUID(jo["id"]))
        user.locked_until = utcnow() + timedelta(minutes=10)
    assert main(["users", "reset-password", jo["email"].upper(), "--unlock", "--quiet"]) == 0
    path = capsys.readouterr().out.strip()
    assert path.startswith("/reset-password/?token=")
    token = path.split("token=", 1)[1]
    anon = TestClient(app, base_url="http://veyra.test")
    assert anon.post("/api/v1/auth/password-reset/check", json={"token": token}).status_code == 200
    assert admin.get(f"/api/v1/users/{jo['id']}").json()["locked_until"] is None

    assert main(["users", "unlock", jo["email"]]) == 0
    assert "was not locked" in capsys.readouterr().out
    assert main(["users", "unlock", "nobody@district.local"]) == 1
    assert "no user" in capsys.readouterr().err

    assert main(["sessions", "revoke", ADMIN_EMAIL]) == 0
    assert admin.get("/api/v1/auth/session").status_code == 401


# ----------------------------------------------------------------- purge


def test_purge_expired_sessions_and_tokens(admin, settings, app):
    jo = _make_user(admin)
    other = _second_client(app)
    other.post("/api/v1/auth/logout")
    admin.post(f"/api/v1/users/{jo['id']}/password-reset-link")
    with session_scope() as db:
        old = utcnow() - timedelta(days=settings.session_retention_days + 1)
        for s in db.scalars(select(UserSession).where(UserSession.revoked_at.is_not(None))):
            s.revoked_at = old
        db.scalar(select(PasswordResetToken)).used_at = utcnow()
    with session_scope() as db:
        assert purge_expired(db, settings) == (1, 1)
        assert db.scalar(select(UserSession).where(UserSession.revoked_at.is_not(None))) is None
    assert admin.get("/api/v1/auth/session").status_code == 200  # live session untouched


# ----------------------------------------------------------------- fetch metadata


def test_cross_site_mutations_are_refused(admin):
    r = admin.post(
        "/api/v1/organizations",
        json={"name": "N", "slug": "n"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert r.status_code == 403 and r.json()["code"] == "cross_site_request"
    r = admin.post(
        "/api/v1/organizations",
        json={"name": "N", "slug": "n"},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert r.status_code == 201
    # reads are never blocked by fetch metadata
    r = admin.get("/api/v1/organizations", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 200
    assert csrf_headers(admin)


def test_logout_clears_site_data(admin):
    r = admin.post("/api/v1/auth/logout")
    assert r.headers.get("Clear-Site-Data") == '"cookies"'
