# SPDX-License-Identifier: AGPL-3.0-or-later
"""Voicemail operator (Milestone 18, docs/CALL_FEATURES.md §3.7): the extension
reached by pressing 0 while a box's greeting plays.

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-18 02:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "voicemail_boxes", sa.Column("operator_extension", sa.String(length=32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("voicemail_boxes", "operator_extension")
