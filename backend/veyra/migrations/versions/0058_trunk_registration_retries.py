# SPDX-License-Identifier: AGPL-3.0-or-later
"""Trunk registration retries (issue #142): retry interval, 403 retry
interval and an optional give-up count.

Revision ID: 0058
Revises: 0057
Create Date: 2026-10-20 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sip_trunks",
        sa.Column("register_retry_interval", sa.Integer(), server_default="60", nullable=False),
    )
    op.add_column(
        "sip_trunks",
        sa.Column("register_forbidden_retry", sa.Integer(), server_default="600", nullable=False),
    )
    op.add_column("sip_trunks", sa.Column("register_max_retries", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("sip_trunks", "register_max_retries")
    op.drop_column("sip_trunks", "register_forbidden_retry")
    op.drop_column("sip_trunks", "register_retry_interval")
