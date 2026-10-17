# SPDX-License-Identifier: AGPL-3.0-or-later
"""Packet captures taken by the root unit (Milestone 18, docs/CALL_FEATURES.md §2.2).

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-17 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "captures",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("filter", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("size_limit_mb", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("packets", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=320), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_captures")),
    )
    op.create_index(op.f("ix_captures_started_at"), "captures", ["started_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_captures_started_at"), table_name="captures")
    op.drop_table("captures")
