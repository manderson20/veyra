# SPDX-License-Identifier: AGPL-3.0-or-later
"""Missed-call email (docs/USER_PORTAL.md §5; issue #136): a short message
for each call to a user's extension nobody answered, when the user turned it
on in My Phone (``portal.missed_call_email``). Voicemail has its own email."""

from __future__ import annotations

import logging
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core import mail
from veyra.core.models import (
    CallRecord,
    Extension,
    Installation,
    Organization,
    User,
    UserPreference,
)

log = logging.getLogger("veyra.reporting")


def _wants(db: Session, user_id: object) -> bool:
    row = db.get(UserPreference, user_id)
    portal = (row.data or {}).get("portal") if row else None
    return bool(isinstance(portal, dict) and portal.get("missed_call_email"))


def notify(db: Session, calls: list[CallRecord], queue_dir: Path) -> int:
    """Queue one email per missed call whose extension's user wants it."""
    missed = [c for c in calls if c.outcome == "missed" and c.to_extension_id]
    if not missed:
        return 0
    smtp = mail.load_smtp_settings(db)
    if not smtp.enabled or smtp.problems():
        return 0
    inst = db.scalar(select(Installation))
    from_address, from_name = mail.sender(smtp, inst.name if inst else "Veyra")
    sent = 0
    for call in missed:
        ext = db.get(Extension, call.to_extension_id)
        if ext is None or ext.user_id is None:
            continue
        user = db.get(User, ext.user_id)
        if user is None or not user.is_active or not user.email or not _wants(db, user.id):
            continue
        org = db.get(Organization, ext.organization_id)
        try:
            tz = ZoneInfo(org.timezone if org and org.timezone else "UTC")
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
        when = call.started_at.astimezone(tz)
        caller = call.from_name or call.from_number or "an unknown caller"
        number = call.from_number if call.from_name and call.from_number else ""
        msg = mail.compose(
            from_address=from_address,
            from_name=from_name,
            to=user.email,
            subject=f"Missed call from {caller}",
            text=(
                f"{caller}{f' ({number})' if number else ''} called extension {ext.number} "
                f"on {when:%A %d %B at %H:%M} and nobody answered.\n\n"
                "Call back from My Phone (Recent calls), or turn these emails off there.\n"
            ),
        )
        mail.enqueue(queue_dir, msg.as_bytes())
        sent += 1
    if sent:
        log.info("Queued %d missed-call emails", sent)
    return sent
