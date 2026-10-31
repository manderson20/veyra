# SPDX-License-Identifier: AGPL-3.0-or-later
"""Queue options (issue #142): announce the expected wait, tell the agent how
long the caller waited, and a delay before the agent is connected.

Revision ID: 0080
Revises: 0079
Create Date: 2026-11-01 02:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0080"
down_revision: str | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in ("announce_holdtime", "report_holdtime"):
        op.add_column(
            "call_queues",
            sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    op.add_column(
        "call_queues", sa.Column("member_delay", sa.Integer(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("call_queues", "member_delay")
    op.drop_column("call_queues", "report_holdtime")
    op.drop_column("call_queues", "announce_holdtime")
