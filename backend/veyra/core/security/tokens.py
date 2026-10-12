"""Opaque random tokens; only their SHA-256 digests are ever persisted."""

from __future__ import annotations

import hashlib
import hmac
import secrets


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def matches(token: str, expected_digest: str) -> bool:
    return hmac.compare_digest(digest(token), expected_digest)
