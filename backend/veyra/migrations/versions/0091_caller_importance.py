# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caller importance in queues, per inbound route and menu (issue #392).

Revision ID: 0091
Revises: 0090
Create Date: 2026-11-02 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0091"
down_revision: str | None = "0090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("inbound_routes", "ivr_menus"):
        op.add_column(
            table, sa.Column("queue_priority", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    for table in ("inbound_routes", "ivr_menus"):
        op.drop_column(table, "queue_priority")
