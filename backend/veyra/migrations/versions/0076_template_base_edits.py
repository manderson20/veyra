# SPDX-License-Identifier: AGPL-3.0-or-later
"""Base File Edit (issue #372): a template's changes to single settings.

Revision ID: 0076
Revises: 0075
Create Date: 2026-10-31 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0076"
down_revision: str | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "device_profiles",
        sa.Column("base_edits", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("device_profiles", "base_edits")
