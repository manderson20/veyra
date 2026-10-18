# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call-flow objects of Milestone 19 (docs/CALL_FEATURES.md §4): announcements
that play a recording and go on, and conference rooms. Engine-neutral; the
generator turns them into dialplan contexts and ``confbridge.conf``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class Announcement(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """Plays a prompt, then sends the call on (docs/CALL_FEATURES.md §4.1).
    Context ``veyra-ann-<slug>`` in the engine."""

    __tablename__ = "announcements"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompts.id", ondelete="SET NULL")
    )
    # A key pressed while the prompt plays skips it (any key) or replays it
    # (``repeat_key``, one of 0-9 * #); off: the prompt plays to the end.
    allow_skip: Mapped[bool] = mapped_column(Boolean, default=False)
    repeat_key: Mapped[str | None] = mapped_column(String(1))
    # Where the call goes afterwards: the shared destination shape
    # (docs/VOICEMAIL_IVR.md §6) plus the Milestone 19 kinds.
    destination_type: Mapped[str] = mapped_column(String(16), default="hangup")
    destination_extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL")
    )
    destination_ivr_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ivr_menus.id", ondelete="SET NULL")
    )
    destination_ring_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ring_groups.id", ondelete="SET NULL")
    )
    destination_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_queues.id", ondelete="SET NULL")
    )
    destination_voicemail_box_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voicemail_boxes.id", ondelete="SET NULL")
    )
    destination_announcement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("announcements.id", ondelete="SET NULL")
    )
    destination_conference_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conference_rooms.id", ondelete="SET NULL", use_alter=True)
    )
    destination_call_flow_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_flows.id", ondelete="SET NULL", use_alter=True)
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class CallFlow(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A day/night switch (docs/CALL_FEATURES.md §4.5): calls follow the
    normal destination, or the override destination while the switch is on.
    Toggled from a phone (``*28<index>``, BLF lit while on), the interface or
    the API; the engine keeps a copy in its store (``veyra/switch/flow``)."""

    __tablename__ = "call_flows"
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        UniqueConstraint("organization_id", "code_index"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    # The digits after the toggle prefix: *28<code_index>, 0-99.
    code_index: Mapped[int] = mapped_column(Integer)
    # Optional PIN asked before the phone toggles (installation key,
    # purpose ``call_flow.pin:<id>``).
    pin_ciphertext: Mapped[str | None] = mapped_column(Text)
    normal_type: Mapped[str] = mapped_column(String(16), default="hangup")
    override_type: Mapped[str] = mapped_column(String(16), default="hangup")
    # The switch: on = calls take the override destination.
    override: Mapped[bool] = mapped_column(Boolean, default=False)
    override_by: Mapped[str | None] = mapped_column(String(200))
    override_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    normal_extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL")
    )
    normal_ivr_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ivr_menus.id", ondelete="SET NULL", use_alter=True)
    )
    normal_ring_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ring_groups.id", ondelete="SET NULL", use_alter=True)
    )
    normal_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_queues.id", ondelete="SET NULL", use_alter=True)
    )
    normal_voicemail_box_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voicemail_boxes.id", ondelete="SET NULL", use_alter=True)
    )
    normal_announcement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("announcements.id", ondelete="SET NULL", use_alter=True)
    )
    normal_conference_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conference_rooms.id", ondelete="SET NULL", use_alter=True)
    )
    normal_call_flow_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_flows.id", ondelete="SET NULL", use_alter=True)
    )
    override_extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL")
    )
    override_ivr_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ivr_menus.id", ondelete="SET NULL", use_alter=True)
    )
    override_ring_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ring_groups.id", ondelete="SET NULL", use_alter=True)
    )
    override_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_queues.id", ondelete="SET NULL", use_alter=True)
    )
    override_voicemail_box_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voicemail_boxes.id", ondelete="SET NULL", use_alter=True)
    )
    override_announcement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("announcements.id", ondelete="SET NULL", use_alter=True)
    )
    override_conference_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conference_rooms.id", ondelete="SET NULL", use_alter=True)
    )
    override_call_flow_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_flows.id", ondelete="SET NULL", use_alter=True)
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ConferenceRoom(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A meet-me room (docs/CALL_FEATURES.md §4.3): dialled by its number or
    reached as a destination; PINs are encrypted with the installation key
    (purposes ``conference.pin:<id>:user`` and ``:admin``)."""

    __tablename__ = "conference_rooms"
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        UniqueConstraint("organization_id", "number"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    # Shares the organization's number space with extensions and groups.
    number: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    user_pin_ciphertext: Mapped[str | None] = mapped_column(Text)
    admin_pin_ciphertext: Mapped[str | None] = mapped_column(Text)
    # 0: no limit.
    max_participants: Mapped[int] = mapped_column(Integer, default=0)
    record: Mapped[bool] = mapped_column(Boolean, default=False)
    announce_join_leave: Mapped[bool] = mapped_column(Boolean, default=True)
    music_on_hold_alone: Mapped[bool] = mapped_column(Boolean, default=True)
    # Participants wait with hold music until an administrator (admin PIN) joins.
    wait_for_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    moh_class_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("moh_classes.id", ondelete="SET NULL")
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ParkingLot(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A parking lot (docs/CALL_FEATURES.md §4.7): a park extension and a range
    of slots in the organization's number space, a timeout that returns the
    call to the parker and then to a destination. ``res_parking.conf`` and the
    lot's dialplan contexts are generated."""

    __tablename__ = "parking_lots"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    # Transfer a call here to park it in the next free slot.
    park_exten: Mapped[str] = mapped_column(String(32))
    # Slots, dialled to retrieve; each has a BLF hint lit while occupied.
    slot_first: Mapped[int] = mapped_column(Integer)
    slot_last: Mapped[int] = mapped_column(Integer)
    # Seconds a call may wait before it rings the parker back.
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=45)
    # How long the parker's phone rings on the way back before the destination.
    return_ring_seconds: Mapped[int] = mapped_column(Integer, default=20)
    courtesy_tone: Mapped[bool] = mapped_column(Boolean, default=True)
    timeout_type: Mapped[str] = mapped_column(String(16), default="hangup")
    timeout_extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL")
    )
    timeout_ivr_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ivr_menus.id", ondelete="SET NULL", use_alter=True)
    )
    timeout_ring_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ring_groups.id", ondelete="SET NULL", use_alter=True)
    )
    timeout_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_queues.id", ondelete="SET NULL", use_alter=True)
    )
    timeout_voicemail_box_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voicemail_boxes.id", ondelete="SET NULL", use_alter=True)
    )
    timeout_announcement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("announcements.id", ondelete="SET NULL", use_alter=True)
    )
    timeout_conference_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conference_rooms.id", ondelete="SET NULL", use_alter=True)
    )
    timeout_call_flow_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_flows.id", ondelete="SET NULL", use_alter=True)
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class CallerBlock(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A blocked caller number of an organization (docs/CALL_FEATURES.md
    §4.8). The engine keeps a copy in its store (``veyra/blacklist/<org>``)
    that inbound routes consult at call time; the worker keeps it in step."""

    __tablename__ = "caller_blocks"
    __table_args__ = (UniqueConstraint("organization_id", "number"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    # As the carrier presents it, digits with an optional leading +.
    number: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(200))
    # api | phone | csv
    source: Mapped[str] = mapped_column(String(16), default="api")
    hits: Mapped[int] = mapped_column(Integer, default=0)
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CallerBlockPolicy(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """Per organization: whether anonymous callers are blocked and where
    blocked calls go (hang up with "no service" when no destination)."""

    __tablename__ = "caller_block_policies"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, index=True
    )
    block_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    anonymous_hits: Mapped[int] = mapped_column(Integer, default=0)
    destination_type: Mapped[str] = mapped_column(String(16), default="hangup")
    destination_extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL")
    )
    destination_ivr_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ivr_menus.id", ondelete="SET NULL", use_alter=True)
    )
    destination_ring_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ring_groups.id", ondelete="SET NULL", use_alter=True)
    )
    destination_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_queues.id", ondelete="SET NULL", use_alter=True)
    )
    destination_voicemail_box_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voicemail_boxes.id", ondelete="SET NULL", use_alter=True)
    )
    destination_announcement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("announcements.id", ondelete="SET NULL", use_alter=True)
    )
    destination_conference_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conference_rooms.id", ondelete="SET NULL", use_alter=True)
    )
    destination_call_flow_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_flows.id", ondelete="SET NULL", use_alter=True)
    )
