# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extension state (docs/CALL_FEATURES.md §3.2, §3.3): Do Not Disturb and the
three call forwards, set from the page or from the phone. The database row
is the record; the engine keeps its own copy (AstDB keys the dialplan reads
and custom device states behind the BLF hints). The API writes both; a
feature code writes the engine's copy and raises a UserEvent that updates
the row; the worker reconciles the two so a restored backup or a failover
never leaves them apart.
"""

from __future__ import annotations

import logging
import re
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
FORWARD_FIELDS = ("cf_always", "cf_busy", "cf_no_answer")
ENGINE_FIELDS = ("dnd", *FORWARD_FIELDS, "fmfm")
# Row attribute -> engine field, where they differ.
_ROW_FIELD = {"fmfm": "fmfm_enabled"}
_NUMBER_RE = re.compile(r"^\+?[0-9]{2,20}$")
# Presence states a user may show (docs/USER_PORTAL.md §7).
PRESENCE_STATES = ("available", "away", "busy", "meeting", "lunch", "out")
PRESENCE_LABELS = {
    "available": "Available",
    "away": "Away",
    "busy": "Busy",
    "meeting": "In a meeting",
    "lunch": "At lunch",
    "out": "Out of the office",
}


class StateError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field, self.message = field, message


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
            "presence": "available",
            "presence_message": None,
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
        "presence": row.presence or "available",
        "presence_message": row.presence_message,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by": row.updated_by,
    }


def set_presence(
    db: Session,
    extension: Extension,
    state: str,
    message: str | None,
    *,
    by: str,
    rules: dict[str, Any] | None = None,
    adapter: Any = None,
) -> dict[str, Any]:
    """Change the presence shown to colleagues and apply the user's automatic
    actions for that state (``rules``: ``{state: {dnd: bool|None, cf_always:
    str|None}}``) through :func:`apply`, so the engine follows at once."""
    if state not in PRESENCE_STATES:
        raise StateError("state", "unknown presence state")
    text = (message or "").strip()[:60] or None
    row = ensure(db, extension)
    changed: dict[str, Any] = {}
    if row.presence != state:
        row.presence = state
        changed["presence"] = state
    if row.presence_message != text:
        row.presence_message = text
        changed["presence_message"] = text
    if changed:
        row.updated_by = by
        row.updated_at = utcnow()
        db.flush()
    actions = (rules or {}).get(state) or {}
    wanted: dict[str, Any] = {}
    if actions.get("dnd") is not None:
        wanted["dnd"] = bool(actions["dnd"])
    if "cf_always" in actions:
        wanted["cf_always"] = actions.get("cf_always") or None
    if wanted:
        changed.update(apply(db, extension, wanted, by=by, adapter=adapter))
    elif changed:
        _publish(extension, changed, by)
    return changed


def normalize_number(field: str, value: Any) -> str | None:
    """A forward target: digits with an optional leading +, or None to clear."""
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"[\s().-]", "", text)
    if not _NUMBER_RE.match(text):
        raise StateError(field, "digits (and a leading +) only, 2 to 20 characters")
    return text


def engine_values(row: ExtensionState) -> dict[str, str | None]:
    """What the engine's copy of a row must hold."""
    return {
        "dnd": "1" if row.dnd else None,
        "cf_always": row.cf_always or None,
        "cf_busy": row.cf_busy or None,
        "cf_no_answer": row.cf_no_answer or None,
        "fmfm": "1" if row.fmfm_enabled else None,
    }


def supports(adapter: Any) -> bool:
    try:
        return adapter is not None and Capability.EXTENSION_STATE in adapter.capabilities()
    except Exception:
        return False


def _publish(extension: Extension, changes: dict[str, Any], by: str) -> None:
    bus.publish(
        Event(
            "extension.state_changed",
            {
                "extension_id": str(extension.id),
                "organization_id": str(extension.organization_id),
                "number": extension.number,
                "changes": changes,
                "by": by,
            },
        )
    )


