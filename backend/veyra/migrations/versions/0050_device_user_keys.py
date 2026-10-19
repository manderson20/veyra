# SPDX-License-Identifier: AGPL-3.0-or-later
"""Devices: the user's own keys in the slots a profile leaves open
(docs/USER_PORTAL.md §8).

Revision ID: 0050
Revises: 0049
Create Date: 2026-10-19 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "devices", sa.Column("user_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("devices", "user_keys")
