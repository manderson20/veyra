# SPDX-License-Identifier: AGPL-3.0-or-later
"""VM Notify: call a list about a new voicemail (issue #392).

Revision ID: 0105
Revises: 0104
Create Date: 2026-11-16 00:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0105"
down_revision: str | None = "0104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "voicemail_boxes",
        sa.Column("notify_numbers", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "voicemail_boxes",
        sa.Column("notify_rounds", sa.Integer(), nullable=False, server_default="2"),
    )
    op.add_column(
        "voicemail_boxes",
        sa.Column("notify_retry_minutes", sa.Integer(), nullable=False, server_default="10"),
    )
    op.add_column(
        "voicemail_boxes",
        sa.Column("notify_urgent_only", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_table(
        "voicemail_notify_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "box_id",
            sa.Uuid(),
            sa.ForeignKey("voicemail_boxes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("numbers", postgresql.JSONB(), nullable=False),
        sa.Column("next_index", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("next_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("last_number", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_voicemail_notify_jobs_box_id", "voicemail_notify_jobs", ["box_id"])


def downgrade() -> None:
    op.drop_index("ix_voicemail_notify_jobs_box_id", table_name="voicemail_notify_jobs")
    op.drop_table("voicemail_notify_jobs")
    for column in ("notify_urgent_only", "notify_retry_minutes", "notify_rounds"):
        op.drop_column("voicemail_boxes", column)
    op.drop_column("voicemail_boxes", "notify_numbers")
