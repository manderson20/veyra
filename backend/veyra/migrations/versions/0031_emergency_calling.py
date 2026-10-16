# SPDX-License-Identifier: AGPL-3.0-or-later
"""Emergency calling validation (Milestone 17, docs/PRODUCTION_HARDENING.md §6):
building addresses, extension and device locations, site-bound emergency
routes, site attestation, responder, callback window, recipients, test
calls; the emergency_calls table.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-16 06:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for col in ("street", "city", "region", "postal_code", "country"):
        length = {"street": 200, "city": 100, "region": 100, "postal_code": 20, "country": 2}[col]
        op.add_column("buildings", sa.Column(col, sa.String(length=length), nullable=True))
    for table in ("extensions", "devices"):
        op.add_column(table, sa.Column("building_id", sa.UUID(), nullable=True))
        op.add_column(table, sa.Column("location", sa.String(length=200), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_{table}_building_id_buildings"),
            table,
            "buildings",
            ["building_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.add_column("outbound_routes", sa.Column("site_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_outbound_routes_site_id_sites"),
        "outbound_routes",
        "sites",
        ["site_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("sites", sa.Column("emergency_attested_by", sa.String(length=320), nullable=True))
    op.add_column(
        "sites", sa.Column("emergency_attested_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("sites", sa.Column("emergency_responder_extension_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_sites_emergency_responder_extension_id_extensions"),
        "sites",
        "extensions",
        ["emergency_responder_extension_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "sites",
        sa.Column("emergency_callback_minutes", sa.Integer(), nullable=False, server_default="30"),
    )
    op.add_column(
        "sites",
        sa.Column(
            "emergency_recipients",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "sites", sa.Column("last_emergency_test_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("sites", sa.Column("last_emergency_test_result", sa.Text(), nullable=True))
    op.add_column(
        "sites",
        sa.Column("last_emergency_notification_test_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "emergency_calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("site_id", sa.UUID(), nullable=True),
        sa.Column("extension_id", sa.UUID(), nullable=True),
        sa.Column("extension_number", sa.String(length=32), nullable=False),
        sa.Column("device_id", sa.UUID(), nullable=True),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("route", sa.String(length=40), nullable=True),
        sa.Column("caller_id", sa.String(length=32), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("channel", sa.String(length=120), nullable=True),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("notifications", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("callback_until", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_emergency_calls_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            name=op.f("fk_emergency_calls_site_id_sites"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["extension_id"],
            ["extensions.id"],
            name=op.f("fk_emergency_calls_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_emergency_calls_device_id_devices"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_emergency_calls")),
    )
    op.create_index(op.f("ix_emergency_calls_occurred_at"), "emergency_calls", ["occurred_at"])
    op.create_index(op.f("ix_emergency_calls_site_id"), "emergency_calls", ["site_id"])


def downgrade() -> None:
    op.drop_table("emergency_calls")
    for col in (
        "last_emergency_notification_test_at",
        "last_emergency_test_result",
        "last_emergency_test_at",
        "emergency_recipients",
        "emergency_callback_minutes",
        "emergency_responder_extension_id",
        "emergency_attested_at",
        "emergency_attested_by",
    ):
        op.drop_column("sites", col)
    op.drop_column("outbound_routes", "site_id")
    for table in ("extensions", "devices"):
        op.drop_column(table, "location")
        op.drop_column(table, "building_id")
    for col in ("country", "postal_code", "region", "city", "street"):
        op.drop_column("buildings", col)
