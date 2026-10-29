# SPDX-License-Identifier: AGPL-3.0-or-later
"""Emergency calling validation (docs/PRODUCTION_HARDENING.md §6): readiness
per site, the site's emergency settings, test calls, notification tests and
the record of emergency calls."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1.sites import _get as get_site
from veyra.api.v1.sites import _visible as visible_sites
from veyra.core import audit
from veyra.core.config import Settings, get_settings
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError
from veyra.core.models import EmergencyCall, Extension, Page, Site
from veyra.core.models.base import utcnow
from veyra.core.security.principal import Principal
from veyra.emergency import service

router = APIRouter(prefix="/emergency", tags=["emergency calling"])
READ = "emergency.read"
MANAGE = "emergency.manage"
DISCLAIMER = (
    "Veyra reports readiness against its own checks; the operator validates emergency "
    "calling with the carrier and the regulations that apply (docs/EMERGENCY_CALLING.md)."
)


def _call_out(c: EmergencyCall) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "occurred_at": c.occurred_at.isoformat(),
        "site_id": str(c.site_id) if c.site_id else None,
        "extension_id": str(c.extension_id) if c.extension_id else None,
        "extension_number": c.extension_number,
        "number": c.number,
        "route": c.route,
        "caller_id": c.caller_id,
        "location": c.location,
        "kind": c.kind,
        "notifications": c.notifications,
        "callback_until": c.callback_until.isoformat() if c.callback_until else None,
    }


def _settings_out(db: Session, site: Site) -> dict[str, Any]:
    responder = (
        db.get(Extension, site.emergency_responder_extension_id)
        if site.emergency_responder_extension_id
        else None
    )
    return {
        "emergency_caller_id_number": site.emergency_caller_id_number,
        "address": service.address_of(site, None),
        "attested": bool(site.emergency_attested_at),
        "attested_by": site.emergency_attested_by,
        "attested_at": site.emergency_attested_at.isoformat()
        if site.emergency_attested_at
        else None,
        "responder_extension_id": str(responder.id) if responder else None,
        "responder_number": responder.number if responder else None,
        "callback_minutes": site.emergency_callback_minutes,
        "recipients": dict(site.emergency_recipients or {}),
        "last_test_at": site.last_emergency_test_at.isoformat()
        if site.last_emergency_test_at
        else None,
        "last_test_result": site.last_emergency_test_result,
        "last_notification_test_at": site.last_emergency_notification_test_at.isoformat()
        if site.last_emergency_notification_test_at
        else None,
    }


@router.get("/sites", summary="Emergency readiness per site")
def sites(
    principal: Principal = Depends(require(READ)), db: Session = Depends(get_db)
) -> dict[str, Any]:
    ids = list(db.scalars(visible_sites(principal, READ).with_only_columns(Site.id)))
    rows = (
        service.sites_overview(db)
        if principal.is_platform_admin
        else [r for r in service.sites_overview(db) if uuid.UUID(r["id"]) in set(ids)]
    )
    return {"sites": rows, "ready": sum(1 for r in rows if r["ready"]), "disclaimer": DISCLAIMER}


@router.get("/sites/{site_id}", summary="A site's readiness, settings and recent emergency calls")
def site_detail(
    site_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    site = get_site(db, principal, site_id, READ)
    calls = db.scalars(
        select(EmergencyCall)
        .where(EmergencyCall.site_id == site.id)
        .order_by(EmergencyCall.occurred_at.desc())
        .limit(20)
    )
    return {
        "id": str(site.id),
        "name": site.name,
        "organization_id": str(site.organization_id),
        "readiness": service.readiness(db, site),
        "settings": _settings_out(db, site),
        "calls": [_call_out(c) for c in calls],
        "disclaimer": DISCLAIMER,
    }


class RecipientsIn(BaseModel):
    emails: list[str] = Field(default_factory=list, max_length=20)
    page_id: uuid.UUID | None = None
    extensions: list[str] = Field(default_factory=list, max_length=20)
    webhook: bool = True


class SiteEmergencyIn(BaseModel):
    attested: bool | None = None
    responder_extension_id: uuid.UUID | None = None
    clear_responder: bool = False
    callback_minutes: int | None = Field(None, ge=1, le=1440)
    recipients: RecipientsIn | None = None


@router.put("/sites/{site_id}", summary="A site's emergency settings")
def put_site(
    site_id: uuid.UUID,
    body: SiteEmergencyIn,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    site = get_site(db, principal, site_id, MANAGE)
    details: dict[str, Any] = {}
    if body.attested is not None and body.attested != bool(site.emergency_attested_at):
        site.emergency_attested_at = utcnow() if body.attested else None
        site.emergency_attested_by = principal.label if body.attested else None
        details["attested"] = body.attested
    if body.clear_responder:
        site.emergency_responder_extension_id = None
        details["responder"] = None
    elif body.responder_extension_id is not None:
        ext = db.get(Extension, body.responder_extension_id)
        if ext is None or ext.organization_id != site.organization_id:
            raise ProblemError(
                422, "Validation failed", "The responder extension is not in this organization."
            )
        site.emergency_responder_extension_id = ext.id
        details["responder"] = ext.number
    if body.callback_minutes is not None:
        site.emergency_callback_minutes = body.callback_minutes
        details["callback_minutes"] = body.callback_minutes
    if body.recipients is not None:
        for n in body.recipients.extensions:
            if not db.scalar(
                select(Extension.id).where(
                    Extension.number == n, Extension.organization_id == site.organization_id
                )
            ):
                raise ProblemError(
                    422, "Validation failed", f"No extension {n} in this organization."
                )
        if body.recipients.page_id is not None:
            page = db.get(Page, body.recipients.page_id)
            if page is None or page.organization_id != site.organization_id:
                raise ProblemError(
                    422, "Validation failed", "The page is not in this site's organization."
                )
        rec = body.recipients.model_dump(mode="json")
        rec["page_id"] = str(body.recipients.page_id) if body.recipients.page_id else None
        site.emergency_recipients = rec
        details["recipients"] = {
            "emails": len(rec["emails"]),
            "page": bool(rec["page_id"]),
            "extensions": rec["extensions"],
            "webhook": rec["webhook"],
        }
    db.flush()
    audit.record(
        db,
        action="emergency.site_update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=site.organization_id,
        target_type="site",
        target_id=site.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=details,
    )
    db.commit()
    return {"readiness": service.readiness(db, site), "settings": _settings_out(db, site)}


class TestCallIn(BaseModel):
    result: str = Field(min_length=1, max_length=1000)
    succeeded: bool = True
    at: datetime | None = None


@router.post("/sites/{site_id}/test-call", summary="Record a carrier test call")
def test_call(
    site_id: uuid.UUID,
    body: TestCallIn,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    site = get_site(db, principal, site_id, MANAGE)
    when = body.at or utcnow()
    if body.succeeded:
        service.record_test_call(db, site, body.result, principal.label, when)
    else:
        site.last_emergency_test_result = f"FAILED: {body.result} (recorded by {principal.label})"
        site.last_emergency_test_at = None
    audit.record(
        db,
        action="emergency.test_call",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=site.organization_id,
        target_type="site",
        target_id=site.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"result": body.result, "succeeded": body.succeeded, "at": when.isoformat()},
    )
    db.commit()
    return {"readiness": service.readiness(db, site), "settings": _settings_out(db, site)}


@router.post(
    "/sites/{site_id}/test-notification", summary="Send the on-site notification as a test"
)
def test_notification(
    site_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    site = get_site(db, principal, site_id, MANAGE)
    ext = db.scalar(select(Extension).where(Extension.site_id == site.id).limit(1))
    call = service.record_call(
        db,
        {
            "extension": ext.number if ext else "0000",
            "site": str(site.id),
            "number": "933",
            "route": "test",
            "emergencycid": site.emergency_caller_id_number or "",
        },
        kind="test",
    )
    adapter = getattr(request.app.state, "telephony", None)
    results = service.notify(db, settings, adapter, call)
    # The Companion pop-up for the responders (issue #127), marked as a test.
    from veyra.api.v1.events import hub_of

    users, alert = service.companion_alert(db, call)
    hub_of(request.app).alert_from_thread(users, alert)
    results = dict(call.notifications or results)
    ok = any(
        str(v.get("state", "")).startswith(("queued", "started", "sent"))
        for v in results.values()
        if isinstance(v, dict)
    ) or any(
        isinstance(v, dict) and any(str(x) == "ringing" for x in v.values())
        for v in results.values()
    )
    if ok:
        site.last_emergency_notification_test_at = utcnow()
    audit.record(
        db,
        action="emergency.test_notification",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=site.organization_id,
        target_type="site",
        target_id=site.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"results": results},
    )
    db.commit()
    return {"ok": ok, "results": results, "call": _call_out(call)}


@router.get("/calls", summary="Emergency calls, newest first")
def calls(
    limit: int = Query(50, ge=1, le=500),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    q = select(EmergencyCall).order_by(EmergencyCall.occurred_at.desc()).limit(limit)
    if not principal.is_platform_admin:
        ids = list(db.scalars(visible_sites(principal, READ).with_only_columns(Site.id)))
        q = q.where(EmergencyCall.site_id.in_(ids))
    return [_call_out(c) for c in db.scalars(q)]
