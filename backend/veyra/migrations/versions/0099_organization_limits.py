# SPDX-License-Identifier: AGPL-3.0-or-later
"""Limits per organization (docs/MULTI_TENANCY_MSP.md §8).

Revision ID: 0099
Revises: 0098
Create Date: 2026-11-08 01:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0099"
down_revision: str | None = "0098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization_limits",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("max_outside_calls", sa.Integer(), nullable=True),
        sa.Column("max_extensions", sa.Integer(), nullable=True),
        sa.Column("max_devices", sa.Integer(), nullable=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(320), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("organization_limits")
