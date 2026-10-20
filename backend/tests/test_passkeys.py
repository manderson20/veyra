# SPDX-License-Identifier: AGPL-3.0-or-later
"""Passkeys (issue #107) with a software authenticator: add one, sign in
with it (also from the pre-authentication session), a replayed or cloned
signature is refused, rename and remove, and IP addresses are refused."""

import base64
import hashlib
import json
import struct

import cbor2
from conftest import ADMIN_PASSWORD, csrf_headers
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from test_api_mfa import _make_user

from veyra.core.db import session_scope
from veyra.core.models import AuditEvent

MFA = "/api/v1/auth/mfa"
ORIGIN = "https://veyra.test"
RP_ID = "veyra.test"


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class SoftAuthenticator:
    """Enough of a FIDO2 authenticator: ES256, "none" attestation, a counter."""

    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = b"veyra-test-credential-1"
        self.count = 0

    def _cose(self) -> bytes:
        n = self.key.public_key().public_numbers()
        return cbor2.dumps(
            {1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")}
        )

    def _client_data(self, kind: str, challenge: str, origin: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin}).encode()

    def create(self, options: dict, origin: str = ORIGIN) -> dict:
        rp_hash = hashlib.sha256(options["rp"]["id"].encode()).digest()
        auth_data = (
            rp_hash
            + bytes([0x45])  # UP | UV | AT
            + struct.pack(">I", self.count)
            + bytes(16)  # AAGUID
            + struct.pack(">H", len(self.cred_id))
            + self.cred_id
            + self._cose()
        )
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        cd = self._client_data("webauthn.create", options["challenge"], origin)
        return {
            "id": b64u(self.cred_id),
            "rawId": b64u(self.cred_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64u(cd),
                "attestationObject": b64u(att),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    def get(self, options: dict, origin: str = ORIGIN, count: int | None = None) -> dict:
        self.count = self.count + 1 if count is None else count
        auth_data = (
            hashlib.sha256(options["rpId"].encode()).digest()
            + bytes([0x05])  # UP | UV
            + struct.pack(">I", self.count)
        )
        cd = self._client_data("webauthn.get", options["challenge"], origin)
        sig = self.key.sign(auth_data + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": b64u(self.cred_id),
            "rawId": b64u(self.cred_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64u(cd),
                "authenticatorData": b64u(auth_data),
                "signature": b64u(sig),
                "userHandle": None,
            },
            "clientExtensionResults": {},
        }


def test_passkey_lifecycle(admin, app):
    _make_user(admin, "pat@example.org")
    c = TestClient(app, base_url="http://veyra.test")
    r = c.post("/api/v1/auth/login", json={"email": "pat@example.org", "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    c.headers.update(csrf_headers(c))
    auth = SoftAuthenticator()

    begin = c.post(f"{MFA}/webauthn/register/begin", json={"label": "MacBook Touch ID"})
    assert begin.status_code == 200, begin.text
    opts = begin.json()["options"]
    assert opts["rp"]["id"] == RP_ID and opts["user"]["name"] == "pat@example.org"
    # A response for another site is refused.
    bad = c.post(
        f"{MFA}/webauthn/register/finish",
        json={
            "method_id": begin.json()["method_id"],
            "credential": auth.create(opts, "https://evil.test"),
        },
    )
    assert bad.status_code == 400 and bad.json()["code"] == "passkey_invalid"
    r = c.post(
        f"{MFA}/webauthn/register/finish",
        json={"method_id": begin.json()["method_id"], "credential": auth.create(opts)},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["recovery_codes"]) == 10
    assert r.json()["method"]["type"] == "webauthn"

    # Sign in again: password, then the passkey.
    c.post("/api/v1/auth/logout")
    c.cookies.clear()
    c.headers.pop("X-CSRF-Token", None)
    r = c.post("/api/v1/auth/login", json={"email": "pat@example.org", "password": ADMIN_PASSWORD})
    assert r.status_code == 202 and r.json()["methods"][0]["type"] == "webauthn", r.text
    c.headers.update(csrf_headers(c))
    assert c.get("/api/v1/me/extensions").status_code == 403  # factor pending
    opts = c.post(f"{MFA}/webauthn/authenticate/begin").json()["options"]
    assert opts["allowCredentials"][0]["id"] == b64u(auth.cred_id)
    assertion = auth.get(opts)
    r = c.post(f"{MFA}/webauthn/authenticate/finish", json={"credential": assertion})
    assert r.status_code == 200, r.text
    c.headers.update(csrf_headers(c))
    assert c.get("/api/v1/me/extensions").status_code == 200
    # The same assertion again: the challenge is gone.
    r = c.post(f"{MFA}/webauthn/authenticate/finish", json={"credential": assertion})
    assert r.status_code == 409
    # A counter that went backwards (a cloned key) is refused.
    opts = c.post(f"{MFA}/webauthn/authenticate/begin").json()["options"]
    r = c.post(f"{MFA}/webauthn/authenticate/finish", json={"credential": auth.get(opts, count=1)})
    assert r.status_code == 401, r.text

    methods = c.get(f"{MFA}/methods").json()["methods"]
    r = c.patch(f"{MFA}/methods/{methods[0]['id']}", json={"label": "Work laptop"})
    assert r.json()["label"] == "Work laptop"
    r = c.post(f"{MFA}/methods/{methods[0]['id']}/remove", json={"password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    with session_scope() as db:
        actions = {
            e.action for e in db.query(AuditEvent).filter(AuditEvent.action.like("auth.passkey_%"))
        }
    assert {"auth.passkey_register", "auth.passkey_verify"} <= actions


def test_passkeys_refuse_ip_addresses(admin, app):
    _make_user(admin, "ip@example.org")
    c = TestClient(app, base_url="http://192.0.2.10")
    r = c.post("/api/v1/auth/login", json={"email": "ip@example.org", "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    c.headers.update(csrf_headers(c))
    r = c.post(f"{MFA}/webauthn/register/begin", json={})
    assert r.status_code == 409 and r.json()["code"] == "passkey_origin", r.text
    assert "host name" in r.json()["detail"]
