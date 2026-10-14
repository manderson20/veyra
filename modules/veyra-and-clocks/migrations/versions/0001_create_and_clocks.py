# SPDX-License-Identifier: AGPL-3.0-or-later
"""Clocks, messages, bell messages and the delivery setup.

Revision ID: and_clocks_0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "and_clocks_0001"
down_revision = None
branch_labels = None
depends_on = None


def _org() -> sa.Column:
    return sa.Column(
        "organization_id",
        sa.Uuid(),
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "mod_and_clocks_clock",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _org(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("group_name", sa.String(100), nullable=False, server_default=""),
        sa.Column("model", sa.String(100), nullable=False, server_default=""),
        sa.Column("reachability", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        _now("created_at"),
        sa.UniqueConstraint("organization_id", "name", name="uq_mod_and_clocks_clock_name"),
    )
    op.create_index(
        "ix_mod_and_clocks_clock_organization_id", "mod_and_clocks_clock", ["organization_id"]
    )
    op.create_table(
        "mod_and_clocks_message",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _org(),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("send_to", sa.String(100), nullable=False, server_default=""),
        sa.Column("color", sa.String(16), nullable=False, server_default="default"),
        sa.Column("seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("flashers", sa.String(8), nullable=False, server_default="off"),
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="scheduled"),
        sa.Column("result", sa.String(300), nullable=False, server_default=""),
        sa.Column("outcomes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("source", sa.String(16), nullable=False, server_default="user"),
        sa.Column("created_by", sa.String(320), nullable=False),
        _now("created_at"),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_mod_and_clocks_message_organization_id", "mod_and_clocks_message", ["organization_id"]
    )
    op.create_index("ix_mod_and_clocks_message_send_at", "mod_and_clocks_message", ["send_at"])
    op.create_table(
        "mod_and_clocks_bell_message",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _org(),
        sa.Column("bell_schedule", sa.String(100), nullable=False),
        sa.Column("text", sa.String(200), nullable=False, server_default="{summary}"),
        sa.Column("send_to", sa.String(100), nullable=False, server_default=""),
        sa.Column("color", sa.String(16), nullable=False, server_default="default"),
        sa.Column("seconds", sa.Integer(), nullable=False, server_default="60"),
        _now("created_at"),
    )
    op.create_index(
        "ix_mod_and_clocks_bell_message_organization_id",
        "mod_and_clocks_bell_message",
        ["organization_id"],
    )
    op.create_table(
        "mod_and_clocks_delivery",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("scheme", sa.String(8), nullable=False, server_default="http"),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("content_type", sa.String(8), nullable=False, server_default="form"),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("auth", sa.String(8), nullable=False, server_default="none"),
        sa.Column("username", sa.String(100), nullable=False, server_default=""),
        sa.Column("password_ciphertext", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by", sa.String(320), nullable=False),
        _now("updated_at"),
    )


def downgrade() -> None:
    op.drop_table("mod_and_clocks_delivery")
    op.drop_table("mod_and_clocks_bell_message")
    op.drop_table("mod_and_clocks_message")
    op.drop_table("mod_and_clocks_clock")
