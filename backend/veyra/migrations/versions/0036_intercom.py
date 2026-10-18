# SPDX-License-Identifier: AGPL-3.0-or-later
"""Intercom and auto-answer (Milestone 18, docs/CALL_FEATURES.md §3.6): the
per-extension setting and the organization's default.

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-18 02:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extensions",
        sa.Column("intercom", sa.String(length=8), nullable=False, server_default="default"),
    )
    op.add_column(
        "organizations",
        sa.Column("intercom_default", sa.String(length=8), nullable=False, server_default="allow"),
    )


def downgrade() -> None:
    op.drop_column("organizations", "intercom_default")
    op.drop_column("extensions", "intercom")
