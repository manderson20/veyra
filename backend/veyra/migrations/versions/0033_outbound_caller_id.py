# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-extension outbound caller ID (Milestone 18, docs/CALL_FEATURES.md §3.5):
the extension's outbound number and name, the route's "force" flag and the
organization's allow list.

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-18 00:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extensions", sa.Column("outbound_caller_id_number", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "extensions", sa.Column("outbound_caller_id_name", sa.String(length=80), nullable=True)
    )
    op.add_column(
        "outbound_routes",
        sa.Column("caller_id_force", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "caller_id_allow_list",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "caller_id_allow_list")
    op.drop_column("outbound_routes", "caller_id_force")
    op.drop_column("extensions", "outbound_caller_id_name")
    op.drop_column("extensions", "outbound_caller_id_number")
