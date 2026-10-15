# SPDX-License-Identifier: AGPL-3.0-or-later
"""OpenID Connect client pieces (docs/INTEGRATIONS.md §1).

Discovery, JWKS, the authorization URL, the code exchange and ID token
verification. Only asymmetric signatures are accepted (RS256 and ES256): an
``alg`` of ``none`` or any HMAC algorithm is refused whatever the header says.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

# Tests replace this with an httpx.MockTransport.
transport: httpx.BaseTransport | None = None

TIMEOUT = 10.0
CLOCK_SKEW = 300
ALGORITHMS = ("RS256", "ES256")

PRESET_ISSUERS = {
    "google": "https://accounts.google.com",
    "microsoft": "https://login.microsoftonline.com/{tenant}/v2.0",
}


class OidcError(Exception):
    """A provider or token problem; ``reason`` is a short machine-readable code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, follow_redirects=False, transport=transport)


def check_issuer(issuer: str) -> str:
    issuer = issuer.strip().rstrip("/")
    parts = urlsplit(issuer)
    if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment:
        raise OidcError("bad_issuer", "The issuer must be an https:// address.")
    return issuer


def _get_json(url: str) -> dict[str, Any]:
    if urlsplit(url).scheme != "https":
        raise OidcError("bad_metadata", f"The provider gave a non-HTTPS address: {url}")
    try:
        with _client() as c:
            r = c.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise OidcError("unreachable", f"Could not reach {urlsplit(url).hostname}: {e}") from e
    if r.status_code != 200:
        raise OidcError("unreachable", f"{url} answered {r.status_code}.")
    try:
        data = r.json()
    except ValueError as e:
        raise OidcError("bad_metadata", f"{url} did not return JSON.") from e
    if not isinstance(data, dict):
        raise OidcError("bad_metadata", f"{url} did not return a JSON object.")
    return data


def discover(issuer: str) -> dict[str, Any]:
    """The provider's discovery document, checked against the issuer."""
    issuer = check_issuer(issuer)
    doc = _get_json(issuer + "/.well-known/openid-configuration")
    # Microsoft's multi-tenant documents use a {tenantid} placeholder.
    reported = str(doc.get("issuer", "")).rstrip("/")
    if reported != issuer and "{tenantid}" not in reported:
        raise OidcError(
            "bad_metadata", f"The provider reports issuer {reported!r}, expected {issuer!r}."
        )
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not isinstance(doc.get(key), str) or urlsplit(doc[key]).scheme != "https":
            raise OidcError("bad_metadata", f"The discovery document has no HTTPS {key}.")
    return doc


def fetch_jwks(doc: dict[str, Any]) -> dict[str, Any]:
    jwks = _get_json(doc["jwks_uri"])
    if not isinstance(jwks.get("keys"), list):
        raise OidcError("bad_metadata", "The provider's key set has no keys.")
    return jwks


# --------------------------------------------------------------------------- PKCE


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def new_verifier() -> str:
    return secrets.token_urlsafe(48)


def challenge_of(verifier: str) -> str:
    return b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def authorization_url(
    doc: dict[str, Any],
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    verifier: str,
    extra: dict[str, str] | None = None,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge_of(verifier),
        "code_challenge_method": "S256",
    }
    params.update(extra or {})
    endpoint = doc["authorization_endpoint"]
    sep = "&" if "?" in endpoint else "?"
    return endpoint + sep + urlencode(params)


