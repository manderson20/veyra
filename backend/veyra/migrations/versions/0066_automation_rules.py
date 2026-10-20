# SPDX-License-Identifier: AGPL-3.0-or-later
"""Automation rules, "when X happens, do Y" (issue #117).

Revision ID: 0066
Revises: 0065
Create Date: 2026-10-20 08:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0066"
down_revision: str | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "automation_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("trigger", sa.String(length=64), nullable=False),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("hook_token_hash", sa.String(length=64), nullable=True),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fire_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_automation_rules_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automation_rules")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_automation_rules_organization_id_name")
        ),
        sa.UniqueConstraint("hook_token_hash", name=op.f("uq_automation_rules_hook_token_hash")),
    )
    op.create_index(
        op.f("ix_automation_rules_organization_id"), "automation_rules", ["organization_id"]
    )
    op.create_table(
        "automation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["automation_rules.id"],
            name=op.f("fk_automation_runs_rule_id_automation_rules"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automation_runs")),
    )
    op.create_index(op.f("ix_automation_runs_rule_id"), "automation_runs", ["rule_id"])
    op.create_index(op.f("ix_automation_runs_created_at"), "automation_runs", ["created_at"])


def downgrade() -> None:
    op.drop_table("automation_runs")
    op.drop_table("automation_rules")
