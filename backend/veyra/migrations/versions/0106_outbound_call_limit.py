# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outbound Call Limit per phone and period on classes of service (issue #392).

Revision ID: 0106
Revises: 0105
Create Date: 2026-11-16 01:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0106"
down_revision: str | None = "0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("classes_of_service", sa.Column("calls_per_period", sa.Integer(), nullable=True))
    op.add_column(
        "classes_of_service",
        sa.Column("call_period", sa.String(8), nullable=False, server_default="day"),
    )


def downgrade() -> None:
    op.drop_column("classes_of_service", "call_period")
    op.drop_column("classes_of_service", "calls_per_period")
