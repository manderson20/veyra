# SPDX-License-Identifier: AGPL-3.0-or-later
"""Users, roles, permissions, role assignments and sessions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, Timestamps, UUIDPrimaryKey, utcnow


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"
    # Email addresses are normalized to lower case before storage.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    # NULL for accounts that can only sign in through an external identity provider.
    password_hash: Mapped[str | None] = mapped_column(Text)
    auth_source: Mapped[str] = mapped_column(String(32), default="local")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # The local recovery administrator always authenticates locally, even
    # when SSO is enforced for everyone else.
    is_recovery_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    home_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when an administrator assigns a temporary password: the user can only
    # reach the authentication endpoints until they choose their own.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    # Multi-factor policy (docs/MFA_DESIGN.md §7): when the requirement started
    # for this user and until when sign-in without a factor is still allowed.
    mfa_required_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Permission(Base):
    """A permission key such as ``users.write``; registered by core or a module."""

    __tablename__ = "permissions"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    module_id: Mapped[str] = mapped_column(String(128), default="core")


class Role(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("organization_id", "key"),)

    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(500), default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    # NULL for installation-wide roles; set for organization-defined custom roles.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_key: Mapped[str] = mapped_column(
        ForeignKey("permissions.key", ondelete="CASCADE"), primary_key=True
    )


class RoleAssignment(UUIDPrimaryKey, Timestamps, Base):
    """Grants a role to a user within a scope (platform, organization or site)."""

    __tablename__ = "role_assignments"
    __table_args__ = (
        CheckConstraint(
            "(scope_type = 'platform' AND organization_id IS NULL AND site_id IS NULL)"
            " OR (scope_type = 'organization' AND organization_id IS NOT NULL AND site_id IS NULL)"
            " OR (scope_type = 'site' AND organization_id IS NOT NULL AND site_id IS NOT NULL)",
            name="scope_consistent",
        ),
        UniqueConstraint("user_id", "role_id", "scope_type", "organization_id", "site_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))
    scope_type: Mapped[str] = mapped_column(String(16))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))


class UserSession(UUIDPrimaryKey, Base):
    """Server-side session. Only SHA-256 hashes of the tokens are stored."""

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    # NULL while the session is a short-lived pre-authentication session that
    # may only complete the second factor (docs/MFA_DESIGN.md §4).
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_failures: Mapped[int] = mapped_column(Integer, default=0)
    # The password (and code) entered again for a sensitive action (issue #137).
    reauth_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The pending passkey sign-in challenge (base64url; issue #107).
    webauthn_challenge: Mapped[str | None] = mapped_column(Text)


class MfaMethod(UUIDPrimaryKey, Base):
    """A second factor: ``totp`` (authenticator app) or ``webauthn`` (passkey)."""

    __tablename__ = "mfa_methods"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(100), default="Authenticator app")
    # TOTP shared secret encrypted with the installation key
    # (purpose ``user.totp_secret:<user id>``); never stored in clear.
    secret_ciphertext: Mapped[str | None] = mapped_column(Text)
    # Passkey (issue #107): {id, public_key (base64url), sign_count, transports,
    # aaguid}; while pending, {challenge, rp_id}.
    credential: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # The last TOTP time step that produced an accepted code (replay protection).
    last_used_step: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # NULL until the user proves the app works by entering a first code.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MfaRecoveryCode(UUIDPrimaryKey, Base):
    """Single-use recovery code, Argon2id-hashed like a password."""

    __tablename__ = "mfa_recovery_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordResetToken(UUIDPrimaryKey, Base):
    """One-time password reset link, issued by an administrator or the CLI.

    Only the SHA-256 digest of the token is stored. A token is valid until
    ``expires_at`` and until it is used (``used_at``). Issuing a new token for
    a user deletes that user's unused tokens, so at most one link is live.
    """

    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Who issued the link: an administrator's email or "cli".
    issued_by: Mapped[str] = mapped_column(String(320))
    issued_from_ip: Mapped[str | None] = mapped_column(String(64))


class ApiToken(UUIDPrimaryKey, Base):
    """A scoped bearer token for a client without cookies (ADR 0015). Only the
    SHA-256 digest is stored; ``scopes`` lists the permission keys the token
    may exercise (intersected with the user's grants at request time)."""

    __tablename__ = "api_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # companion
    label: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_ip: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_ip: Mapped[str | None] = mapped_column(String(64))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TrustedBrowser(UUIDPrimaryKey, Base):
    """A browser that skips the second factor for a while (issue #137): the
    cookie holds a random token, the row its digest. Changing or resetting the
    password, resetting the second factor or signing out of other sessions
    forgets every trusted browser of the user."""

    __tablename__ = "trusted_browsers"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    label: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ip: Mapped[str | None] = mapped_column(String(45))


class UserPreference(Base):
    """Per-user settings document (companion speed dials and the like)."""

    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow
    )
