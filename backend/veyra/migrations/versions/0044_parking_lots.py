# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parking lots (docs/CALL_FEATURES.md §4.7).

Revision ID: 0044
Revises: 0043
Create Date: 2026-10-18 16:13:21.100847
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "parking_lots",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("park_exten", sa.String(length=32), nullable=False),
        sa.Column("slot_first", sa.Integer(), nullable=False),
        sa.Column("slot_last", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("return_ring_seconds", sa.Integer(), nullable=False),
        sa.Column("courtesy_tone", sa.Boolean(), nullable=False),
        sa.Column("timeout_type", sa.String(length=16), nullable=False),
        sa.Column("timeout_extension_id", sa.UUID(), nullable=True),
        sa.Column("timeout_ivr_id", sa.UUID(), nullable=True),
        sa.Column("timeout_ring_group_id", sa.UUID(), nullable=True),
        sa.Column("timeout_queue_id", sa.UUID(), nullable=True),
        sa.Column("timeout_voicemail_box_id", sa.UUID(), nullable=True),
        sa.Column("timeout_announcement_id", sa.UUID(), nullable=True),
        sa.Column("timeout_conference_id", sa.UUID(), nullable=True),
        sa.Column("timeout_call_flow_id", sa.UUID(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
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
            name=op.f("fk_parking_lots_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["timeout_extension_id"],
            ["extensions.id"],
            name=op.f("fk_parking_lots_timeout_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parking_lots")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_parking_lots_organization_id_name")
        ),
        sa.UniqueConstraint("slug", name=op.f("uq_parking_lots_slug")),
    )
    op.create_index(
        op.f("ix_parking_lots_organization_id"), "parking_lots", ["organization_id"], unique=False
    )
    # use_alter foreign keys, added once the table exists.
    op.create_foreign_key(
        op.f("fk_parking_lots_timeout_announcement_id_announcements"),
        "parking_lots",
        "announcements",
        ["timeout_announcement_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_parking_lots_timeout_call_flow_id_call_flows"),
        "parking_lots",
        "call_flows",
        ["timeout_call_flow_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_parking_lots_timeout_conference_id_conference_rooms"),
        "parking_lots",
        "conference_rooms",
        ["timeout_conference_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_parking_lots_timeout_ivr_id_ivr_menus"),
        "parking_lots",
        "ivr_menus",
        ["timeout_ivr_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_parking_lots_timeout_queue_id_call_queues"),
        "parking_lots",
        "call_queues",
        ["timeout_queue_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_parking_lots_timeout_ring_group_id_ring_groups"),
        "parking_lots",
        "ring_groups",
        ["timeout_ring_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_parking_lots_timeout_voicemail_box_id_voicemail_boxes"),
        "parking_lots",
        "voicemail_boxes",
        ["timeout_voicemail_box_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_parking_lots_timeout_announcement_id_announcements"),
        "parking_lots",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_parking_lots_timeout_call_flow_id_call_flows"), "parking_lots", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_parking_lots_timeout_conference_id_conference_rooms"),
        "parking_lots",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_parking_lots_timeout_ivr_id_ivr_menus"), "parking_lots", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_parking_lots_timeout_queue_id_call_queues"), "parking_lots", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_parking_lots_timeout_ring_group_id_ring_groups"),
        "parking_lots",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_parking_lots_timeout_voicemail_box_id_voicemail_boxes"),
        "parking_lots",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_parking_lots_organization_id"), table_name="parking_lots")
    op.drop_table("parking_lots")
