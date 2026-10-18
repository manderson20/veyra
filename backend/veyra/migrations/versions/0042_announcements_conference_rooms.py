# SPDX-License-Identifier: AGPL-3.0-or-later
"""Announcements and conference rooms (docs/CALL_FEATURES.md §4.1, §4.3) and
the destination kinds that reach them: every destination holder gains
``<prefix>_announcement_id`` and ``<prefix>_conference_id`` (ON DELETE SET
NULL, like the existing target columns).

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-18 15:20:39.816603
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conference_rooms",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("user_pin_ciphertext", sa.Text(), nullable=True),
        sa.Column("admin_pin_ciphertext", sa.Text(), nullable=True),
        sa.Column("max_participants", sa.Integer(), nullable=False),
        sa.Column("record", sa.Boolean(), nullable=False),
        sa.Column("announce_join_leave", sa.Boolean(), nullable=False),
        sa.Column("music_on_hold_alone", sa.Boolean(), nullable=False),
        sa.Column("wait_for_admin", sa.Boolean(), nullable=False),
        sa.Column("moh_class_id", sa.UUID(), nullable=True),
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
            ["moh_class_id"],
            ["moh_classes.id"],
            name=op.f("fk_conference_rooms_moh_class_id_moh_classes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_conference_rooms_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conference_rooms")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_conference_rooms_organization_id_name")
        ),
        sa.UniqueConstraint(
            "organization_id", "number", name=op.f("uq_conference_rooms_organization_id_number")
        ),
        sa.UniqueConstraint("slug", name=op.f("uq_conference_rooms_slug")),
    )
    op.create_index(
        op.f("ix_conference_rooms_organization_id"),
        "conference_rooms",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "announcements",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("prompt_id", sa.UUID(), nullable=True),
        sa.Column("allow_skip", sa.Boolean(), nullable=False),
        sa.Column("repeat_key", sa.String(length=1), nullable=True),
        sa.Column("destination_type", sa.String(length=16), nullable=False),
        sa.Column("destination_extension_id", sa.UUID(), nullable=True),
        sa.Column("destination_ivr_id", sa.UUID(), nullable=True),
        sa.Column("destination_ring_group_id", sa.UUID(), nullable=True),
        sa.Column("destination_queue_id", sa.UUID(), nullable=True),
        sa.Column("destination_voicemail_box_id", sa.UUID(), nullable=True),
        sa.Column("destination_announcement_id", sa.UUID(), nullable=True),
        sa.Column("destination_conference_id", sa.UUID(), nullable=True),
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
            ["destination_announcement_id"],
            ["announcements.id"],
            name=op.f("fk_announcements_destination_announcement_id_announcements"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["destination_extension_id"],
            ["extensions.id"],
            name=op.f("fk_announcements_destination_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["destination_ivr_id"],
            ["ivr_menus.id"],
            name=op.f("fk_announcements_destination_ivr_id_ivr_menus"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["destination_queue_id"],
            ["call_queues.id"],
            name=op.f("fk_announcements_destination_queue_id_call_queues"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["destination_ring_group_id"],
            ["ring_groups.id"],
            name=op.f("fk_announcements_destination_ring_group_id_ring_groups"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["destination_voicemail_box_id"],
            ["voicemail_boxes.id"],
            name=op.f("fk_announcements_destination_voicemail_box_id_voicemail_boxes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_announcements_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["prompts.id"],
            name=op.f("fk_announcements_prompt_id_prompts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_announcements")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_announcements_organization_id_name")
        ),
        sa.UniqueConstraint("slug", name=op.f("uq_announcements_slug")),
    )
    op.create_index(
        op.f("ix_announcements_organization_id"), "announcements", ["organization_id"], unique=False
    )
    # Declared with use_alter (announcements and conference rooms point at each
    # other through destinations), so it is added after both tables exist.
    op.create_foreign_key(
        op.f("fk_announcements_destination_conference_id_conference_rooms"),
        "announcements",
        "conference_rooms",
        ["destination_conference_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("call_queues", sa.Column("failover_announcement_id", sa.UUID(), nullable=True))
    op.add_column("call_queues", sa.Column("failover_conference_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_call_queues_failover_conference_id_conference_rooms"),
        "call_queues",
        "conference_rooms",
        ["failover_conference_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_call_queues_failover_announcement_id_announcements"),
        "call_queues",
        "announcements",
        ["failover_announcement_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.add_column(
        "inbound_routes", sa.Column("destination_announcement_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "inbound_routes", sa.Column("destination_conference_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "inbound_routes", sa.Column("after_hours_announcement_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "inbound_routes", sa.Column("after_hours_conference_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_inbound_routes_after_hours_announcement_id_announcements"),
        "inbound_routes",
        "announcements",
        ["after_hours_announcement_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_inbound_routes_destination_conference_id_conference_rooms"),
        "inbound_routes",
        "conference_rooms",
        ["destination_conference_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_inbound_routes_destination_announcement_id_announcements"),
        "inbound_routes",
        "announcements",
        ["destination_announcement_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_inbound_routes_after_hours_conference_id_conference_rooms"),
        "inbound_routes",
        "conference_rooms",
        ["after_hours_conference_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.add_column("ivr_entries", sa.Column("destination_announcement_id", sa.UUID(), nullable=True))
    op.add_column("ivr_entries", sa.Column("destination_conference_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ivr_entries_destination_announcement_id_announcements"),
        "ivr_entries",
        "announcements",
        ["destination_announcement_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_ivr_entries_destination_conference_id_conference_rooms"),
        "ivr_entries",
        "conference_rooms",
        ["destination_conference_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.add_column("ivr_menus", sa.Column("timeout_announcement_id", sa.UUID(), nullable=True))
    op.add_column("ivr_menus", sa.Column("timeout_conference_id", sa.UUID(), nullable=True))
    op.add_column("ivr_menus", sa.Column("invalid_announcement_id", sa.UUID(), nullable=True))
    op.add_column("ivr_menus", sa.Column("invalid_conference_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ivr_menus_timeout_announcement_id_announcements"),
        "ivr_menus",
        "announcements",
        ["timeout_announcement_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_ivr_menus_invalid_announcement_id_announcements"),
        "ivr_menus",
        "announcements",
        ["invalid_announcement_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_ivr_menus_timeout_conference_id_conference_rooms"),
        "ivr_menus",
        "conference_rooms",
        ["timeout_conference_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_ivr_menus_invalid_conference_id_conference_rooms"),
        "ivr_menus",
        "conference_rooms",
        ["invalid_conference_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.add_column("ring_groups", sa.Column("failover_announcement_id", sa.UUID(), nullable=True))
    op.add_column("ring_groups", sa.Column("failover_conference_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ring_groups_failover_conference_id_conference_rooms"),
        "ring_groups",
        "conference_rooms",
        ["failover_conference_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_ring_groups_failover_announcement_id_announcements"),
        "ring_groups",
        "announcements",
        ["failover_announcement_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_ring_groups_failover_announcement_id_announcements"),
        "ring_groups",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_ring_groups_failover_conference_id_conference_rooms"),
        "ring_groups",
        type_="foreignkey",
    )
    op.drop_column("ring_groups", "failover_conference_id")
    op.drop_column("ring_groups", "failover_announcement_id")
    op.drop_constraint(
        op.f("fk_ivr_menus_invalid_conference_id_conference_rooms"), "ivr_menus", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_ivr_menus_timeout_conference_id_conference_rooms"), "ivr_menus", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_ivr_menus_invalid_announcement_id_announcements"), "ivr_menus", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_ivr_menus_timeout_announcement_id_announcements"), "ivr_menus", type_="foreignkey"
    )
    op.drop_column("ivr_menus", "invalid_conference_id")
    op.drop_column("ivr_menus", "invalid_announcement_id")
    op.drop_column("ivr_menus", "timeout_conference_id")
    op.drop_column("ivr_menus", "timeout_announcement_id")
    op.drop_constraint(
        op.f("fk_ivr_entries_destination_conference_id_conference_rooms"),
        "ivr_entries",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_ivr_entries_destination_announcement_id_announcements"),
        "ivr_entries",
        type_="foreignkey",
    )
    op.drop_column("ivr_entries", "destination_conference_id")
    op.drop_column("ivr_entries", "destination_announcement_id")
    op.drop_constraint(
        op.f("fk_inbound_routes_after_hours_conference_id_conference_rooms"),
        "inbound_routes",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_inbound_routes_destination_announcement_id_announcements"),
        "inbound_routes",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_inbound_routes_destination_conference_id_conference_rooms"),
        "inbound_routes",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_inbound_routes_after_hours_announcement_id_announcements"),
        "inbound_routes",
        type_="foreignkey",
    )
    op.drop_column("inbound_routes", "after_hours_conference_id")
    op.drop_column("inbound_routes", "after_hours_announcement_id")
    op.drop_column("inbound_routes", "destination_conference_id")
    op.drop_column("inbound_routes", "destination_announcement_id")
    op.drop_constraint(
        op.f("fk_call_queues_failover_announcement_id_announcements"),
        "call_queues",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_call_queues_failover_conference_id_conference_rooms"),
        "call_queues",
        type_="foreignkey",
    )
    op.drop_column("call_queues", "failover_conference_id")
    op.drop_column("call_queues", "failover_announcement_id")
    op.drop_constraint(
        op.f("fk_announcements_destination_conference_id_conference_rooms"),
        "announcements",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_announcements_organization_id"), table_name="announcements")
    op.drop_table("announcements")
    op.drop_index(op.f("ix_conference_rooms_organization_id"), table_name="conference_rooms")
    op.drop_table("conference_rooms")
