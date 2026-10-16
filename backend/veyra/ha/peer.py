# SPDX-License-Identifier: AGPL-3.0-or-later
"""The peer channel between the two nodes (docs/HIGH_AVAILABILITY.md §3.2):
``POST https://<peer>/api/v1/ha/peer/<verb>`` signed with the node keys in
Milestone 15's message format (:mod:`veyra.central.protocol`, reused as is).
The ``Veyra-Instance`` header carries the calling node's id.
"""

from __future__ import annotations

import json
import ssl
import time
from typing import Any

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.central import protocol
from veyra.core.models import CentralNonce
from veyra.core.models.base import utcnow

PEER_PREFIX = "/api/v1/ha/peer/"
VERBS = ("join", "health", "heartbeat", "manifest", "file", "run", "epoch")
# Verbs a peer may ask this node's agent to run (§3.2); everything else is
# refused with 403 even when the signature is good.
RUNNABLE = (
    "freeze",
    "unfreeze",
    "engine-stop",
    "demote",
    "rejoin",
    "release-address",
    "postgres-stop",
    "checkpoint",
    "current-lsn",
    "upgrade",
    "status",
    "set-peer-epoch",
    "standalone",
)
HEALTH_TIMEOUT = 5.0
CALL_TIMEOUT = 120.0
FILE_TIMEOUT = 900.0
MAX_BODY = 256 * 1024


class PeerError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def path_for(verb: str) -> str:
    return PEER_PREFIX + verb


def encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


# ------------------------------------------------------------------ client


def post(
    url: str,
    verb: str,
    payload: dict[str, Any],
    *,
    node_id: str,
    private_key: str,
    peer_public_key: str | None,
    ca_pem: str | None,
    timeout: float = CALL_TIMEOUT,
    verify_tls: bool = True,
) -> httpx.Response:
    """A signed POST; the answer's signature is checked against the peer's
    key when one is known (not yet at ``join``). ``verify_tls=False`` is
    for the join only: the new node has no CA yet, and the bundle's secrecy
    rests on the single-use token, not on TLS."""
    path = path_for(verb)
    body = encode(payload)
    ts, nonce = str(int(time.time())), protocol.new_nonce()
    headers = {
        "Content-Type": "application/json",
        protocol.H_INSTANCE: node_id,
        protocol.H_TIMESTAMP: ts,
        protocol.H_NONCE: nonce,
        protocol.H_SIGNATURE: protocol.sign(
            private_key, protocol.request_string("POST", path, ts, nonce, body)
        ),
    }
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            verify=_verify(ca_pem) if verify_tls else False,
            transport=protocol.transport,
        ) as c:
            r = c.post(url.rstrip("/") + path, content=body, headers=headers)
    except httpx.HTTPError as e:
        raise PeerError(
            502, "unreachable", f"The peer is not reachable: {type(e).__name__}: {e}"
        ) from e
    if peer_public_key:
        sig = r.headers.get(protocol.H_CONSOLE_SIGNATURE, "")
        rts = r.headers.get(protocol.H_TIMESTAMP, "")
        expected = protocol.answer_string(rts, nonce, r.content)
        good = sig and protocol.fresh(rts) and protocol.verify(peer_public_key, expected, sig)
        if not good:
            raise PeerError(502, "bad_answer", "The peer's answer is not signed with its node key.")
    return r


def _verify(ca_pem: str | None) -> ssl.SSLContext | bool:
    """Only the shared Veyra CA when it is known, else the system's authorities."""
    return ssl.create_default_context(cadata=ca_pem) if ca_pem else True


def call(url: str, verb: str, payload: dict[str, Any], **kw: Any) -> dict[str, Any]:
    """A signed call expecting a JSON object back; HTTP errors become PeerError
    with the peer's problem code."""
    r = post(url, verb, payload, **kw)
    if r.status_code >= 400:
        code, detail = "peer_error", r.text[:200]
        try:
            data = r.json()
            code = str(data.get("code") or code)
            detail = str(data.get("detail") or detail)
        except ValueError:
            pass
        raise PeerError(r.status_code, code, detail)
    try:
        data = r.json()
    except ValueError as e:
        raise PeerError(502, "bad_answer", "The peer's answer is not JSON.") from e
    if not isinstance(data, dict):
        raise PeerError(502, "bad_answer", "The peer's answer is not a JSON object.")
    return data


# ------------------------------------------------------------------ server


def parse_body(body: bytes) -> dict[str, Any]:
    if len(body) > MAX_BODY:
        raise PeerError(413, "too_large", "The request is too large.")
    try:
        data = json.loads(body or b"{}")
    except ValueError as e:
        raise PeerError(400, "bad_request", "The request is not JSON.") from e
    if not isinstance(data, dict):
        raise PeerError(400, "bad_request", "The request is not a JSON object.")
    return data


def verify_request(
    db: Session, public_key: str, verb: str, body: bytes, headers: dict[str, str]
) -> str:
    """Signature, freshness and single use of the nonce; returns the nonce.
    Nonces share Milestone 15's table (``central_nonces``)."""
    ts = headers.get(protocol.H_TIMESTAMP.lower(), "")
    nonce = headers.get(protocol.H_NONCE.lower(), "")
    sig = headers.get(protocol.H_SIGNATURE.lower(), "")
    if not (ts and nonce and sig) or len(nonce) > 64:
        raise PeerError(401, "unsigned", "The request is not signed.")
    if not protocol.fresh(ts):
        raise PeerError(401, "stale", "The request's time is off by more than five minutes.")
    if not protocol.verify(
        public_key, protocol.request_string("POST", path_for(verb), ts, nonce, body), sig
    ):
        raise PeerError(401, "bad_signature", "The request's signature is not valid.")
    if db.bind is not None and _in_recovery(db):
        # A standby cannot record nonces; the signature and the five-minute
        # window still hold, and a standby only answers read verbs.
        return nonce
    try:
        with db.begin_nested():
            db.add(CentralNonce(nonce=nonce, seen_at=utcnow()))
    except IntegrityError as e:
        raise PeerError(401, "replayed", "This request was already received.") from e
    return nonce


def _in_recovery(db: Session) -> bool:
    from sqlalchemy import func, select

    try:
        return bool(db.scalar(select(func.pg_is_in_recovery())))
    except Exception:
        db.rollback()
        return False


def answer(private_key: str, nonce: str, payload: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    body = encode(payload)
    return body, protocol.sign_answer(private_key, nonce, body)


def answer_headers(private_key: str, nonce: str, body_sha256: str) -> dict[str, str]:
    """Signed headers for a streamed body whose SHA-256 is already known."""
    ts = str(int(time.time()))
    data = f"answer\n{ts}\n{nonce}\n{body_sha256}".encode()
    return {
        protocol.H_TIMESTAMP: ts,
        protocol.H_CONSOLE_SIGNATURE: protocol.sign(private_key, data),
    }
