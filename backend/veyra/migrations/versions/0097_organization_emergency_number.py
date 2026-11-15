# SPDX-License-Identifier: AGPL-3.0-or-later
"""The organization's emergency number (docs/MULTI_TENANCY_MSP.md §6.1).

Filled with a site emergency caller ID the organization owns, else its main
number: what a 911 call presents when neither the phone nor its site has
one, while several organizations share the server.

Revision ID: 0097
Revises: 0096
Create Date: 2026-11-07 23:00:00.000000
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0097"
down_revision: str | None = "0096"
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
    op.add_column(
        "organizations", sa.Column("emergency_caller_id_number", sa.String(18), nullable=True)
    )
    bind = op.get_bind()
    blocks = list(
        bind.execute(sa.text("SELECT organization_id, first, last FROM organization_numbers"))
    )
    chosen: dict[object, str] = {}
    for org, raw in bind.execute(
        sa.text(
            "SELECT organization_id, emergency_caller_id_number FROM sites"
            " WHERE emergency_caller_id_number IS NOT NULL ORDER BY created_at"
        )
    ):
        n = _canonical(raw)
        if n and any(
            o == org and len(f) == len(n) and f <= n <= last for o, f, last in blocks
        ):
            chosen.setdefault(org, n)
    for org, main in bind.execute(
        sa.text("SELECT id, main_number FROM organizations WHERE main_number IS NOT NULL")
    ):
        chosen.setdefault(org, main)
    for org, number in chosen.items():
        bind.execute(
            sa.text("UPDATE organizations SET emergency_caller_id_number = :n WHERE id = :o"),
            {"n": number, "o": org},
        )


def downgrade() -> None:
    op.drop_column("organizations", "emergency_caller_id_number")
