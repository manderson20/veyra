# SPDX-License-Identifier: AGPL-3.0-or-later
"""Queue auto-pause (issue #392): pause a logged-in agent after missed calls.

Revision ID: 0084
Revises: 0083
Create Date: 2026-11-01 07:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0084"
down_revision: str | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "call_queues",
        sa.Column("auto_pause_misses", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("call_queues", "auto_pause_misses")
