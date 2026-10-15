# SPDX-License-Identifier: AGPL-3.0-or-later
"""The central console's view of its instances (docs/CENTRAL_MANAGEMENT.md §7).

Only the console installation fills these tables; an instance keeps its
membership in ``system_settings`` (``central.membership``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, Timestamps, UUIDPrimaryKey


class CentralPolicy(UUIDPrimaryKey, Timestamps, Base):
    """Settings the console wants on its instances (§4)."""

    __tablename__ = "central_policies"

    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Raised on every change; instances report the version they applied.
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class CentralInstance(Timestamps, Base):
    """An enrolled installation, by its permanent ``instance_id``."""

    __tablename__ = "central_instances"

    instance_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    label: Mapped[str | None] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str | None] = mapped_column(String(64))
    public_key: Mapped[str] = mapped_column(String(100))
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("central_policies.id", ondelete="SET NULL")
    )
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_address: Mapped[str | None] = mapped_column(String(64))
    last_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CentralSample(UUIDPrimaryKey, Base):
    """Counts every 5 minutes for the console's graphs (kept 30 days)."""

    __tablename__ = "central_samples"

    instance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("central_instances.instance_id", ondelete="CASCADE"), index=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    registered: Mapped[int | None] = mapped_column(Integer)
    active_calls: Mapped[int | None] = mapped_column(Integer)
    extensions: Mapped[int | None] = mapped_column(Integer)
    alerts: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))


class CentralCommand(UUIDPrimaryKey, Base):
    """A one-shot action for an instance (§5)."""

    __tablename__ = "central_commands"

    instance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("central_instances.instance_id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ok | failed | refused | expired
    outcome: Mapped[str | None] = mapped_column(String(16))
    message: Mapped[str | None] = mapped_column(Text)


class CentralEnrollmentToken(UUIDPrimaryKey, Base):
    """Single-use enrollment token (§2); only its digest is kept."""

    __tablename__ = "central_enrollment_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str | None] = mapped_column(String(120))
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("central_policies.id", ondelete="SET NULL")
    )
    created_by: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[uuid.UUID | None] = mapped_column()


class CentralNonce(Base):
    """Nonces seen in the last minutes: a replayed check-in is refused."""

    __tablename__ = "central_nonces"

    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
