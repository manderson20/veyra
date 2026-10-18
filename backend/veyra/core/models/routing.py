# SPDX-License-Identifier: AGPL-3.0-or-later
"""SIP trunks, inbound and outbound routing, time conditions (Milestone 6).

Engine-neutral: the generator turns these rows into PJSIP sections and
dialplan contexts (docs/TRUNKS_ROUTING.md). Trunks and outbound routes are
installation-wide; inbound routes and time conditions belong to one
organization.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey


class SipTrunk(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "sip_trunks"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    # Section and context name part (``trunk-<slug>``); derived from the name
    # when the trunk is created and stable afterwards.
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # ``registration`` (we register to the carrier) or ``ip`` (address trust).
    auth_mode: Mapped[str] = mapped_column(String(16))
    host: Mapped[str] = mapped_column(String(253))
    port: Mapped[int] = mapped_column(Integer, default=5060)
    transport: Mapped[str] = mapped_column(String(8), default="udp")
    username: Mapped[str | None] = mapped_column(String(80))
    auth_username: Mapped[str | None] = mapped_column(String(80))
    # Encrypted with the installation key; purpose ``trunk.sip_secret:<id>``.
    password_ciphertext: Mapped[str | None] = mapped_column(Text)
    from_user: Mapped[str | None] = mapped_column(String(80))
    from_domain: Mapped[str | None] = mapped_column(String(253))
    outbound_proxy: Mapped[str | None] = mapped_column(String(260))
    # Addresses or CIDRs whose calls are recognised as this trunk (list of str).
    match_addresses: Mapped[list[str]] = mapped_column(JSONB, default=list)
    codecs: Mapped[list[str] | None] = mapped_column(JSONB)
    max_channels: Mapped[int | None] = mapped_column(Integer)
    default_caller_id: Mapped[str | None] = mapped_column(String(32))
    caller_id_header: Mapped[str] = mapped_column(String(8), default="pai")
    dtmf_mode: Mapped[str] = mapped_column(String(8), default="rfc4733")
    qualify_frequency: Mapped[int] = mapped_column(Integer, default=60)
    register_expiry: Mapped[int] = mapped_column(Integer, default=3600)


class TimeCondition(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    __tablename__ = "time_conditions"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(64))
    # [{"days": ["mon", ...], "start": "HH:MM", "end": "HH:MM"}, ...]
    ranges: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # ["MM-DD", ...], closed all day, repeating yearly.
    holidays: Mapped[list[str]] = mapped_column(JSONB, default=list)


class InboundRoute(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    __tablename__ = "inbound_routes"
    # One route per DID per trunk restriction; NULL (every trunk) counts as a value.
    __table_args__ = (
        UniqueConstraint("trunk_id", "did_canonical", postgresql_nulls_not_distinct=True),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    # The number as the carrier sends it, or ``any`` for the catch-all.
    did: Mapped[str] = mapped_column(String(24))
    # Ten digits for North American numbers however they were entered; the
    # uniqueness key together with the trunk restriction.
    did_canonical: Mapped[str] = mapped_column(String(24))
    trunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sip_trunks.id", ondelete="RESTRICT")
    )
    description: Mapped[str | None] = mapped_column(Text)
    # extension | voicemail (of the extension) | ivr | ring_group | queue, with the
    # matching target column (docs/VOICEMAIL_IVR.md §6, RING_GROUPS_QUEUES.md §5).
    # A missing target is flagged, not fatal.
    destination_type: Mapped[str] = mapped_column(String(16), default="extension")
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
    time_condition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("time_conditions.id", ondelete="RESTRICT")
    )
    after_hours_type: Mapped[str] = mapped_column(String(16), default="extension")
    after_hours_extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL")
    )
    after_hours_ivr_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ivr_menus.id", ondelete="SET NULL")
    )
    after_hours_ring_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ring_groups.id", ondelete="SET NULL")
    )
    after_hours_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_queues.id", ondelete="SET NULL")
    )
    after_hours_voicemail_box_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voicemail_boxes.id", ondelete="SET NULL", use_alter=True)
    )
    caller_id_prefix: Mapped[str | None] = mapped_column(String(40))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class OutboundRoute(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "outbound_routes"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_emergency: Mapped[bool] = mapped_column(Boolean, default=False)
    # An emergency route bound to one site (docs/PRODUCTION_HARDENING.md §6);
    # NULL serves every site.
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # [{"prefix": "9", "match": "NXXNXXXXXX", "prepend": "1"}, ...]
    patterns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    caller_id_number: Mapped[str | None] = mapped_column(String(32))
    # The route's caller ID replaces the extension's outbound caller ID too
    # (docs/CALL_FEATURES.md §3.5); otherwise the extension's wins.
    caller_id_force: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Only this organization's phones use the route; none: every organization
    # (docs/MULTI_TENANCY.md §4).
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )


class OutboundRouteTrunk(Base):
    """Ordered trunks of an outbound route (failover order = position)."""

    __tablename__ = "outbound_route_trunks"
    __table_args__ = (UniqueConstraint("route_id", "position"),)

    route_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outbound_routes.id", ondelete="CASCADE"), primary_key=True
    )
    trunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sip_trunks.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)
