# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outside line access (issue #392).

Revision ID: 0087
Revises: 0086
Create Date: 2026-11-01 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0087"
down_revision: str | None = "0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "disa_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(40), nullable=False, unique=True),
        sa.Column("pin_ciphertext", sa.Text(), nullable=False),
        sa.Column(
            "class_of_service_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classes_of_service.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("caller_id_number", sa.String(32), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("organization_id", "name"),
    )


def downgrade() -> None:
    op.drop_table("disa_lines")
