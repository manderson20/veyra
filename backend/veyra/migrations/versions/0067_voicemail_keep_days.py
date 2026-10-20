# SPDX-License-Identifier: AGPL-3.0-or-later
"""Voicemail pruning: delete messages older than a box's keep_days (issue #142).

Revision ID: 0067
Revises: 0066
Create Date: 2026-10-20 09:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067"
down_revision: str | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("voicemail_boxes", sa.Column("keep_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("voicemail_boxes", "keep_days")
