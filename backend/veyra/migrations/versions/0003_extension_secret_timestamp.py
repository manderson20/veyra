# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extensions: when the SIP secret was last set or rotated.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-12 19:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('extensions', sa.Column('sip_secret_changed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('extensions', 'sip_secret_changed_at')
