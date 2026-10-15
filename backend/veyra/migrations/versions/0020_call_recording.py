# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call recording (Milestone 10, docs/REPORTING.md §4): recording policies
and recordings.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-15 02:41:01.961930
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recording_policies",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("inbound", sa.Boolean(), nullable=False),
        sa.Column("outbound", sa.Boolean(), nullable=False),
        sa.Column("internal", sa.Boolean(), nullable=False),
        sa.Column("scope", sa.String(length=10), nullable=False),
        sa.Column("extension_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("ring_group_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("queue_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("inbound_route_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("announcement_prompt_id", sa.UUID(), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["announcement_prompt_id"],
            ["prompts.id"],
            name=op.f("fk_recording_policies_announcement_prompt_id_prompts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_recording_policies_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recording_policies")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_recording_policies_organization_id_name")
        ),
    )
    op.create_index(
        op.f("ix_recording_policies_organization_id"),
        "recording_policies",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "call_recordings",
        sa.Column("ref", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("call_id", sa.UUID(), nullable=True),
        sa.Column("policy_id", sa.UUID(), nullable=True),
        sa.Column("path", sa.String(length=300), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delete_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("held", sa.Boolean(), nullable=False),
        sa.Column("held_by", sa.String(length=200), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(length=200), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name=op.f("fk_call_recordings_call_id_calls"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_call_recordings_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["recording_policies.id"],
            name=op.f("fk_call_recordings_policy_id_recording_policies"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_recordings")),
        sa.UniqueConstraint("ref", name=op.f("uq_call_recordings_ref")),
    )
    op.create_index(
        op.f("ix_call_recordings_call_id"), "call_recordings", ["call_id"], unique=False
    )
    op.create_index(
        op.f("ix_call_recordings_delete_after"), "call_recordings", ["delete_after"], unique=False
    )
    op.create_index(
        op.f("ix_call_recordings_organization_id"),
        "call_recordings",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_call_recordings_organization_id"), table_name="call_recordings")
    op.drop_index(op.f("ix_call_recordings_delete_after"), table_name="call_recordings")
    op.drop_index(op.f("ix_call_recordings_call_id"), table_name="call_recordings")
    op.drop_table("call_recordings")
    op.drop_index(op.f("ix_recording_policies_organization_id"), table_name="recording_policies")
    op.drop_table("recording_policies")
