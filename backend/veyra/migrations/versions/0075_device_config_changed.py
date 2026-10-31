# SPDX-License-Identifier: AGPL-3.0-or-later
"""When a phone's own configuration last changed (issue #372): Extension Mapping
shows whether the phone has fetched since.

Revision ID: 0075
Revises: 0074
Create Date: 2026-10-31 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0075"
down_revision: str | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("config_changed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("devices", "config_changed_at")
