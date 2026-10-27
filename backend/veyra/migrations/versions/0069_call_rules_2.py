# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rest of the Metaswitch comparison's build-next items (issue #173):
an organization-wide Do Not Disturb exception list (#170).

Revision ID: 0069
Revises: 0068
Create Date: 2026-10-27 02:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0069"
down_revision: str | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "dnd_allow",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "dnd_allow")
