# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 13 (docs/INTEGRATIONS.md): OpenID Connect sign-in for the web
interface and the Companion, integration tokens, outgoing webhooks, and the
directory's groups."""

from __future__ import annotations

import json
import time
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, login
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from fake_adapter import FakeAdapter
from test_api_ivr import _upload

from veyra.core.db import session_scope
from veyra.core.models import AuditEvent, Extension, User, Webhook, WebhookDelivery
from veyra.core.models.base import utcnow
from veyra.core.security import oidc
from veyra.integrations import sources, webhooks

GOOGLE = "https://accounts.google.com"
CLIENT_ID = "veyra-test.apps.googleusercontent.com"
EXT_ID = "abcdefghijklmnopabcdefghijklmnop"


def _b64(data: bytes) -> str:
    return oidc.b64url(data)


def _int_b64(n: int) -> str:
    return _b64(n.to_bytes((n.bit_length() + 7) // 8, "big"))


class Provider:
    """A fake OpenID provider behind an httpx.MockTransport."""

    def __init__(self, issuer: str = GOOGLE) -> None:
        self.issuer = issuer
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "k1"
        self.claims: dict[str, object] = {}
        self.nonce: str | None = None
        self.token_requests: list[dict[str, list[str]]] = []

    def jwk(self) -> dict[str, str]:
        pub = self.key.public_key().public_numbers()
        return {
            "kty": "RSA",
            "kid": self.kid,
            "use": "sig",
            "alg": "RS256",
            "n": _int_b64(pub.n),
            "e": _int_b64(pub.e),
        }

    def sign(self, claims: dict[str, object], *, alg: str = "RS256", kid: str | None = None) -> str:
        header = {"alg": alg, "kid": kid or self.kid, "typ": "JWT"}
        h = _b64(json.dumps(header).encode())
        p = _b64(json.dumps(claims).encode())
        sig = self.key.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{h}.{p}.{_b64(sig)}"

    def id_token(self, **over: object) -> str:
        now = int(time.time())
        claims: dict[str, object] = {
            "iss": self.issuer,
            "aud": CLIENT_ID,
            "sub": "sub-alice",
            "iat": now,
            "exp": now + 300,
            "nonce": self.nonce,
            "email": "alice@example.org",
            "email_verified": True,
            "hd": "example.org",
            "name": "Alice Example",
        }
        claims.update(self.claims)
        claims.update(over)
        return self.sign(claims)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == self.issuer + "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": self.issuer,
                    "authorization_endpoint": self.issuer + "/o/oauth2/v2/auth",
                    "token_endpoint": "https://oauth2.example.net/token",
                    "jwks_uri": "https://oauth2.example.net/certs",
                },
            )
        if url == "https://oauth2.example.net/certs":
            return httpx.Response(200, json={"keys": [self.jwk()]})
        if url == "https://oauth2.example.net/token":
            form = parse_qs(request.content.decode())
            self.token_requests.append(form)
            if form.get("code") != ["good-code"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"id_token": self.id_token(), "access_token": "x"})
        return httpx.Response(404)


