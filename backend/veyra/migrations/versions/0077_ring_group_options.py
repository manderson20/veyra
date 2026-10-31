# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ring group options (issue #142): answered elsewhere, ignoring a phone's own
forwarding, and a distinctive ring.

Revision ID: 0077
Revises: 0076
Create Date: 2026-10-31 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0077"
down_revision: str | None = "0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in ("answered_elsewhere", "ignore_forwards"):
        op.add_column(
            "ring_groups",
            sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    op.add_column("ring_groups", sa.Column("alert_info", sa.String(100)))


def downgrade() -> None:
    op.drop_column("ring_groups", "alert_info")
    op.drop_column("ring_groups", "ignore_forwards")
    op.drop_column("ring_groups", "answered_elsewhere")
