# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provisioning variables (docs/PROVISIONING_BREADTH.md §2): named values at
installation, organization, site or profile scope that templates and key
lists reference.

Revision ID: 0054
Revises: 0053
Create Date: 2026-10-19 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provisioning_variables",
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.UUID(), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("sensitive", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_provisioning_variables_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provisioning_variables")),
        sa.UniqueConstraint(
            "scope", "scope_id", "name", name=op.f("uq_provisioning_variables_scope_scope_id_name")
        ),
    )
    op.create_index(
        op.f("ix_provisioning_variables_organization_id"),
        "provisioning_variables",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_provisioning_variables_organization_id"), table_name="provisioning_variables"
    )
    op.drop_table("provisioning_variables")
