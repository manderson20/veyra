# SPDX-License-Identifier: AGPL-3.0-or-later
"""Presence from the user's calendar (issue #136; docs/USER_PORTAL.md §7).

The user gives the secret iCal address of their calendar (Google: "Secret
address in iCal format"; Outlook: a published ICS link). Every few minutes
the worker reads it: while a timed event is on, an *available* user shows
*in a meeting* (with the user's automatic actions for that state); when it
ends, the calendar puts back *available* — only if the calendar set the
meeting, so a state the user chose by hand is never overwritten. All-day
events are ignored. The address is stored encrypted (it is a secret) in a
system setting per user, and only https addresses of public hosts are
fetched, so a user cannot make the server read internal addresses.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import urllib.parse
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.bells import calendars
from veyra.core.models import Extension, ExtensionState, SystemSetting, UserPreference
from veyra.core.models.base import utcnow
from veyra.core.security.crypto import InstallationKey

log = logging.getLogger("veyra.presence")

KEY_PREFIX = "presence.calendar:"
INTERVAL = timedelta(minutes=5)
MEETING = "meeting"
AVAILABLE = "available"


class CalendarAddressError(ValueError):
    pass


def setting_key(user_id: uuid.UUID) -> str:
    return f"{KEY_PREFIX}{user_id}"


def purpose(user_id: uuid.UUID) -> str:
    return f"presence.calendar_url:{user_id}"


def check_public_url(url: str) -> str:
    """https (webcal accepted) to a host whose every address is public."""
    try:
        url = calendars.check_url(url)
    except calendars.CalendarError as e:
        raise CalendarAddressError(str(e)) from e
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise CalendarAddressError("use the calendar's https address")
    host = parts.hostname or ""
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as e:
        raise CalendarAddressError(f"the calendar's host {host} is not known") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise CalendarAddressError("only calendars on the internet can be used")
    return url


def load(db: Session, user_id: uuid.UUID) -> dict[str, Any]:
    row = db.get(SystemSetting, setting_key(user_id))
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


def save(db: Session, user_id: uuid.UUID, value: dict[str, Any] | None) -> None:
    row = db.get(SystemSetting, setting_key(user_id))
    if value is None:
        if row is not None:
            db.delete(row)
        return
    if row is None:
        db.add(SystemSetting(key=setting_key(user_id), value=value))
    else:
        row.value = value


def current_event(data: bytes, now: datetime, tz: str | None = None) -> calendars.Occurrence | None:
    """The timed event going on at ``now``, if any."""
    for occ in calendars.expand(data, start=now - timedelta(hours=12), end=now, default_tz=tz):
        if occ.all_day or occ.ends_at is None:
            continue
        if occ.starts_at <= now < occ.ends_at:
            return occ
    return None


def _rules(db: Session, user_id: uuid.UUID) -> dict[str, Any]:
    prefs = db.get(UserPreference, user_id)
    portal = ((prefs.data or {}) if prefs else {}).get("portal") or {}
    return dict(portal.get("presence_rules") or {})


def apply(db: Session, user_id: uuid.UUID, busy: bool, adapter: Any = None) -> list[str]:
    """Meeting on or off for the user's extensions; returns the changed numbers."""
    from veyra.telephony import extension_state

    changed: list[str] = []
    rules = _rules(db, user_id)
    cfg = load(db, user_id)
    for ext in db.scalars(select(Extension).where(Extension.user_id == user_id)):
        row = db.get(ExtensionState, ext.id)
        presence = row.presence if row is not None else AVAILABLE
        if busy and presence == AVAILABLE:
            extension_state.set_presence(
                db, ext, MEETING, "In a meeting", by="calendar", rules=rules, adapter=adapter
            )
            changed.append(ext.number)
        elif not busy and presence == MEETING and cfg.get("set_meeting"):
            extension_state.set_presence(
                db, ext, AVAILABLE, None, by="calendar", rules=rules, adapter=adapter
            )
            changed.append(ext.number)
    cfg["set_meeting"] = busy if busy else False
    save(db, user_id, cfg)
    return changed


def process(
    db: Session,
    key: InstallationKey | None,
    adapter: Any = None,
    now: datetime | None = None,
    fetch: Any = None,
) -> int:
    """One pass over the users whose check is due."""
    if key is None:
        return 0
    now = now or utcnow()
    fetch = fetch or calendars.fetch
    done = 0
    for row in db.scalars(
        select(SystemSetting).where(SystemSetting.key.like(f"{KEY_PREFIX}%"))
    ).all():
        cfg = dict(row.value or {})
        last = cfg.get("checked_at")
        if last and now - datetime.fromisoformat(last) < INTERVAL:
            continue
        user_id = uuid.UUID(row.key[len(KEY_PREFIX) :])
        cfg["checked_at"] = now.isoformat()
        try:
            url = key.decrypt(str(cfg.get("url_enc") or ""), purpose(user_id))
            event = current_event(fetch(check_public_url(url)), now, cfg.get("timezone"))
        except Exception as e:  # one broken calendar never stops the others
            cfg["error"] = str(e)[:300]
            row.value = cfg
            db.commit()
            continue
        cfg.pop("error", None)
        cfg["in_meeting"] = event is not None
        row.value = cfg
        db.flush()
        apply(db, user_id, event is not None, adapter)
        db.commit()
        done += 1
    return done
