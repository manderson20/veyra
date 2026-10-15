# SPDX-License-Identifier: AGPL-3.0-or-later
"""Report builder (Milestone 10b, docs/REPORT_BUILDER.md): saved reports,
and the queue and ring group of each call (filled in from the legs).

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-15 03:55:13.082901
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_reports",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("shared", sa.Boolean(), nullable=False),
        sa.Column("schedule", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
            name=op.f("fk_saved_reports_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_saved_reports_owner_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_reports")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_saved_reports_organization_id_name")
        ),
    )
    op.create_index(
        op.f("ix_saved_reports_next_run_at"), "saved_reports", ["next_run_at"], unique=False
    )
    op.create_index(
        op.f("ix_saved_reports_organization_id"), "saved_reports", ["organization_id"], unique=False
    )
    op.add_column("calls", sa.Column("queue", sa.String(length=80), nullable=True))
    op.add_column("calls", sa.Column("ring_group", sa.String(length=80), nullable=True))
    op.create_index(op.f("ix_calls_queue"), "calls", ["queue"], unique=False)
    op.create_index(op.f("ix_calls_ring_group"), "calls", ["ring_group"], unique=False)
    for column, prefix in (("queue", "veyra-queue-"), ("ring_group", "veyra-rg-")):
        op.execute(
            sa.text(
                f"""
                UPDATE calls SET {column} = sub.slug
                FROM (
                    SELECT call_id, min(COALESCE(
                        substring(dcontext from '^{prefix}(.+)$'),
                        substring(channel from '@{prefix}(.+)-[0-9a-f]{{8}};[12]$')
                    )) AS slug
                    FROM call_legs
                    WHERE dcontext LIKE '{prefix}%' OR channel LIKE '%@{prefix}%'
                    GROUP BY call_id
                ) AS sub
                WHERE sub.call_id = calls.id AND sub.slug IS NOT NULL
                """
            )
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_calls_ring_group"), table_name="calls")
    op.drop_index(op.f("ix_calls_queue"), table_name="calls")
    op.drop_column("calls", "ring_group")
    op.drop_column("calls", "queue")
    op.drop_index(op.f("ix_saved_reports_organization_id"), table_name="saved_reports")
    op.drop_index(op.f("ix_saved_reports_next_run_at"), table_name="saved_reports")
    op.drop_table("saved_reports")
