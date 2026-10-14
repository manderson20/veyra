# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

clocks = Table(
    "mod_and_clocks_clock",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False, index=True),
    Column("name", String(100), nullable=False),
    Column("address", String(255), nullable=False),
    Column("group_name", String(100), nullable=False, server_default=""),
    Column("model", String(100), nullable=False, server_default=""),
    Column("reachability", String(16), nullable=False, server_default="unknown"),
    Column("last_checked_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("organization_id", "name", name="uq_mod_and_clocks_clock_name"),
)

messages = Table(
    "mod_and_clocks_message",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False, index=True),
    Column("text", Text, nullable=False),
    Column("send_to", String(100), nullable=False, server_default=""),
    Column("color", String(16), nullable=False, server_default="default"),
    Column("seconds", Integer, nullable=False, server_default="60"),
    Column("priority", String(16), nullable=False, server_default="normal"),
    Column("flashers", String(8), nullable=False, server_default="off"),
    Column("send_at", DateTime(timezone=True), nullable=False, index=True),
    # scheduled | sending | sent | partial | failed | not_sent
    Column("status", String(16), nullable=False, server_default="scheduled"),
    Column("result", String(300), nullable=False, server_default=""),
    Column("outcomes", JSONB, nullable=False, server_default="[]"),
    Column("source", String(16), nullable=False, server_default="user"),  # user | bell
    Column("created_by", String(320), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("sent_at", DateTime(timezone=True)),
)

bell_messages = Table(
    "mod_and_clocks_bell_message",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False, index=True),
    Column("bell_schedule", String(100), nullable=False),
    Column("text", String(200), nullable=False, server_default="{summary}"),
    Column("send_to", String(100), nullable=False, server_default=""),
    Column("color", String(16), nullable=False, server_default="default"),
    Column("seconds", Integer, nullable=False, server_default="60"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

delivery = Table(
    "mod_and_clocks_delivery",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False, unique=True),
    Column("method", String(8), nullable=False),
    Column("scheme", String(8), nullable=False, server_default="http"),
    Column("path", String(500), nullable=False),
    Column("content_type", String(8), nullable=False, server_default="form"),
    Column("body", Text, nullable=False, server_default=""),
    Column("auth", String(8), nullable=False, server_default="none"),
    Column("username", String(100), nullable=False, server_default=""),
    Column("password_ciphertext", Text, nullable=False, server_default=""),
    Column("updated_by", String(320), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
