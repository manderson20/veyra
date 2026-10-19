# SPDX-License-Identifier: AGPL-3.0-or-later
"""Trusted browsers: skip the second factor on a remembered browser for a
while (issue #137).

Revision ID: 0059
Revises: 0058
Create Date: 2026-10-20 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trusted_browsers",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ip", sa.String(length=45), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_trusted_browsers_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trusted_browsers")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_trusted_browsers_token_hash")),
    )
    op.create_index(
        op.f("ix_trusted_browsers_user_id"), "trusted_browsers", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_trusted_browsers_user_id"), table_name="trusted_browsers")
    op.drop_table("trusted_browsers")
