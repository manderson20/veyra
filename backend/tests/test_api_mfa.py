# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 4b: two-factor sign-in, enrolment, recovery codes, policy and resets."""

import time
from datetime import timedelta

from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, csrf_headers, login
from fastapi.testclient import TestClient
from sqlalchemy import select

from veyra.cli.main import main
from veyra.core.db import session_scope
from veyra.core.models import MfaMethod, MfaRecoveryCode, User, UserSession
from veyra.core.models.base import utcnow
from veyra.core.security import totp
from veyra.core.security.crypto import load_installation_key

MFA = "/api/v1/auth/mfa"


def _client(app) -> TestClient:
    return TestClient(app, base_url="http://veyra.test")


def _enrol(client: TestClient) -> tuple[str, list[str]]:
    """Enrol an authenticator for the signed-in client; returns (secret, recovery codes)."""
    begin = client.post(f"{MFA}/totp/begin", json={"label": "Phone"})
    assert begin.status_code == 200, begin.text
    b = begin.json()
    assert b["qr_svg"].startswith("data:image/svg+xml") and b["uri"].startswith("otpauth://")
    r = client.post(
        f"{MFA}/totp/confirm",
        json={"method_id": b["method_id"], "code": totp.totp(b["secret"], time.time())},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert len(out["recovery_codes"]) == 10 and out["method"]["label"] == "Phone"
    return b["secret"], out["recovery_codes"]


def _make_user(admin, email, role=None, scope="organization"):
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    r = admin.post(
        "/api/v1/users",
        json={
            "email": email,
            "display_name": email.split("@")[0],
            "password": ADMIN_PASSWORD,
            "home_organization_id": org,
            "require_password_change": False,
        },
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    if role:
        body = {"role_key": role, "scope_type": scope}
        if scope == "organization":
            body["organization_id"] = org
        r = admin.post(f"/api/v1/users/{uid}/roles", json=body)
        assert r.status_code == 201, r.text
    return uid


def test_admin_gets_a_grace_window_then_must_enrol(admin, app):
    s = admin.get("/api/v1/auth/session").json()
    assert s["mfa"] == {
        "enabled": False,
        "required": True,
        "grace_until": s["mfa"]["grace_until"],
        "methods": 0,
        "recovery_codes_remaining": 0,
    }
    assert s["mfa"]["grace_until"] is not None  # 14 days from the first sign-in
    assert admin.get("/api/v1/organizations").status_code == 200  # usable during grace

    # grace over: the password alone yields a pre-authentication session
    with session_scope() as db:
        u = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        u.mfa_grace_until = utcnow() - timedelta(minutes=1)
    c = _client(app)
    r = c.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 202, r.text
    ch = r.json()
    assert ch["mfa_pending"] and ch["enrol"] is True and ch["methods"] == []
    c.headers.update(csrf_headers(c))
    assert c.get("/api/v1/auth/session").json()["code"] == "mfa_required"
    assert c.get("/api/v1/organizations").status_code == 403
    assert c.get(f"{MFA}/challenge").json()["enrol"] is True
    # verify is impossible without a factor, enrolment completes the sign-in
    assert c.post(f"{MFA}/verify", json={"code": "123456"}).json()["code"] == "mfa_not_enrolled"
    secret, _codes = _enrol(c)
    assert c.get("/api/v1/auth/session").status_code == 200
    assert c.get("/api/v1/organizations").status_code == 200
    s = c.get("/api/v1/auth/session").json()
    assert s["mfa"]["enabled"] and s["mfa"]["recovery_codes_remaining"] == 10
    assert s["user"]["mfa_enabled"] is True
    with session_scope() as db:
        row = db.scalar(select(MfaMethod).where(MfaMethod.confirmed_at.is_not(None)))
        assert row.secret_ciphertext.startswith("v1:") and secret not in row.secret_ciphertext
        assert all(c_.code_hash.startswith("$argon2") for c_ in db.scalars(select(MfaRecoveryCode)))
    events = admin.get("/api/v1/audit", params={"q": "auth.mfa_enrol"}).json()["items"]
    assert {e["action"] for e in events} == {"auth.mfa_enrol_begin", "auth.mfa_enrol_confirm"}
    assert all("secret" not in str(e["details"]).lower() for e in events)


def test_sign_in_with_code_drift_replay_lockout_and_recovery(admin, app, monkeypatch):
    import veyra.api.v1.auth as auth_mod
    from veyra.core.security.ratelimit import SlidingWindowLimiter

    # this test signs in and verifies far more than ten times a minute from one address
    monkeypatch.setattr(auth_mod, "_limiter", lambda _settings: SlidingWindowLimiter(1000, 60))
    secret, codes = _enrol(admin)
    # new sign-in: password gives a pre-auth session
    c = _client(app)
    r = c.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 202 and r.json()["enrol"] is False
    assert r.json()["methods"][0]["type"] == "totp"
    c.headers.update(csrf_headers(c))
    # the pre-auth session cannot add another authenticator
    assert c.post(f"{MFA}/totp/begin", json={}).status_code == 403
    # a wrong code is refused, a right one is accepted, the same one is not accepted again
    r = c.post(f"{MFA}/verify", json={"code": "000000"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_code"
    # enrolment consumed the current code; the next step is within the drift window
    good = totp.hotp(secret, totp.step(time.time()) + 1)
    r = c.post(f"{MFA}/verify", json={"code": good})
    assert r.status_code == 200, r.text
    assert r.json()["mfa"]["enabled"] is True
    assert any(c_.startswith("veyra_csrf=") for c_ in r.headers.get_list("set-cookie"))
    c.headers.update(csrf_headers(c))
    assert c.get("/api/v1/organizations").status_code == 200
    assert c.post(f"{MFA}/verify", json={"code": good}).json()["code"] == "already_verified"

    d = _client(app)
    d.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    d.headers.update(csrf_headers(d))
    r = d.post(f"{MFA}/verify", json={"code": good})  # replay within the same step
    assert r.status_code == 401
    # a recovery code works once
    r = d.post(f"{MFA}/verify", json={"code": codes[0].lower()})
    assert r.status_code == 200, r.text
    assert r.json()["mfa"]["recovery_codes_remaining"] == 9
    e = _client(app)
    e.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    e.headers.update(csrf_headers(e))
    assert e.post(f"{MFA}/verify", json={"code": codes[0]}).status_code == 401
    # five failures lock the pre-auth session
    for _ in range(4):
        r = e.post(f"{MFA}/verify", json={"code": "111111"})
    assert r.status_code == 401 and r.json()["code"] == "mfa_locked"
    assert e.get(f"{MFA}/challenge").status_code == 401
    with session_scope() as db:
        locked = db.scalars(select(UserSession).where(UserSession.mfa_verified_at.is_(None))).all()
        assert all(s.revoked_at is not None for s in locked)
    events = admin.get("/api/v1/audit", params={"q": "auth.mfa_verify"}).json()["items"]
    assert any(e_["outcome"] == "failure" and e_["details"].get("locked") for e_ in events)
    assert any(e_["details"].get("method") == "recovery_code" for e_ in events)
    # pre-auth and locked sessions are not listed as signed-in sessions
    assert len(admin.get("/api/v1/auth/sessions").json()) == 3  # admin, c, d


def test_methods_removal_and_recovery_code_regeneration(admin, app):
    _secret, codes = _enrol(admin)
    m = admin.get(f"{MFA}/methods").json()
    assert m["status"]["enabled"] and len(m["methods"]) == 1 and m["allowed_methods"] == ["totp"]
    mid = m["methods"][0]["id"]
    # wrong password
    r = admin.post(f"{MFA}/methods/{mid}/remove", json={"password": "nope nope nope"})
    assert r.status_code == 400 and r.json()["code"] == "invalid_credentials"
    # policy requires MFA for platform administrators: the last method stays
    r = admin.post(f"{MFA}/methods/{mid}/remove", json={"password": ADMIN_PASSWORD})
    assert r.status_code == 409 and r.json()["code"] == "mfa_required_by_policy"
    # regenerate codes: the old ones stop working
    r = admin.post(f"{MFA}/recovery-codes/regenerate", json={"password": ADMIN_PASSWORD})
    new_codes = r.json()["recovery_codes"]
    assert len(new_codes) == 10 and set(new_codes).isdisjoint(codes)
    # a second device: no new recovery codes
    begin = admin.post(f"{MFA}/totp/begin", json={"label": "Tablet"}).json()
    r = admin.post(
        f"{MFA}/totp/confirm",
        json={"method_id": begin["method_id"], "code": totp.totp(begin["secret"], time.time())},
    )
    assert r.status_code == 200 and r.json()["recovery_codes"] == []
    assert len(admin.get(f"{MFA}/methods").json()["methods"]) == 2
    # now the first one can go
    r = admin.post(f"{MFA}/methods/{mid}/remove", json={"password": ADMIN_PASSWORD})
    assert r.status_code == 200 and "removed" in r.json()["message"]
    # relax the policy and remove the last one: codes go too, MFA is off
    r = admin.put(
        f"{MFA}/policy", json={"required_for": [], "grace_days": 7, "allowed_methods": ["totp"]}
    )
    assert r.status_code == 200, r.text
    last = admin.get(f"{MFA}/methods").json()["methods"][0]["id"]
    r = admin.post(f"{MFA}/methods/{last}/remove", json={"password": ADMIN_PASSWORD})
    assert r.status_code == 200 and "off" in r.json()["message"]
    s = admin.get("/api/v1/auth/session").json()["mfa"]
    assert s == {
        "enabled": False,
        "required": False,
        "grace_until": None,
        "methods": 0,
        "recovery_codes_remaining": 0,
    }
    with session_scope() as db:
        assert db.scalar(select(MfaRecoveryCode)) is None


def test_policy_applies_to_roles_and_is_audited(admin, app):
    viewer = _make_user(admin, "viewer@district.local", "read_only")
    oa = _make_user(admin, "oa@district.local", "org_admin")
    v = login(_client(app), "viewer@district.local", ADMIN_PASSWORD)
    assert v.get("/api/v1/auth/session").json()["mfa"]["required"] is False
    o = login(_client(app), "oa@district.local", ADMIN_PASSWORD)
    assert o.get("/api/v1/auth/session").json()["mfa"]["required"] is True
    assert v.get(f"{MFA}/policy").status_code == 403
    assert o.put(f"{MFA}/policy", json={"required_for": []}).status_code == 403
    r = admin.put(
        f"{MFA}/policy",
        json={"required_for": ["platform_admin", "read_only"], "grace_days": 0},
    )
    assert r.status_code == 200, r.text
    assert r.json()["policy"]["grace_days"] == 0
    assert any(role["key"] == "read_only" for role in r.json()["roles"])
    # the viewer is now required with no grace: the next sign-in must enrol
    r = _client(app).post(
        "/api/v1/auth/login", json={"email": "viewer@district.local", "password": ADMIN_PASSWORD}
    )
    assert r.status_code == 202 and r.json()["enrol"] is True
    # the organization administrator is no longer required
    assert o.get("/api/v1/auth/session").json()["mfa"]["required"] is False
    with session_scope() as db:
        assert db.get(User, oa).mfa_required_at is None
        assert db.get(User, viewer).mfa_required_at is not None
    r = admin.put(f"{MFA}/policy", json={"required_for": ["nobody"]})
    assert r.status_code == 422
    ev = admin.get("/api/v1/audit", params={"q": "security.mfa_policy_update"}).json()["items"]
    assert ev and ev[0]["details"]["users_affected"] >= 2


def test_admin_and_console_reset(admin, app, capsys):
    uid = _make_user(admin, "jo@district.local", "org_admin")
    jo = login(_client(app), "jo@district.local", ADMIN_PASSWORD)
    _enrol(jo)
    assert admin.get(f"/api/v1/users/{uid}").json()["mfa_enabled"] is True
    listed = admin.get("/api/v1/users", params={"q": "jo@"}).json()["items"][0]
    assert listed["mfa_enabled"] is True
    me = admin.get("/api/v1/auth/session").json()["user"]["id"]
    assert admin.post(f"/api/v1/users/{me}/mfa/reset").json()["code"] == "self_mfa_reset"
    r = admin.post(f"/api/v1/users/{uid}/mfa/reset")
    assert r.status_code == 200 and "Removed 1 method" in r.json()["message"]
    assert jo.get("/api/v1/auth/session").status_code == 401  # signed out
    assert admin.get(f"/api/v1/users/{uid}").json()["mfa_enabled"] is False
    # jo signs in again inside a fresh grace window
    jo = login(_client(app), "jo@district.local", ADMIN_PASSWORD)
    s = jo.get("/api/v1/auth/session").json()["mfa"]
    assert s["enabled"] is False and s["required"] is True and s["grace_until"]
    # an organization administrator cannot reset a platform administrator
    _enrol(admin)
    assert jo.post(f"/api/v1/users/{me}/mfa/reset").status_code in (403, 404)
    # the console command is the escape hatch for the recovery administrator
    assert main(["users", "mfa-reset", ADMIN_EMAIL]) == 0
    out = capsys.readouterr().out
    assert "removed 1 second-factor method" in out
    assert admin.get("/api/v1/auth/session").status_code == 401
    a = login(_client(app), ADMIN_EMAIL, ADMIN_PASSWORD)
    events = a.get("/api/v1/audit", params={"q": "user.mfa_reset"}).json()["items"]
    actors = [e["actor_label"] for e in events]
    assert "cli" in actors and ADMIN_EMAIL in actors


def test_missing_installation_key_is_reported(admin, app):
    app.state.settings.installation_key_file = app.state.settings.config_dir / "missing.key"
    r = admin.post(f"{MFA}/totp/begin", json={})
    assert r.status_code == 503 and r.json()["code"] == "installation_key_missing"


def test_enrolment_secret_is_bound_to_the_user(admin, app):
    secret, _ = _enrol(admin)
    uid = _make_user(admin, "x@district.local", "read_only")
    with session_scope() as db:
        mine = db.scalar(select(MfaMethod).where(MfaMethod.confirmed_at.is_not(None)))
        copied = MfaMethod(
            id=__import__("uuid").uuid4(),
            user_id=uid,
            type="totp",
            label="copied",
            secret_ciphertext=mine.secret_ciphertext,
            created_at=utcnow(),
            confirmed_at=utcnow(),
        )
        db.add(copied)
    c = _client(app)
    r = c.post("/api/v1/auth/login", json={"email": "x@district.local", "password": ADMIN_PASSWORD})
    assert r.status_code == 202
    c.headers.update(csrf_headers(c))
    r = c.post(f"{MFA}/verify", json={"code": totp.totp(secret, time.time())})
    assert r.status_code == 503 and r.json()["code"] == "secret_unreadable"
    load_installation_key(app.state.settings)  # the key itself is fine


def test_trusted_browser_skips_the_code_until_forgotten(admin, app, monkeypatch):
    """ "Trust this browser" (#137): off by default, then the code is skipped on
    that browser only, and a password change forgets it."""
    import veyra.api.v1.auth as auth_mod
    from veyra.core.security import trusted
    from veyra.core.security.ratelimit import SlidingWindowLimiter

    monkeypatch.setattr(auth_mod, "_limiter", lambda _settings: SlidingWindowLimiter(1000, 60))
    secret, _codes = _enrol(admin)
    step = [totp.step(time.time()) + 1]

    def sign_in(client: TestClient, trust: bool) -> dict:
        r = client.post(
            "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        if r.status_code == 200:
            return {"skipped": True}
        assert r.status_code == 202, r.text
        client.headers.update(csrf_headers(client))
        with session_scope() as db:  # replay protection: each sign-in reuses this step
            for m in db.scalars(select(MfaMethod)):
                m.last_used_step = None
        code = totp.hotp(secret, step[0])
        v = client.post(f"{MFA}/verify", json={"code": code, "trust_browser": trust})
        assert v.status_code == 200, v.text
        return {"skipped": False, "trust_days": r.json()["trust_days"]}

    # Off by default: no choice offered, no cookie set.
    c = _client(app)
    assert sign_in(c, True) == {"skipped": False, "trust_days": 0}
    assert trusted.COOKIE not in c.cookies
    r = admin.put(f"{MFA}/policy", json={"trusted_browser_days": 30})
    assert r.status_code == 200, r.text
    c = _client(app)
    assert sign_in(c, True) == {"skipped": False, "trust_days": 30}
    assert trusted.COOKIE in c.cookies
    c.headers.update(csrf_headers(c))
    rows = c.get("/api/v1/auth/trusted-browsers").json()
    assert len(rows) == 1 and rows[0]["current"] is True
    # The same browser signs in without a code; another browser still asks.
    browser = c.cookies.get(trusted.COOKIE)
    again = _client(app)
    again.cookies.set(trusted.COOKIE, browser)
    assert sign_in(again, False) == {"skipped": True}
    assert sign_in(_client(app), False)["skipped"] is False
    # Changing the password forgets every trusted browser.
    again.headers.update(csrf_headers(again))
    new_pw = "another long enough passphrase"
    r = again.post(
        "/api/v1/auth/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": new_pw},
    )
    assert r.status_code == 200, r.text
    with session_scope() as db:
        from veyra.core.models import TrustedBrowser

        assert db.query(TrustedBrowser).count() == 0
