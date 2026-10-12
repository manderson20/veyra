# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration revisions: deployment mode (now / when no calls are active).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12 21:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('config_revisions', sa.Column('deploy_mode', sa.String(length=16), server_default='now', nullable=False))
    op.alter_column('config_revisions', 'deploy_mode', server_default=None)
    op.add_column('config_revisions', sa.Column('deploy_requested_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('config_revisions', 'deploy_requested_at')
    op.drop_column('config_revisions', 'deploy_mode')
