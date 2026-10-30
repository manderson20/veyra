# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call recording (docs/REPORTING.md §4): what an organization records, and
the recordings themselves. Asterisk writes ``<data>/recordings/incoming/
<uniqueid>--<policy>.wav``; the worker converts each finished file to Ogg
Opus under ``<data>/recordings/<org>/<yyyy>/<mm>/`` and records it here."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey, utcnow


class RecordingPolicy(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    __tablename__ = "recording_policies"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    inbound: Mapped[bool] = mapped_column(Boolean, default=True)
    outbound: Mapped[bool] = mapped_column(Boolean, default=False)
    internal: Mapped[bool] = mapped_column(Boolean, default=False)
    # "all": every call of the organization in the chosen directions;
    # "selected": calls touching the chosen extensions, groups, queues or DIDs.
    scope: Mapped[str] = mapped_column(String(10), default="all")
    extension_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    ring_group_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    queue_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    inbound_route_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list
    )
    # Played to the caller before the call connects ("This call may be recorded").
    announcement_prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompts.id", ondelete="SET NULL")
    )
    retention_days: Mapped[int] = mapped_column(Integer, default=90)


class CallRecording(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "call_recordings"

    # The recording identifier: the recorded channel's UNIQUEID (CDR veyra_rec).
    ref: Mapped[str] = mapped_column(String(64), unique=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calls.id", ondelete="SET NULL"), index=True
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recording_policies.id", ondelete="SET NULL")
    )
    # A conference room's recording (issue #133) instead of a call's.
    conference_room_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conference_rooms.id", ondelete="SET NULL"), index=True
    )
    # Relative to <data>/recordings.
    path: Mapped[str] = mapped_column(String(300))
    # The file's own AES-256-GCM key wrapped by the installation key
    # (issue #122); NULL: stored in the clear (before 0.27.4).
    key_ciphertext: Mapped[str | None] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(16), default="ogg")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # Held recordings are exempt from retention (a records request).
    held: Mapped[bool] = mapped_column(Boolean, default=False)
    held_by: Mapped[str | None] = mapped_column(String(200))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(String(200))
    # The copy on a backup destination (docs/RECORDING_ARCHIVE.md).
    archive_destination: Mapped[str | None] = mapped_column(String(40))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archive_removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
