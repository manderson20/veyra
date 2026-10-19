# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conference recordings are stored with the call recordings and name their
room (issue #133).

Revision ID: 0055
Revises: 0054
Create Date: 2026-10-20 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "call_recordings", sa.Column("conference_room_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_call_recordings_conference_room_id_conference_rooms"),
        "call_recordings",
        "conference_rooms",
        ["conference_room_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_call_recordings_conference_room_id"),
        "call_recordings",
        ["conference_room_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_call_recordings_conference_room_id"), table_name="call_recordings")
    op.drop_constraint(
        op.f("fk_call_recordings_conference_room_id_conference_rooms"),
        "call_recordings",
        type_="foreignkey",
    )
    op.drop_column("call_recordings", "conference_room_id")
