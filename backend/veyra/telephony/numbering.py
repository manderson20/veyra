# SPDX-License-Identifier: AGPL-3.0-or-later
"""The extension numbering plan.

One installation-wide plan (``system_settings`` key ``telephony.numbering``)
says how long extension numbers are, which range they come from and which
leading digits are kept free: ``0`` for an operator, ``9`` for outside
lines and the emergency numbers (``911``, ``933`` for the test line) so no
extension can ever shadow them. Feature codes start with ``*`` and never
collide with extensions.

Multi-tenancy (Milestone 14) may add per-organization ranges; until then
numbers are unique across the installation because every extension lives in
the same dialplan context.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from veyra.core.models import SystemSetting

NUMBERING_KEY = "telephony.numbering"
MIN_LENGTH = 3
MAX_LENGTH = 6
# Reserved by default: operator, outside line, emergency and the emergency test number.
DEFAULT_RESERVED = ["0", "9", "911", "933"]
_DIGITS_RE = re.compile(r"^[0-9]+$")
# Upper bound for scanning the range when suggesting a free number.
_SCAN_LIMIT = 1_000_000


class NumberingPlan(BaseModel):
    extension_length: int = Field(4, ge=MIN_LENGTH, le=MAX_LENGTH)
    first_extension: str = Field("1000", min_length=MIN_LENGTH, max_length=MAX_LENGTH)
    last_extension: str = Field("7999", min_length=MIN_LENGTH, max_length=MAX_LENGTH)
    reserved_prefixes: list[str] = Field(default_factory=lambda: list(DEFAULT_RESERVED))

    @field_validator("first_extension", "last_extension")
    @classmethod
    def _digits(cls, v: str) -> str:
        v = v.strip()
        if not _DIGITS_RE.match(v):
            raise ValueError("must contain digits only")
        return v

    @field_validator("reserved_prefixes")
    @classmethod
    def _prefixes(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for p in v:
            p = p.strip()
            if not p:
                continue
            if not _DIGITS_RE.match(p) or len(p) > MAX_LENGTH:
                raise ValueError(f"reserved prefix {p!r} must be 1 to {MAX_LENGTH} digits")
            if p not in out:
                out.append(p)
        return out

    # --- checks ---------------------------------------------------------------

    def problems(self) -> list[str]:
        """Cross-field problems that make the plan unusable."""
        out: list[str] = []
        for label, value in (("first", self.first_extension), ("last", self.last_extension)):
            if len(value) != self.extension_length:
                out.append(
                    f"The {label} extension {value} does not have {self.extension_length} digits."
                )
        if not out and int(self.last_extension) < int(self.first_extension):
            out.append("The last extension must not be lower than the first.")
        if not out and self.next_available(()) is None:
            out.append("Every number in the range starts with a reserved prefix.")
        return out

    def is_reserved(self, number: str) -> str | None:
        """The reserved prefix a number starts with, or None."""
        for p in self.reserved_prefixes:
            if number.startswith(p):
                return p
        return None

    def check_number(self, number: str) -> list[str]:
        """Why a number is not acceptable under this plan (empty = acceptable)."""
        out: list[str] = []
        if not _DIGITS_RE.match(number):
            return ["Extension numbers contain digits only."]
        if len(number) != self.extension_length:
            out.append(f"Extension numbers have {self.extension_length} digits.")
            return out
        if not int(self.first_extension) <= int(number) <= int(self.last_extension):
            out.append(
                f"Extensions are numbered from {self.first_extension} to {self.last_extension}."
            )
        reserved = self.is_reserved(number)
        if reserved:
            out.append(f"Numbers starting with {reserved} are reserved.")
        return out

    def next_available(self, used: Iterable[str], after: str | None = None) -> str | None:
        """The lowest free number in the range, optionally above ``after``."""
        taken = set(used)
        width = self.extension_length
        start = int(self.first_extension)
        if after and _DIGITS_RE.match(after):
            start = max(start, int(after) + 1)
        end = min(int(self.last_extension), start + _SCAN_LIMIT)
        for n in range(start, end + 1):
            candidate = str(n).zfill(width)
            if len(candidate) != width:
                break
            if candidate in taken or self.is_reserved(candidate):
                continue
            return candidate
        return None

    def describe(self) -> str:
        reserved = ", ".join(self.reserved_prefixes) or "none"
        return (
            f"{self.extension_length}-digit numbers from {self.first_extension} to "
            f"{self.last_extension}; reserved leading digits: {reserved}"
        )


def load_numbering_plan(db: Session) -> NumberingPlan:
    row = db.get(SystemSetting, NUMBERING_KEY)
    if row is None or not isinstance(row.value, dict):
        return NumberingPlan()
    return NumberingPlan.model_validate(row.value)


def save_numbering_plan(db: Session, plan: NumberingPlan, updated_by: Any = None) -> None:
    row = db.get(SystemSetting, NUMBERING_KEY)
    value = plan.model_dump(mode="json")
    if row is None:
        db.add(SystemSetting(key=NUMBERING_KEY, value=value, updated_by=updated_by))
    else:
        row.value = value
        row.updated_by = updated_by
    db.flush()


# --- the shared number space --------------------------------------------------


def used_numbers(db: Session) -> set[str]:
    """Every number taken by an extension, a ring group or a queue."""
    from sqlalchemy import select

    from veyra.core.models import CallQueue, Extension, Page, PagingZone, RingGroup

    used: set[str] = set()
    for column in (
        Extension.number,
        RingGroup.number,
        CallQueue.number,
        PagingZone.number,
        Page.number,
    ):
        used |= {n for n in db.scalars(select(column)).all() if n}
    return used


def number_owner(db: Session, number: str, *, exclude: tuple[str, Any] | None = None) -> str | None:
    """What already uses ``number``: ``"extension"``, ``"ring group"``,
    ``"queue"``, ``"paging zone"`` or ``"page"``; None when it is free. Takes
    the advisory lock that serialises concurrent creations of the same number
    across the tables.
    ``exclude`` is ``(kind, id)`` of the object being edited."""
    from sqlalchemy import select, text

    from veyra.core.models import CallQueue, Extension, Page, PagingZone, RingGroup

    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"veyra.extension:{number}"}
    )
    for kind, model in (
        ("extension", Extension),
        ("ring group", RingGroup),
        ("queue", CallQueue),
        ("paging zone", PagingZone),
        ("page", Page),
    ):
        stmt = select(model.id).where(model.number == number)
        if exclude is not None and exclude[0] == kind:
            stmt = stmt.where(model.id != exclude[1])
        if db.scalar(stmt) is not None:
            return kind
    return None
