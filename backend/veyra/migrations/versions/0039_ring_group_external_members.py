# SPDX-License-Identifier: AGPL-3.0-or-later
"""External members of ring groups (Milestone 18, docs/CALL_FEATURES.md §3.4).

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-18 05:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ring_groups",
        sa.Column(
            "external_members",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "ring_groups",
        sa.Column("confirm_external", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("ring_groups", "confirm_external")
    op.drop_column("ring_groups", "external_members")
