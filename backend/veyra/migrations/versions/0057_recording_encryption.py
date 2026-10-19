# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call recordings encrypted at rest (issue #122): each file's key, wrapped by
the installation key.

Revision ID: 0057
Revises: 0056
Create Date: 2026-10-20 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("call_recordings", sa.Column("key_ciphertext", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("call_recordings", "key_ciphertext")
