# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phones that may register an extension (issue #82, docs/EXTENSIONS.md §1):
an explicit per-extension limit beside the count derived from provisioned
phones. NULL keeps the derived behaviour.

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-18 09:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("extensions", sa.Column("max_registrations", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("extensions", "max_registrations")
