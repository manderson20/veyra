# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forward when unreachable, call waiting off, anonymous call rejection, Do
Not Disturb exceptions (issues #163, #165, #170) and the trunk channels kept
for emergency calls (issue #171).

Revision ID: 0068
Revises: 0067
Create Date: 2026-10-26 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("extension_states", sa.Column("cf_unavailable", sa.String(32), nullable=True))
    op.add_column(
        "extension_states",
        sa.Column("call_waiting_off", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "extension_states",
        sa.Column("anonymous_reject", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "extension_states",
        sa.Column("dnd_allow", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "sip_trunks",
        sa.Column(
            "emergency_reserved_channels", sa.Integer(), nullable=False, server_default="1"
        ),
    )


def downgrade() -> None:
    op.drop_column("sip_trunks", "emergency_reserved_channels")
    for col in ("dnd_allow", "anonymous_reject", "call_waiting_off", "cf_unavailable"):
        op.drop_column("extension_states", col)
