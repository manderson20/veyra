# SPDX-License-Identifier: AGPL-3.0-or-later
"""Classes of service (issue #142): which ring groups, queues and conference
rooms a class may call (null: all), and whether it may page.

Revision ID: 0078
Revises: 0077
Create Date: 2026-10-31 23:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0078"
down_revision: str | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("allowed_ring_group_ids", "allowed_queue_ids", "allowed_conference_ids")


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column("classes_of_service", sa.Column(column, postgresql.JSONB()))
    op.add_column(
        "classes_of_service",
        sa.Column("allow_paging", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("classes_of_service", "allow_paging")
    for column in COLUMNS:
        op.drop_column("classes_of_service", column)
