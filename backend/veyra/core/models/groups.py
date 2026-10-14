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

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
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


class RingGroup(UUIDPrimaryKey, Timestamps, TenantScoped, _Failover, Base):
    """A number that rings several extensions. Context ``veyra-rg-<slug>``."""

    __tablename__ = "ring_groups"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    # ``ringall`` (every member at once) or ``sequential`` (in order).
    strategy: Mapped[str] = mapped_column(String(16), default="ringall")
    ring_seconds: Mapped[int] = mapped_column(Integer, default=20)
    ring_busy_members: Mapped[bool] = mapped_column(Boolean, default=False)
    caller_id_prefix: Mapped[str | None] = mapped_column(String(40))
    failover_ring_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ring_groups.id", ondelete="SET NULL")
    )
    # Groups and queues point at each other; this side is added after both
    # tables exist (use_alter) so the schema can be created in one pass.
    failover_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_queues.id", ondelete="SET NULL", use_alter=True)
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


class CallQueue(UUIDPrimaryKey, Timestamps, TenantScoped, _Failover, Base):
    """A number that queues callers for agents. Queue ``veyra-<slug>`` in
    ``queues.conf``, context ``veyra-queue-<slug>``."""

    __tablename__ = "call_queues"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    number: Mapped[str] = mapped_column(String(32), unique=True)
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
    failover_ring_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ring_groups.id", ondelete="SET NULL")
    )
    failover_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_queues.id", ondelete="SET NULL")
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
