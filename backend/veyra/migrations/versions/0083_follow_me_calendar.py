# SPDX-License-Identifier: AGPL-3.0-or-later
"""Follow-me linked to a calendar (issue #392): on while an event is on.

Revision ID: 0083
Revises: 0082
Create Date: 2026-11-01 06:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0083"
down_revision: str | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "follow_me",
        sa.Column(
            "calendar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("calendars.id", ondelete="SET NULL"),
        ),
    )
    op.add_column("follow_me", sa.Column("calendar_match", sa.String(100)))
    op.add_column("follow_me", sa.Column("calendar_state", sa.String(16)))


def downgrade() -> None:
    op.drop_column("follow_me", "calendar_state")
    op.drop_column("follow_me", "calendar_match")
    op.drop_column("follow_me", "calendar_id")
