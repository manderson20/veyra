# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conference room owners (issue #96): extensions whose users control the room
from My Phone.

Revision ID: 0073
Revises: 0072
Create Date: 2026-10-30 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0073"
down_revision: str | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conference_room_owners",
        sa.Column(
            "room_id",
            sa.Uuid(),
            sa.ForeignKey("conference_rooms.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "extension_id",
            sa.Uuid(),
            sa.ForeignKey("extensions.id", ondelete="CASCADE"),
            primary_key=True,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("conference_room_owners")
