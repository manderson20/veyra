# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ring groups, call queues, pickup groups; group and queue destinations (Milestone 8).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-14 02:16:33.816784
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pickup_groups",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
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
            name=op.f("fk_pickup_groups_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pickup_groups")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_pickup_groups_organization_id_name")
        ),
        sa.UniqueConstraint("slug", name=op.f("uq_pickup_groups_slug")),
    )
    op.create_index(
        op.f("ix_pickup_groups_organization_id"), "pickup_groups", ["organization_id"], unique=False
    )
    op.create_table(
        "pickup_group_members",
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("extension_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["extension_id"],
            ["extensions.id"],
            name=op.f("fk_pickup_group_members_extension_id_extensions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["pickup_groups.id"],
            name=op.f("fk_pickup_group_members_group_id_pickup_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("group_id", "extension_id", name=op.f("pk_pickup_group_members")),
    )
    op.create_table(
        "ring_groups",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("strategy", sa.String(length=16), nullable=False),
        sa.Column("ring_seconds", sa.Integer(), nullable=False),
        sa.Column("ring_busy_members", sa.Boolean(), nullable=False),
        sa.Column("caller_id_prefix", sa.String(length=40), nullable=True),
        sa.Column("failover_ring_group_id", sa.UUID(), nullable=True),
        sa.Column("failover_queue_id", sa.UUID(), nullable=True),
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
        sa.Column("failover_type", sa.String(length=16), nullable=False),
        sa.Column("failover_extension_id", sa.UUID(), nullable=True),
        sa.Column("failover_ivr_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["failover_extension_id"],
            ["extensions.id"],
            name=op.f("fk_ring_groups_failover_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["failover_ivr_id"],
            ["ivr_menus.id"],
            name=op.f("fk_ring_groups_failover_ivr_id_ivr_menus"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["failover_ring_group_id"],
            ["ring_groups.id"],
            name=op.f("fk_ring_groups_failover_ring_group_id_ring_groups"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_ring_groups_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ring_groups")),
        sa.UniqueConstraint("number", name=op.f("uq_ring_groups_number")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_ring_groups_organization_id_name")
        ),
        sa.UniqueConstraint("slug", name=op.f("uq_ring_groups_slug")),
    )
    op.create_index(
        op.f("ix_ring_groups_organization_id"), "ring_groups", ["organization_id"], unique=False
    )
    op.create_table(
        "call_queues",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("strategy", sa.String(length=16), nullable=False),
        sa.Column("member_timeout", sa.Integer(), nullable=False),
        sa.Column("retry_seconds", sa.Integer(), nullable=False),
        sa.Column("wrapup_seconds", sa.Integer(), nullable=False),
        sa.Column("max_wait_seconds", sa.Integer(), nullable=False),
        sa.Column("max_callers", sa.Integer(), nullable=False),
        sa.Column("join_when_empty", sa.Boolean(), nullable=False),
        sa.Column("announce_position", sa.Boolean(), nullable=False),
        sa.Column("announce_frequency", sa.Integer(), nullable=False),
        sa.Column("announcement_prompt_id", sa.UUID(), nullable=True),
        sa.Column("periodic_prompt_id", sa.UUID(), nullable=True),
        sa.Column("periodic_seconds", sa.Integer(), nullable=False),
        sa.Column("music", sa.String(length=16), nullable=False),
        sa.Column("failover_ring_group_id", sa.UUID(), nullable=True),
        sa.Column("failover_queue_id", sa.UUID(), nullable=True),
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
        sa.Column("failover_type", sa.String(length=16), nullable=False),
        sa.Column("failover_extension_id", sa.UUID(), nullable=True),
        sa.Column("failover_ivr_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["announcement_prompt_id"],
            ["prompts.id"],
            name=op.f("fk_call_queues_announcement_prompt_id_prompts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["failover_extension_id"],
            ["extensions.id"],
            name=op.f("fk_call_queues_failover_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["failover_ivr_id"],
            ["ivr_menus.id"],
            name=op.f("fk_call_queues_failover_ivr_id_ivr_menus"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["failover_queue_id"],
            ["call_queues.id"],
            name=op.f("fk_call_queues_failover_queue_id_call_queues"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["failover_ring_group_id"],
            ["ring_groups.id"],
            name=op.f("fk_call_queues_failover_ring_group_id_ring_groups"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_call_queues_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["periodic_prompt_id"],
            ["prompts.id"],
            name=op.f("fk_call_queues_periodic_prompt_id_prompts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_queues")),
        sa.UniqueConstraint("number", name=op.f("uq_call_queues_number")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_call_queues_organization_id_name")
        ),
        sa.UniqueConstraint("slug", name=op.f("uq_call_queues_slug")),
    )
    op.create_index(
        op.f("ix_call_queues_organization_id"), "call_queues", ["organization_id"], unique=False
    )
    # Ring groups and queues point at each other: this side is added once both exist.
    op.create_foreign_key(
        op.f("fk_ring_groups_failover_queue_id_call_queues"),
        "ring_groups",
        "call_queues",
        ["failover_queue_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "ring_group_members",
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("extension_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["extension_id"],
            ["extensions.id"],
            name=op.f("fk_ring_group_members_extension_id_extensions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["ring_groups.id"],
            name=op.f("fk_ring_group_members_group_id_ring_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("group_id", "extension_id", name=op.f("pk_ring_group_members")),
        sa.UniqueConstraint(
            "group_id", "position", name=op.f("uq_ring_group_members_group_id_position")
        ),
    )
    op.create_table(
        "queue_members",
        sa.Column("queue_id", sa.UUID(), nullable=False),
        sa.Column("extension_id", sa.UUID(), nullable=False),
        sa.Column("penalty", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["extension_id"],
            ["extensions.id"],
            name=op.f("fk_queue_members_extension_id_extensions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["queue_id"],
            ["call_queues.id"],
            name=op.f("fk_queue_members_queue_id_call_queues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("queue_id", "extension_id", name=op.f("pk_queue_members")),
    )
    op.add_column(
        "inbound_routes", sa.Column("destination_ring_group_id", sa.UUID(), nullable=True)
    )
    op.add_column("inbound_routes", sa.Column("destination_queue_id", sa.UUID(), nullable=True))
    op.add_column(
        "inbound_routes", sa.Column("after_hours_ring_group_id", sa.UUID(), nullable=True)
    )
    op.add_column("inbound_routes", sa.Column("after_hours_queue_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_inbound_routes_destination_ring_group_id_ring_groups"),
        "inbound_routes",
        "ring_groups",
        ["destination_ring_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_inbound_routes_destination_queue_id_call_queues"),
        "inbound_routes",
        "call_queues",
        ["destination_queue_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_inbound_routes_after_hours_ring_group_id_ring_groups"),
        "inbound_routes",
        "ring_groups",
        ["after_hours_ring_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_inbound_routes_after_hours_queue_id_call_queues"),
        "inbound_routes",
        "call_queues",
        ["after_hours_queue_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("ivr_entries", sa.Column("destination_ring_group_id", sa.UUID(), nullable=True))
    op.add_column("ivr_entries", sa.Column("destination_queue_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ivr_entries_destination_ring_group_id_ring_groups"),
        "ivr_entries",
        "ring_groups",
        ["destination_ring_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_ivr_entries_destination_queue_id_call_queues"),
        "ivr_entries",
        "call_queues",
        ["destination_queue_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("ivr_menus", sa.Column("timeout_ring_group_id", sa.UUID(), nullable=True))
    op.add_column("ivr_menus", sa.Column("timeout_queue_id", sa.UUID(), nullable=True))
    op.add_column("ivr_menus", sa.Column("invalid_ring_group_id", sa.UUID(), nullable=True))
    op.add_column("ivr_menus", sa.Column("invalid_queue_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ivr_menus_invalid_ring_group_id_ring_groups"),
        "ivr_menus",
        "ring_groups",
        ["invalid_ring_group_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_ivr_menus_timeout_queue_id_call_queues"),
        "ivr_menus",
        "call_queues",
        ["timeout_queue_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_ivr_menus_timeout_ring_group_id_ring_groups"),
        "ivr_menus",
        "ring_groups",
        ["timeout_ring_group_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_ivr_menus_invalid_queue_id_call_queues"),
        "ivr_menus",
        "call_queues",
        ["invalid_queue_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_ivr_menus_invalid_queue_id_call_queues"), "ivr_menus", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_ivr_menus_timeout_ring_group_id_ring_groups"), "ivr_menus", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_ivr_menus_timeout_queue_id_call_queues"), "ivr_menus", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_ivr_menus_invalid_ring_group_id_ring_groups"), "ivr_menus", type_="foreignkey"
    )
    op.drop_column("ivr_menus", "invalid_queue_id")
    op.drop_column("ivr_menus", "invalid_ring_group_id")
    op.drop_column("ivr_menus", "timeout_queue_id")
    op.drop_column("ivr_menus", "timeout_ring_group_id")
    op.drop_constraint(
        op.f("fk_ivr_entries_destination_queue_id_call_queues"), "ivr_entries", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_ivr_entries_destination_ring_group_id_ring_groups"),
        "ivr_entries",
        type_="foreignkey",
    )
    op.drop_column("ivr_entries", "destination_queue_id")
    op.drop_column("ivr_entries", "destination_ring_group_id")
    op.drop_constraint(
        op.f("fk_inbound_routes_after_hours_queue_id_call_queues"),
        "inbound_routes",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_inbound_routes_after_hours_ring_group_id_ring_groups"),
        "inbound_routes",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_inbound_routes_destination_queue_id_call_queues"),
        "inbound_routes",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_inbound_routes_destination_ring_group_id_ring_groups"),
        "inbound_routes",
        type_="foreignkey",
    )
    op.drop_column("inbound_routes", "after_hours_queue_id")
    op.drop_column("inbound_routes", "after_hours_ring_group_id")
    op.drop_column("inbound_routes", "destination_queue_id")
    op.drop_column("inbound_routes", "destination_ring_group_id")
    op.drop_table("queue_members")
    op.drop_table("ring_group_members")
    op.drop_constraint(
        op.f("fk_ring_groups_failover_queue_id_call_queues"), "ring_groups", type_="foreignkey"
    )
    op.drop_index(op.f("ix_call_queues_organization_id"), table_name="call_queues")
    op.drop_table("call_queues")
    op.drop_index(op.f("ix_ring_groups_organization_id"), table_name="ring_groups")
    op.drop_table("ring_groups")
    op.drop_table("pickup_group_members")
    op.drop_index(op.f("ix_pickup_groups_organization_id"), table_name="pickup_groups")
    op.drop_table("pickup_groups")
