# SPDX-License-Identifier: AGPL-3.0-or-later
"""Emergency calling (docs/PRODUCTION_HARDENING.md §6, EMERGENCY_CALLING.md).

``handle_event`` turns the dialplan's ``UserEvent(VeyraEmergency)`` into an
``emergency_calls`` row and the on-site notifications (email, a recorded
page, a desk phone ring, a webhook). ``readiness`` says per site what is
still missing before the operator validates it with the carrier. Veyra
never declares a site compliant by itself.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.core.models import (
    Building,
    Device,
    EmergencyCall,
    Extension,
    Installation,
    OutboundRoute,
    OutboundRouteTrunk,
    SipTrunk,
    Site,
    User,
)
from veyra.core.models.base import utcnow

log = logging.getLogger("veyra.emergency")

EVENT = "VeyraEmergency"
WEBHOOK_EVENT = "emergency.call"
TEST_WINDOW = timedelta(days=365)
NOTIFY_CONTEXT = "veyra-emergency-notify"


@dataclass
class Location:
    text: str
    building: str | None
    address: str | None


def address_of(site: Site, building: Building | None) -> str | None:
    """The building's civic address when it has one, else the site's."""
    for obj in (building, site):
        if obj is None:
            continue
        parts = [obj.street, obj.city, obj.region, obj.postal_code, obj.country]
        if obj.street or obj.city:
            return ", ".join(str(p) for p in parts if p)
    return None


def location_of(
    db: Session, site: Site | None, ext: Extension | None, device: Device | None
) -> Location:
    """The device's location, else the extension's, else the site's address."""
    building = None
    text = None
    for obj in (device, ext):
        if obj is None:
            continue
        if obj.building_id and building is None:
            building = db.get(Building, obj.building_id)
        if obj.location and text is None:
            text = obj.location
    address = address_of(site, building) if site is not None else None
    bits = [b for b in (building.name if building else None, text, address) if b]
    return Location(
        ", ".join(bits) or "unknown location", building.name if building else None, address
    )


# ------------------------------------------------------------------ the event


def parse_userevent(data: dict[str, Any]) -> dict[str, str]:
    """The ``userevent`` body of an ARI ``ChannelUserevent``: header-style
    pairs written by the dialplan."""
    out: dict[str, str] = {}
    for k, v in data.items():
        out[str(k).strip().lower()] = str(v).strip()
    return out


def record_call(
    db: Session,
    fields: dict[str, str],
    *,
    kind: str = "live",
    now: datetime | None = None,
) -> EmergencyCall:
    now = now or utcnow()
    number = fields.get("number") or ""
    ext_number = fields.get("extension") or ""
    site_id = fields.get("site") or ""
    site = None
    try:
        site = db.get(Site, uuid.UUID(site_id)) if site_id else None
    except ValueError:
        site = None
    ext = None
    if ext_number:
        q = select(Extension).where(Extension.number == ext_number)
        if site is not None:
            q = q.where(Extension.organization_id == site.organization_id)
        ext = db.scalar(q.limit(1))
    if site is None and ext is not None and ext.site_id:
        site = db.get(Site, ext.site_id)
    device = None
    if ext is not None:
        device = db.scalar(
            select(Device)
            .where(Device.primary_extension_id == ext.id)
            .order_by(Device.last_seen_at.desc())
            .limit(1)
        )
    loc = location_of(db, site, ext, device)
    minutes = int(site.emergency_callback_minutes or 30) if site else 30
    row = EmergencyCall(
        id=uuid.uuid4(),
        occurred_at=now,
        organization_id=site.organization_id if site else (ext.organization_id if ext else None),
        site_id=site.id if site else None,
        extension_id=ext.id if ext else None,
        extension_number=ext_number or "?",
        device_id=device.id if device else None,
        number=number,
        route=fields.get("route") or None,
        caller_id=fields.get("emergencycid") or (site.emergency_caller_id_number if site else None),
        location=loc.text,
        channel=fields.get("channel") or None,
        kind=kind,
        notifications={},
        callback_until=now + timedelta(minutes=minutes),
    )
    db.add(row)
    db.flush()
    return row


