# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extension state (docs/CALL_FEATURES.md §3.2): Do Not Disturb set from the
page or from the phone. The database row is the record; the engine keeps its
own copy (an AstDB key the dialplan reads and a custom device state behind
the BLF hint). The API writes both; a feature code writes the engine's copy
and raises a UserEvent that updates the row; the worker reconciles the two
so a restored backup or a failover never leaves them apart.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.events import Event, bus
from veyra.core.models import Extension, ExtensionState, Organization
from veyra.core.models.base import utcnow
from veyra.telephony.adapter import Capability, EngineUnavailable, NotSupported

log = logging.getLogger("veyra.extension_state")

RING_MIN, RING_MAX, RING_DEFAULT = 5, 120, 30


def get(db: Session, extension_id: uuid.UUID) -> ExtensionState | None:
    return db.get(ExtensionState, extension_id)


def ensure(db: Session, extension: Extension) -> ExtensionState:
    row = db.get(ExtensionState, extension.id)
    if row is None:
        row = ExtensionState(extension_id=extension.id, updated_at=utcnow())
        db.add(row)
        db.flush()
    return row


def out(row: ExtensionState | None) -> dict[str, Any]:
    if row is None:
        return {
            "dnd": False,
            "cf_always": None,
            "cf_busy": None,
            "cf_no_answer": None,
            "fmfm_enabled": False,
            "ring_seconds": RING_DEFAULT,
            "updated_at": None,
            "updated_by": None,
        }
    return {
        "dnd": row.dnd,
        "cf_always": row.cf_always,
        "cf_busy": row.cf_busy,
        "cf_no_answer": row.cf_no_answer,
        "fmfm_enabled": row.fmfm_enabled,
        "ring_seconds": row.ring_seconds,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by": row.updated_by,
    }


def supports(adapter: Any) -> bool:
    try:
        return adapter is not None and Capability.EXTENSION_STATE in adapter.capabilities()
    except Exception:
        return False


def set_dnd(
    db: Session, extension: Extension, on: bool, *, by: str, adapter: Any = None
) -> ExtensionState:
    """From the page or the console: the row, then the engine (best effort; the
    worker's sync catches a failed engine write)."""
    row = ensure(db, extension)
    row.dnd = bool(on)
    row.updated_by = by
    row.updated_at = utcnow()
    db.flush()
    if supports(adapter):
        org = db.get(Organization, extension.organization_id)
        try:
            adapter.set_dnd(org.slug if org else "", extension.number, bool(on))
        except (EngineUnavailable, NotSupported, ValueError) as e:
            log.warning("Do Not Disturb of %s not written to the engine: %s", extension.number, e)
    bus.publish(
        Event(
            "extension.state_changed",
            {
                "extension_id": str(extension.id),
                "organization_id": str(extension.organization_id),
                "number": extension.number,
                "field": "dnd",
                "value": bool(on),
                "by": by,
            },
        )
    )
    return row


def parse_userevent(userevent: dict[str, Any]) -> dict[str, str]:
    """The fields the feature-code dialplan sends: Org, Extension, Field, Value."""
    out: dict[str, str] = {}
    for key in ("Org", "Extension", "Field", "Value"):
        value = userevent.get(key)
        if value is None:
            value = userevent.get(key.lower())
        out[key.lower()] = str(value or "").strip()
    return out


def handle_userevent(db: Session, userevent: dict[str, Any]) -> ExtensionState | None:
    """A phone changed its own state through a feature code; the engine's copy
    is already written by the dialplan, so only the row and the event remain."""
    fields = parse_userevent(userevent)
    if fields["field"] != "dnd" or not fields["extension"]:
        return None
    org = db.scalar(select(Organization).where(Organization.slug == fields["org"]))
    if org is None:
        return None
    ext = db.scalar(
        select(Extension).where(
            Extension.organization_id == org.id, Extension.number == fields["extension"]
        )
    )
    if ext is None:
        return None
    on = fields["value"] in ("1", "true", "on", "yes")
    row = ensure(db, ext)
    row.dnd = on
    row.updated_by = "phone"
    row.updated_at = utcnow()
    db.flush()
    bus.publish(
        Event(
            "extension.state_changed",
            {
                "extension_id": str(ext.id),
                "organization_id": str(ext.organization_id),
                "number": ext.number,
                "field": "dnd",
                "value": on,
                "by": "phone",
            },
        )
    )
    return row


def sync(db: Session, adapter: Any) -> int:
    """Make the engine's Do Not Disturb copies match the rows (worker, every
    pass). Returns how many were corrected."""
    if not supports(adapter):
        return 0
    try:
        engine = adapter.dnd_states()
    except (EngineUnavailable, NotSupported):
        return 0
    slugs = {o.id: o.slug for o in db.scalars(select(Organization))}
    wanted: dict[tuple[str, str], bool] = {}
    for ext, state in db.execute(
        select(Extension, ExtensionState)
        .join(ExtensionState, ExtensionState.extension_id == Extension.id, isouter=True)
        .where(Extension.is_enabled.is_(True))
    ):
        wanted[(slugs.get(ext.organization_id, ""), ext.number)] = bool(state and state.dnd)
    fixed = 0
    for key, on in wanted.items():
        if bool(engine.get(key)) != on:
            try:
                adapter.set_dnd(key[0], key[1], on)
                fixed += 1
            except (EngineUnavailable, NotSupported, ValueError) as e:
                log.warning("Could not sync Do Not Disturb of %s: %s", key[1], e)
    # Keys of extensions that no longer exist are cleared too.
    for key, on in engine.items():
        if on and key not in wanted:
            try:
                adapter.set_dnd(key[0], key[1], False)
                fixed += 1
            except (EngineUnavailable, NotSupported, ValueError):
                pass
    return fixed