def exchange_code(
    doc: dict[str, Any],
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    verifier: str,
) -> str:
    """The ID token from the token endpoint. Access and refresh tokens are dropped."""
    try:
        with _client() as c:
            r = c.post(
                doc["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code_verifier": verifier,
                },
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as e:
        raise OidcError("unreachable", f"Could not reach the provider: {e}") from e
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code != 200:
        error = data.get("error") if isinstance(data, dict) else None
        raise OidcError(
            "token_exchange", f"The provider refused the code ({error or r.status_code})."
        )
    token = data.get("id_token") if isinstance(data, dict) else None
    if not isinstance(token, str):
        raise OidcError("token_exchange", "The provider returned no ID token.")
    return token


# --------------------------------------------------------------------------- ID token


@dataclass(frozen=True)
class IdClaims:
    subject: str
    email: str
    name: str
    hosted_domain: str | None
    amr: list[str]
    raw: dict[str, Any]


def _parts(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    try:
        h64, p64, s64 = token.split(".")
        header = json.loads(_b64url_decode(h64))
        payload = json.loads(_b64url_decode(p64))
        signature = _b64url_decode(s64)
    except (ValueError, TypeError) as e:
        raise OidcError("bad_token", "The ID token is malformed.") from e
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise OidcError("bad_token", "The ID token is malformed.")
    return header, payload, f"{h64}.{p64}".encode("ascii"), signature


def find_key(jwks: dict[str, Any], kid: str | None, alg: str) -> dict[str, Any] | None:
    kty = "RSA" if alg.startswith("RS") else "EC"
    for key in jwks.get("keys", []):
        if not isinstance(key, dict) or key.get("kty") != kty:
            continue
        if key.get("use") not in (None, "sig"):
            continue
        if kid is None or key.get("kid") == kid:
            return key
    return None


def _verify_signature(alg: str, jwk: dict[str, Any], signed: bytes, signature: bytes) -> None:
    try:
        if alg == "RS256":
            n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
            e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
            rsa.RSAPublicNumbers(e, n).public_key().verify(
                signature, signed, padding.PKCS1v15(), hashes.SHA256()
            )
        elif alg == "ES256":
            if jwk.get("crv") != "P-256" or len(signature) != 64:
                raise OidcError("bad_signature", "The ID token signature is invalid.")
            x = int.from_bytes(_b64url_decode(jwk["x"]), "big")
            y = int.from_bytes(_b64url_decode(jwk["y"]), "big")
            key = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
            der = encode_dss_signature(
                int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
            )
            key.verify(der, signed, ec.ECDSA(hashes.SHA256()))
        else:
            raise OidcError("bad_token", f"Signature algorithm {alg!r} is not accepted.")
    except InvalidSignature as e:
        raise OidcError("bad_signature", "The ID token signature is invalid.") from e
    except (KeyError, ValueError, TypeError) as e:
        raise OidcError("bad_signature", "The provider's signing key is unusable.") from e


def token_kid(token: str) -> str | None:
    header, _, _, _ = _parts(token)
    kid = header.get("kid")
    return kid if isinstance(kid, str) else None


def verify_id_token(
    token: str,
    jwks: dict[str, Any],
    *,
    issuer: str,
    client_id: str,
    nonce: str,
    now: float | None = None,
) -> IdClaims:
    header, claims, signed, signature = _parts(token)
    alg = header.get("alg")
    if alg not in ALGORITHMS:
        raise OidcError("bad_token", f"Signature algorithm {alg!r} is not accepted.")
    kid = header.get("kid") if isinstance(header.get("kid"), str) else None
    jwk = find_key(jwks, kid, alg)
    if jwk is None:
        raise OidcError("unknown_key", "The ID token was signed with an unknown key.")
    _verify_signature(alg, jwk, signed, signature)

    now = time.time() if now is None else now
    iss = str(claims.get("iss", "")).rstrip("/")
    if iss != issuer.rstrip("/"):
        # Microsoft's common endpoints issue per-tenant tokens; the tenant is in tid.
        tid = claims.get("tid")
        if not (
            "{tenantid}" in issuer
            and isinstance(tid, str)
            and iss == issuer.replace("{tenantid}", tid)
        ):
            raise OidcError("bad_token", "The ID token comes from another issuer.")
    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if client_id not in audiences:
        raise OidcError("bad_token", "The ID token is for another application.")
    if len(audiences) > 1 and claims.get("azp") != client_id:
        raise OidcError("bad_token", "The ID token is for another application.")
    if "azp" in claims and claims["azp"] != client_id:
        raise OidcError("bad_token", "The ID token is for another application.")
    exp, iat = claims.get("exp"), claims.get("iat")
    if not isinstance(exp, (int, float)) or exp + CLOCK_SKEW < now:
        raise OidcError("expired", "The ID token has expired.")
    if not isinstance(iat, (int, float)) or iat - CLOCK_SKEW > now:
        raise OidcError("bad_token", "The ID token is not valid yet.")
    if not nonce or not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OidcError("bad_nonce", "The ID token does not belong to this sign-in.")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise OidcError("bad_token", "The ID token has no subject.")
    email = claims.get("email") or (
        claims.get("preferred_username")
        if "{tenantid}" in issuer or "microsoftonline" in issuer
        else None
    )
    if not isinstance(email, str) or "@" not in email:
        raise OidcError("no_email", "The provider did not share an e-mail address.")
    verified = claims.get("email_verified")
    # Entra ID does not send email_verified; its addresses are tenant-controlled.
    if verified is False or (verified is None and "microsoftonline" not in issuer):
        raise OidcError("unverified_email", "The provider has not verified this e-mail address.")
    if isinstance(verified, str) and verified.lower() != "true":
        raise OidcError("unverified_email", "The provider has not verified this e-mail address.")
    name = claims.get("name")
    hd = claims.get("hd")
    amr = claims.get("amr")
    return IdClaims(
        subject=sub,
        email=email.strip().lower(),
        name=name.strip() if isinstance(name, str) and name.strip() else email.split("@")[0],
        hosted_domain=hd.lower() if isinstance(hd, str) else None,
        amr=[str(a) for a in amr] if isinstance(amr, list) else [],
        raw=claims,
    )


def domain_allowed(claims: IdClaims, allowed: list[str], *, kind: str) -> bool:
    domains = {d.strip().lower().lstrip("@") for d in allowed if d.strip()}
    if not domains:
        return False
    domain = claims.email.rsplit("@", 1)[1]
    if domain not in domains:
        return False
    # A Google account in an allowed domain must also belong to that Workspace.
    return not (kind == "google" and claims.hosted_domain not in domains)
