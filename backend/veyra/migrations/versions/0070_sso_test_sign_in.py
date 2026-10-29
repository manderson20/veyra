# SPDX-License-Identifier: AGPL-3.0-or-later
"""A test sign-in from the single sign-on setup wizard keeps its result on
the sign-in attempt (docs/INTEGRATIONS.md §1.8).

Revision ID: 0070
Revises: 0069
Create Date: 2026-10-29 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sso_requests",
        sa.Column("test_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sso_requests", "test_result")
