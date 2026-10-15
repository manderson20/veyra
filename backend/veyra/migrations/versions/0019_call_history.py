# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call history (Milestone 10, docs/REPORTING.md §3): calls folded by
linkedid from the CDR file, and their legs.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-15 02:20:19.568553
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calls",
        sa.Column("linkedid", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("from_number", sa.String(length=64), nullable=True),
        sa.Column("from_name", sa.String(length=200), nullable=True),
        sa.Column("to_number", sa.String(length=64), nullable=True),
        sa.Column("did", sa.String(length=64), nullable=True),
        sa.Column("from_extension_id", sa.UUID(), nullable=True),
        sa.Column("to_extension_id", sa.UUID(), nullable=True),
        sa.Column("answered_extension_id", sa.UUID(), nullable=True),
        sa.Column("trunk_id", sa.UUID(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ring_seconds", sa.Integer(), nullable=False),
        sa.Column("talk_seconds", sa.Integer(), nullable=False),
        sa.Column("leg_count", sa.Integer(), nullable=False),
        sa.Column("recording_ref", sa.String(length=64), nullable=True),
        sa.Column("is_final", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["answered_extension_id"],
            ["extensions.id"],
            name=op.f("fk_calls_answered_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["from_extension_id"],
            ["extensions.id"],
            name=op.f("fk_calls_from_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_calls_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["to_extension_id"],
            ["extensions.id"],
            name=op.f("fk_calls_to_extension_id_extensions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["trunk_id"],
            ["sip_trunks.id"],
            name=op.f("fk_calls_trunk_id_sip_trunks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calls")),
        sa.UniqueConstraint("linkedid", name=op.f("uq_calls_linkedid")),
    )
    op.create_index(
        op.f("ix_calls_answered_extension_id"), "calls", ["answered_extension_id"], unique=False
    )
    op.create_index(
        op.f("ix_calls_from_extension_id"), "calls", ["from_extension_id"], unique=False
    )
    op.create_index(op.f("ix_calls_from_number"), "calls", ["from_number"], unique=False)
    op.create_index(
        "ix_calls_organization_id_started_at",
        "calls",
        ["organization_id", "started_at"],
        unique=False,
    )
    op.create_index(op.f("ix_calls_started_at"), "calls", ["started_at"], unique=False)
    op.create_index(op.f("ix_calls_to_extension_id"), "calls", ["to_extension_id"], unique=False)
    op.create_index(op.f("ix_calls_to_number"), "calls", ["to_number"], unique=False)
    op.create_table(
        "call_legs",
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("uniqueid", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=128), nullable=False),
        sa.Column("dstchannel", sa.String(length=128), nullable=False),
        sa.Column("src", sa.String(length=80), nullable=False),
        sa.Column("clid", sa.String(length=200), nullable=False),
        sa.Column("dst", sa.String(length=80), nullable=False),
        sa.Column("dcontext", sa.String(length=80), nullable=False),
        sa.Column("lastapp", sa.String(length=80), nullable=False),
        sa.Column("disposition", sa.String(length=16), nullable=False),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answer", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration", sa.Integer(), nullable=False),
        sa.Column("billsec", sa.Integer(), nullable=False),
        sa.Column("rec", sa.String(length=64), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["call_id"], ["calls.id"], name=op.f("fk_call_legs_call_id_calls"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_legs")),
        sa.UniqueConstraint(
            "call_id",
            "uniqueid",
            "start",
            "dstchannel",
            name=op.f("uq_call_legs_call_id_uniqueid_start_dstchannel"),
        ),
    )
    op.create_index(op.f("ix_call_legs_call_id"), "call_legs", ["call_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_call_legs_call_id"), table_name="call_legs")
    op.drop_table("call_legs")
    op.drop_index(op.f("ix_calls_to_number"), table_name="calls")
    op.drop_index(op.f("ix_calls_to_extension_id"), table_name="calls")
    op.drop_index(op.f("ix_calls_started_at"), table_name="calls")
    op.drop_index("ix_calls_organization_id_started_at", table_name="calls")
    op.drop_index(op.f("ix_calls_from_number"), table_name="calls")
    op.drop_index(op.f("ix_calls_from_extension_id"), table_name="calls")
    op.drop_index(op.f("ix_calls_answered_extension_id"), table_name="calls")
    op.drop_table("calls")
