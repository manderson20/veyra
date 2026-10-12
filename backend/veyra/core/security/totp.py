# SPDX-License-Identifier: AGPL-3.0-or-later
"""Time-based one-time passwords (RFC 6238 over RFC 4226 HOTP).

Standard library only: 30-second steps, six digits, HMAC-SHA1, which is what
every authenticator app expects. A code is accepted for the current step and
one step either side (clock drift), and never for a step at or before the
last step that produced an accepted code (replay protection).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import re
import secrets
import struct
from urllib.parse import quote

PERIOD_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1
SECRET_BYTES = 20  # 160 bits, the RFC 4226 recommendation
ISSUER = "Veyra"
_CODE_RE = re.compile(r"^[0-9]{6}$")


def new_secret() -> str:
    """A fresh shared secret, base32 without padding (32 characters)."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def _key(secret_b32: str) -> bytes:
    padded = secret_b32.strip().upper() + "=" * (-len(secret_b32.strip()) % 8)
    return base64.b32decode(padded, casefold=True)


def hotp(secret_b32: str, counter: int) -> str:
    digest = hmac.new(_key(secret_b32), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10**DIGITS:0{DIGITS}d}"


def step(timestamp: float) -> int:
    return int(timestamp // PERIOD_SECONDS)


def totp(secret_b32: str, timestamp: float) -> str:
    return hotp(secret_b32, step(timestamp))


def normalize_code(code: str) -> str:
    return re.sub(r"[\s-]", "", code or "")


def verify(
    secret_b32: str,
    code: str,
    *,
    timestamp: float,
    last_used_step: int | None = None,
    drift: int = DRIFT_STEPS,
) -> int | None:
    """The time step that ``code`` is valid for, or None.

    Steps at or before ``last_used_step`` are never accepted, so a code seen
    once cannot be replayed within its window.
    """
    code = normalize_code(code)
    if not _CODE_RE.match(code):
        return None
    current = step(timestamp)
    matched: int | None = None
    for delta in range(-drift, drift + 1):
        candidate = current + delta
        if last_used_step is not None and candidate <= last_used_step:
            continue
        # Compare every candidate (no early exit) so timing does not reveal
        # which step matched.
        if hmac.compare_digest(hotp(secret_b32, candidate), code) and matched is None:
            matched = candidate
    return matched


def provisioning_uri(secret_b32: str, account: str, issuer: str = ISSUER) -> str:
    """The ``otpauth://`` URI that authenticator apps read from the QR code."""
    label = quote(f"{issuer}:{account}", safe=":@")
    return (
        f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={PERIOD_SECONDS}"
    )


def qr_svg_data_uri(text: str) -> str:
    """The QR code for ``text`` as an SVG data URI, rendered here rather than
    by a third-party image service (the secret must not leave the server)."""
    import segno

    qr = segno.make(text, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=5, border=2, dark="#0b1d3a", light="#ffffff", xmldecl=False)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
