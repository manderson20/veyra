# SPDX-License-Identifier: AGPL-3.0-or-later
"""Monitoring alerts (Milestone 10, docs/REPORTING.md §6.1): rules and
occurrences.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-15 03:00:13.058743
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("delay_minutes", sa.Integer(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=True),
        sa.Column("recipients", postgresql.ARRAY(sa.String(length=254)), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_alert_rules")),
    )
    op.create_table(
        "alerts",
        sa.Column("rule", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notify_error", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
    )
    op.create_index(op.f("ix_alerts_cleared_at"), "alerts", ["cleared_at"], unique=False)
    op.create_index(
        "ix_alerts_rule_subject_state", "alerts", ["rule", "subject", "state"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_rule_subject_state", table_name="alerts")
    op.drop_index(op.f("ix_alerts_cleared_at"), table_name="alerts")
    op.drop_table("alerts")
    op.drop_table("alert_rules")
