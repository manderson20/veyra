# SPDX-License-Identifier: AGPL-3.0-or-later
"""Queue pause reasons (issue #392).

Revision ID: 0085
Revises: 0084
Create Date: 2026-11-01 08:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0085"
down_revision: str | None = "0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "queue_pause_reasons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("code", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("organization_id", "code"),
    )
    op.add_column(
        "queue_members",
        sa.Column(
            "pause_reason_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("queue_pause_reasons.id", ondelete="SET NULL"),
        ),
    )


def downgrade() -> None:
    op.drop_column("queue_members", "pause_reason_id")
    op.drop_table("queue_pause_reasons")
