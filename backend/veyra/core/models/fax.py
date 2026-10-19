# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fax (docs/USER_PORTAL.md §9): inboxes that answer a DID or an inbound
route with ReceiveFAX and email the pages as a PDF, and the jobs a user sends
from My Phone or an inbox received."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey

# queued → dialling → sending → sent | failed (outbound; failed may requeue);
# received (inbound); cancelled (by the user or an administrator).
JOB_STATES = ("queued", "dialling", "sending", "sent", "failed", "received", "cancelled")
ACTIVE_STATES = ("queued", "dialling", "sending")


class FaxInbox(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A destination "Fax to email": context ``veyra-fax-in-<slug>`` answers,
    receives the pages and the API emails the PDF to the recipients."""

    __tablename__ = "fax_inboxes"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    # Email addresses the PDF goes to.
    recipients: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # Sent to the remote machine as the local station id / page header;
    # the organization's values apply when empty.
    station_id: Mapped[str | None] = mapped_column(String(32))
    header: Mapped[str | None] = mapped_column(String(64))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class FaxJob(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """One fax: sent by a user (``out``) or received on an inbox (``in``).
    Files live under ``<data>/fax/<org slug>/`` and are named by the job id
    (``file`` is the TIFF the engine sends or wrote, ``pdf_file`` the PDF the
    user uploaded or the one made from the received pages)."""

    __tablename__ = "fax_jobs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL")
    )
    inbox_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fax_inboxes.id", ondelete="SET NULL")
    )
    direction: Mapped[str] = mapped_column(String(3))  # out | in
    # The number dialled (out) or the caller's number (in).
    number: Mapped[str] = mapped_column(String(32))
    caller_id: Mapped[str | None] = mapped_column(String(32))
    remote_id: Mapped[str | None] = mapped_column(String(64))
    pages: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    file: Mapped[str | None] = mapped_column(String(255))
    pdf_file: Mapped[str | None] = mapped_column(String(255))
    original_name: Mapped[str | None] = mapped_column(String(255))
    # {"to": ..., "from": ..., "subject": ..., "note": ...} when a cover page was added.
    cover: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # The engine channel of the attempt in progress (ChannelDestroyed ends it).
    channel_id: Mapped[str | None] = mapped_column(String(80), index=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
