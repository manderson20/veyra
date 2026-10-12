"""Password hashing (Argon2id) and password policy."""

from __future__ import annotations

import contextlib

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024

_hasher = PasswordHasher()  # Argon2id with argon2-cffi's RFC 9106 low-memory defaults

# A valid hash of an unguessable value, verified when the user does not exist
# so that response timing does not reveal which accounts exist.
_DUMMY_HASH = _hasher.hash("veyra-timing-equalizer-not-a-password")


class PasswordPolicyError(ValueError):
    pass


def validate_password(password: str, *, email: str | None = None) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters.")
    if email and password.strip().lower() == email.strip().lower():
        raise PasswordPolicyError("Password must not be the same as the email address.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        _verify_dummy(password)
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def _verify_dummy(password: str) -> None:
    with contextlib.suppress(VerificationError):
        _hasher.verify(_DUMMY_HASH, password)


def verify_dummy(password: str) -> None:
    """Spend the same time as a real verification (for unknown accounts)."""
    _verify_dummy(password)
