# SPDX-License-Identifier: AGPL-3.0-or-later
"""SIP trunks, inbound and outbound routes, time conditions (Milestone 6).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-13 10:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sip_trunks",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("auth_mode", sa.String(length=16), nullable=False),
        sa.Column("host", sa.String(length=253), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("transport", sa.String(length=8), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=True),
        sa.Column("auth_username", sa.String(length=80), nullable=True),
        sa.Column("password_ciphertext", sa.Text(), nullable=True),
        sa.Column("from_user", sa.String(length=80), nullable=True),
        sa.Column("from_domain", sa.String(length=253), nullable=True),
        sa.Column("outbound_proxy", sa.String(length=260), nullable=True),
        sa.Column("match_addresses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("codecs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("max_channels", sa.Integer(), nullable=True),
        sa.Column("default_caller_id", sa.String(length=32), nullable=True),
        sa.Column("caller_id_header", sa.String(length=8), nullable=False),
        sa.Column("dtmf_mode", sa.String(length=8), nullable=False),
        sa.Column("qualify_frequency", sa.Integer(), nullable=False),
        sa.Column("register_expiry", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sip_trunks")),
        sa.UniqueConstraint("name", name=op.f("uq_sip_trunks_name")),
        sa.UniqueConstraint("slug", name=op.f("uq_sip_trunks_slug")),
    )
    op.create_table(
        "time_conditions",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("ranges", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("holidays", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            name=op.f("fk_time_conditions_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_time_conditions")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_time_conditions_organization_id_name")
        ),
    )
    op.create_index(
        op.f("ix_time_conditions_organization_id"),
        "time_conditions",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "inbound_routes",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("did", sa.String(length=24), nullable=False),
        sa.Column("did_canonical", sa.String(length=24), nullable=False),
        sa.Column("trunk_id", sa.UUID(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("destination_type", sa.String(length=16), nullable=False),
        sa.Column("destination_extension_id", sa.UUID(), nullable=True),
        sa.Column("time_condition_id", sa.UUID(), nullable=True),
        sa.Column("after_hours_extension_id", sa.UUID(), nullable=True),
        sa.Column("caller_id_prefix", sa.String(length=40), nullable=True),
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
            ["after_hours_extension_id"],
            ["extensions.id"],
            name=op.f("fk_inbound_routes_after_hours_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["destination_extension_id"],
            ["extensions.id"],
            name=op.f("fk_inbound_routes_destination_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_inbound_routes_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["time_condition_id"],
            ["time_conditions.id"],
            name=op.f("fk_inbound_routes_time_condition_id_time_conditions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trunk_id"],
            ["sip_trunks.id"],
            name=op.f("fk_inbound_routes_trunk_id_sip_trunks"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbound_routes")),
        sa.UniqueConstraint(
            "trunk_id",
            "did_canonical",
            name=op.f("uq_inbound_routes_trunk_id_did_canonical"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        op.f("ix_inbound_routes_organization_id"),
        "inbound_routes",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "outbound_routes",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_emergency", sa.Boolean(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("patterns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("caller_id_number", sa.String(length=32), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbound_routes")),
        sa.UniqueConstraint("name", name=op.f("uq_outbound_routes_name")),
        sa.UniqueConstraint("slug", name=op.f("uq_outbound_routes_slug")),
    )
    op.create_table(
        "outbound_route_trunks",
        sa.Column("route_id", sa.UUID(), nullable=False),
        sa.Column("trunk_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["route_id"],
            ["outbound_routes.id"],
            name=op.f("fk_outbound_route_trunks_route_id_outbound_routes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trunk_id"],
            ["sip_trunks.id"],
            name=op.f("fk_outbound_route_trunks_trunk_id_sip_trunks"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("route_id", "trunk_id", name=op.f("pk_outbound_route_trunks")),
        sa.UniqueConstraint(
            "route_id", "position", name=op.f("uq_outbound_route_trunks_route_id_position")
        ),
    )


def downgrade() -> None:
    op.drop_table("outbound_route_trunks")
    op.drop_table("outbound_routes")
    op.drop_index(op.f("ix_inbound_routes_organization_id"), table_name="inbound_routes")
    op.drop_table("inbound_routes")
    op.drop_index(op.f("ix_time_conditions_organization_id"), table_name="time_conditions")
    op.drop_table("time_conditions")
    op.drop_table("sip_trunks")
