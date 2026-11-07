# SPDX-License-Identifier: AGPL-3.0-or-later
"""Number inventory and dedicated trunks (docs/MULTI_TENANCY_MSP.md §4, C4).

Fills the inventory from the inbound routes (except ``any``), then from the
sites' and extensions' emergency caller IDs of ten digits or more. A number
routed by two organizations goes to the organization of the route for every
trunk, else of the older route; the other route is reported as a conflict.

Revision ID: 0095
Revises: 0094
Create Date: 2026-11-07 18:00:00.000000
"""

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0095"
down_revision: str | None = "0094"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _canonical(value: str | None) -> str | None:
    """As ``veyra.core.numbers.canonical``, kept here so the migration does
    not change with the code."""
    v = re.sub(r"[\s().-]", "", (value or "").strip())
    if not re.match(r"^\+?[0-9]{2,20}$", v):
        return None
    digits = v.lstrip("+")
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    return digits if 2 <= len(digits) <= 18 else None


def upgrade() -> None:
    op.create_table(
        "organization_numbers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("first", sa.String(18), nullable=False),
        sa.Column("last", sa.String(18), nullable=False),
        sa.Column(
            "trunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sip_trunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.CheckConstraint(
            "first ~ '^[0-9]{2,18}$' AND last ~ '^[0-9]{2,18}$'"
            " AND length(first) = length(last) AND first <= last",
            name="numbers_canonical",
        ),
        postgresql.ExcludeConstraint(
            (sa.text("int8range(first::bigint, last::bigint, '[]')"), "&&"),
            name="uq_organization_numbers_no_overlap",
            using="gist",
        ),
    )
    op.create_index(
        "ix_organization_numbers_organization_id", "organization_numbers", ["organization_id"]
    )
    op.add_column(
        "sip_trunks",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_sip_trunks_organization_id", "sip_trunks", ["organization_id"])

    bind = op.get_bind()
    now = datetime.now(UTC)
    owned: dict[str, object] = {}
    candidates: list[tuple[str | None, object]] = []
    for did, org in bind.execute(
        sa.text(
            "SELECT did, organization_id FROM inbound_routes WHERE did <> 'any'"
            " ORDER BY trunk_id IS NOT NULL, created_at"
        )
    ):
        candidates.append((_canonical(did), org))
    for table in ("sites", "extensions"):
        for number, org in bind.execute(
            sa.text(
                f"SELECT emergency_caller_id_number, organization_id FROM {table}"  # noqa: S608
                " WHERE emergency_caller_id_number IS NOT NULL ORDER BY created_at"
            )
        ):
            n = _canonical(number)
            if n is not None and len(n) >= 10:
                candidates.append((n, org))
    rows = []
    for number, org in candidates:
        if number is None or number in owned:
            continue
        owned[number] = org
        rows.append(
            {
                "id": uuid.uuid4(),
                "organization_id": org,
                "first": number,
                "last": number,
                "trunk_id": None,
                "label": None,
                "source": "migration",
                "created_at": now,
                "created_by": "migration 0095",
            }
        )
    if rows:
        table = sa.table(
            "organization_numbers",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("organization_id", postgresql.UUID(as_uuid=True)),
            sa.column("first", sa.String),
            sa.column("last", sa.String),
            sa.column("trunk_id", postgresql.UUID(as_uuid=True)),
            sa.column("label", sa.String),
            sa.column("source", sa.String),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("created_by", sa.String),
        )
        op.bulk_insert(table, rows)


def downgrade() -> None:
    op.drop_index("ix_sip_trunks_organization_id", table_name="sip_trunks")
    op.drop_column("sip_trunks", "organization_id")
    op.drop_index("ix_organization_numbers_organization_id", table_name="organization_numbers")
    op.drop_table("organization_numbers")
