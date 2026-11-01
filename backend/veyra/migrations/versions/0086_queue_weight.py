# SPDX-License-Identifier: AGPL-3.0-or-later
"""Queue weight (issue #392).

Revision ID: 0086
Revises: 0085
Create Date: 2026-11-01 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0086"
down_revision: str | None = "0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "call_queues", sa.Column("weight", sa.Integer(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("call_queues", "weight")
