# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hold music from an internet stream (issue #138).

Revision ID: 0063
Revises: 0062
Create Date: 2026-10-20 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0063"
down_revision: str | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("moh_classes", sa.Column("stream_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("moh_classes", "stream_url")
