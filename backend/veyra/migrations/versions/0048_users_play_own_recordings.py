# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizations: whether users may play recordings of their own calls from
My Phone (docs/USER_PORTAL.md §5).

Revision ID: 0048
Revises: 0047
Create Date: 2026-10-19 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "users_play_own_recordings",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "users_play_own_recordings")
