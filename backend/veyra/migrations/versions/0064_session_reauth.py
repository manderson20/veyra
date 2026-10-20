# SPDX-License-Identifier: AGPL-3.0-or-later
"""Step-up authentication: when a session last entered the password again
(issue #137).

Revision ID: 0064
Revises: 0063
Create Date: 2026-10-20 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("reauth_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "reauth_at")
