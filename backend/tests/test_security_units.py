# SPDX-License-Identifier: AGPL-3.0-or-later
import uuid

import pytest

from veyra.core.audit import REDACTED, sanitize
from veyra.core.security import passwords, tokens
from veyra.core.security.principal import Grant, Principal
from veyra.core.security.ratelimit import SlidingWindowLimiter


def test_password_hash_roundtrip():
    h = passwords.hash_password("a long enough password")
    assert h.startswith("$argon2id$")
    assert passwords.verify_password(h, "a long enough password")
    assert not passwords.verify_password(h, "wrong password here")
    assert not passwords.verify_password(None, "anything")
    assert not passwords.verify_password("not-a-hash", "anything")


def test_password_policy():
    with pytest.raises(passwords.PasswordPolicyError):
        passwords.validate_password("short")
    with pytest.raises(passwords.PasswordPolicyError):
        passwords.validate_password("someone@example.org", email="Someone@example.org")
    passwords.validate_password("twelve chars ok")


@pytest.mark.parametrize(
    "password",
    [
        "aaaaaaaaaaaa",  # too few distinct characters
        "password1234",  # weak word padded with digits
        "PasswordPassword",  # weak word repeated
        "qwertyuiop12!!",
        "Veyra-2026-!!",  # the product name
        "Taylor loves cats",  # the user's own name
        "mtaylor-rocks-2026",  # the email local part
    ],
)
def test_password_policy_rejects_weak_and_personal(password):
    with pytest.raises(passwords.PasswordPolicyError):
        passwords.validate_password(
            password, email="mtaylor@district.local", display_name="Taylor Morgan"
        )


def test_password_policy_accepts_ordinary_passphrases():
    for ok in ("correct horse battery staple", "Rain on the 5th floor!", "x7#Lq9!pR2vZ"):
        passwords.validate_password(ok, email="mtaylor@district.local", display_name="Taylor")


def test_tokens_only_digest_matches():
    t = tokens.new_token()
    assert tokens.matches(t, tokens.digest(t))
    assert not tokens.matches(t + "x", tokens.digest(t))


def test_rate_limiter_window():
    lim = SlidingWindowLimiter(2, 60)
    assert lim.hit("a", now=0) and lim.hit("a", now=1)
    assert not lim.hit("a", now=2)
    assert lim.hit("b", now=2)
    assert lim.hit("a", now=61)


def test_audit_sanitizes_secrets():
    out = sanitize(
        {"password": "x", "nested": {"sip_secret": "y", "ok": 1}, "items": [{"api_token": "z"}]}
    )
    assert out == {
        "password": REDACTED,
        "nested": {"sip_secret": REDACTED, "ok": 1},
        "items": [{"api_token": REDACTED}],
    }


def test_principal_scopes():
    org_a, org_b, site = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    p = Principal(
        uuid.uuid4(),
        "x@y.z",
        "X",
        grants=[
            Grant("organization", org_a, None, frozenset({"users.read", "modules.manage"})),
            Grant("site", org_b, site, frozenset({"extensions.write"})),
        ],
    )
    assert p.has("users.read", org_a)
    assert not p.has("users.read", org_b)
    assert not p.has("users.read")  # no org given -> platform grant required
    assert not p.has("modules.manage", org_a)  # platform-only permission
    assert not p.has_any_scope("modules.manage")
    assert p.has("extensions.write", org_b, site)
    assert not p.has("extensions.write", org_b)
    assert p.organization_ids_with("users.read") == {org_a}

    admin = Principal(
        uuid.uuid4(), "a@b.c", "A", grants=[Grant("platform", None, None, frozenset({"*"}))]
    )
    assert admin.is_platform_admin
    assert admin.has("modules.manage") and admin.has("users.read", org_b)
    assert admin.organization_ids_with("users.read") is None
