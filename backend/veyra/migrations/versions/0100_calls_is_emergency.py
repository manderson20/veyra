# SPDX-License-Identifier: AGPL-3.0-or-later
"""Calls that left through an emergency route (docs/MULTI_TENANCY_MSP.md §9).

Revision ID: 0100
Revises: 0099
Create Date: 2026-11-08 02:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0100"
down_revision: str | None = "0099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "calls",
        sa.Column("is_emergency", sa.Boolean(), nullable=False, server_default="false"),
    )
    # Earlier calls to 911 and 933 (the emergency numbers Veyra reserves).
    op.execute(
        "UPDATE calls SET is_emergency = true"
        " WHERE direction = 'outbound' AND to_number IN ('911', '933')"
    )


def downgrade() -> None:
    op.drop_column("calls", "is_emergency")