def notify(db: Session, settings: Any, adapter: Any, call: EmergencyCall) -> dict[str, Any]:
    """Tell the site's recipients; each result is recorded on the call."""
    from veyra.core import mail
    from veyra.integrations import webhooks

    site = db.get(Site, call.site_id) if call.site_id else None
    ext = db.get(Extension, call.extension_id) if call.extension_id else None
    recipients = dict(site.emergency_recipients or {}) if site else {}
    inst = db.scalar(select(Installation))
    who = f"{ext.display_name} ({call.extension_number})" if ext else call.extension_number
    where = call.location or "unknown location"
    summary = (
        f"EMERGENCY CALL to {call.number} from {who} at {site.name if site else 'unknown site'}: "
        f"{where}. Placed {call.occurred_at.strftime('%H:%M:%S')} UTC."
        + (" (TEST)" if call.kind == "test" else "")
    )
    results: dict[str, Any] = {}
    # Email through the mail queue.
    emails = [str(e) for e in (recipients.get("emails") or []) if str(e).strip()]
    if emails:
        try:
            smtp = mail.load_smtp_settings(db)
            from_address, from_name = mail.sender(smtp, inst.name if inst else "Veyra")
            for to in emails:
                msg = mail.compose(
                    from_address=from_address,
                    from_name=from_name,
                    to=to,
                    subject=f"EMERGENCY call from {who}"
                    + (" (test)" if call.kind == "test" else ""),
                    text=summary + f"\n\nSite: {site.name if site else '-'}\nExtension: {who}\n"
                    f"Location: {where}\nNumber dialled: {call.number}\n"
                    f"Caller ID presented: {call.caller_id or '-'}\n",
                )
                mail.enqueue(settings.mailqueue_dir, msg.as_bytes())
            results["email"] = {"state": "queued", "to": emails}
        except Exception as e:
            results["email"] = {"state": "failed", "error": str(e)[:200]}
    # A recorded page.
    page_id = recipients.get("page_id")
    if page_id:
        try:
            from veyra.api.v1.pages import start_page
            from veyra.core.models import Page as PageModel

            page = db.get(PageModel, uuid.UUID(str(page_id)))
            if page is None:
                raise ValueError("the page no longer exists")
            ok, message, _channel = start_page(
                db, adapter, page, trigger="emergency", actor="emergency"
            )
            results["page"] = {"state": "started" if ok else "failed", "detail": message}
        except Exception as e:
            results["page"] = {"state": "failed", "error": str(e)[:200]}
    # Desk phones: ring them and say the extension.
    numbers = [str(n) for n in (recipients.get("extensions") or []) if str(n).strip()]
    if numbers and adapter is not None:
        rung: dict[str, str] = {}
        for n in numbers:
            try:
                endpoint = db.scalar(
                    select(Extension.endpoint_name).where(
                        Extension.number == n,
                        Extension.organization_id == call.organization_id,
                    )
                )
                if not endpoint:
                    raise ValueError("no such extension")
                adapter.originate(
                    f"PJSIP/{endpoint}",
                    call.extension_number,
                    caller_id=f"EMERGENCY {call.extension_number}",
                    context=NOTIFY_CONTEXT,
                    timeout=30,
                )
                rung[n] = "ringing"
            except Exception as e:
                rung[n] = f"failed: {str(e)[:100]}"
        results["extensions"] = rung
    # Webhooks.
    if recipients.get("webhook", True):
        try:
            delivered = webhooks.emit(
                db,
                call.organization_id,
                WEBHOOK_EVENT,
                {
                    "kind": call.kind,
                    "site": {"id": str(site.id), "name": site.name} if site else None,
                    "extension": {
                        "number": call.extension_number,
                        "name": ext.display_name if ext else None,
                    },
                    "number": call.number,
                    "location": where,
                    "caller_id": call.caller_id,
                    "occurred_at": call.occurred_at.isoformat(),
                },
                occurred_at=call.occurred_at,
            )
            results["webhook"] = {"state": "queued", "deliveries": delivered}
        except Exception as e:
            results["webhook"] = {"state": "failed", "error": str(e)[:200]}
    call.notifications = results
    db.flush()
    log.warning("%s notified: %s", summary, {k: v.get("state", v) for k, v in results.items()})
    return results


