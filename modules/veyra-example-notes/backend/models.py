# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, Uuid, func

metadata = MetaData()

notes = Table(
    "mod_example_notes_note",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False, index=True),
    Column("title", String(200), nullable=False),
    Column("body", Text, nullable=False, server_default=""),
    Column("created_by", String(320), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
