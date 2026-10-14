# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hold music sets (Milestone 9c, docs/PAGING_RECORDINGS.md §3.2): classes and
their tracks, the default set of an organization, the set of a queue, and
what ring group callers hear.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-15 03:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "moh_classes",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("random", sa.Boolean(), nullable=False),
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
            name=op.f("fk_moh_classes_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_moh_classes")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_moh_classes_organization_id_name")
        ),
        sa.UniqueConstraint("slug", name=op.f("uq_moh_classes_slug")),
    )
    op.create_index(
        op.f("ix_moh_classes_organization_id"), "moh_classes", ["organization_id"], unique=False
    )
    op.create_table(
        "moh_class_tracks",
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column("prompt_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["moh_classes.id"],
            name=op.f("fk_moh_class_tracks_class_id_moh_classes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["prompts.id"],
            name=op.f("fk_moh_class_tracks_prompt_id_prompts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("class_id", "prompt_id", name=op.f("pk_moh_class_tracks")),
    )
    op.add_column("call_queues", sa.Column("moh_class_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_call_queues_moh_class_id_moh_classes"),
        "call_queues",
        "moh_classes",
        ["moh_class_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("organizations", sa.Column("moh_class_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_organizations_moh_class_id_moh_classes"),
        "organizations",
        "moh_classes",
        ["moh_class_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    # Existing groups keep ringing their callers (the behaviour before this
    # revision); the server default is dropped again so the model's default rules.
    op.add_column(
        "ring_groups",
        sa.Column("music", sa.String(length=16), nullable=False, server_default="ring"),
    )
    op.alter_column("ring_groups", "music", server_default=None)
    op.add_column("ring_groups", sa.Column("moh_class_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ring_groups_moh_class_id_moh_classes"),
        "ring_groups",
        "moh_classes",
        ["moh_class_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_ring_groups_moh_class_id_moh_classes"), "ring_groups", type_="foreignkey"
    )
    op.drop_column("ring_groups", "moh_class_id")
    op.drop_column("ring_groups", "music")
    op.drop_constraint(
        op.f("fk_organizations_moh_class_id_moh_classes"), "organizations", type_="foreignkey"
    )
    op.drop_column("organizations", "moh_class_id")
    op.drop_constraint(
        op.f("fk_call_queues_moh_class_id_moh_classes"), "call_queues", type_="foreignkey"
    )
    op.drop_column("call_queues", "moh_class_id")
    op.drop_table("moh_class_tracks")
    op.drop_index(op.f("ix_moh_classes_organization_id"), table_name="moh_classes")
    op.drop_table("moh_classes")
