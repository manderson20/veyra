# SPDX-License-Identifier: AGPL-3.0-or-later
"""Firewall and phone trust (Milestone 9d, docs/FIREWALL_TRUST.md): address
rules, bans, events and blocklist feeds; per device the first HTTPS fetch and
the bootstrap switch; per organization whether the HTTP bootstrap carries the
enrollment credential.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-15 01:15:23.944990
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "firewall_bans",
        sa.Column("address", sa.String(length=45), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("offence", sa.Integer(), nullable=False),
        sa.Column("banned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lifted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lifted_by", sa.String(length=200), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_firewall_bans")),
    )
    op.create_index(op.f("ix_firewall_bans_address"), "firewall_bans", ["address"], unique=False)
    op.create_index(
        op.f("ix_firewall_bans_expires_at"), "firewall_bans", ["expires_at"], unique=False
    )
    op.create_table(
        "firewall_events",
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("address", sa.String(length=45), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.String(length=300), nullable=True),
        sa.Column("count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("would_ban", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_firewall_events")),
    )
    op.create_index(
        op.f("ix_firewall_events_address"), "firewall_events", ["address"], unique=False
    )
    op.create_index(op.f("ix_firewall_events_at"), "firewall_events", ["at"], unique=False)
    op.create_table(
        "firewall_feeds",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("key_ciphertext", sa.Text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_firewall_feeds")),
        sa.UniqueConstraint("name", name=op.f("uq_firewall_feeds_name")),
    )
    op.create_table(
        "firewall_rules",
        sa.Column("action", sa.String(length=8), nullable=False),
        sa.Column("cidr", sa.String(length=64), nullable=False),
        sa.Column("services", postgresql.ARRAY(sa.String(length=16)), nullable=False),
        sa.Column("comment", sa.String(length=200), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_firewall_rules")),
        sa.UniqueConstraint(
            "action", "cidr", "origin", name=op.f("uq_firewall_rules_action_cidr_origin")
        ),
    )
    op.add_column("devices", sa.Column("https_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "devices", sa.Column("allow_bootstrap", sa.Boolean(), server_default="true", nullable=False)
    )
    op.add_column(
        "organizations",
        sa.Column(
            "bootstrap_includes_credential", sa.Boolean(), server_default="false", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "bootstrap_includes_credential")
    op.drop_column("devices", "allow_bootstrap")
    op.drop_column("devices", "https_seen_at")
    op.drop_table("firewall_rules")
    op.drop_table("firewall_feeds")
    op.drop_index(op.f("ix_firewall_events_at"), table_name="firewall_events")
    op.drop_index(op.f("ix_firewall_events_address"), table_name="firewall_events")
    op.drop_table("firewall_events")
    op.drop_index(op.f("ix_firewall_bans_expires_at"), table_name="firewall_bans")
    op.drop_index(op.f("ix_firewall_bans_address"), table_name="firewall_bans")
    op.drop_table("firewall_bans")
