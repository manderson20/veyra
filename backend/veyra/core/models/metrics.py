# SPDX-License-Identifier: AGPL-3.0-or-later
"""Telephony samples for the dashboard graphs (docs/INTERFACE_REWORK.md §2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, UUIDPrimaryKey


class CallSample(UUIDPrimaryKey, Base):
    """One reading of the engine every worker iteration: channels (``Local/``
    legs excluded), external calls (trunk legs), the internal estimate and
    registered extensions. Kept 14 days."""

    __tablename__ = "call_samples"

    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    channels: Mapped[int] = mapped_column(Integer)
    calls_internal: Mapped[int] = mapped_column(Integer)
    calls_external: Mapped[int] = mapped_column(Integer)
    registrations: Mapped[int] = mapped_column(Integer)
    # Phones the engine knows (registered or not); NULL before 0.26.5.
    endpoints: Mapped[int | None] = mapped_column(Integer)
