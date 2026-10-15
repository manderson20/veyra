# SPDX-License-Identifier: AGPL-3.0-or-later
"""Queue events from Asterisk's queue_log for queue reports (Milestone 10,
docs/REPORTING.md §5.1).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-15 02:52:41.758002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "queue_events",
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("callid", sa.String(length=64), nullable=False),
        sa.Column("queue", sa.String(length=80), nullable=False),
        sa.Column("agent", sa.String(length=128), nullable=False),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("data1", sa.String(length=64), nullable=False),
        sa.Column("data2", sa.String(length=64), nullable=False),
        sa.Column("data3", sa.String(length=64), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_queue_events")),
    )
    op.create_index(op.f("ix_queue_events_at"), "queue_events", ["at"], unique=False)
    op.create_index(op.f("ix_queue_events_callid"), "queue_events", ["callid"], unique=False)
    op.create_index("ix_queue_events_queue_at", "queue_events", ["queue", "at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_queue_events_queue_at", table_name="queue_events")
    op.drop_index(op.f("ix_queue_events_callid"), table_name="queue_events")
    op.drop_index(op.f("ix_queue_events_at"), table_name="queue_events")
    op.drop_table("queue_events")
