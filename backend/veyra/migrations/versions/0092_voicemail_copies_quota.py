# SPDX-License-Identifier: AGPL-3.0-or-later
"""Voicemail extra recipients, quota and alternate greeting (issue #392).

Revision ID: 0092
Revises: 0091
Create Date: 2026-11-04 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0092"
down_revision: str | None = "0091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "voicemail_boxes",
        sa.Column(
            "copy_to_box_ids", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
    )
    op.add_column("voicemail_boxes", sa.Column("max_messages", sa.Integer(), nullable=True))
    op.add_column(
        "voicemail_boxes", sa.Column("max_message_seconds", sa.Integer(), nullable=True)
    )
    op.add_column(
        "voicemail_boxes",
        sa.Column("alternate_greeting", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    for column in ("alternate_greeting", "max_message_seconds", "max_messages", "copy_to_box_ids"):
        op.drop_column("voicemail_boxes", column)
