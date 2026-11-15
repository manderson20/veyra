# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extension Routing: the extensions allowed on an outbound route (issue #392).

Revision ID: 0107
Revises: 0106
Create Date: 2026-11-16 02:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0107"
down_revision: str | None = "0106"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbound_routes", sa.Column("allowed_extension_ids", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("outbound_routes", "allowed_extension_ids")
