# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caller name lookup on inbound routes (issue #392).

Revision ID: 0104
Revises: 0103
Create Date: 2026-11-15 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0104"
down_revision: str | None = "0103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "inbound_routes",
        sa.Column("name_lookup", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("inbound_routes", "name_lookup")