def handle_event(
    db: Session, settings: Any, adapter: Any, userevent: dict[str, Any]
) -> EmergencyCall:
    """The ARI listener's entry point (one transaction; the caller commits)."""
    fields = parse_userevent(userevent)
    call = record_call(db, fields)
    notify(db, settings, adapter, call)
    return call


def companion_alert(db: Session, call: EmergencyCall) -> tuple[set[uuid.UUID], dict[str, Any]]:
    """Who sees the Companion pop-up (issue #127) and what it says: the users
    of the site's recipient extensions and the users with a recipient email
    address, the people the site already chose as responders."""
    site = db.get(Site, call.site_id) if call.site_id else None
    ext = db.get(Extension, call.extension_id) if call.extension_id else None
    recipients = dict(site.emergency_recipients or {}) if site else {}
    numbers = [str(n) for n in recipients.get("extensions") or [] if str(n).strip()]
    emails = [str(e).strip().lower() for e in recipients.get("emails") or [] if str(e).strip()]
    users: set[uuid.UUID] = set()
    if numbers:
        users |= {
            u
            for u in db.scalars(
                select(Extension.user_id).where(
                    Extension.organization_id == call.organization_id,
                    Extension.number.in_(numbers),
                    Extension.user_id.is_not(None),
                )
            )
            if u
        }
    if emails:
        users |= set(
            db.scalars(
                select(User.id).where(func.lower(User.email).in_(emails), User.is_active.is_(True))
            )
        )
    payload = {
        "type": "emergency",
        "test": call.kind == "test",
        "number": call.number,
        "extension_number": call.extension_number,
        "extension_name": ext.display_name if ext else None,
        "site": site.name if site else None,
        "location": call.location or "unknown location",
        "at": call.occurred_at.isoformat(timespec="seconds"),
    }
    if users:
        notes = dict(call.notifications or {})
        notes["companion"] = {"state": "sent", "users": len(users)}
        call.notifications = notes
        db.flush()
    return users, payload


# ------------------------------------------------------------------ readiness


