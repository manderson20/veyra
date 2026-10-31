# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caller ID rules on inbound routes (issue #142): anonymous callers or a
number send the call to another destination.

Revision ID: 0082
Revises: 0081
Create Date: 2026-11-01 04:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0082"
down_revision: str | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _target(column: str, table: str) -> sa.Column:
    return sa.Column(
        column,
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey(f"{table}.id", ondelete="SET NULL"),
    )


def upgrade() -> None:
    op.create_table(
        "inbound_caller_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "route_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inbound_routes.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("match", sa.String(16), nullable=False),
        sa.Column("number", sa.String(24)),
        sa.Column("destination_type", sa.String(16), nullable=False),
        _target("destination_extension_id", "extensions"),
        _target("destination_ivr_id", "ivr_menus"),
        _target("destination_ring_group_id", "ring_groups"),
        _target("destination_queue_id", "call_queues"),
        _target("destination_voicemail_box_id", "voicemail_boxes"),
        _target("destination_announcement_id", "announcements"),
        _target("destination_conference_id", "conference_rooms"),
        _target("destination_call_flow_id", "call_flows"),
        _target("destination_fax_inbox_id", "fax_inboxes"),
        sa.Column("destination_custom_context", sa.String(64)),
    )


def downgrade() -> None:
    op.drop_table("inbound_caller_rules")
