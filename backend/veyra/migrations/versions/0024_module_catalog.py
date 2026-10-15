# SPDX-License-Identifier: AGPL-3.0-or-later
"""Module catalog sources (Milestone 11, docs/MODULE_CATALOG.md §3).

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-15 04:21:10.573904
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "module_catalog_sources",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("index", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("signed_by", sa.String(length=64), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_module_catalog_sources")),
        sa.UniqueConstraint("name", name=op.f("uq_module_catalog_sources_name")),
        sa.UniqueConstraint("url", name=op.f("uq_module_catalog_sources_url")),
    )


def downgrade() -> None:
    op.drop_table("module_catalog_sources")
