# SPDX-License-Identifier: AGPL-3.0-or-later
"""Module catalog sources (docs/MODULE_CATALOG.md §3): signed index URLs and
the last verified copy of each, so the catalog page works offline."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, Timestamps, UUIDPrimaryKey


class CatalogSource(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "module_catalog_sources"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    url: Mapped[str] = mapped_column(String(500), unique=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # The last index that verified, and the key that signed it.
    index: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    signed_by: Mapped[str | None] = mapped_column(String(64))
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(16))  # ok | failed
    last_error: Mapped[str | None] = mapped_column(Text)
