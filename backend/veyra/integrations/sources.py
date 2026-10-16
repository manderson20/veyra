# SPDX-License-Identifier: AGPL-3.0-or-later
"""Webhook events that need more than one line at their source
(docs/INTEGRATIONS.md §3.2): live call events from the ARI stream, finished
calls from the call history, voicemail notifications and phone registrations."""

from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.callevents import CallEvent
from veyra.core.models import (
    CallRecord,
    Extension,
    SipTrunk,
    SystemSetting,
    VoicemailBox,
)
from veyra.integrations import webhooks

log = logging.getLogger("veyra.webhooks")

VM_SUFFIX = ".vmevent"
VM_COUNTS_KEY = "webhooks.voicemail_counts"
REG_STATE_KEY = "webhooks.registrations"
_LIVE_CACHE_SECONDS = 30.0
_live_cache: dict[str, tuple[float, bool]] = {}


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


# --------------------------------------------------------------------------- live calls


def _live_wanted(db: Session, event: str) -> bool:
    now = time.monotonic()
    cached = _live_cache.get(event)
    if cached and now - cached[0] < _LIVE_CACHE_SECONDS:
        return cached[1]
    wanted = webhooks.subscribed(db, event)
    _live_cache[event] = (now, wanted)
    return wanted


def call_live(db: Session, ce: CallEvent) -> int:
    """``call.ringing`` / ``call.answered`` for an extension's phone."""
    if ce.type not in ("call.ringing", "call.answered") or not _live_wanted(db, ce.type):
        return 0
    ext = db.scalar(select(Extension).where(Extension.endpoint_name == ce.endpoint))
    if ext is None:
        return 0
    n = webhooks.emit(
        db,
        ext.organization_id,
        ce.type,
        {
            "call_id": ce.channel_id,
            "extension": {"number": ext.number, "name": ext.display_name},
            "direction": "inbound" if ce.direction == "in" else "outbound",
            "remote": {"number": ce.remote_number, "name": ce.remote_name},
        },
    )
    db.commit()
    return n


# --------------------------------------------------------------------------- call history


def call_ended(db: Session, call: CallRecord) -> int:
    ids = {
        i for i in (call.from_extension_id, call.to_extension_id, call.answered_extension_id) if i
    }
    exts = (
        {e.id: e for e in db.scalars(select(Extension).where(Extension.id.in_(ids)))} if ids else {}
    )

    def ext(i: uuid.UUID | None) -> dict[str, str] | None:
        e = exts.get(i) if i else None
        return {"number": e.number, "name": e.display_name} if e else None

    trunk = db.get(SipTrunk, call.trunk_id) if call.trunk_id else None
    return webhooks.emit(
        db,
        call.organization_id,
        "call.ended",
        {
            "call_id": call.linkedid,
            "direction": call.direction,
            "outcome": call.outcome,
            "from": {"number": call.from_number, "name": call.from_name},
            "to": {"number": call.to_number},
            "did": call.did,
            "from_extension": ext(call.from_extension_id),
            "to_extension": ext(call.to_extension_id),
            "answered_by": ext(call.answered_extension_id),
            "trunk": trunk.name if trunk else None,
            "queue": call.queue,
            "ring_group": call.ring_group,
            "started_at": _iso(call.started_at),
            "answered_at": _iso(call.answered_at),
            "ended_at": _iso(call.ended_at),
            "ring_seconds": call.ring_seconds,
            "talk_seconds": call.talk_seconds,
        },
        occurred_at=call.ended_at,
    )


# --------------------------------------------------------------------------- voicemail

_VM_LINE = re.compile(r"^(\S+) (\d+) (\d+) (\d+) (\d+)$")


def _setting(db: Session, key: str) -> dict[str, Any]:
    row = db.get(SystemSetting, key)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


def _save_setting(db: Session, key: str, value: dict[str, Any]) -> None:
    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value


