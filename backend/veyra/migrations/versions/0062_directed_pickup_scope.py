# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who may answer with **<extension>: the organization or pickup groups
(issue #138).

Revision ID: 0062
Revises: 0061
Create Date: 2026-10-20 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "directed_pickup", sa.String(length=16), server_default="organization", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "directed_pickup")
