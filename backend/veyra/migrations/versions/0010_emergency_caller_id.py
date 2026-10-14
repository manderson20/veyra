# SPDX-License-Identifier: AGPL-3.0-or-later
"""Emergency caller ID per extension (Milestone 9, docs/TRUNKS_ROUTING.md §7).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-14 15:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extensions", sa.Column("emergency_caller_id_number", sa.String(length=32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("extensions", "emergency_caller_id_number")
