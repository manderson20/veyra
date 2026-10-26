# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forward when unreachable, call waiting off, anonymous call rejection, Do
Not Disturb exceptions (issues #163, #165, #170), the trunk channels kept
for emergency calls (issue #171), the voicemail extended absence (#169),
hotline phones (#168), per-member ring times in ring groups (#166) and the
supervisor flags of a class of service (#167).

Revision ID: 0068
Revises: 0067
Create Date: 2026-10-26 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("extension_states", sa.Column("cf_unavailable", sa.String(32), nullable=True))
    op.add_column(
        "extension_states",
        sa.Column("call_waiting_off", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "extension_states",
        sa.Column("anonymous_reject", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "extension_states",
        sa.Column("dnd_allow", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "sip_trunks",
        sa.Column(
            "emergency_reserved_channels", sa.Integer(), nullable=False, server_default="1"
        ),
    )


    op.add_column(
        "voicemail_boxes",
        sa.Column("absence_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("voicemail_boxes", sa.Column("absence_starts_on", sa.Date(), nullable=True))
    op.add_column("voicemail_boxes", sa.Column("absence_ends_on", sa.Date(), nullable=True))
    op.add_column(
        "voicemail_boxes",
        sa.Column("absence_refuse", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "voicemail_boxes",
        sa.Column("absence_state", sa.String(8), nullable=False, server_default="off"),
    )

    op.add_column("extensions", sa.Column("hotline_target", sa.String(32), nullable=True))
    op.add_column(
        "extensions",
        sa.Column("hotline_delay", sa.Integer(), nullable=False, server_default="0"),
    )

    op.add_column("ring_group_members", sa.Column("ring_seconds", sa.Integer(), nullable=True))

    op.add_column(
        "classes_of_service",
        sa.Column("allow_monitor", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "classes_of_service",
        sa.Column("monitor_protected", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("classes_of_service", "monitor_protected")
    op.drop_column("classes_of_service", "allow_monitor")
    op.drop_column("ring_group_members", "ring_seconds")
    op.drop_column("extensions", "hotline_delay")
    op.drop_column("extensions", "hotline_target")
    for col in (
        "absence_state",
        "absence_refuse",
        "absence_ends_on",
        "absence_starts_on",
        "absence_enabled",
    ):
        op.drop_column("voicemail_boxes", col)
    op.drop_column("sip_trunks", "emergency_reserved_channels")
    for col in ("dnd_allow", "anonymous_reject", "call_waiting_off", "cf_unavailable"):
        op.drop_column("extension_states", col)
