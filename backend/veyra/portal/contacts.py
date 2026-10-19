# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resolve numbers against a user's personal contacts (docs/USER_PORTAL.md
§6): the call history and the voicemail list show the contact's name
instead of a bare number."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.models import UserContact

_STRIP = re.compile(r"[^0-9+*#]")


def digits(number: str | None) -> str:
    return _STRIP.sub("", number or "")


def names_by_number(db: Session, user_id: uuid.UUID) -> dict[str, str]:
    """Normalized number → contact name; a national number is also keyed by
    its last ten digits so +1 573 555 0100 and 5735550100 both match."""
    out: dict[str, str] = {}
    for row in db.scalars(select(UserContact).where(UserContact.user_id == user_id)):
        for n in row.numbers or []:
            key = digits(str(n.get("number") or ""))
            if not key:
                continue
            out.setdefault(key, row.name)
            tail = key.lstrip("+")
            if len(tail) > 10:
                out.setdefault(tail[-10:], row.name)
    return out


def resolve(names: dict[str, str], number: str | None) -> str | None:
    key = digits(number)
    if not key:
        return None
    if key in names:
        return names[key]
    tail = key.lstrip("+")
    if len(tail) >= 10 and tail[-10:] in names:
        return names[tail[-10:]]
    return None
