# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wake-up calls (issue #392).

Revision ID: 0088
Revises: 0087
Create Date: 2026-11-01 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0088"
down_revision: str | None = "0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wakeup_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "extension_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("extensions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hhmm", sa.String(4), nullable=False),
        sa.Column("daily", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("next_at", sa.DateTime(timezone=True), index=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_result", sa.String(16)),
        sa.Column("created_by", sa.String(320)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("extension_id", "hhmm"),
    )


def downgrade() -> None:
    op.drop_table("wakeup_calls")
