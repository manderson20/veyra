# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caller block list and its per-organization policy (docs/CALL_FEATURES.md §4.8).

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-18 16:25:47.216631
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "caller_blocks",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_caller_blocks_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_caller_blocks")),
        sa.UniqueConstraint(
            "organization_id", "number", name=op.f("uq_caller_blocks_organization_id_number")
        ),
    )
    op.create_index(
        op.f("ix_caller_blocks_organization_id"), "caller_blocks", ["organization_id"], unique=False
    )
    op.create_table(
        "caller_block_policies",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("block_anonymous", sa.Boolean(), nullable=False),
        sa.Column("anonymous_hits", sa.Integer(), nullable=False),
        sa.Column("destination_type", sa.String(length=16), nullable=False),
        sa.Column("destination_extension_id", sa.UUID(), nullable=True),
        sa.Column("destination_ivr_id", sa.UUID(), nullable=True),
        sa.Column("destination_ring_group_id", sa.UUID(), nullable=True),
        sa.Column("destination_queue_id", sa.UUID(), nullable=True),
        sa.Column("destination_voicemail_box_id", sa.UUID(), nullable=True),
        sa.Column("destination_announcement_id", sa.UUID(), nullable=True),
        sa.Column("destination_conference_id", sa.UUID(), nullable=True),
        sa.Column("destination_call_flow_id", sa.UUID(), nullable=True),
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
            ["destination_extension_id"],
            ["extensions.id"],
            name=op.f("fk_caller_block_policies_destination_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_caller_block_policies_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_caller_block_policies")),
    )
    op.create_index(
        op.f("ix_caller_block_policies_organization_id"),
        "caller_block_policies",
        ["organization_id"],
        unique=True,
    )
    # use_alter foreign keys, added once the table exists.
    op.create_foreign_key(
        op.f("fk_caller_block_policies_destination_announcement_id_announcements"),
        "caller_block_policies",
        "announcements",
        ["destination_announcement_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_caller_block_policies_destination_call_flow_id_call_flows"),
        "caller_block_policies",
        "call_flows",
        ["destination_call_flow_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_caller_block_policies_destination_conference_id_conference_rooms"),
        "caller_block_policies",
        "conference_rooms",
        ["destination_conference_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_caller_block_policies_destination_ivr_id_ivr_menus"),
        "caller_block_policies",
        "ivr_menus",
        ["destination_ivr_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_caller_block_policies_destination_queue_id_call_queues"),
        "caller_block_policies",
        "call_queues",
        ["destination_queue_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_caller_block_policies_destination_ring_group_id_ring_groups"),
        "caller_block_policies",
        "ring_groups",
        ["destination_ring_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_caller_block_policies_destination_voicemail_box_id_voicemail_boxes"),
        "caller_block_policies",
        "voicemail_boxes",
        ["destination_voicemail_box_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_caller_block_policies_destination_announcement_id_announcements"),
        "caller_block_policies",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_caller_block_policies_destination_call_flow_id_call_flows"),
        "caller_block_policies",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_caller_block_policies_destination_conference_id_conference_rooms"),
        "caller_block_policies",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_caller_block_policies_destination_ivr_id_ivr_menus"),
        "caller_block_policies",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_caller_block_policies_destination_queue_id_call_queues"),
        "caller_block_policies",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_caller_block_policies_destination_ring_group_id_ring_groups"),
        "caller_block_policies",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_caller_block_policies_destination_voicemail_box_id_voicemail_boxes"),
        "caller_block_policies",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_caller_block_policies_organization_id"), table_name="caller_block_policies"
    )
    op.drop_table("caller_block_policies")
    op.drop_index(op.f("ix_caller_blocks_organization_id"), table_name="caller_blocks")
    op.drop_table("caller_blocks")