def readiness(db: Session, site: Site, now: datetime | None = None) -> dict[str, Any]:
    """What is still missing before the site can be validated (§6)."""
    now = now or utcnow()
    checks: list[dict[str, Any]] = []

    def check(key: str, ok: bool, label: str, detail: str = "", advisory: bool = False) -> None:
        checks.append(
            {"key": key, "ok": ok, "label": label, "detail": detail, "advisory": advisory}
        )

    routes = list(
        db.scalars(
            select(OutboundRoute).where(
                OutboundRoute.is_emergency.is_(True),
                OutboundRoute.is_enabled.is_(True),
                (OutboundRoute.site_id == site.id) | (OutboundRoute.site_id.is_(None)),
                (OutboundRoute.organization_id == site.organization_id)
                | (OutboundRoute.organization_id.is_(None)),
            )
        )
    )
    carried = (
        {
            rid
            for rid in db.scalars(
                select(OutboundRouteTrunk.route_id).where(
                    OutboundRouteTrunk.route_id.in_([r.id for r in routes])
                )
            )
        }
        if routes
        else set()
    )
    with_trunks = [r for r in routes if r.id in carried]
    check(
        "route",
        bool(with_trunks),
        "An enabled emergency route with a trunk reaches this site",
        ", ".join(r.name for r in with_trunks) or "none",
    )
    # Issue #171: a channel is kept for emergency calls only on a trunk whose
    # channel count is known. Advice, not a condition of readiness.
    trunks = (
        list(
            db.scalars(
                select(SipTrunk)
                .join(OutboundRouteTrunk, OutboundRouteTrunk.trunk_id == SipTrunk.id)
                .where(OutboundRouteTrunk.route_id.in_([r.id for r in with_trunks]))
                .distinct()
            )
        )
        if with_trunks
        else []
    )
    open_trunks = [
        tr.name for tr in trunks if not tr.max_channels or not tr.emergency_reserved_channels
    ]
    check(
        "reserve",
        bool(trunks) and not open_trunks,
        "Every emergency trunk keeps a channel free for emergency calls",
        (
            "set the carrier's channel count and the channels kept for emergency calls on: "
            + ", ".join(open_trunks)
        )
        if open_trunks
        else "",
        advisory=True,
    )
    check(
        "elin",
        bool(site.emergency_caller_id_number),
        "The site has an emergency caller ID (ELIN or registered DID)",
        site.emergency_caller_id_number or "",
    )
    addr = address_of(site, None)
    check("address", bool(addr), "The site has a civic address", addr or "")
    check(
        "attested",
        bool(site.emergency_attested_at),
        "The address is attested as registered with the carrier's E911 service",
        f"by {site.emergency_attested_by} on {site.emergency_attested_at:%Y-%m-%d}"
        if site.emergency_attested_at
        else "",
    )
    exts = list(
        db.scalars(
            select(Extension).where(Extension.site_id == site.id, Extension.is_enabled.is_(True))
        )
    )
    missing = [e.number for e in exts if not (e.location or e.building_id)]
    check(
        "locations",
        not missing,
        "Every extension of the site has a location (building or floor/room)",
        f"{len(exts) - len(missing)} of {len(exts)}; missing: {', '.join(missing[:10])}"
        if exts
        else "no extensions",
    )
    rec = dict(site.emergency_recipients or {})
    has_recipient = bool(rec.get("emails") or rec.get("page_id") or rec.get("extensions"))
    check("recipients", has_recipient, "On-site notification recipients are set")
    check(
        "notification_test",
        bool(site.last_emergency_notification_test_at),
        "The notification was tested",
        f"{site.last_emergency_notification_test_at:%Y-%m-%d}"
        if site.last_emergency_notification_test_at
        else "",
    )
    recent = (
        site.last_emergency_test_at is not None and now - site.last_emergency_test_at <= TEST_WINDOW
    )
    check(
        "test_call",
        recent,
        "A test call with the carrier succeeded within the last year",
        f"{site.last_emergency_test_at:%Y-%m-%d}: {site.last_emergency_test_result or ''}"
        if site.last_emergency_test_at
        else "",
    )
    ready = all(c["ok"] for c in checks if not c["advisory"])
    return {"ready": ready, "checks": checks, "extensions": len(exts)}


def sites_overview(
    db: Session, organization_ids: list[uuid.UUID] | None = None
) -> list[dict[str, Any]]:
    q = select(Site).order_by(Site.name)
    if organization_ids is not None:
        q = q.where(Site.organization_id.in_(organization_ids))
    out = []
    for site in db.scalars(q):
        r = readiness(db, site)
        calls = (
            db.scalar(
                select(func.count())
                .select_from(EmergencyCall)
                .where(EmergencyCall.site_id == site.id)
            )
            or 0
        )
        out.append(
            {
                "id": str(site.id),
                "name": site.name,
                "organization_id": str(site.organization_id),
                "ready": r["ready"],
                "missing": [c["label"] for c in r["checks"] if not c["ok"] and not c["advisory"]],
                "extensions": r["extensions"],
                "calls": int(calls),
                "elin": site.emergency_caller_id_number,
            }
        )
    return out


def record_test_call(
    db: Session, site: Site, result: str, by: str, now: datetime | None = None
) -> None:
    now = now or utcnow()
    site.last_emergency_test_at = now
    site.last_emergency_test_result = f"{result} (recorded by {by})"[:1000]
    db.flush()
