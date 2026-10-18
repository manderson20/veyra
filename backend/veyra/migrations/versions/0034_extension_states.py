# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extension states (Milestone 18, docs/CALL_FEATURES.md §3.2): Do Not Disturb,
forwards, follow-me and ring time per extension.

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-18 00:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extension_states",
        sa.Column("extension_id", sa.UUID(), nullable=False),
        sa.Column("dnd", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("cf_always", sa.String(length=32), nullable=True),
        sa.Column("cf_busy", sa.String(length=32), nullable=True),
        sa.Column("cf_no_answer", sa.String(length=32), nullable=True),
        sa.Column("fmfm_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("ring_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=16), nullable=False, server_default="admin"),
        sa.ForeignKeyConstraint(
            ["extension_id"],
            ["extensions.id"],
            name=op.f("fk_extension_states_extension_id_extensions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("extension_id", name=op.f("pk_extension_states")),
    )


def downgrade() -> None:
    op.drop_table("extension_states")
