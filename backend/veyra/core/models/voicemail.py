# SPDX-License-Identifier: AGPL-3.0-or-later
"""Voicemail boxes, audio prompts and IVR menus (Milestone 7).

Engine-neutral: the generator turns these rows into ``voicemail.conf`` and
dialplan contexts (docs/VOICEMAIL_IVR.md). Everything belongs to one
organization; the mailbox number is the extension number.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class VoicemailBox(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """One box per extension. The PIN is encrypted with the installation key
    (purpose ``voicemail.pin:<box id>``); Asterisk needs it in clear in the
    generated ``voicemail.conf``, which is therefore a sensitive file."""

    __tablename__ = "voicemail_boxes"
    __table_args__ = (UniqueConstraint("organization_id", "number"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    # NULL for a shared inbox (docs/PAGING_RECORDINGS.md §5): then ``number``
    # (shared number space) and ``name`` identify it and members' lamps light.
    extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), unique=True
    )
    number: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(100))
    pin_ciphertext: Mapped[str] = mapped_column(Text)
    # Where messages are delivered; empty = no email.
    email: Mapped[str | None] = mapped_column(String(254))
    attach_audio: Mapped[bool] = mapped_column(Boolean, default=True)
    delete_after_email: Mapped[bool] = mapped_column(Boolean, default=False)
    # How long the phone rings before voicemail answers.
    ring_seconds: Mapped[int] = mapped_column(Integer, default=20)
    # Pressing 0 while the greeting plays reaches this extension
    # (docs/CALL_FEATURES.md §3.7); none: 0 does nothing.
    operator_extension: Mapped[str | None] = mapped_column(String(32))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class VoicemailBoxMember(Base):
    """Extensions whose message lamps follow a shared inbox."""

    __tablename__ = "voicemail_box_members"

    box_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("voicemail_boxes.id", ondelete="CASCADE"), primary_key=True
    )
    extension_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), primary_key=True
    )


class Prompt(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """An audio file played by IVR menus, stored as
    ``<prompts dir>/<organization slug>/<slug>.wav`` (8 kHz 16-bit mono)."""

    __tablename__ = "prompts"
    __table_args__ = (UniqueConstraint("organization_id", "slug"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    # File name part; derived from the name when created and stable afterwards.
    slug: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    # ``upload`` or ``recording`` (adopted from a phone recording).
    source: Mapped[str] = mapped_column(String(16), default="upload")
    duration_seconds: Mapped[float] = mapped_column(Float, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    # Audio library (docs/PAGING_RECORDINGS.md §3): what the recording is for
    # (prompt | bell | announcement | greeting | music) and where it came from.
    kind: Mapped[str] = mapped_column(String(16), default="prompt")
    license: Mapped[str | None] = mapped_column(String(100))
    credit: Mapped[str | None] = mapped_column(String(200))


class IvrMenu(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """An auto-attendant menu: a prompt, a key map, timeout and invalid
    handling. Context ``veyra-ivr-<slug>`` in the engine."""

    __tablename__ = "ivr_menus"
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
    invalid_prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompts.id", ondelete="SET NULL")
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=5)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    allow_direct_dial: Mapped[bool] = mapped_column(Boolean, default=True)
    # Where callers go after max_retries timeouts / invalid keys:
    # extension | voicemail | ivr | ring_group | queue | hangup, with the matching
    # target column.
    timeout_type: Mapped[str] = mapped_column(String(16), default="hangup")
    timeout_extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL")
    )
    timeout_ivr_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ivr_menus.id", ondelete="SET NULL")
    )
    # Menus and groups point at each other; these constraints are added after
    # both tables exist (use_alter) so the schema can be created in one pass.
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
    invalid_type: Mapped[str] = mapped_column(String(16), default="hangup")
    invalid_extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL")
    )
    invalid_ivr_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ivr_menus.id", ondelete="SET NULL")
    )
    invalid_ring_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ring_groups.id", ondelete="SET NULL", use_alter=True)
    )
    invalid_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_queues.id", ondelete="SET NULL", use_alter=True)
    )
    invalid_voicemail_box_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voicemail_boxes.id", ondelete="SET NULL", use_alter=True)
    )
    invalid_announcement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("announcements.id", ondelete="SET NULL", use_alter=True)
    )
    invalid_conference_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conference_rooms.id", ondelete="SET NULL", use_alter=True)
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class IvrEntry(Base):
    """One key of a menu (``0``-``9``, ``*``, ``#``) and its destination."""

    __tablename__ = "ivr_entries"

    menu_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ivr_menus.id", ondelete="CASCADE"), primary_key=True
    )
    digit: Mapped[str] = mapped_column(String(1), primary_key=True)
    destination_type: Mapped[str] = mapped_column(String(16))
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
        ForeignKey("voicemail_boxes.id", ondelete="SET NULL", use_alter=True)
    )
    destination_announcement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("announcements.id", ondelete="SET NULL", use_alter=True)
    )
    destination_conference_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conference_rooms.id", ondelete="SET NULL", use_alter=True)
    )


class MohClass(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A hold music set (docs/PAGING_RECORDINGS.md §3.2): an ordered list of
    library recordings played to held and queued callers as the engine's
    class ``veyra-<slug>`` from ``<moh dir>/<slug>/``."""

    __tablename__ = "moh_classes"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    # Engine class name part; unique across the installation like IVR slugs.
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    # Play the tracks in a random order instead of the listed one.
    random: Mapped[bool] = mapped_column(Boolean, default=False)


class MohClassTrack(Base):
    """A recording of a hold music set, in playing order."""

    __tablename__ = "moh_class_tracks"

    class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("moh_classes.id", ondelete="CASCADE"), primary_key=True
    )
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompts.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)
