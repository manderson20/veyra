# SPDX-License-Identifier: AGPL-3.0-or-later
"""Multi-factor authentication: policy, factors and recovery codes.

See docs/MFA_DESIGN.md and ADR 0012. TOTP secrets are encrypted with the
installation key (purpose ``user.totp_secret:<user id>``); recovery codes are
hashed with Argon2id like passwords because they are only ever compared.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from veyra.core.models import (
    MfaMethod,
    MfaRecoveryCode,
    Role,
    RoleAssignment,
    SystemSetting,
    User,
)
from veyra.core.models.base import utcnow
from veyra.core.security import passwords
from veyra.core.security.permissions import SYSTEM_ROLE_DEFS

MFA_POLICY_KEY = "security.mfa"
METHOD_TOTP = "totp"
ALLOWED_METHODS = (METHOD_TOTP,)  # "webauthn" arrives with passkeys (Milestone 17)
RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_LENGTH = 10
# 32 symbols: no I, O, 0 or 1, which are easy to confuse when typed.
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
# Incorrect codes before a pre-authentication session is locked.
MAX_VERIFY_FAILURES = 5
PRE_AUTH_TTL = timedelta(minutes=5)
_ROLE_KEYS = {key for key, _, _ in SYSTEM_ROLE_DEFS}


def secret_purpose(user_id: uuid.UUID) -> str:
    return f"user.totp_secret:{user_id}"


# ----------------------------------------------------------------- policy


class MfaPolicy(BaseModel):
    """Who must use a second factor. Evaluated from role assignments at sign-in."""

    required_for: list[str] = Field(default_factory=lambda: ["platform_admin", "org_admin"])
    grace_days: int = Field(14, ge=0, le=365)
    allowed_methods: list[str] = Field(default_factory=lambda: [METHOD_TOTP])

    @field_validator("required_for")
    @classmethod
    def _roles(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for key in v:
            key = key.strip()
            if key not in _ROLE_KEYS:
                raise ValueError(f"unknown role {key!r}")
            if key not in out:
                out.append(key)
        return out

    @field_validator("allowed_methods")
    @classmethod
    def _methods(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for m in v:
            if m not in ALLOWED_METHODS:
                raise ValueError(
                    f"unsupported method {m!r}; available: {', '.join(ALLOWED_METHODS)}"
                )
            if m not in out:
                out.append(m)
        if not out:
            raise ValueError("allow at least one method")
        return out


def load_policy(db: Session) -> MfaPolicy:
    row = db.get(SystemSetting, MFA_POLICY_KEY)
    if row is None or not isinstance(row.value, dict):
        return MfaPolicy()
    return MfaPolicy.model_validate(row.value)


def save_policy(db: Session, policy: MfaPolicy, updated_by: uuid.UUID | None = None) -> None:
    row = db.get(SystemSetting, MFA_POLICY_KEY)
    value = policy.model_dump(mode="json")
    if row is None:
        db.add(SystemSetting(key=MFA_POLICY_KEY, value=value, updated_by=updated_by))
    else:
        row.value = value
        row.updated_by = updated_by
    db.flush()


def role_keys_of(db: Session, user_id: uuid.UUID) -> set[str]:
    return set(
        db.scalars(
            select(Role.key)
            .join(RoleAssignment, RoleAssignment.role_id == Role.id)
            .where(RoleAssignment.user_id == user_id)
        ).all()
    )


def is_required(db: Session, policy: MfaPolicy, user: User) -> bool:
    """Whether policy requires a second factor for this user. External identity
    providers bring their own MFA (docs/MFA_DESIGN.md §8); the recovery
    administrator always authenticates locally and is never exempt."""
    if user.auth_source != "local" and not user.is_recovery_admin:
        return False
    return bool(role_keys_of(db, user.id) & set(policy.required_for))


def confirmed_methods(db: Session, user_id: uuid.UUID) -> list[MfaMethod]:
    return list(
        db.scalars(
            select(MfaMethod)
            .where(MfaMethod.user_id == user_id, MfaMethod.confirmed_at.is_not(None))
            .order_by(MfaMethod.created_at)
        )
    )


def recovery_codes_remaining(db: Session, user_id: uuid.UUID) -> int:
    return len(
        db.scalars(
            select(MfaRecoveryCode.id).where(
                MfaRecoveryCode.user_id == user_id, MfaRecoveryCode.used_at.is_(None)
            )
        ).all()
    )


def in_grace(user: User, now: datetime) -> bool:
    return bool(user.mfa_grace_until and user.mfa_grace_until > now)


def ensure_requirement(user: User, policy: MfaPolicy, required: bool, now: datetime) -> None:
    """Start (or clear) the enrolment window on a user according to policy."""
    if required:
        if user.mfa_required_at is None:
            user.mfa_required_at = now
            user.mfa_grace_until = now + timedelta(days=policy.grace_days)
    else:
        user.mfa_required_at = None
        user.mfa_grace_until = None


def apply_policy(db: Session, policy: MfaPolicy, now: datetime | None = None) -> int:
    """Re-evaluate every local user against a (new) policy. Returns how many
    users had their requirement started or cleared."""
    now = now or utcnow()
    changed = 0
    for user in db.scalars(select(User).where(User.is_active.is_(True))):
        before = (user.mfa_required_at, user.mfa_grace_until)
        ensure_requirement(user, policy, is_required(db, policy, user), now)
        if (user.mfa_required_at, user.mfa_grace_until) != before:
            changed += 1
    db.flush()
    return changed


# ----------------------------------------------------------------- recovery codes


def new_recovery_code() -> str:
    return "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH))


def format_recovery_code(code: str) -> str:
    """``ABCDEFGHJK`` -> ``ABCDE-FGHJK`` for display."""
    half = RECOVERY_CODE_LENGTH // 2
    return f"{code[:half]}-{code[half:]}"


def normalize_recovery_code(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def looks_like_recovery_code(code: str) -> bool:
    n = normalize_recovery_code(code)
    return len(n) == RECOVERY_CODE_LENGTH and all(ch in RECOVERY_ALPHABET for ch in n)


def replace_recovery_codes(db: Session, user_id: uuid.UUID) -> list[str]:
    """Issue a fresh set of codes (the old ones stop working). Returns the
    clear-text codes, formatted, to be shown exactly once."""
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id))
    now = utcnow()
    codes = [new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    for code in codes:
        db.add(
            MfaRecoveryCode(
                id=uuid.uuid4(),
                user_id=user_id,
                code_hash=passwords.hash_password(code),
                created_at=now,
            )
        )
    db.flush()
    return [format_recovery_code(c) for c in codes]


def use_recovery_code(db: Session, user_id: uuid.UUID, code: str, now: datetime) -> bool:
    """Consume a recovery code. Returns True when one matched."""
    candidate = normalize_recovery_code(code)
    if len(candidate) != RECOVERY_CODE_LENGTH:
        return False
    for row in db.scalars(
        select(MfaRecoveryCode).where(
            MfaRecoveryCode.user_id == user_id, MfaRecoveryCode.used_at.is_(None)
        )
    ):
        if passwords.verify_password(row.code_hash, candidate):
            row.used_at = now
            db.flush()
            return True
    return False


def remove_all_factors(db: Session, user_id: uuid.UUID) -> int:
    """Delete every method and recovery code of a user (administrator reset)."""
    methods = db.execute(delete(MfaMethod).where(MfaMethod.user_id == user_id))
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id))
    db.flush()
    return int(getattr(methods, "rowcount", 0) or 0)
