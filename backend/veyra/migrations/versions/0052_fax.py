# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fax (docs/USER_PORTAL.md §9): inboxes and jobs, the destination kind
"fax" on every destination holder, the organization's fax header and station
id, T.38 on trunks and the class-of-service flag.

Revision ID: 0052
Revises: 0051
Create Date: 2026-10-19 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, destination column prefix) of every stored destination.
HOLDERS = (
    ("announcements", "destination"),
    ("call_flows", "normal"),
    ("call_flows", "override"),
    ("parking_lots", "timeout"),
    ("caller_block_policies", "destination"),
    ("ring_groups", "failover"),
    ("call_queues", "failover"),
    ("inbound_routes", "destination"),
    ("inbound_routes", "after_hours"),
    ("ivr_menus", "timeout"),
    ("ivr_menus", "invalid"),
    ("ivr_entries", "destination"),
)


def upgrade() -> None:
    op.create_table(
        "fax_inboxes",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("recipients", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("station_id", sa.String(length=32), nullable=True),
        sa.Column("header", sa.String(length=64), nullable=True),
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
            name=op.f("fk_fax_inboxes_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fax_inboxes")),
        sa.UniqueConstraint("slug", name=op.f("uq_fax_inboxes_slug")),
    )
    op.create_index(
        op.f("ix_fax_inboxes_organization_id"), "fax_inboxes", ["organization_id"], unique=False
    )
    op.create_table(
        "fax_jobs",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("extension_id", sa.UUID(), nullable=True),
        sa.Column("inbox_id", sa.UUID(), nullable=True),
        sa.Column("direction", sa.String(length=3), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("caller_id", sa.String(length=32), nullable=True),
        sa.Column("remote_id", sa.String(length=64), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("file", sa.String(length=255), nullable=True),
        sa.Column("pdf_file", sa.String(length=255), nullable=True),
        sa.Column("original_name", sa.String(length=255), nullable=True),
        sa.Column("cover", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("channel_id", sa.String(length=80), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            ["extension_id"],
            ["extensions.id"],
            name=op.f("fk_fax_jobs_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["inbox_id"],
            ["fax_inboxes.id"],
            name=op.f("fk_fax_jobs_inbox_id_fax_inboxes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_fax_jobs_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_fax_jobs_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fax_jobs")),
    )
    op.create_index(op.f("ix_fax_jobs_channel_id"), "fax_jobs", ["channel_id"], unique=False)
    op.create_index(
        op.f("ix_fax_jobs_organization_id"), "fax_jobs", ["organization_id"], unique=False
    )
    op.create_index(op.f("ix_fax_jobs_state"), "fax_jobs", ["state"], unique=False)
    op.create_index(op.f("ix_fax_jobs_user_id"), "fax_jobs", ["user_id"], unique=False)

    op.add_column("organizations", sa.Column("fax_header", sa.String(length=64), nullable=True))
    op.add_column(
        "organizations", sa.Column("fax_station_id", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "sip_trunks",
        sa.Column("fax_t38", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "classes_of_service",
        sa.Column("allow_fax", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    for table, prefix in HOLDERS:
        op.add_column(table, sa.Column(f"{prefix}_fax_inbox_id", sa.UUID(), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_{table}_{prefix}_fax_inbox_id_fax_inboxes"),
            table,
            "fax_inboxes",
            [f"{prefix}_fax_inbox_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table, prefix in reversed(HOLDERS):
        op.drop_constraint(
            op.f(f"fk_{table}_{prefix}_fax_inbox_id_fax_inboxes"), table, type_="foreignkey"
        )
        op.drop_column(table, f"{prefix}_fax_inbox_id")
    op.drop_column("classes_of_service", "allow_fax")
    op.drop_column("sip_trunks", "fax_t38")
    op.drop_column("organizations", "fax_station_id")
    op.drop_column("organizations", "fax_header")
    op.drop_index(op.f("ix_fax_jobs_user_id"), table_name="fax_jobs")
    op.drop_index(op.f("ix_fax_jobs_state"), table_name="fax_jobs")
    op.drop_index(op.f("ix_fax_jobs_organization_id"), table_name="fax_jobs")
    op.drop_index(op.f("ix_fax_jobs_channel_id"), table_name="fax_jobs")
    op.drop_table("fax_jobs")
    op.drop_index(op.f("ix_fax_inboxes_organization_id"), table_name="fax_inboxes")
    op.drop_table("fax_inboxes")
