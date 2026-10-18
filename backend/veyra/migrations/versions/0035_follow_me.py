# SPDX-License-Identifier: AGPL-3.0-or-later
"""Find me / follow me per extension (Milestone 18, docs/CALL_FEATURES.md §3.4).

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-18 01:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "follow_me",
        sa.Column("extension_id", sa.UUID(), nullable=False),
        sa.Column("strategy", sa.String(length=16), nullable=False, server_default="ringall"),
        sa.Column("initial_ring_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirm_calls", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("caller_id_mode", sa.String(length=16), nullable=False, server_default="caller"),
        sa.Column(
            "members", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"
        ),
        sa.Column("no_answer_destination", sa.String(length=32), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=320), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(
            ["extension_id"],
            ["extensions.id"],
            name=op.f("fk_follow_me_extension_id_extensions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("extension_id", name=op.f("pk_follow_me")),
    )


def downgrade() -> None:
    op.drop_table("follow_me")
