# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conference options of issue #392: count announcement, silent listener PIN,
end on silence, calls placed when a conference starts, record at N members.

Revision ID: 0101
Revises: 0100
Create Date: 2026-11-15 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0101"
down_revision: str | None = "0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def _columns() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("announce_count", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("announce_count_above", sa.Integer(), nullable=True),
        sa.Column("listener_pin_ciphertext", sa.Text(), nullable=True),
        sa.Column("end_on_silence_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "auto_outcall",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("record_at_members", sa.Integer(), nullable=True),
    ]


def upgrade() -> None:
    for column in _columns():
        op.add_column("conference_rooms", column)


def downgrade() -> None:
    for column in reversed(_columns()):
        op.drop_column("conference_rooms", column.name)
