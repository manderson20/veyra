# SPDX-License-Identifier: AGPL-3.0-or-later
"""TOTP against the RFC 6238 Appendix B vectors (SHA-1), drift and replay rules,
recovery code helpers."""

import base64

import pytest

from veyra.core.security import mfa, totp

# RFC 6238 test secret "12345678901234567890" (ASCII) as base32.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
# (time, expected 8-digit code) from Appendix B; we compare the last six digits.
RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


@pytest.mark.parametrize(("when", "expected"), RFC_VECTORS)
def test_rfc6238_vectors(when, expected):
    assert totp.totp(RFC_SECRET, when) == expected[-6:]


def test_drift_window_and_replay_protection():
    secret = totp.new_secret()
    assert len(secret) == 32 and secret.isupper()
    now = 1_700_000_000.0
    step = totp.step(now)
    current, previous, following = (totp.hotp(secret, step + d) for d in (0, -1, 1))
    assert totp.verify(secret, current, timestamp=now) == step
    assert totp.verify(secret, previous, timestamp=now) == step - 1
    assert totp.verify(secret, following, timestamp=now) == step + 1
    assert totp.verify(secret, totp.hotp(secret, step + 2), timestamp=now) is None
    # a code already used in its step (or any earlier step) is refused
    assert totp.verify(secret, current, timestamp=now, last_used_step=step) is None
    assert totp.verify(secret, previous, timestamp=now, last_used_step=step) is None
    assert totp.verify(secret, following, timestamp=now, last_used_step=step) == step + 1
    # formatting tolerance and garbage
    assert totp.verify(secret, f"{current[:3]} {current[3:]}", timestamp=now) == step
    for bad in ("", "12345", "1234567", "abcdef", "000 000 0"):
        assert totp.verify(secret, bad, timestamp=now) is None


def test_provisioning_uri_and_qr():
    uri = totp.provisioning_uri("ABCDEFGHIJKLMNOP", "jo@district.local")
    assert uri.startswith("otpauth://totp/Veyra:jo@district.local?secret=ABCDEFGHIJKLMNOP")
    assert "issuer=Veyra" in uri and "digits=6" in uri and "period=30" in uri
    data = totp.qr_svg_data_uri(uri)
    assert data.startswith("data:image/svg+xml;base64,")
    svg = base64.b64decode(data.split(",", 1)[1]).decode()
    assert svg.startswith("<svg") and "<path" in svg


def test_recovery_code_helpers():
    code = mfa.new_recovery_code()
    assert len(code) == 10 and all(ch in mfa.RECOVERY_ALPHABET for ch in code)
    shown = mfa.format_recovery_code(code)
    assert shown == f"{code[:5]}-{code[5:]}"
    assert mfa.normalize_recovery_code(shown.lower()) == code
    assert mfa.normalize_recovery_code(" ab cde-fgh jk ") == "ABCDEFGHJK"
    assert mfa.looks_like_recovery_code(shown) and not mfa.looks_like_recovery_code("123456")
    assert not mfa.looks_like_recovery_code("ABCDE-FGHI0")  # 0 is not in the alphabet


def test_policy_validation():
    assert mfa.MfaPolicy().required_for == ["platform_admin", "org_admin"]
    with pytest.raises(ValueError):
        mfa.MfaPolicy(required_for=["superuser"])
    with pytest.raises(ValueError):
        mfa.MfaPolicy(allowed_methods=["sms"])
    with pytest.raises(ValueError):
        mfa.MfaPolicy(grace_days=400)
    assert mfa.MfaPolicy(required_for=["org_admin", " org_admin "]).required_for == ["org_admin"]
