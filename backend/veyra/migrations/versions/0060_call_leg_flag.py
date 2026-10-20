# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call legs carry the CDR's refusal flag (issue #135): blocked callers and
class-of-service refusals get their own outcome.

Revision ID: 0060
Revises: 0059
Create Date: 2026-10-20 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "call_legs", sa.Column("flag", sa.String(length=16), server_default="", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("call_legs", "flag")
