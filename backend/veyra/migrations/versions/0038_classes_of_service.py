# SPDX-License-Identifier: AGPL-3.0-or-later
"""Classes of service (Milestone 18, docs/CALL_FEATURES.md §3.8): what an
organization's phones may do, and the class an extension belongs to.

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-18 03:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "classes_of_service",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "allowed_outbound_route_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "allowed_feature_code_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("allow_external_forwards", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("allow_external_follow_me", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("allow_intercom", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("max_outbound_calls", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_classes_of_service_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classes_of_service")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_classes_of_service_organization_id")
        ),
        sa.UniqueConstraint("slug", name=op.f("uq_classes_of_service_slug")),
    )
    op.create_index(
        op.f("ix_classes_of_service_organization_id"),
        "classes_of_service",
        ["organization_id"],
        unique=False,
    )
    op.add_column("extensions", sa.Column("class_of_service_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_extensions_class_of_service_id_classes_of_service"),
        "extensions",
        "classes_of_service",
        ["class_of_service_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_extensions_class_of_service_id_classes_of_service"), "extensions", type_="foreignkey"
    )
    op.drop_column("extensions", "class_of_service_id")
    op.drop_index(op.f("ix_classes_of_service_organization_id"), table_name="classes_of_service")
    op.drop_table("classes_of_service")
