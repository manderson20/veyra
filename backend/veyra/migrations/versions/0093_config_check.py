# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration checks: overrides, modes and the device summary
(docs/CONFIG_VERIFICATION.md §5, §6).

Revision ID: 0093
Revises: 0092
Create Date: 2026-11-07 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0093"
down_revision: str | None = "0092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "installation",
        sa.Column("config_check_mode", sa.String(16), nullable=False, server_default="enforce"),
    )
    op.add_column("organizations", sa.Column("config_check_mode", sa.String(16), nullable=True))
    op.add_column("device_profiles", sa.Column("config_check_mode", sa.String(16), nullable=True))
    op.add_column("devices", sa.Column("config_check", postgresql.JSONB(), nullable=True))
    op.create_table(
        "config_check_overrides",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("rule", sa.String(40), nullable=False),
        sa.Column("vendor", sa.String(40), nullable=False),
        sa.Column("family", sa.String(40), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("release", sa.String(40), nullable=False),
        sa.Column("catalog_revision", sa.Integer(), nullable=False),
        sa.Column("file", sa.String(128), nullable=False),
        sa.Column("parameter", sa.String(200), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("value_sha256", sa.String(64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("checker_wrong", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_by_label", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_by", sa.UUID(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stale_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_config_check_overrides_organization_id", "config_check_overrides", ["organization_id"]
    )
    # One live override per finding and scope; a revoked one stays as history.
    op.create_index(
        "uq_config_check_overrides_live",
        "config_check_overrides",
        ["scope_type", "scope_id", "fingerprint"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_config_check_overrides_live", table_name="config_check_overrides")
    op.drop_index("ix_config_check_overrides_organization_id", table_name="config_check_overrides")
    op.drop_table("config_check_overrides")
    op.drop_column("devices", "config_check")
    op.drop_column("device_profiles", "config_check_mode")
    op.drop_column("organizations", "config_check_mode")
    op.drop_column("installation", "config_check_mode")
