# SPDX-License-Identifier: AGPL-3.0-or-later
"""Firewall (docs/FIREWALL_TRUST.md §2): address rules (allow and block),
automatic timed bans, the suspicious events behind them, and blocklist
feeds. System-wide: the firewall belongs to the server, not to an
organization. Settings live in ``system_settings`` under ``firewall``."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, Timestamps, UUIDPrimaryKey, utcnow


class FirewallRule(UUIDPrimaryKey, Timestamps, Base):
    """An allow or block entry. Rows with an ``origin`` other than ``manual``
    are maintained by Veyra (server addresses, SIP local networks, trunks)
    and are read-only in the interface."""

    __tablename__ = "firewall_rules"
    __table_args__ = (UniqueConstraint("action", "cidr", "origin"),)

    action: Mapped[str] = mapped_column(String(8))  # allow | block
    cidr: Mapped[str] = mapped_column(String(64))
    # Empty: every service. Otherwise sip, rtp, web, provisioning, ssh.
    services: Mapped[list[str]] = mapped_column(ARRAY(String(16)), default=list)
    comment: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(16), default="manual")
    created_by: Mapped[str | None] = mapped_column(String(200))


class FirewallBan(UUIDPrimaryKey, Base):
    __tablename__ = "firewall_bans"

    address: Mapped[str] = mapped_column(String(45), index=True)
    reason: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(16))
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    offence: Mapped[int] = mapped_column(Integer, default=1)
    banned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lifted_by: Mapped[str | None] = mapped_column(String(200))


class FirewallEvent(UUIDPrimaryKey, Base):
    __tablename__ = "firewall_events"

    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    address: Mapped[str] = mapped_column(String(45), index=True)
    source: Mapped[str] = mapped_column(String(16))  # asterisk | auth | provisioning | nginx
    kind: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(String(300))
    # Identical events of one pass are stored once with their count (a
    # scanner can produce thousands per second).
    count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Set when the address is on the allow list and would otherwise have
    # pushed it over the ban threshold (how a misconfigured LAN phone shows up).
    would_ban: Mapped[bool] = mapped_column(default=False)


class FirewallFeed(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "firewall_feeds"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(16))  # crowdsec | list
    url: Mapped[str] = mapped_column(String(500))
    # CrowdSec bouncer key, encrypted with the installation key
    # (purpose ``firewall.feed:<id>``).
    key_ciphertext: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(default=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(16))  # ok | failed
    last_error: Mapped[str | None] = mapped_column(Text)
    entry_count: Mapped[int] = mapped_column(Integer, default=0)
