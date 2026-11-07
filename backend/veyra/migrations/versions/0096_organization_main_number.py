# SPDX-License-Identifier: AGPL-3.0-or-later
"""The organization's main number (docs/MULTI_TENANCY_MSP.md §5.2).

Filled with the organization's own number that a trunk sends as its default
caller ID, else its lowest number, so outside calls keep a caller ID when
several organizations share the server.

Revision ID: 0096
Revises: 0095
Create Date: 2026-11-07 20:00:00.000000
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0096"
down_revision: str | None = "0095"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _canonical(value: str | None) -> str | None:
    v = re.sub(r"[\s().-]", "", (value or "").strip())
    if not re.match(r"^\+?[0-9]{2,20}$", v):
        return None
    digits = v.lstrip("+")
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    return digits if 2 <= len(digits) <= 18 else None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("main_number", sa.String(18), nullable=True))
    bind = op.get_bind()
    blocks = list(
        bind.execute(
            sa.text(
                "SELECT organization_id, first, last FROM organization_numbers ORDER BY first"
            )
        )
    )
    defaults = [
        n
        for (raw,) in bind.execute(
            sa.text("SELECT default_caller_id FROM sip_trunks WHERE default_caller_id IS NOT NULL")
        )
        if (n := _canonical(raw))
    ]
    chosen: dict[object, str] = {}
    for n in defaults:
        for org, first, last in blocks:
            if len(first) == len(n) and first <= n <= last:
                chosen.setdefault(org, n)
    for org, first, _ in blocks:
        chosen.setdefault(org, first)
    for org, number in chosen.items():
        bind.execute(
            sa.text("UPDATE organizations SET main_number = :n WHERE id = :o"),
            {"n": number, "o": org},
        )


def downgrade() -> None:
    op.drop_column("organizations", "main_number")
