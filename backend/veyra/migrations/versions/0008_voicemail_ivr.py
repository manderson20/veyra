# SPDX-License-Identifier: AGPL-3.0-or-later
"""Voicemail boxes, prompts, IVR menus; inbound route destinations (Milestone 7).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-13 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "voicemail_boxes",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("extension_id", sa.UUID(), nullable=False),
        sa.Column("pin_ciphertext", sa.Text(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("attach_audio", sa.Boolean(), nullable=False),
        sa.Column("delete_after_email", sa.Boolean(), nullable=False),
        sa.Column("ring_seconds", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["extension_id"],
            ["extensions.id"],
            name=op.f("fk_voicemail_boxes_extension_id_extensions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_voicemail_boxes_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_voicemail_boxes")),
        sa.UniqueConstraint("extension_id", name=op.f("uq_voicemail_boxes_extension_id")),
    )
    op.create_index(
        op.f("ix_voicemail_boxes_organization_id"),
        "voicemail_boxes",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "prompts",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_prompts_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompts")),
        sa.UniqueConstraint("organization_id", "slug", name=op.f("uq_prompts_organization_id_slug")),
    )
    op.create_index(op.f("ix_prompts_organization_id"), "prompts", ["organization_id"], unique=False)
    op.create_table(
        "ivr_menus",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("prompt_id", sa.UUID(), nullable=True),
        sa.Column("invalid_prompt_id", sa.UUID(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("allow_direct_dial", sa.Boolean(), nullable=False),
        sa.Column("timeout_type", sa.String(length=16), nullable=False),
        sa.Column("timeout_extension_id", sa.UUID(), nullable=True),
        sa.Column("timeout_ivr_id", sa.UUID(), nullable=True),
        sa.Column("invalid_type", sa.String(length=16), nullable=False),
        sa.Column("invalid_extension_id", sa.UUID(), nullable=True),
        sa.Column("invalid_ivr_id", sa.UUID(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["invalid_extension_id"],
            ["extensions.id"],
            name=op.f("fk_ivr_menus_invalid_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["invalid_ivr_id"],
            ["ivr_menus.id"],
            name=op.f("fk_ivr_menus_invalid_ivr_id_ivr_menus"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["invalid_prompt_id"],
            ["prompts.id"],
            name=op.f("fk_ivr_menus_invalid_prompt_id_prompts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_ivr_menus_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["prompts.id"],
            name=op.f("fk_ivr_menus_prompt_id_prompts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["timeout_extension_id"],
            ["extensions.id"],
            name=op.f("fk_ivr_menus_timeout_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["timeout_ivr_id"],
            ["ivr_menus.id"],
            name=op.f("fk_ivr_menus_timeout_ivr_id_ivr_menus"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ivr_menus")),
        sa.UniqueConstraint("organization_id", "name", name=op.f("uq_ivr_menus_organization_id_name")),
        sa.UniqueConstraint("slug", name=op.f("uq_ivr_menus_slug")),
    )
    op.create_index(
        op.f("ix_ivr_menus_organization_id"), "ivr_menus", ["organization_id"], unique=False
    )
    op.create_table(
        "ivr_entries",
        sa.Column("menu_id", sa.UUID(), nullable=False),
        sa.Column("digit", sa.String(length=1), nullable=False),
        sa.Column("destination_type", sa.String(length=16), nullable=False),
        sa.Column("destination_extension_id", sa.UUID(), nullable=True),
        sa.Column("destination_ivr_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["destination_extension_id"],
            ["extensions.id"],
            name=op.f("fk_ivr_entries_destination_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["destination_ivr_id"],
            ["ivr_menus.id"],
            name=op.f("fk_ivr_entries_destination_ivr_id_ivr_menus"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["menu_id"],
            ["ivr_menus.id"],
            name=op.f("fk_ivr_entries_menu_id_ivr_menus"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("menu_id", "digit", name=op.f("pk_ivr_entries")),
    )
    # Inbound routes: destinations may now be an extension's voicemail or an
    # IVR menu, for the main destination and the after-hours branch alike.
    op.add_column("inbound_routes", sa.Column("destination_ivr_id", sa.UUID(), nullable=True))
    op.add_column(
        "inbound_routes",
        sa.Column(
            "after_hours_type",
            sa.String(length=16),
            nullable=False,
            server_default="extension",
        ),
    )
    op.add_column("inbound_routes", sa.Column("after_hours_ivr_id", sa.UUID(), nullable=True))
    op.alter_column("inbound_routes", "after_hours_type", server_default=None)
    op.create_foreign_key(
        op.f("fk_inbound_routes_destination_ivr_id_ivr_menus"),
        "inbound_routes",
        "ivr_menus",
        ["destination_ivr_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_inbound_routes_after_hours_ivr_id_ivr_menus"),
        "inbound_routes",
        "ivr_menus",
        ["after_hours_ivr_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_inbound_routes_after_hours_ivr_id_ivr_menus"), "inbound_routes", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_inbound_routes_destination_ivr_id_ivr_menus"), "inbound_routes", type_="foreignkey"
    )
    op.drop_column("inbound_routes", "after_hours_ivr_id")
    op.drop_column("inbound_routes", "after_hours_type")
    op.drop_column("inbound_routes", "destination_ivr_id")
    op.drop_table("ivr_entries")
    op.drop_index(op.f("ix_ivr_menus_organization_id"), table_name="ivr_menus")
    op.drop_table("ivr_menus")
    op.drop_index(op.f("ix_prompts_organization_id"), table_name="prompts")
    op.drop_table("prompts")
    op.drop_index(op.f("ix_voicemail_boxes_organization_id"), table_name="voicemail_boxes")
    op.drop_table("voicemail_boxes")
