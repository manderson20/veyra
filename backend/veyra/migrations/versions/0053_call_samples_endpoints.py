# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call samples record the number of phones the engine knows, so the
dashboard can graph phones online against offline (docs/INTERFACE_REWORK.md §2).

Revision ID: 0053
Revises: 0052
Create Date: 2026-10-19 17:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("call_samples", sa.Column("endpoints", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("call_samples", "endpoints")
