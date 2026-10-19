# SPDX-License-Identifier: AGPL-3.0-or-later
"""Personal contacts of the user portal (docs/USER_PORTAL.md §6).

Revision ID: 0047
Revises: 0046
Create Date: 2026-10-19 11:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_contacts",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("company", sa.String(length=100), nullable=True),
        sa.Column("numbers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("favourite", sa.Boolean(), nullable=False),
        sa.Column("speed_dial", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_contacts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_contacts")),
        sa.UniqueConstraint(
            "user_id", "speed_dial", name=op.f("uq_user_contacts_user_id_speed_dial")
        ),
    )
    op.create_index(op.f("ix_user_contacts_user_id"), "user_contacts", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_contacts_user_id"), table_name="user_contacts")
    op.drop_table("user_contacts")