@pytest.fixture
def provider(monkeypatch):
    p = Provider()
    monkeypatch.setattr(oidc, "transport", httpx.MockTransport(p.handler))
    return p


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _create_provider(admin, **over):
    body = {
        "kind": "google",
        "name": "Google",
        "client_id": CLIENT_ID,
        "client_secret": "s3cret",
        "allowed_domains": ["example.org"],
        "organization_id": _org(admin)["id"],
    }
    body.update(over)
    r = admin.post("/api/v1/identity-providers", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _make_user(admin, email):
    r = admin.post(
        "/api/v1/users",
        json={
            "email": email,
            "display_name": "Alice",
            "password": ADMIN_PASSWORD,
            "home_organization_id": _org(admin)["id"],
            "require_password_change": False,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _start(http, p: Provider, pid: str, **params):
    r = http.get(f"/api/v1/auth/sso/{pid}/start", params=params, follow_redirects=False)
    assert r.status_code == 303, r.text
    loc = urlsplit(r.headers["location"])
    q = {k: v[0] for k, v in parse_qs(loc.query).items()}
    p.nonce = q["nonce"]
    return q


def _signed_out(client):
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    return client


# ----------------------------------------------------------------- ID tokens


def test_id_token_verification_rules():
    p = Provider()
    p.nonce = "n1"
    jwks = {"keys": [p.jwk()]}

    def check(token, **kw):
        return oidc.verify_id_token(
            token, jwks, issuer=GOOGLE, client_id=CLIENT_ID, nonce=kw.get("nonce", "n1")
        )

    claims = check(p.id_token())
    assert claims.email == "alice@example.org" and claims.hosted_domain == "example.org"
    for bad, reason in (
        (p.id_token(aud="other"), "bad_token"),
        (p.id_token(iss="https://evil.example"), "bad_token"),
        (p.id_token(nonce="other"), "bad_nonce"),
        (p.id_token(exp=int(time.time()) - 600), "expired"),
        (p.id_token(email_verified=False), "unverified_email"),
        (p.sign({"sub": "x"}, kid="unknown"), "unknown_key"),
    ):
        with pytest.raises(oidc.OidcError) as e:
            check(bad)
        assert e.value.reason == reason
    # alg=none and HMAC are refused whatever the token says.
    good = p.id_token().split(".")
    for alg in ("none", "HS256"):
        h = _b64(json.dumps({"alg": alg, "kid": "k1"}).encode())
        with pytest.raises(oidc.OidcError):
            check(f"{h}.{good[1]}.{good[2]}")
    # A tampered payload fails the signature.
    tampered = _b64(json.dumps({"sub": "mallory"}).encode())
    with pytest.raises(oidc.OidcError) as e:
        check(f"{good[0]}.{tampered}.{good[2]}")
    assert e.value.reason == "bad_signature"
    # Google accounts must belong to an allowed Workspace (hd), not just the domain.
    c = check(p.id_token(hd=None))
    assert not oidc.domain_allowed(c, ["example.org"], kind="google")
    assert oidc.domain_allowed(c, ["example.org"], kind="oidc")
    assert not oidc.domain_allowed(claims, ["example.com"], kind="google")


def test_es256_tokens():
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_numbers()
    jwk = {"kty": "EC", "crv": "P-256", "kid": "e1", "x": _int_b64(pub.x), "y": _int_b64(pub.y)}
    now = int(time.time())
    claims = {
        "iss": GOOGLE,
        "aud": CLIENT_ID,
        "sub": "s",
        "iat": now,
        "exp": now + 60,
        "nonce": "n",
        "email": "a@example.org",
        "email_verified": True,
    }
    h = _b64(json.dumps({"alg": "ES256", "kid": "e1"}).encode())
    p = _b64(json.dumps(claims).encode())
    r, s = decode_dss_signature(key.sign(f"{h}.{p}".encode(), ec.ECDSA(hashes.SHA256())))
    token = f"{h}.{p}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    out = oidc.verify_id_token(
        token, {"keys": [jwk]}, issuer=GOOGLE, client_id=CLIENT_ID, nonce="n"
    )
    assert out.subject == "s"


# ----------------------------------------------------------------- web sign-in


def test_web_sso_links_existing_account_and_policy(admin, provider):
    prov = _create_provider(admin)
    assert prov["redirect_uri"].endswith("/api/v1/auth/sso/callback")
    assert prov["has_secret"] and "client_secret" not in prov
    alice = _make_user(admin, "alice@example.org")
    r = admin.post(f"/api/v1/identity-providers/{prov['id']}/test")
    assert r.json()["ok"] and r.json()["keys"] == 1

    c = _signed_out(admin)
    assert [p["name"] for p in c.get("/api/v1/auth/sso/providers").json()] == ["Google"]
    q = _start(c, provider, prov["id"], next="/calls/")
    assert q["hd"] == "example.org" and q["code_challenge_method"] == "S256"
    assert q["redirect_uri"] == prov["redirect_uri"]
    r = c.get(
        "/api/v1/auth/sso/callback",
        params={"code": "good-code", "state": q["state"]},
        follow_redirects=False,
    )
    assert r.status_code == 200 and "url=/calls/" in r.text, r.text
    # The provider got the PKCE verifier and the stored client secret.
    form = provider.token_requests[-1]
    assert form["client_secret"] == ["s3cret"] and form["code_verifier"][0]
    me = c.get("/api/v1/auth/session").json()
    assert me["user"]["email"] == "alice@example.org"
    # The same state cannot be used twice.
    r = c.get(
        "/api/v1/auth/sso/callback",
        params={"code": "good-code", "state": q["state"]},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "sso_error" in r.headers["location"]

    login(c, ADMIN_EMAIL, ADMIN_PASSWORD)
    ids = c.get(f"/api/v1/users/{alice['id']}/identities").json()
    assert len(ids) == 1 and ids[0]["email"] == "alice@example.org"
    # Require SSO: Alice's password stops working, the recovery admin's does not.
    r = c.put("/api/v1/identity-providers/policy", json={"require_sso": True})
    assert r.status_code == 200
    r = c.post(f"/api/v1/users/{alice['id']}/password-reset-link")
    assert r.status_code == 409
    _signed_out(c)
    r = c.post(
        "/api/v1/auth/login", json={"email": "alice@example.org", "password": ADMIN_PASSWORD}
    )
    assert r.status_code == 403 and r.json()["code"] == "sso_required"
    login(c, ADMIN_EMAIL, ADMIN_PASSWORD)
    with session_scope() as db:
        actions = [a.action for a in db.query(AuditEvent).all()]
    assert "auth.sso.login" in actions and "auth.sso.failed" in actions


def test_web_sso_refusals_and_account_creation(admin, provider):
    prov = _create_provider(admin, allowed_domains=["example.org", "district.local"])
    c = _signed_out(admin)
    # No account and creation off.
    q = _start(c, provider, prov["id"], next="//evil.example/")
    r = c.get(
        "/api/v1/auth/sso/callback",
        params={"code": "good-code", "state": q["state"]},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "no%20Veyra%20account" in r.headers["location"].replace(
        "There%20is%20", ""
    )
    # The recovery administrator never signs in through a provider.
    provider.claims = {"email": ADMIN_EMAIL, "hd": "district.local", "sub": "sub-admin"}
    q = _start(c, provider, prov["id"])
    r = c.get(
        "/api/v1/auth/sso/callback",
        params={"code": "good-code", "state": q["state"]},
        follow_redirects=False,
    )
    assert "recovery%20administrator" in r.headers["location"]
    # A wrong Workspace is refused even with a matching e-mail domain.
    provider.claims = {"hd": "other.org"}
    q = _start(c, provider, prov["id"])
    r = c.get(
        "/api/v1/auth/sso/callback",
        params={"code": "good-code", "state": q["state"]},
        follow_redirects=False,
    )
    assert "not%20allowed" in r.headers["location"]
    # A callback without the browser cookie of its start is refused.
    provider.claims = {}
    q = _start(c, provider, prov["id"])
    c.cookies.delete("veyra_sso", path="/api/v1/auth/sso/")
    r = c.get(
        "/api/v1/auth/sso/callback",
        params={"code": "good-code", "state": q["state"]},
        follow_redirects=False,
    )
    assert "another%20browser" in r.headers["location"]
    # The provider's own refusal (prompt=none and no session) goes back politely.
    q = _start(c, provider, prov["id"], silent="true")
    assert q["prompt"] == "none"
    r = c.get(
        "/api/v1/auth/sso/callback",
        params={"error": "login_required", "state": q["state"]},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "sso_error" in r.headers["location"]

    # Account creation on: Alice arrives with the provider's default role.
    login(c, ADMIN_EMAIL, ADMIN_PASSWORD)
    body = {**prov, "create_accounts": True, "default_role_key": "read_only", "client_secret": None}
    r = c.put(f"/api/v1/identity-providers/{prov['id']}", json=body)
    assert r.status_code == 200 and r.json()["create_accounts"]
    _signed_out(c)
    q = _start(c, provider, prov["id"], next="//evil.example/")
    r = c.get(
        "/api/v1/auth/sso/callback",
        params={"code": "good-code", "state": q["state"]},
        follow_redirects=False,
    )
    assert r.status_code == 200 and 'url=/"' in r.text  # the open redirect became "/"
    with session_scope() as db:
        u = db.query(User).filter_by(email="alice@example.org").one()
        assert u.auth_source == "google" and u.password_hash is None
    perms = c.get("/api/v1/auth/session").json()["permissions"]
    assert "users.write" not in perms


def test_companion_sso(admin, provider, app):
    app.state.settings.companion_dev_extension_ids = EXT_ID
    prov = _create_provider(admin)
    _make_user(admin, "alice@example.org")
    c = _signed_out(admin)
    verifier = oidc.new_verifier()
    redirect = f"https://{EXT_ID}.chromiumapp.org/sso"
    r = c.get(
        f"/api/v1/auth/sso/{prov['id']}/start",
        params={
            "client": "companion",
            "redirect_uri": "https://evil.chromiumapp.org/sso",
            "code_challenge": oidc.challenge_of(verifier),
        },
        follow_redirects=False,
    )
    assert r.status_code == 400 and r.json()["code"] == "bad_redirect"
    q = _start(
        c,
        provider,
        prov["id"],
        client="companion",
        redirect_uri=redirect,
        code_challenge=oidc.challenge_of(verifier),
        login_hint="alice@example.org",
        silent="true",
    )
    assert q["login_hint"] == "alice@example.org" and q["prompt"] == "none"
    r = c.get(
        "/api/v1/auth/sso/callback",
        params={"code": "good-code", "state": q["state"]},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].startswith(redirect + "?code=")
    assert "__Host-veyra_session" not in r.headers.get("set-cookie", "")
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    r = c.post(
        "/api/v1/auth/companion/sso",
        json={"code": code, "code_verifier": oidc.new_verifier(), "device": "Chromebook"},
    )
    assert r.status_code == 401  # wrong verifier, and the code is now spent
    r = c.post("/api/v1/auth/companion/sso", json={"code": code, "code_verifier": verifier})
    assert r.status_code == 401
    q = _start(
        c,
        provider,
        prov["id"],
        client="companion",
        redirect_uri=redirect,
        code_challenge=oidc.challenge_of(verifier),
    )
    r = c.get(
        "/api/v1/auth/sso/callback",
        params={"code": "good-code", "state": q["state"]},
        follow_redirects=False,
    )
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    r = c.post(
        "/api/v1/auth/companion/sso",
        json={"code": code, "code_verifier": verifier, "device": "Chromebook"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert r.json()["user"]["email"] == "alice@example.org"
    me = c.get("/api/v1/me/extensions", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    # Interaction needed: the extension gets an error it can act on.
    q = _start(
        c,
        provider,
        prov["id"],
        client="companion",
        redirect_uri=redirect,
        code_challenge=oidc.challenge_of(verifier),
        silent="true",
    )
    r = c.get(
        "/api/v1/auth/sso/callback",
        params={"error": "interaction_required", "state": q["state"]},
        follow_redirects=False,
    )
    assert r.headers["location"].startswith(redirect + "?error=interaction_required")


def test_provider_administration(admin, provider):
    r = admin.post(
        "/api/v1/identity-providers",
        json={
            "kind": "oidc",
            "name": "Other",
            "client_id": "x",
            "client_secret": "y",
            "allowed_domains": [],
            "organization_id": _org(admin)["id"],
        },
    )
    assert r.status_code == 422
    r = admin.post(
        "/api/v1/identity-providers",
        json={
            "kind": "oidc",
            "name": "Other",
            "issuer": "http://idp.example",
            "client_id": "x",
            "client_secret": "y",
            "allowed_domains": ["example.org"],
            "organization_id": _org(admin)["id"],
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "bad_issuer"
    prov = _create_provider(admin)
    assert prov["issuer"] == GOOGLE
    r = admin.delete(f"/api/v1/identity-providers/{prov['id']}")
    assert r.status_code == 204
    assert admin.get("/api/v1/auth/sso/providers").json() == []


# ----------------------------------------------------------------- integration tokens


def _page(admin, app, tmp_path):
    org = _org(admin)
    z = admin.post(
        "/api/v1/paging-zones",
        json={
            "organization_id": org["id"],
            "name": "Main",
            "multicast_address": "239.1.2.10",
            "multicast_port": 5004,
            "poly_group": 3,
        },
    ).json()
    bell = _upload(admin, org["id"], "Door open", kind="bell")
    page = admin.post(
        "/api/v1/pages",
        json={
            "organization_id": org["id"],
            "name": "Door alert",
            "zones": [z["id"]],
            "audio_id": bell["id"],
        },
    ).json()
    adapter = FakeAdapter(prompts_dir=app.state.settings.prompts_dir)
    app.state.telephony = adapter
    return page


def test_integration_token_sends_a_page(admin, app, tmp_path):
    page = _page(admin, app, tmp_path)
    org = _org(admin)
    assert {s["key"] for s in admin.get("/api/v1/integrations/scopes").json()} >= {"paging.send"}
    r = admin.post(
        "/api/v1/integrations",
        json={"organization_id": org["id"], "name": "Door controller", "scopes": ["users.write"]},
    )
    assert r.status_code == 422
    r = admin.post(
        "/api/v1/integrations",
        json={"organization_id": org["id"], "name": "Door controller", "scopes": ["paging.send"]},
    )
    assert r.status_code == 201, r.text
    created = r.json()
    token = created["token"]
    assert token.startswith("vyi_")
    hdr = {"Authorization": f"Bearer {token}"}
    _signed_out(admin)
    r = admin.post(f"/api/v1/pages/{page['id']}/send", json={}, headers=hdr)
    assert r.status_code == 200, r.text
    assert admin.get("/api/v1/users", headers=hdr).status_code == 403
    assert admin.get("/api/v1/pages", headers=hdr).status_code == 403
    with session_scope() as db:
        labels = [a.actor_label for a in db.query(AuditEvent).all()]
        assert db.query(User).filter_by(auth_source="integration").count() == 1
    login(admin, ADMIN_EMAIL, ADMIN_PASSWORD)
    # Service accounts are not people.
    users = admin.get("/api/v1/users").json()["items"]
    assert all(not u["email"].endswith("integrations.invalid") for u in users)
    listed = admin.get("/api/v1/integrations").json()
    assert listed[0]["last_used_at"] is not None and "token" not in listed[0]
    # Allowed addresses: the test client's address is not in 10.0.0.0/8.
    body = {
        "name": "Door controller",
        "scopes": ["paging.send"],
        "allowed_networks": ["10.0.0.0/8"],
    }
    assert admin.put(f"/api/v1/integrations/{created['id']}", json=body).status_code == 200
    r = admin.post(f"/api/v1/pages/{page['id']}/send", json={}, headers={**hdr, "X-CSRF-Token": ""})
    assert r.status_code == 403 and r.json()["code"] == "address_not_allowed"
    body["allowed_networks"] = []
    admin.put(f"/api/v1/integrations/{created['id']}", json=body)
    # Rotation: the old token stops at once.
    new = admin.post(f"/api/v1/integrations/{created['id']}/rotate").json()["token"]
    _signed_out(admin)
    assert admin.post(f"/api/v1/pages/{page['id']}/send", json={}, headers=hdr).status_code == 401
    r = admin.post(
        f"/api/v1/pages/{page['id']}/send", json={}, headers={"Authorization": f"Bearer {new}"}
    )
    assert r.status_code == 200
    login(admin, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert admin.delete(f"/api/v1/integrations/{created['id']}").status_code == 204
    with session_scope() as db:
        assert db.query(User).filter_by(auth_source="integration").count() == 0
    assert any(lbl == "Integration: Door controller" for lbl in labels)


# ----------------------------------------------------------------- webhooks


class Receiver:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, text="ok")


@pytest.fixture
def receiver(monkeypatch):
    rec = Receiver()
    monkeypatch.setattr(webhooks, "transport", httpx.MockTransport(rec))
    monkeypatch.setattr(webhooks, "resolver", lambda host, port: ["10.20.30.40"])
    return rec


def _hook(admin, **over):
    body = {
        "organization_id": _org(admin)["id"],
        "name": "Screens",
        "url": "https://hooks.example.org/veyra?k=1",
        "events": ["page.*", "bell.rang"],
    }
    body.update(over)
    r = admin.post("/api/v1/webhooks", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _decrypt(app):
    from veyra.core.security.crypto import load_installation_key

    key = load_installation_key(app.state.settings)
    return lambda enc: key.decrypt(enc, webhooks.SECRET_PURPOSE)


def test_webhook_rules(admin, monkeypatch):
    org = _org(admin)["id"]
    for url, allow_http, code in (
        ("http://door.example.org/x", False, "bad_url"),
        ("https://127.0.0.1/x", False, "bad_url"),
        ("https://169.254.169.254/latest", False, "bad_url"),
        ("https://user:pw@hooks.example.org/", False, "bad_url"),
    ):
        r = admin.post(
            "/api/v1/webhooks",
            json={
                "organization_id": org,
                "name": "x",
                "url": url,
                "allow_http": allow_http,
                "events": ["call.*"],
            },
        )
        assert r.status_code == 422 and r.json()["code"] == code, url
    r = admin.post(
        "/api/v1/webhooks",
        json={
            "organization_id": org,
            "name": "x",
            "url": "https://a.example.org/",
            "events": ["nope"],
        },
    )
    assert r.json()["code"] == "bad_events"
    names = {e["name"] for e in admin.get("/api/v1/webhooks/events").json()}
    assert {"call.ended", "voicemail.message", "bell.rang"} <= names
    assert webhooks.matches(["call.*"], "call.ended") and not webhooks.matches(
        ["call.*"], "bell.rang"
    )
    # Names resolving to the server itself are refused at delivery time.
    monkeypatch.setattr(webhooks, "resolver", lambda h, p: ["127.0.0.1"])
    with pytest.raises(webhooks.UnsafeDestination):
        webhooks.pinned_target("https://rebind.example.org/")
    # Private networks are the point (door controllers, screens).
    target, host, sni = webhooks.pinned_target("http://192.168.1.20:8080/hook?a=1")
    assert sni == "192.168.1.20"
    assert target == "http://192.168.1.20:8080/hook?a=1" and host == "192.168.1.20:8080"


def test_webhook_delivery_signature_retries_and_test(admin, app, tmp_path, receiver):
    page = _page(admin, app, tmp_path)
    created = _hook(admin)
    secret = created["secret"]
    assert secret.startswith("whsec_")
    r = admin.post(f"/api/v1/pages/{page['id']}/send", json={})
    assert r.status_code == 200
    with session_scope() as db:
        assert webhooks.deliver_due(db, _decrypt(app)) == 1
    req = receiver.requests[-1]
    assert req.url.host == "10.20.30.40" and req.headers["host"] == "hooks.example.org"
    assert req.extensions.get("sni_hostname") == "hooks.example.org"
    assert req.headers["veyra-event"] == "page.sent"
    assert webhooks.verify(secret, req.headers["veyra-signature"], req.content)
    assert not webhooks.verify("whsec_other", req.headers["veyra-signature"], req.content)
    body = json.loads(req.content)
    assert body["event"] == "page.sent" and body["data"]["page"]["name"] == "Door alert"
    assert body["data"]["trigger"] == "ui" and body["data"]["zones"][0]["name"] == "Main"
    assert body["id"] == req.headers["veyra-delivery"]

    # A failing receiver: retried later, then the webhook is turned off after 3 days.
    receiver.status = 500
    admin.post(f"/api/v1/pages/{page['id']}/send", json={})
    with session_scope() as db:
        webhooks.deliver_due(db, _decrypt(app))
        d = db.query(WebhookDelivery).filter_by(status="pending").one()
        assert d.attempts == 1 and d.error == "HTTP 500"
        assert d.next_attempt_at > utcnow() + timedelta(seconds=50)
        h = db.get(Webhook, uuid.UUID(created["id"]))
        h.failing_since = utcnow() - timedelta(days=4)
        d.next_attempt_at = utcnow()
    with session_scope() as db:
        webhooks.deliver_due(db, _decrypt(app))
        h = db.get(Webhook, uuid.UUID(created["id"]))
        assert not h.enabled and "3 days" in h.disabled_reason
    hook = admin.get(f"/api/v1/webhooks/{created['id']}").json()
    assert hook["enabled"] is False and hook["last_status"] == "failed"
    # Turning it on again clears the failure.
    edit = {"name": "Screens", "url": hook["url"], "events": hook["events"], "enabled": True}
    assert (
        admin.put(f"/api/v1/webhooks/{created['id']}", json=edit).json()["disabled_reason"] is None
    )

    # Test button, secret rotation (two signatures for a day), redeliver.
    receiver.status = 204
    new_secret = admin.post(f"/api/v1/webhooks/{created['id']}/rotate-secret").json()["secret"]
    r = admin.post(f"/api/v1/webhooks/{created['id']}/test")
    assert r.status_code == 200 and r.json()["status"] == "delivered", r.text
    sig = receiver.requests[-1].headers["veyra-signature"]
    assert sig.count("v1=") == 2
    assert webhooks.verify(new_secret, sig, receiver.requests[-1].content)
    assert webhooks.verify(secret, sig, receiver.requests[-1].content)
    deliveries = admin.get(f"/api/v1/webhooks/{created['id']}/deliveries").json()
    first = deliveries[-1]
    r = admin.post(f"/api/v1/webhooks/{created['id']}/deliveries/{first['id']}/redeliver")
    assert r.status_code == 201 and r.json()["payload"]["id"] != first["id"]
    with session_scope() as db:
        assert webhooks.prune(db, now=utcnow() + timedelta(days=8)) == 2


def test_live_calls_voicemail_and_registrations(admin, app, tmp_path, receiver):
    from veyra.core.callevents import CallEvent
    from veyra.telephony.adapter import EndpointStatus

    org = _org(admin)
    ext = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1001", "display_name": "Front Office"},
    ).json()
    _hook(admin, name="All", events=["call.*", "voicemail.message", "registration.changed"])
    sources._live_cache.clear()
    with session_scope() as db:
        endpoint = db.get(Extension, uuid.UUID(ext["id"])).endpoint_name
        ce = CallEvent(
            type="call.ringing",
            channel_id="c1",
            endpoint=endpoint,
            direction="in",
            remote_number="+15551230000",
            remote_name="Caller",
            at="now",
        )
        assert sources.call_live(db, ce) == 1
        dialing = CallEvent(
            type="call.dialing",
            channel_id="c1",
            endpoint=endpoint,
            direction="out",
            remote_number=None,
            remote_name=None,
            at="now",
        )
        assert sources.call_live(db, dialing) == 0
    # Voicemail: counts from veyra-vmnotify; only a rise is a new message.
    r = admin.post("/api/v1/voicemail", json={"extension_id": ext["id"]})
    assert r.status_code == 201, r.text
    qdir = app.state.settings.mailqueue_dir
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / "a.vmevent").write_text("veyra 1001 1 0 0\n")
    (qdir / "b.vmevent").write_text("veyra 1001 0 1 0\n")
    (qdir / "c.vmevent").write_text("garbage; rm -rf /\n")

    class Store:  # the voicemail store helper: the newest message names the caller
        def list(self, context, mailbox, folder):
            assert (context, mailbox, folder) == ("veyra", "1001", "INBOX")
            return {
                "messages": [
                    {"callerid": '"Old" <5550000>', "origtime": 1760000000, "msg_id": "a"},
                    {
                        "callerid": '"Parent" <5551234>',
                        "origtime": 1760800000,
                        "msg_id": "b",
                        "duration": 12,
                    },
                ]
            }

    with session_scope() as db:
        sources.voicemail_notifications(db, qdir, store=Store())
    assert not list(qdir.glob("*.vmevent"))

    # Registrations: the first pass only learns, the next reports changes.
    class Adapter:
        def __init__(self, registered):
            self.registered = registered

        def endpoint_statuses(self):
            return [
                EndpointStatus(
                    endpoint=endpoint,
                    registered=self.registered,
                    contacts=["sip:1001@10.0.0.9:5060"],
                    user_agent="Poly",
                )
            ]

    with session_scope() as db:
        assert sources.registrations(db, Adapter(False)) == 0
        assert sources.registrations(db, Adapter(True)) == 1
        assert sources.registrations(db, Adapter(True)) == 0
    with session_scope() as db:
        events = [d.event for d in db.query(WebhookDelivery).order_by(WebhookDelivery.created_at)]
        live = db.query(WebhookDelivery).filter_by(event="call.ringing").one()
        assert live.max_attempts == 1
        assert live.payload["data"]["extension"]["number"] == "1001"
    assert events.count("voicemail.message") == 1
    with session_scope() as db:
        vm = db.query(WebhookDelivery).filter_by(event="voicemail.message").one()
        msg = vm.payload["data"]["message"]
        assert (msg["caller_number"], msg["caller_name"], msg["msg_id"]) == (
            "5551234",
            "Parent",
            "b",
        )
        assert msg["duration_seconds"] == 12
    assert "registration.changed" in events and "call.ringing" in events


def test_directory_lists_groups(admin):
    org = _org(admin)
    ext = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1001", "display_name": "Front Office"},
    ).json()
    r = admin.post(
        "/api/v1/ring-groups",
        json={
            "organization_id": org["id"],
            "name": "Office",
            "number": "1500",
            "members": [ext["id"]],
        },
    )
    assert r.status_code == 201, r.text
    out = admin.get("/api/v1/directory", params={"q": "Office"}).json()["results"]
    assert {(e["type"], e["number"]) for e in out} == {
        ("extension", "1001"),
        ("ring_group", "1500"),
    }


def test_generated_voicemail_conf_has_externnotify():
    from veyra.telephony.asterisk import generator

    out = generator._voicemail({}, {}, "/opt/veyra/current/installer/bin/veyra-mailqueue")
    assert "externnotify=/opt/veyra/current/installer/bin/veyra-vmnotify" in out.content
