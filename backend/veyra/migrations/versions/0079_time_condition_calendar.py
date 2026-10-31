# SPDX-License-Identifier: AGPL-3.0-or-later
"""Time conditions (issue #142): closed while an event of a calendar is on.

Revision ID: 0079
Revises: 0078
Create Date: 2026-11-01 00:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0079"
down_revision: str | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "time_conditions",
        sa.Column(
            "closed_calendar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("calendars.id", ondelete="SET NULL"),
        ),
    )
    op.add_column("time_conditions", sa.Column("closed_calendar_match", sa.String(100)))


def downgrade() -> None:
    op.drop_column("time_conditions", "closed_calendar_match")
    op.drop_column("time_conditions", "closed_calendar_id")
