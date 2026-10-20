# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call history (docs/REPORTING.md §3): one row per call as a person sees it
(Asterisk's ``linkedid``) and the CDR legs behind it, folded by the worker
from the CDR file. The organization may be unknown (a call that never
touched a phone or a routed DID); such calls are visible to platform
administrators only."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, TenantScoped, UUIDPrimaryKey, utcnow


class CallRecord(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "calls"
    __table_args__ = (
        Index("ix_calls_organization_id_started_at", "organization_id", "started_at"),
    )

    linkedid: Mapped[str] = mapped_column(String(64), unique=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    direction: Mapped[str] = mapped_column(String(10))  # internal | inbound | outbound
    # answered | missed | busy | failed | voicemail | abandoned | blocked | denied
    outcome: Mapped[str] = mapped_column(String(10))
    from_number: Mapped[str | None] = mapped_column(String(64), index=True)
    from_name: Mapped[str | None] = mapped_column(String(200))
    to_number: Mapped[str | None] = mapped_column(String(64), index=True)
    did: Mapped[str | None] = mapped_column(String(64))
    from_extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL"), index=True
    )
    to_extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL"), index=True
    )
    answered_extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL"), index=True
    )
    trunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sip_trunks.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ring_seconds: Mapped[int] = mapped_column(Integer, default=0)
    talk_seconds: Mapped[int] = mapped_column(Integer, default=0)
    leg_count: Mapped[int] = mapped_column(Integer, default=0)
    # Recording identifier from CDR(veyra_rec) (docs/REPORTING.md §4.2).
    recording_ref: Mapped[str | None] = mapped_column(String(64))
    # The queue and ring group the call went through, by slug
    # (docs/REPORT_BUILDER.md §1), from the legs' contexts.
    queue: Mapped[str | None] = mapped_column(String(80), index=True)
    ring_group: Mapped[str | None] = mapped_column(String(80), index=True)
    # No leg added for a minute after the last end: the call is complete.
    is_final: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CallLeg(UUIDPrimaryKey, Base):
    """One CDR as Asterisk wrote it (simple mode)."""

    __tablename__ = "call_legs"
    __table_args__ = (UniqueConstraint("call_id", "uniqueid", "start", "dstchannel"),)

    call_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    uniqueid: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(128))
    dstchannel: Mapped[str] = mapped_column(String(128), default="")
    src: Mapped[str] = mapped_column(String(80), default="")
    clid: Mapped[str] = mapped_column(String(200), default="")
    dst: Mapped[str] = mapped_column(String(80), default="")
    dcontext: Mapped[str] = mapped_column(String(80), default="")
    lastapp: Mapped[str] = mapped_column(String(80), default="")
    disposition: Mapped[str] = mapped_column(String(16))
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    answer: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration: Mapped[int] = mapped_column(Integer, default=0)
    billsec: Mapped[int] = mapped_column(Integer, default=0)
    rec: Mapped[str] = mapped_column(String(64), default="")
    # A call Veyra refused (issue #135): blocked, denied; empty otherwise.
    flag: Mapped[str] = mapped_column(String(16), default="", server_default="")


class QueueEvent(UUIDPrimaryKey, Base):
    """One line of Asterisk's queue_log for queue reports (docs/REPORTING.md
    §5.1): ENTERQUEUE, CONNECT, ABANDON, EXITWITHTIMEOUT, COMPLETE*…"""

    __tablename__ = "queue_events"
    __table_args__ = (Index("ix_queue_events_queue_at", "queue", "at"),)

    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    callid: Mapped[str] = mapped_column(String(64), index=True)
    # The queue's slug (Asterisk name veyra-<slug> without the prefix).
    queue: Mapped[str] = mapped_column(String(80))
    agent: Mapped[str] = mapped_column(String(128), default="")
    event: Mapped[str] = mapped_column(String(32))
    data1: Mapped[str] = mapped_column(String(64), default="")
    data2: Mapped[str] = mapped_column(String(64), default="")
    data3: Mapped[str] = mapped_column(String(64), default="")
