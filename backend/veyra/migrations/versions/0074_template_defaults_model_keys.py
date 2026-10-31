# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone templates (issue #372): the default template of a brand and line keys
per model.

Revision ID: 0074
Revises: 0073
Create Date: 2026-10-31 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0074"
down_revision: str | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "device_profiles",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "device_profiles",
        sa.Column("model_keys", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("device_profiles", "model_keys")
    op.drop_column("device_profiles", "is_default")
