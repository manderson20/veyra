# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wire format between instances and the central console
(docs/CENTRAL_MANAGEMENT.md §2-3).

Every request is signed by the instance and every answer by the console,
both with Ed25519 over a canonical string that includes a timestamp, a nonce
and the SHA-256 of the body. The console's answer also covers the request's
nonce, so an old answer cannot be replayed to an instance.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import secrets
import ssl
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from cryptography.exceptions import InvalidSignature

from veyra.core.signing import generate_keypair, load_private_key, load_public_key

CHECK_IN_PATH = "/api/v1/central/check-in"
ENROLL_PATH = "/api/v1/central/enroll"
MAX_SKEW = 300
TIMEOUT = 15.0
KEY_PURPOSE = "central:private-key"

H_INSTANCE = "Veyra-Instance"
H_TIMESTAMP = "Veyra-Timestamp"
H_NONCE = "Veyra-Nonce"
H_SIGNATURE = "Veyra-Signature"
H_CONSOLE_SIGNATURE = "Veyra-Console-Signature"

# Tests replace this with an httpx.MockTransport or an ASGI transport.
transport: httpx.BaseTransport | None = None


class ProtocolError(Exception):
    pass


def new_keypair() -> tuple[str, str]:
    """(private, public), both base64 of the raw Ed25519 keys."""
    return generate_keypair()


def fingerprint(public_key_b64: str) -> str:
    """Short, comparable form of a public key: ``ab12-cd34-…`` (8 groups)."""
    raw = base64.b64decode(public_key_b64)
    digest = hashlib.sha256(raw).hexdigest()[:32]
    return "-".join(digest[i : i + 4] for i in range(0, 32, 4))


def normalize_fingerprint(value: str) -> str:
    return "".join(c for c in value.lower() if c in "0123456789abcdef")


def body_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def request_string(method: str, path: str, ts: str, nonce: str, body: bytes) -> bytes:
    return f"{method.upper()} {path}\n{ts}\n{nonce}\n{body_hash(body)}".encode()


def answer_string(ts: str, request_nonce: str, body: bytes) -> bytes:
    return f"answer\n{ts}\n{request_nonce}\n{body_hash(body)}".encode()


def sign(private_key_b64: str, data: bytes) -> str:
    return base64.b64encode(load_private_key(private_key_b64).sign(data)).decode()


def verify(public_key_b64: str, data: bytes, signature: str) -> bool:
    try:
        load_public_key(public_key_b64).verify(base64.b64decode(signature, validate=True), data)
    except (InvalidSignature, binascii.Error, ValueError):
        return False
    return True


def fresh(ts: str, now: float | None = None) -> bool:
    try:
        value = int(ts)
    except ValueError:
        return False
    return abs((now if now is not None else time.time()) - value) <= MAX_SKEW


def new_nonce() -> str:
    return secrets.token_urlsafe(24)


def check_console_url(url: str) -> str:
    """HTTPS, or plain HTTP to a loopback address (the console on this server)."""
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ProtocolError("The console address must start with https://")
    if parts.path or parts.query or parts.fragment or parts.username:
        raise ProtocolError("Enter only the console's address, such as https://console.example.org")
    if parts.scheme == "http":
        try:
            loopback = ipaddress.ip_address(parts.hostname).is_loopback
        except ValueError:
            loopback = parts.hostname == "localhost"
        if not loopback:
            raise ProtocolError("The console address must start with https://")
    return url


def client(ca_pem: str | None) -> httpx.Client:
    """An HTTP client that trusts the system's authorities, or only the
    console's own authority when one was given at enrollment."""
    verify: ssl.SSLContext | bool = True
    if ca_pem:
        verify = ssl.create_default_context(cadata=ca_pem)
    return httpx.Client(timeout=TIMEOUT, follow_redirects=False, verify=verify, transport=transport)


def signed_post(
    base_url: str,
    path: str,
    body: bytes,
    *,
    instance_id: str,
    private_key: str,
    ca_pem: str | None,
) -> tuple[httpx.Response, str]:
    """POST a signed request; returns the response and the nonce used."""
    ts, nonce = str(int(time.time())), new_nonce()
    headers = {
        "Content-Type": "application/json",
        H_INSTANCE: instance_id,
        H_TIMESTAMP: ts,
        H_NONCE: nonce,
        H_SIGNATURE: sign(private_key, request_string("POST", path, ts, nonce, body)),
    }
    try:
        with client(ca_pem) as c:
            r = c.post(base_url + path, content=body, headers=headers)
    except httpx.HTTPError as e:
        raise ProtocolError(f"The console is not reachable: {type(e).__name__}: {e}") from e
    return r, nonce


def check_answer(r: httpx.Response, console_key: str, request_nonce: str) -> dict[str, Any]:
    """The console's signed answer, or ProtocolError."""
    sig = r.headers.get(H_CONSOLE_SIGNATURE, "")
    ts = r.headers.get(H_TIMESTAMP, "")
    if (
        not sig
        or not fresh(ts)
        or not verify(console_key, answer_string(ts, request_nonce, r.content), sig)
    ):
        raise ProtocolError("The console's answer is not signed by the console we enrolled with")
    try:
        data = r.json()
    except ValueError as e:
        raise ProtocolError("The console's answer is not JSON") from e
    if not isinstance(data, dict):
        raise ProtocolError("The console's answer is not a JSON object")
    return data


def sign_answer(private_key: str, request_nonce: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    return {
        H_TIMESTAMP: ts,
        H_CONSOLE_SIGNATURE: sign(private_key, answer_string(ts, request_nonce, body)),
    }