def apply(
    db: Session,
    extension: Extension,
    changes: dict[str, Any],
    *,
    by: str,
    adapter: Any = None,
) -> dict[str, Any]:
    """Change ``dnd`` and/or the forwards from the page or the console: the
    row, then the engine (best effort; the worker's sync catches a failed
    engine write). Returns what actually changed."""
    row = ensure(db, extension)
    applied: dict[str, Any] = {}
    if "dnd" in changes and changes["dnd"] is not None and bool(changes["dnd"]) != row.dnd:
        row.dnd = bool(changes["dnd"])
        applied["dnd"] = row.dnd
    if (
        "fmfm_enabled" in changes
        and changes["fmfm_enabled"] is not None
        and bool(changes["fmfm_enabled"]) != row.fmfm_enabled
    ):
        row.fmfm_enabled = bool(changes["fmfm_enabled"])
        applied["fmfm"] = row.fmfm_enabled
    for field in FORWARD_FIELDS:
        if field in changes:
            value = normalize_number(field, changes[field])
            if value != getattr(row, field):
                setattr(row, field, value)
                applied[field] = value
    if not applied:
        return applied
    row.updated_by = by
    row.updated_at = utcnow()
    db.flush()
    if supports(adapter):
        org = db.get(Organization, extension.organization_id)
        slug = org.slug if org else ""
        values = engine_values(row)
        for field in applied:
            try:
                adapter.set_extension_state(slug, extension.number, field, values[field])
            except (EngineUnavailable, NotSupported, ValueError) as e:
                log.warning("%s of %s not written to the engine: %s", field, extension.number, e)
    _publish(extension, applied, by)
    return applied


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
    field = fields["field"]
    if field not in ENGINE_FIELDS or not fields["extension"]:
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
    row = ensure(db, ext)
    if field in ("dnd", "fmfm"):
        value: Any = fields["value"] in ("1", "true", "on", "yes")
        setattr(row, _ROW_FIELD.get(field, field), value)
    else:
        try:
            value = normalize_number(field, fields["value"])
        except StateError:
            return None
        setattr(row, field, value)
    row.updated_by = "phone"
    row.updated_at = utcnow()
    db.flush()
    _publish(ext, {field: value}, "phone")
    return row


def sync(db: Session, adapter: Any) -> int:
    """Make the engine's copies match the rows (worker, every pass). Returns
    how many fields were corrected."""
    if not supports(adapter):
        return 0
    try:
        engine = adapter.extension_states()
    except (EngineUnavailable, NotSupported):
        return 0
    slugs = {o.id: o.slug for o in db.scalars(select(Organization))}
    wanted: dict[tuple[str, str], dict[str, str | None]] = {}
    for ext, state in db.execute(
        select(Extension, ExtensionState)
        .join(ExtensionState, ExtensionState.extension_id == Extension.id, isouter=True)
        .where(Extension.is_enabled.is_(True))
    ):
        key = (slugs.get(ext.organization_id, ""), ext.number)
        wanted[key] = engine_values(state) if state else dict.fromkeys(ENGINE_FIELDS)
    fixed = 0
    for key, values in wanted.items():
        have = engine.get(key, {})
        for field, value in values.items():
            if (have.get(field) or None) != value:
                try:
                    adapter.set_extension_state(key[0], key[1], field, value)
                    fixed += 1
                except (EngineUnavailable, NotSupported, ValueError) as e:
                    log.warning("Could not sync %s of %s: %s", field, key[1], e)
    # Keys of extensions that no longer exist are cleared too.
    for key, have in engine.items():
        if key in wanted:
            continue
        for field in have:
            try:
                adapter.set_extension_state(key[0], key[1], field, None)
                fixed += 1
            except (EngineUnavailable, NotSupported, ValueError):
                pass
    return fixed
