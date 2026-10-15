# SPDX-License-Identifier: AGPL-3.0-or-later
"""Download, approval and installation of updates (Milestone 12, docs/SOFTWARE_UPDATES.md).

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-15 05:19:41.189350
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "available_updates", sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "available_updates", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "available_updates", sa.Column("approved_by", sa.String(length=320), nullable=True)
    )
    op.add_column(
        "available_updates", sa.Column("install_when", sa.String(length=16), nullable=True)
    )
    op.add_column(
        "available_updates",
        sa.Column("install_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "available_updates",
        sa.Column("install_finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("available_updates", sa.Column("error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("available_updates", "error")
    op.drop_column("available_updates", "install_finished_at")
    op.drop_column("available_updates", "install_started_at")
    op.drop_column("available_updates", "install_when")
    op.drop_column("available_updates", "approved_by")
    op.drop_column("available_updates", "approved_at")
    op.drop_column("available_updates", "downloaded_at")
