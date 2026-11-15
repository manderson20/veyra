# SPDX-License-Identifier: AGPL-3.0-or-later
"""Weighted trunk distribution on outbound routes (issue #392).

Revision ID: 0103
Revises: 0102
Create Date: 2026-11-15 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0103"
down_revision: str | None = "0102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbound_routes",
        sa.Column("trunk_strategy", sa.String(16), nullable=False, server_default="failover"),
    )
    op.add_column(
        "outbound_route_trunks",
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("outbound_route_trunks", "weight")
    op.drop_column("outbound_routes", "trunk_strategy")
