# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caller block list (docs/CALL_FEATURES.md §4.8). The rows are the truth;
the engine's store (``veyra/blacklist/<org>/<number>`` = ``1``) is what the
inbound routes consult at call time. The API writes both, phones add and
remove numbers through feature codes (``UserEvent(VeyraBlacklist)``), the
dialplan reports blocked calls (``UserEvent(VeyraBlocked)``) and the
worker's sync keeps the store in step with the rows."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.events import Event, bus
from veyra.core.models import CallerBlock, CallerBlockPolicy, Organization
from veyra.core.models.base import utcnow
from veyra.telephony.adapter import Capability, EngineUnavailable, NotSupported

log = logging.getLogger("veyra.blacklist")

FAMILY = "veyra/blacklist"
LASTCID_FAMILY = "veyra/lastcid"
BLACKLIST_EVENT = "VeyraBlacklist"
BLOCKED_EVENT = "VeyraBlocked"
# What the dialplan treats as a withheld number.
ANONYMOUS_VALUES = ("", "anonymous", "restricted", "unavailable", "unknown", "private")
_NUMBER_RE = re.compile(r"^\+?[0-9]{2,32}$")


class BlockError(ValueError):
    pass


def normalize(number: str) -> str:
    """Digits with an optional leading +; spaces, dashes and brackets dropped."""
    cleaned = re.sub(r"[\s().-]", "", str(number or ""))
    if not _NUMBER_RE.match(cleaned):
        raise BlockError("a number is 2 to 32 digits, optionally with a leading +")
    return cleaned


def family(org_slug: str) -> str:
    return f"{FAMILY}/{org_slug}"


def supports(adapter: Any) -> bool:
    try:
        return adapter is not None and Capability.EXTENSION_STATE in adapter.capabilities()
    except Exception:
        return False


def _write(adapter: Any, org_slug: str, number: str, present: bool) -> None:
    if not supports(adapter):
        return
    try:
        adapter.store_put(family(org_slug), number, "1" if present else None)
    except (EngineUnavailable, NotSupported, ValueError) as e:
        log.warning("Block list entry %s/%s not written to the engine: %s", org_slug, number, e)


def policy_for(db: Session, organization_id: Any, create: bool = False) -> CallerBlockPolicy | None:
    row = db.scalar(
        select(CallerBlockPolicy).where(CallerBlockPolicy.organization_id == organization_id)
    )
    if row is None and create:
        row = CallerBlockPolicy(organization_id=organization_id, block_anonymous=False)
        db.add(row)
        db.flush()
    return row


def add(
    db: Session,
    org: Organization,
    number: str,
    *,
    description: str | None = None,
    source: str = "api",
    adapter: Any = None,
) -> tuple[CallerBlock, bool]:
    """Block a number; returns (row, created). An existing row keeps its hits
    and takes a new description when one is given."""
    number = normalize(number)
    row = db.scalar(
        select(CallerBlock).where(
            CallerBlock.organization_id == org.id, CallerBlock.number == number
        )
    )
    created = row is None
    if row is None:
        row = CallerBlock(
            organization_id=org.id, number=number, description=description, source=source
        )
        db.add(row)
    elif description:
        row.description = description
    db.flush()
    _write(adapter, org.slug, number, True)
    bus.publish(
        Event(
            "caller_block.added",
            {"organization_id": str(org.id), "number": number, "source": source},
        )
    )
    return row, created


def remove(db: Session, org: Organization, row: CallerBlock, *, adapter: Any = None) -> None:
    number = row.number
    db.delete(row)
    db.flush()
    _write(adapter, org.slug, number, False)
    bus.publish(Event("caller_block.removed", {"organization_id": str(org.id), "number": number}))


# ----------------------------------------------------------------- events


def _fields(userevent: dict[str, Any], names: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in names:
        value = userevent.get(key)
        if value is None:
            value = userevent.get(key.lower())
        out[key.lower()] = str(value or "").strip()
    return out


def handle_blacklist_event(db: Session, userevent: dict[str, Any]) -> bool:
    """A phone added or removed a number (the store is already written by the
    dialplan); returns whether a row changed."""
    f = _fields(userevent, ("Action", "Org", "Number", "By"))
    org = db.scalar(select(Organization).where(Organization.slug == f["org"]))
    if org is None:
        return False
    try:
        number = normalize(f["number"])
    except BlockError:
        return False
    if f["action"] == "add":
        _, created = add(
            db,
            org,
            number,
            description=f"Blocked from extension {f['by']}" if f["by"] else None,
            source="phone",
            adapter=None,
        )
        return created
    if f["action"] == "remove":
        row = db.scalar(
            select(CallerBlock).where(
                CallerBlock.organization_id == org.id, CallerBlock.number == number
            )
        )
        if row is None:
            return False
        remove(db, org, row, adapter=None)
        return True
    return False


def handle_blocked_event(db: Session, userevent: dict[str, Any]) -> bool:
    """A call was refused: count it on the number (or the anonymous counter)."""
    f = _fields(userevent, ("Org", "Number", "Did"))
    org = db.scalar(select(Organization).where(Organization.slug == f["org"]))
    if org is None:
        return False
    row = None
    if f["number"] and f["number"].lower() not in ANONYMOUS_VALUES:
        row = db.scalar(
            select(CallerBlock).where(
                CallerBlock.organization_id == org.id, CallerBlock.number == f["number"]
            )
        )
    if row is not None:
        row.hits = int(row.hits or 0) + 1
        row.last_hit_at = utcnow()
    else:
        policy = policy_for(db, org.id, create=True)
        assert policy is not None
        policy.anonymous_hits = int(policy.anonymous_hits or 0) + 1
    db.flush()
    bus.publish(
        Event(
            "caller_block.hit",
            {"organization_id": str(org.id), "number": f["number"], "did": f["did"]},
        )
    )
    return True


# ----------------------------------------------------------------- sync


def wanted(db: Session) -> dict[str, set[str]]:
    """organization slug -> the numbers that should be in its store family."""
    slugs = {o.id: o.slug for o in db.scalars(select(Organization))}
    out: dict[str, set[str]] = {slug: set() for slug in slugs.values()}
    for row in db.scalars(select(CallerBlock)):
        slug = slugs.get(row.organization_id)
        if slug:
            out.setdefault(slug, set()).add(row.number)
    return out


def sync(db: Session, adapter: Any) -> int:
    """Make every organization's store family match its rows (worker, every
    pass). Returns how many entries were corrected."""
    if not supports(adapter):
        return 0
    fixed = 0
    for slug, numbers in wanted(db).items():
        try:
            have = set(adapter.store_entries(family(slug)))
        except (EngineUnavailable, NotSupported, ValueError):
            continue
        for number in numbers - have:
            try:
                adapter.store_put(family(slug), number, "1")
                fixed += 1
            except (EngineUnavailable, NotSupported, ValueError) as e:
                log.warning("Could not sync block list entry %s/%s: %s", slug, number, e)
        for number in have - numbers:
            try:
                adapter.store_put(family(slug), number, None)
                fixed += 1
            except (EngineUnavailable, NotSupported, ValueError):
                pass
    return fixed
