# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pickup In-call allow lists and delayed paging (Grandstream, issue #392).

Revision ID: 0102
Revises: 0101
Create Date: 2026-11-15 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0102"
down_revision: str | None = "0101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extensions",
        sa.Column(
            "pickup_incall_ids", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
    )
    op.add_column("paging_zones", sa.Column("delayed_seconds", sa.Integer(), nullable=True))
    op.add_column("pages", sa.Column("delayed_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("pages", "delayed_seconds")
    op.drop_column("paging_zones", "delayed_seconds")
    op.drop_column("extensions", "pickup_incall_ids")
