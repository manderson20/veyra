# SPDX-License-Identifier: AGPL-3.0-or-later
"""Custom dialplan (docs/CUSTOM_DIALPLAN.md): the destination kind "custom" on
every destination holder.

Revision ID: 0071
Revises: 0070
Create Date: 2026-10-30 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0071"
down_revision: str | None = "0070"
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
    for table, prefix in HOLDERS:
        op.add_column(table, sa.Column(f"{prefix}_custom_context", sa.String(64), nullable=True))


def downgrade() -> None:
    for table, prefix in HOLDERS:
        op.drop_column(table, f"{prefix}_custom_context")
