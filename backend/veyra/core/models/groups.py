# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ring groups, call queues and pickup groups (Milestone 8).

Engine-neutral: the generator turns these rows into dialplan contexts,
``queues.conf`` and named pickup groups on endpoints
(docs/RING_GROUPS_QUEUES.md). Everything belongs to one organization. Ring
groups and queues take a number from the numbering plan, unique across
extensions, ring groups and queues of the installation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class _Failover:
    """Where the call goes when the group or queue does not connect it:
    extension | voicemail | ivr | ring_group | queue | hangup, with the
    matching target column (docs/RING_GROUPS_QUEUES.md §5)."""

    failover_type: Mapped[str] = mapped_column(String(16), default="hangup")
    failover_extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL")
    )
    failover_ivr_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ivr_menus.id", ondelete="SET NULL")
    )
    failover_announcement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("announcements.id", ondelete="SET NULL", use_alter=True)
    )
    failover_conference_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conference_rooms.id", ondelete="SET NULL", use_alter=True)
    )
    failover_call_flow_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_flows.id", ondelete="SET NULL", use_alter=True)
    )
    failover_fax_inbox_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fax_inboxes.id", ondelete="SET NULL", use_alter=True)
    )
    failover_custom_context: Mapped[str | None] = mapped_column(String(64))


class RingGroup(UUIDPrimaryKey, Timestamps, TenantScoped, _Failover, Base):
    """A number that rings several extensions. Context ``veyra-rg-<slug>``."""

    __tablename__ = "ring_groups"
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        # Numbers are per organization (docs/MULTI_TENANCY.md §3).
        UniqueConstraint("organization_id", "number"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    number: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    # ``ringall`` (every member at once), ``sequential`` (in order) or, one
    # member at a time (issue #166): ``circular`` (starting after the member
    # who answered last), ``roundrobin`` (each call starts one member later),
    # ``longest_idle`` (the member whose last answer is oldest first).
    strategy: Mapped[str] = mapped_column(String(16), default="ringall")
    ring_seconds: Mapped[int] = mapped_column(Integer, default=20)
    ring_busy_members: Mapped[bool] = mapped_column(Boolean, default=False)
    # Skip a member after this many unanswered calls in a row, for
    # skip_minutes (issue #166); None: never.
    skip_after_misses: Mapped[int | None] = mapped_column(Integer)
    skip_minutes: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    # Outside numbers rung with the members (docs/CALL_FEATURES.md §3.4):
    # ["5735550100", ...]; the leg must press 1 when confirm_external is on.
    external_members: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    confirm_external: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    caller_id_prefix: Mapped[str | None] = mapped_column(String(40))
    # Phones that stop ringing log "answered elsewhere", not a missed call.
    answered_elsewhere: Mapped[bool] = mapped_column(Boolean, default=False)
    # A forward (302) a member's phone answers with is not followed.
    ignore_forwards: Mapped[bool] = mapped_column(Boolean, default=False)
    # Alert-Info header, which many phones map to a distinctive ring.
    alert_info: Mapped[str | None] = mapped_column(String(100))
    # What callers hear while the members ring: ``ring`` (ringing) or
    # ``default`` (hold music: the set below, or the built-in one).
    music: Mapped[str] = mapped_column(String(16), default="ring")
    moh_class_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("moh_classes.id", ondelete="SET NULL")
    )
    failover_ring_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ring_groups.id", ondelete="SET NULL")
    )
    # Groups and queues point at each other; this side is added after both
    # tables exist (use_alter) so the schema can be created in one pass.
    failover_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_queues.id", ondelete="SET NULL", use_alter=True)
    )
    failover_voicemail_box_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voicemail_boxes.id", ondelete="SET NULL", use_alter=True)
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class RingGroupMember(Base):
    __tablename__ = "ring_group_members"
    __table_args__ = (UniqueConstraint("group_id", "position"),)

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ring_groups.id", ondelete="CASCADE"), primary_key=True
    )
    extension_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)
    # This member's ring time in the one-at-a-time strategies (issue #166);
    # None: the group's.
    ring_seconds: Mapped[int | None] = mapped_column(Integer)


class CallQueue(UUIDPrimaryKey, Timestamps, TenantScoped, _Failover, Base):
    """A number that queues callers for agents. Queue ``veyra-<slug>`` in
    ``queues.conf``, context ``veyra-queue-<slug>``."""

    __tablename__ = "call_queues"
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        UniqueConstraint("organization_id", "number"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    number: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    strategy: Mapped[str] = mapped_column(String(16), default="ringall")
    member_timeout: Mapped[int] = mapped_column(Integer, default=15)
    retry_seconds: Mapped[int] = mapped_column(Integer, default=5)
    wrapup_seconds: Mapped[int] = mapped_column(Integer, default=0)
    # 0 = unlimited.
    max_wait_seconds: Mapped[int] = mapped_column(Integer, default=300)
    max_callers: Mapped[int] = mapped_column(Integer, default=0)
    join_when_empty: Mapped[bool] = mapped_column(Boolean, default=False)
    announce_position: Mapped[bool] = mapped_column(Boolean, default=False)
    announce_frequency: Mapped[int] = mapped_column(Integer, default=60)
    announcement_prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompts.id", ondelete="SET NULL")
    )
    periodic_prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompts.id", ondelete="SET NULL")
    )
    periodic_seconds: Mapped[int] = mapped_column(Integer, default=60)
    # ``default`` (music on hold) or ``ring``.
    music: Mapped[str] = mapped_column(String(16), default="default")
    # The hold music set for ``music=default``; none = the built-in class.
    moh_class_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("moh_classes.id", ondelete="SET NULL")
    )
    failover_ring_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ring_groups.id", ondelete="SET NULL")
    )
    failover_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_queues.id", ondelete="SET NULL")
    )
    failover_voicemail_box_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voicemail_boxes.id", ondelete="SET NULL", use_alter=True)
    )
    # Break-out menu (docs/CALL_FEATURES.md §4.10): while waiting, callers may
    # press one of this IVR menu's keys to leave the queue.
    breakout_ivr_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ivr_menus.id", ondelete="SET NULL")
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class QueueMember(Base):
    __tablename__ = "queue_members"

    queue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("call_queues.id", ondelete="CASCADE"), primary_key=True
    )
    extension_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), primary_key=True
    )
    penalty: Mapped[int] = mapped_column(Integer, default=0)
    # Dynamic agents (docs/CALL_FEATURES.md §4.9) join the queue only while
    # logged in (*45, the interface or the API); static ones are always in.
    dynamic: Mapped[bool] = mapped_column(Boolean, default=False)
    logged_in: Mapped[bool] = mapped_column(Boolean, default=False)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    state_by: Mapped[str | None] = mapped_column(String(200))
    state_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PickupGroup(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """Extensions that may answer each other's ringing calls with ``*8``;
    the slug is the Asterisk named group."""

    __tablename__ = "pickup_groups"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class PickupGroupMember(Base):
    __tablename__ = "pickup_group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pickup_groups.id", ondelete="CASCADE"), primary_key=True
    )
    extension_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), primary_key=True
    )
