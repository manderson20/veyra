# SPDX-License-Identifier: AGPL-3.0-or-later
"""Menu keys of several digits, direct dial lists, keys by time (issue #392).

Revision ID: 0090
Revises: 0089
Create Date: 2026-11-02 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0090"
down_revision: str | None = "0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLOSED = {
    "closed_extension_id": "extensions",
    "closed_ivr_id": "ivr_menus",
    "closed_ring_group_id": "ring_groups",
    "closed_queue_id": "call_queues",
    "closed_voicemail_box_id": "voicemail_boxes",
    "closed_announcement_id": "announcements",
    "closed_conference_id": "conference_rooms",
    "closed_call_flow_id": "call_flows",
    "closed_fax_inbox_id": "fax_inboxes",
    "time_condition_id": "time_conditions",
}


def upgrade() -> None:
    op.add_column(
        "ivr_menus",
        sa.Column("direct_dial_mode", sa.String(8), nullable=False, server_default="all"),
    )
    op.add_column(
        "ivr_menus",
        sa.Column(
            "direct_dial_extension_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.alter_column("ivr_entries", "digit", type_=sa.String(8), existing_nullable=False)
    op.add_column("ivr_entries", sa.Column("closed_type", sa.String(16), nullable=True))
    op.add_column("ivr_entries", sa.Column("closed_custom_context", sa.String(64), nullable=True))
    for column, table in CLOSED.items():
        op.add_column("ivr_entries", sa.Column(column, sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_ivr_entries_{column}", "ivr_entries", table, [column], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    op.execute("DELETE FROM ivr_entries WHERE length(digit) > 1")
    for column in CLOSED:
        op.drop_constraint(f"fk_ivr_entries_{column}", "ivr_entries", type_="foreignkey")
        op.drop_column("ivr_entries", column)
    op.drop_column("ivr_entries", "closed_custom_context")
    op.drop_column("ivr_entries", "closed_type")
    op.alter_column("ivr_entries", "digit", type_=sa.String(1), existing_nullable=False)
    op.drop_column("ivr_menus", "direct_dial_extension_ids")
    op.drop_column("ivr_menus", "direct_dial_mode")
