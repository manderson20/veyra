# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wake-up call list of one extension, for the administrator's and the
user's endpoints (issue #392)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.errors import conflict, not_found
from veyra.core.models import Extension, WakeupCall
from veyra.telephony import wakeup


class WakeupIn(BaseModel):
    time: str
    daily: bool = False

    @field_validator("time")
    @classmethod
    def _time(cls, v: str) -> str:
        v = v.replace(":", "").strip()
        if not wakeup.valid_time(v):
            raise ValueError("enter a time such as 06:30")
        return v


class WakeupOut(BaseModel):
    id: uuid.UUID
    time: str
    daily: bool
    next_at: datetime | None
    attempts: int
    last_result: str | None
    created_by: str | None


def out(row: WakeupCall) -> WakeupOut:
    return WakeupOut(
        id=row.id,
        time=f"{row.hhmm[:2]}:{row.hhmm[2:]}",
        daily=row.daily,
        next_at=row.next_at,
        attempts=row.attempts,
        last_result=row.last_result,
        created_by=row.created_by,
    )


def listing(db: Session, ext: Extension) -> list[WakeupOut]:
    rows = db.scalars(
        select(WakeupCall).where(WakeupCall.extension_id == ext.id).order_by(WakeupCall.hhmm)
    )
    return [out(r) for r in rows]


def add(db: Session, ext: Extension, body: WakeupIn, by: str) -> WakeupOut:
    row = wakeup.schedule(db, ext, body.time, daily=body.daily, by=by)
    if row is None:
        raise conflict(
            f"This phone already has {wakeup.MAX_PER_EXTENSION} wake-up calls.", "wakeup_limit"
        )
    return out(row)


def remove(db: Session, ext: Extension, call_id: uuid.UUID) -> None:
    row = db.get(WakeupCall, call_id)
    if row is None or row.extension_id != ext.id:
        raise not_found("Wake-up call")
    db.delete(row)
