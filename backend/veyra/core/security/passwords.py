"""Password hashing (Argon2id) and password policy."""

from __future__ import annotations

import contextlib
import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024
MIN_DISTINCT_CHARACTERS = 4

_hasher = PasswordHasher()  # Argon2id with argon2-cffi's RFC 9106 low-memory defaults

# A valid hash of an unguessable value, verified when the user does not exist
# so that response timing does not reveal which accounts exist.
_DUMMY_HASH = _hasher.hash("veyra-timing-equalizer-not-a-password")

# Words that make a password weak however it is padded: the password with
# digits and punctuation stripped must not be one of these or a repetition
# of one. This is a small, documented list, not a breached-password service
# (which would need a network call); the length rule rejects the common
# short passwords.
_WEAK_WORDS = frozenset(
    {
        "password",
        "passphrase",
        "qwerty",
        "qwertyuiop",
        "asdfghjkl",
        "letmein",
        "welcome",
        "admin",
        "administrator",
        "changeme",
        "default",
        "secret",
        "iloveyou",
        "abcdefghijkl",
        "veyra",
        "telephone",
        "asterisk",
    }
)
_NON_ALPHA = re.compile(r"[^a-z]+")


class PasswordPolicyError(ValueError):
    pass


def _words(value: str | None, minimum: int = 4) -> set[str]:
    """Lower-case alphabetic words of at least ``minimum`` letters in ``value``."""
    if not value:
        return set()
    return {w for w in _NON_ALPHA.split(value.lower()) if len(w) >= minimum}


def validate_password(
    password: str, *, email: str | None = None, display_name: str | None = None
) -> None:
    """Raise :class:`PasswordPolicyError` when the password is not acceptable.

    Rules: 12 to 1024 characters; at least four distinct characters; not the
    email address; not built from the email's local part, the user's name or
    a well-known weak word. Composition rules (digits, symbols) are
    deliberately not required; length and unpredictability matter more.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters.")
    if len(set(password)) < MIN_DISTINCT_CHARACTERS:
        raise PasswordPolicyError(
            f"Password must contain at least {MIN_DISTINCT_CHARACTERS} different characters."
        )
    lowered = password.strip().lower()
    if email and lowered == email.strip().lower():
        raise PasswordPolicyError("Password must not be the same as the email address.")
    letters = _NON_ALPHA.sub("", lowered)
    personal = _words(email.split("@", 1)[0] if email else None) | _words(display_name)
    for word in personal:
        if word in lowered:
            raise PasswordPolicyError("Password must not contain your name or email address.")
    if letters and _is_repetition_of_weak_word(letters):
        raise PasswordPolicyError("Password is too easy to guess. Choose a less common phrase.")


def _is_repetition_of_weak_word(letters: str) -> bool:
    """True when ``letters`` is a weak word repeated one or more times."""
    for word in _WEAK_WORDS:
        if len(letters) % len(word) == 0 and letters == word * (len(letters) // len(word)):
            return True
    return False


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
