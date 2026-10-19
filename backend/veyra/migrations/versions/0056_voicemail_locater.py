# SPDX-License-Identifier: AGPL-3.0-or-later
"""Voicemail locater (issue #131): pressing 1 or 2 during a box's greeting
reaches follow me or another number of the organization.

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-20 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("voicemail_boxes", sa.Column("locater_1", sa.String(length=32), nullable=True))
    op.add_column("voicemail_boxes", sa.Column("locater_2", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("voicemail_boxes", "locater_2")
    op.drop_column("voicemail_boxes", "locater_1")
