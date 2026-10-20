# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dial-by-name directory: custom entries and the operator per organization
(issue #135).

Revision ID: 0061
Revises: 0060
Create Date: 2026-10-20 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "directory_entries",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_directory_entries_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_directory_entries")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_directory_entries_organization_id_name")
        ),
    )
    op.create_index(
        op.f("ix_directory_entries_organization_id"),
        "directory_entries",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "directory_settings",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("operator_number", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_directory_settings_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("pk_directory_settings")),
    )


def downgrade() -> None:
    op.drop_table("directory_settings")
    op.drop_index(op.f("ix_directory_entries_organization_id"), table_name="directory_entries")
    op.drop_table("directory_entries")
