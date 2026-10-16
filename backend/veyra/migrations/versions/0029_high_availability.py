# SPDX-License-Identifier: AGPL-3.0-or-later
"""High availability: node keys, epochs, replication figures, the cluster epoch
and the switchover freeze (Milestone 16, docs/HIGH_AVAILABILITY.md §11).

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-16 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cluster_nodes", sa.Column("public_key", sa.String(length=100), nullable=True))
    op.add_column("cluster_nodes", sa.Column("fingerprint", sa.String(length=64), nullable=True))
    op.add_column(
        "cluster_nodes",
        sa.Column("epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "cluster_nodes",
        sa.Column("db_role", sa.String(length=16), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "cluster_nodes",
        sa.Column(
            "replication",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column("cluster_nodes", sa.Column("sync_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "cluster_nodes",
        sa.Column("holds_address", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "installation",
        sa.Column("ha_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "installation",
        sa.Column("ha_frozen", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("installation", "ha_frozen")
    op.drop_column("installation", "ha_epoch")
    for col in (
        "holds_address",
        "sync_at",
        "replication",
        "db_role",
        "epoch",
        "fingerprint",
        "public_key",
    ):
        op.drop_column("cluster_nodes", col)
