# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extensions a class of service may call (issue #392).

Revision ID: 0089
Revises: 0088
Create Date: 2026-11-02 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0089"
down_revision: str | None = "0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "classes_of_service",
        sa.Column("allowed_extension_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("classes_of_service", "allowed_extension_ids")
