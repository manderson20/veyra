# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call flows (day/night switches) and the time-condition override, code and
PIN (docs/CALL_FEATURES.md §4.5, §4.6); every destination holder gains
``<prefix>_call_flow_id``.

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-18 15:54:55.520044
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "call_flows",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("code_index", sa.Integer(), nullable=False),
        sa.Column("pin_ciphertext", sa.Text(), nullable=True),
        sa.Column("normal_type", sa.String(length=16), nullable=False),
        sa.Column("override_type", sa.String(length=16), nullable=False),
        sa.Column("override", sa.Boolean(), nullable=False),
        sa.Column("override_by", sa.String(length=200), nullable=True),
        sa.Column("override_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("normal_extension_id", sa.UUID(), nullable=True),
        sa.Column("normal_ivr_id", sa.UUID(), nullable=True),
        sa.Column("normal_ring_group_id", sa.UUID(), nullable=True),
        sa.Column("normal_queue_id", sa.UUID(), nullable=True),
        sa.Column("normal_voicemail_box_id", sa.UUID(), nullable=True),
        sa.Column("normal_announcement_id", sa.UUID(), nullable=True),
        sa.Column("normal_conference_id", sa.UUID(), nullable=True),
        sa.Column("normal_call_flow_id", sa.UUID(), nullable=True),
        sa.Column("override_extension_id", sa.UUID(), nullable=True),
        sa.Column("override_ivr_id", sa.UUID(), nullable=True),
        sa.Column("override_ring_group_id", sa.UUID(), nullable=True),
        sa.Column("override_queue_id", sa.UUID(), nullable=True),
        sa.Column("override_voicemail_box_id", sa.UUID(), nullable=True),
        sa.Column("override_announcement_id", sa.UUID(), nullable=True),
        sa.Column("override_conference_id", sa.UUID(), nullable=True),
        sa.Column("override_call_flow_id", sa.UUID(), nullable=True),
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
            ["normal_extension_id"],
            ["extensions.id"],
            name=op.f("fk_call_flows_normal_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_call_flows_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["override_extension_id"],
            ["extensions.id"],
            name=op.f("fk_call_flows_override_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_flows")),
        sa.UniqueConstraint(
            "organization_id", "code_index", name=op.f("uq_call_flows_organization_id_code_index")
        ),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_call_flows_organization_id_name")
        ),
        sa.UniqueConstraint("slug", name=op.f("uq_call_flows_slug")),
    )
    op.create_index(
        op.f("ix_call_flows_organization_id"), "call_flows", ["organization_id"], unique=False
    )
    # Declared with use_alter (call flows point at menus, groups, rooms,
    # announcements and each other), so added once the table exists.
    op.create_foreign_key(
        op.f("fk_call_flows_normal_announcement_id_announcements"),
        "call_flows",
        "announcements",
        ["normal_announcement_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_call_flows_normal_call_flow_id_call_flows"),
        "call_flows",
        "call_flows",
        ["normal_call_flow_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_call_flows_normal_conference_id_conference_rooms"),
        "call_flows",
        "conference_rooms",
        ["normal_conference_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_call_flows_normal_ivr_id_ivr_menus"),
        "call_flows",
        "ivr_menus",
        ["normal_ivr_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_call_flows_normal_queue_id_call_queues"),
        "call_flows",
        "call_queues",
        ["normal_queue_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_call_flows_normal_ring_group_id_ring_groups"),
        "call_flows",
        "ring_groups",
        ["normal_ring_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_call_flows_normal_voicemail_box_id_voicemail_boxes"),
        "call_flows",
        "voicemail_boxes",
        ["normal_voicemail_box_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_call_flows_override_announcement_id_announcements"),
        "call_flows",
        "announcements",
        ["override_announcement_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_call_flows_override_call_flow_id_call_flows"),
        "call_flows",
        "call_flows",
        ["override_call_flow_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_call_flows_override_conference_id_conference_rooms"),
        "call_flows",
        "conference_rooms",
        ["override_conference_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_call_flows_override_ivr_id_ivr_menus"),
        "call_flows",
        "ivr_menus",
        ["override_ivr_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_call_flows_override_queue_id_call_queues"),
        "call_flows",
        "call_queues",
        ["override_queue_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_call_flows_override_ring_group_id_ring_groups"),
        "call_flows",
        "ring_groups",
        ["override_ring_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_call_flows_override_voicemail_box_id_voicemail_boxes"),
        "call_flows",
        "voicemail_boxes",
        ["override_voicemail_box_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("announcements", sa.Column("destination_call_flow_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_announcements_destination_call_flow_id_call_flows"),
        "announcements",
        "call_flows",
        ["destination_call_flow_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.add_column("call_queues", sa.Column("failover_call_flow_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_call_queues_failover_call_flow_id_call_flows"),
        "call_queues",
        "call_flows",
        ["failover_call_flow_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.add_column("inbound_routes", sa.Column("destination_call_flow_id", sa.UUID(), nullable=True))
    op.add_column("inbound_routes", sa.Column("after_hours_call_flow_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_inbound_routes_destination_call_flow_id_call_flows"),
        "inbound_routes",
        "call_flows",
        ["destination_call_flow_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_inbound_routes_after_hours_call_flow_id_call_flows"),
        "inbound_routes",
        "call_flows",
        ["after_hours_call_flow_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.add_column("ivr_entries", sa.Column("destination_call_flow_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ivr_entries_destination_call_flow_id_call_flows"),
        "ivr_entries",
        "call_flows",
        ["destination_call_flow_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.add_column("ivr_menus", sa.Column("timeout_call_flow_id", sa.UUID(), nullable=True))
    op.add_column("ivr_menus", sa.Column("invalid_call_flow_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ivr_menus_invalid_call_flow_id_call_flows"),
        "ivr_menus",
        "call_flows",
        ["invalid_call_flow_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_ivr_menus_timeout_call_flow_id_call_flows"),
        "ivr_menus",
        "call_flows",
        ["timeout_call_flow_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.add_column("ring_groups", sa.Column("failover_call_flow_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ring_groups_failover_call_flow_id_call_flows"),
        "ring_groups",
        "call_flows",
        ["failover_call_flow_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.add_column("time_conditions", sa.Column("override", sa.String(length=8), nullable=True))
    op.add_column("time_conditions", sa.Column("override_temporary", sa.Boolean(), nullable=False))
    op.add_column("time_conditions", sa.Column("override_since_open", sa.Boolean(), nullable=True))
    op.add_column("time_conditions", sa.Column("override_by", sa.String(length=200), nullable=True))
    op.add_column(
        "time_conditions", sa.Column("override_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("time_conditions", sa.Column("code_index", sa.Integer(), nullable=True))
    op.add_column("time_conditions", sa.Column("pin_ciphertext", sa.Text(), nullable=True))
    op.create_unique_constraint(
        op.f("uq_time_conditions_organization_id_code_index"),
        "time_conditions",
        ["organization_id", "code_index"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_time_conditions_organization_id_code_index"), "time_conditions", type_="unique"
    )
    op.drop_column("time_conditions", "pin_ciphertext")
    op.drop_column("time_conditions", "code_index")
    op.drop_column("time_conditions", "override_at")
    op.drop_column("time_conditions", "override_by")
    op.drop_column("time_conditions", "override_since_open")
    op.drop_column("time_conditions", "override_temporary")
    op.drop_column("time_conditions", "override")
    op.drop_constraint(
        op.f("fk_ring_groups_failover_call_flow_id_call_flows"), "ring_groups", type_="foreignkey"
    )
    op.drop_column("ring_groups", "failover_call_flow_id")
    op.drop_constraint(
        op.f("fk_ivr_menus_timeout_call_flow_id_call_flows"), "ivr_menus", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_ivr_menus_invalid_call_flow_id_call_flows"), "ivr_menus", type_="foreignkey"
    )
    op.drop_column("ivr_menus", "invalid_call_flow_id")
    op.drop_column("ivr_menus", "timeout_call_flow_id")
    op.drop_constraint(
        op.f("fk_ivr_entries_destination_call_flow_id_call_flows"),
        "ivr_entries",
        type_="foreignkey",
    )
    op.drop_column("ivr_entries", "destination_call_flow_id")
    op.drop_constraint(
        op.f("fk_inbound_routes_after_hours_call_flow_id_call_flows"),
        "inbound_routes",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_inbound_routes_destination_call_flow_id_call_flows"),
        "inbound_routes",
        type_="foreignkey",
    )
    op.drop_column("inbound_routes", "after_hours_call_flow_id")
    op.drop_column("inbound_routes", "destination_call_flow_id")
    op.drop_constraint(
        op.f("fk_call_queues_failover_call_flow_id_call_flows"), "call_queues", type_="foreignkey"
    )
    op.drop_column("call_queues", "failover_call_flow_id")
    op.drop_constraint(
        op.f("fk_announcements_destination_call_flow_id_call_flows"),
        "announcements",
        type_="foreignkey",
    )
    op.drop_column("announcements", "destination_call_flow_id")
    op.drop_constraint(
        op.f("fk_call_flows_normal_announcement_id_announcements"), "call_flows", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_call_flows_normal_call_flow_id_call_flows"), "call_flows", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_call_flows_normal_conference_id_conference_rooms"),
        "call_flows",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_call_flows_normal_ivr_id_ivr_menus"), "call_flows", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_call_flows_normal_queue_id_call_queues"), "call_flows", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_call_flows_normal_ring_group_id_ring_groups"), "call_flows", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_call_flows_normal_voicemail_box_id_voicemail_boxes"),
        "call_flows",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_call_flows_override_announcement_id_announcements"),
        "call_flows",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_call_flows_override_call_flow_id_call_flows"), "call_flows", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_call_flows_override_conference_id_conference_rooms"),
        "call_flows",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_call_flows_override_ivr_id_ivr_menus"), "call_flows", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_call_flows_override_queue_id_call_queues"), "call_flows", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_call_flows_override_ring_group_id_ring_groups"), "call_flows", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_call_flows_override_voicemail_box_id_voicemail_boxes"),
        "call_flows",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_call_flows_organization_id"), table_name="call_flows")
    op.drop_table("call_flows")
