"""Users, roles, permissions, role assignments and sessions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, Timestamps, UUIDPrimaryKey


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
