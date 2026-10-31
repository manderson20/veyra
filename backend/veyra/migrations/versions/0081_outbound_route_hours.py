# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outbound routes (issue #142): usable only while a time condition is open.

Revision ID: 0081
Revises: 0080
Create Date: 2026-11-01 03:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0081"
down_revision: str | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbound_routes",
        sa.Column(
            "time_condition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("time_conditions.id", ondelete="SET NULL"),
        ),
    )


def downgrade() -> None:
    op.drop_column("outbound_routes", "time_condition_id")
