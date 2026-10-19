# SPDX-License-Identifier: AGPL-3.0-or-later
"""Presence on extension states (docs/USER_PORTAL.md §7).

Revision ID: 0049
Revises: 0048
Create Date: 2026-10-19 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extension_states",
        sa.Column(
            "presence", sa.String(length=16), server_default="available", nullable=False
        ),
    )
    op.add_column(
        "extension_states", sa.Column("presence_message", sa.String(length=60), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("extension_states", "presence_message")
    op.drop_column("extension_states", "presence")
