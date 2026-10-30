# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recording archive (docs/RECORDING_ARCHIVE.md): where each recording's copy
is, and when that copy was removed.

Revision ID: 0072
Revises: 0071
Create Date: 2026-10-30 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0072"
down_revision: str | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("call_recordings", sa.Column("archive_destination", sa.String(40)))
    op.add_column("call_recordings", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.add_column("call_recordings", sa.Column("archive_removed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("call_recordings", "archive_removed_at")
    op.drop_column("call_recordings", "archived_at")
    op.drop_column("call_recordings", "archive_destination")
