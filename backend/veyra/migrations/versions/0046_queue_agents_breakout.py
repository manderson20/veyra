# SPDX-License-Identifier: AGPL-3.0-or-later
"""Queue dynamic agents and the break-out menu (docs/CALL_FEATURES.md §4.9, §4.10):
queue_members gain dynamic/logged_in/paused state, call_queues a break-out IVR menu.

Revision ID: 0046
Revises: 0045
Create Date: 2026-10-18 16:39:53.168422
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("call_queues", sa.Column("breakout_ivr_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_call_queues_breakout_ivr_id_ivr_menus"),
        "call_queues",
        "ivr_menus",
        ["breakout_ivr_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "queue_members",
        sa.Column("dynamic", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "queue_members",
        sa.Column("logged_in", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "queue_members",
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("queue_members", sa.Column("state_by", sa.String(length=200), nullable=True))
    op.add_column("queue_members", sa.Column("state_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("queue_members", "state_at")
    op.drop_column("queue_members", "state_by")
    op.drop_column("queue_members", "paused")
    op.drop_column("queue_members", "logged_in")
    op.drop_column("queue_members", "dynamic")
    op.drop_constraint(
        op.f("fk_call_queues_breakout_ivr_id_ivr_menus"), "call_queues", type_="foreignkey"
    )
    op.drop_column("call_queues", "breakout_ivr_id")
