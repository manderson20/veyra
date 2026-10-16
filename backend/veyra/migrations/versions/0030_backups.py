# SPDX-License-Identifier: AGPL-3.0-or-later
"""Backups taken by the root runner (Milestone 17, docs/PRODUCTION_HARDENING.md §2).

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-16 05:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backups",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("encrypted", sa.Boolean(), nullable=False),
        sa.Column("recipients", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("parts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("copies", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("verify", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=320), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backups")),
    )
    op.create_index(op.f("ix_backups_started_at"), "backups", ["started_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_backups_started_at"), table_name="backups")
    op.drop_table("backups")