def voicemail_notifications(db: Session, queue_dir: Path, limit: int = 200) -> int:
    """Read the files ``veyra-vmnotify`` (Asterisk's ``externnotify``) leaves in
    the mail queue directory; a rising count of new messages is a new message."""
    if not queue_dir.is_dir():
        return 0
    files = sorted(queue_dir.glob(f"*{VM_SUFFIX}"))[:limit]
    if not files:
        return 0
    counts = _setting(db, VM_COUNTS_KEY)
    emitted = 0
    for f in files:
        try:
            line = f.read_text(encoding="utf-8", errors="replace").strip()
            f.unlink()
        except OSError:
            log.exception("Cannot read voicemail notification %s", f.name)
            continue
        # "<context> <mailbox> <new> <old> <urgent>" as written by the script.
        m = _VM_LINE.match(line)
        if m is None:
            continue
        number, new, old, urgent = m.group(2), int(m.group(3)), int(m.group(4)), int(m.group(5))
        before = int(counts.get(number, 0))
        counts[number] = new
        if new <= before:
            continue
        box = db.scalar(select(VoicemailBox).where(VoicemailBox.number == number))
        name = box.name if box is not None else None
        if box is None:
            # An extension's own box is numbered after the extension.
            ext = db.scalar(select(Extension).where(Extension.number == number))
            box = (
                db.scalar(select(VoicemailBox).where(VoicemailBox.extension_id == ext.id))
                if ext is not None
                else None
            )
            name = ext.display_name if ext is not None else None
        if box is None:
            continue
        emitted += webhooks.emit(
            db,
            box.organization_id,
            "voicemail.message",
            {
                "box": {"number": number, "name": name},
                "new_messages": new,
                "old_messages": old,
                "urgent_messages": urgent,
            },
        )
    _save_setting(db, VM_COUNTS_KEY, counts)
    db.commit()
    return emitted


# --------------------------------------------------------------------------- registrations


def registrations(db: Session, adapter: Any) -> int:
    """Compare phone registrations with the last pass (worker, once a minute)."""
    if not webhooks.subscribed(db, "registration.changed"):
        return 0
    try:
        statuses = adapter.endpoint_statuses()
    except Exception:
        return 0
    # Where each endpoint registers from (CALL_FEATURES.md §2.1), when the
    # engine can say; the event then carries the source and contact addresses.
    details: dict[str, Any] = {}
    caps: set[Any] = getattr(adapter, "capabilities", lambda: set())()
    if "registrations" in {str(c) for c in caps}:
        try:
            for r in adapter.registrations():
                details.setdefault(r.endpoint, r)
        except Exception:
            details = {}
    previous = _setting(db, REG_STATE_KEY)
    first = not previous
    current: dict[str, Any] = {}
    changed: list[tuple[str, Any]] = []
    for s in statuses:
        name = s.endpoint
        registered = bool(s.registered)
        d = details.get(name)
        address = s.contacts[0] if s.contacts else None
        if d is not None and d.source_host:
            address = f"{d.source_host}:{d.source_port}" if d.source_port else d.source_host
        current[name] = {
            "registered": registered,
            "address": address,
            "contact_address": (
                f"{d.contact_host}:{d.contact_port}"
                if d and d.contact_host and d.contact_port
                else (d.contact_host if d else None)
            ),
            "nat": bool(d.nat) if d else False,
        }
        before = previous.get(name)
        if not first and (before is None or before.get("registered") != registered):
            if before is None and not registered:
                continue
            changed.append((name, s))
    _save_setting(db, REG_STATE_KEY, {"_": True, **current})
    emitted = 0
    for name, s in changed:
        ext = db.scalar(select(Extension).where(Extension.endpoint_name == name))
        if ext is None:
            continue
        emitted += webhooks.emit(
            db,
            ext.organization_id,
            "registration.changed",
            {
                "extension": {"number": ext.number, "name": ext.display_name},
                "registered": current[name]["registered"],
                "address": current[name]["address"],
                "contact_address": current[name].get("contact_address"),
                "nat": current[name].get("nat", False),
                "user_agent": (details[name].user_agent if name in details else None)
                or s.user_agent,
            },
        )
    db.commit()
    return emitted


# --------------------------------------------------------------------------- module events


def module_event(event: Any) -> None:
    """Bus handler: events modules publish (``ctx.publish``) go to webhooks that
    subscribe to them. Core events have their own sources above."""
    if getattr(event, "source", "core") == "core":
        return
    from veyra.core.db import session_scope

    try:
        with session_scope() as db:
            if not webhooks.subscribed(db, event.name):
                return
            data = dict(event.payload or {})
            org = data.get("organization_id")
            try:
                org_id = uuid.UUID(str(org)) if org else None
            except ValueError:
                org_id = None
            data["module"] = event.source
            if org_id is not None:
                webhooks.emit(db, org_id, event.name, data, occurred_at=event.occurred_at)
            else:
                webhooks.emit_all(db, event.name, data)
    except Exception:
        log.exception("Could not queue webhook for module event %s", getattr(event, "name", "?"))


def subscribe(bus: Any) -> None:
    bus.unsubscribe_owner("webhooks")
    bus.subscribe("*", module_event, owner="webhooks")
