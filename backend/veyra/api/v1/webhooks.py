# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outgoing webhooks (docs/INTEGRATIONS.md §3): signed JSON events sent to
other systems when something happens in Veyra."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1.extensions import installation_key
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require, require_in_org
from veyra.core.errors import ProblemError, conflict, not_found
from veyra.core.models import InstalledModule, Organization, Webhook, WebhookDelivery
from veyra.core.models.base import utcnow
from veyra.core.security.principal import Principal
from veyra.integrations import webhooks

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

READ = "webhooks.read"
WRITE = "webhooks.write"


class EventOut(BaseModel):
    name: str
    group: str
    description: str
    live: bool
    module: str | None = None


class WebhookIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2000)
    allow_http: bool = False
    events: list[str] = Field(min_length=1, max_length=100)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return v.strip()


class WebhookCreateIn(WebhookIn):
    organization_id: uuid.UUID


class WebhookOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    url: str
    allow_http: bool
    events: list[str]
    enabled: bool
    disabled_reason: str | None
    failing_since: datetime | None
    last_delivery_at: datetime | None
    last_status: str | None
    pending: int
    created_at: datetime
    created_by: str


class WebhookSecretOut(WebhookOut):
    # Shown once, when created or rotated.
    secret: str


class DeliveryOut(BaseModel):
    id: uuid.UUID
    event: str
    status: str
    attempts: int
    max_attempts: int
    created_at: datetime
    next_attempt_at: datetime
    delivered_at: datetime | None
    response_code: int | None
    duration_ms: int | None
    error: str | None
    response_excerpt: str | None
    payload: dict[str, Any]


def _module_events(db: Session) -> dict[str, str]:
    """Events enabled modules declare they publish (module API, M11)."""
    out: dict[str, str] = {}
    for m in db.scalars(select(InstalledModule).where(InstalledModule.state == "enabled")):
        manifest = m.manifest if isinstance(m.manifest, dict) else {}
        for name in (manifest.get("events") or {}).get("publishes") or []:
            if isinstance(name, str) and "*" not in name:
                out[name] = m.module_id
    return out


def _allowed_events(db: Session) -> set[str]:
    return webhooks.known_events(_module_events(db))


def _out(db: Session, h: Webhook) -> WebhookOut:
    pending = db.scalar(
        select(func.count())
        .select_from(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == h.id, WebhookDelivery.status == "pending")
    )
    return WebhookOut(
        id=h.id,
        organization_id=h.organization_id,
        name=h.name,
        url=h.url,
        allow_http=h.allow_http,
        events=list(h.events or []),
        enabled=h.enabled,
        disabled_reason=h.disabled_reason,
        failing_since=h.failing_since,
        last_delivery_at=h.last_delivery_at,
        last_status=h.last_status,
        pending=int(pending or 0),
        created_at=h.created_at,
        created_by=h.created_by,
    )


def _get(db: Session, principal: Principal, webhook_id: uuid.UUID, perm: str) -> Webhook:
    h = db.get(Webhook, webhook_id)
    if h is None or not principal.has(perm, h.organization_id):
        raise not_found("Webhook")
    return h


def _validate(db: Session, body: WebhookIn) -> tuple[str, list[str]]:
    try:
        url = webhooks.check_url(body.url, allow_http=body.allow_http)
    except ValueError as e:
        raise ProblemError(422, "Invalid address", str(e), code="bad_url") from e
    try:
        events = webhooks.check_patterns(body.events, _allowed_events(db))
    except ValueError as e:
        raise ProblemError(422, "Invalid events", str(e), code="bad_events") from e
    return url, events


def _record(
    db: Session, principal: Principal, ctx: RequestContext, action: str, h: Webhook, **extra: Any
) -> None:
    from urllib.parse import urlsplit

    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=h.organization_id,
        target_type="webhook",
        target_id=h.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        # The host only: a query string may carry the receiver's own key.
        details={"name": h.name, "host": urlsplit(h.url).hostname, "events": h.events, **extra},
    )


@router.get("/events", response_model=list[EventOut], summary="Events a webhook can subscribe to")
def events(
    db: Session = Depends(get_db), principal: Principal = Depends(require(READ))
) -> list[EventOut]:
    out = [
        EventOut(name=e.name, group=e.group, description=e.description, live=e.live)
        for e in webhooks.EVENTS
    ]
    for name, module_id in sorted(_module_events(db).items()):
        if name not in webhooks.EVENT_NAMES:
            out.append(
                EventOut(name=name, group="Modules", description=name, live=False, module=module_id)
            )
    return out


@router.get("", response_model=list[WebhookOut], summary="Webhooks")
def list_webhooks(
    organization_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(READ)),
) -> list[WebhookOut]:
    stmt = select(Webhook).order_by(Webhook.name)
    orgs = principal.organization_ids_with(READ)
    if orgs is not None:
        stmt = stmt.where(Webhook.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    if organization_id is not None:
        stmt = stmt.where(Webhook.organization_id == organization_id)
    return [_out(db, h) for h in db.scalars(stmt)]


@router.post("", response_model=WebhookSecretOut, status_code=201, summary="Create a webhook")
def create_webhook(
    body: WebhookCreateIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> WebhookSecretOut:
    require_in_org(principal, WRITE, body.organization_id)
    if db.get(Organization, body.organization_id) is None:
        raise not_found("Organization")
    url, events_ = _validate(db, body)
    secret = webhooks.new_secret()
    h = Webhook(
        id=uuid.uuid4(),
        organization_id=body.organization_id,
        name=body.name,
        url=url,
        allow_http=body.allow_http,
        events=events_,
        secret_enc=installation_key(request).encrypt(secret, webhooks.SECRET_PURPOSE),
        enabled=body.enabled,
        created_by=principal.label,
    )
    db.add(h)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("A webhook with this name already exists.") from e
    _record(db, principal, ctx, "webhook.create", h)
    db.commit()
    return WebhookSecretOut(**_out(db, h).model_dump(), secret=secret)


@router.get("/{webhook_id}", response_model=WebhookOut)
def get_webhook(
    webhook_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(READ)),
) -> WebhookOut:
    return _out(db, _get(db, principal, webhook_id, READ))


@router.put("/{webhook_id}", response_model=WebhookOut)
def update_webhook(
    webhook_id: uuid.UUID,
    body: WebhookIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> WebhookOut:
    h = _get(db, principal, webhook_id, WRITE)
    url, events_ = _validate(db, body)
    h.name, h.url, h.allow_http, h.events = body.name, url, body.allow_http, events_
    if body.enabled and not h.enabled:
        h.disabled_reason = None
        h.failing_since = None
    h.enabled = body.enabled
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("A webhook with this name already exists.") from e
    _record(db, principal, ctx, "webhook.update", h, enabled=h.enabled)
    db.commit()
    return _out(db, h)


@router.delete("/{webhook_id}", status_code=204)
def delete_webhook(
    webhook_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    h = _get(db, principal, webhook_id, WRITE)
    _record(db, principal, ctx, "webhook.delete", h)
    db.delete(h)
    db.commit()
    return Response(status_code=204)


@router.post("/{webhook_id}/rotate-secret", response_model=WebhookSecretOut)
def rotate_secret(
    webhook_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> WebhookSecretOut:
    h = _get(db, principal, webhook_id, WRITE)
    key = installation_key(request)
    secret = webhooks.new_secret()
    h.previous_secret_enc = h.secret_enc
    h.previous_secret_until = utcnow() + webhooks.ROTATION_OVERLAP
    h.secret_enc = key.encrypt(secret, webhooks.SECRET_PURPOSE)
    _record(db, principal, ctx, "webhook.rotate_secret", h)
    db.commit()
    return WebhookSecretOut(**_out(db, h).model_dump(), secret=secret)


@router.post("/{webhook_id}/test", response_model=DeliveryOut, summary="Send a test event now")
def test_webhook(
    webhook_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
) -> DeliveryOut:
    """Sent right away (not through the worker) so the result shows at once."""
    h = _get(db, principal, webhook_id, WRITE)
    webhooks.emit(
        db,
        h.organization_id,
        webhooks.TEST_EVENT,
        {"message": "Test from Veyra", "requested_by": principal.label},
        only=h.id,
    )
    d = db.scalar(
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == h.id, WebhookDelivery.event == webhooks.TEST_EVENT)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(1)
    )
    assert d is not None
    key = installation_key(request)
    d.max_attempts = 1
    webhooks.send(h, d, lambda enc: key.decrypt(enc, webhooks.SECRET_PURPOSE))
    if d.status != "delivered":
        d.status = "failed"
    h.last_delivery_at = utcnow()
    h.last_status = "delivered" if d.status == "delivered" else "failed"
    db.commit()
    return DeliveryOut.model_validate(d, from_attributes=True)


@router.get("/{webhook_id}/deliveries", response_model=list[DeliveryOut])
def list_deliveries(
    webhook_id: uuid.UUID,
    status: str | None = Query(None, pattern="^(pending|delivered|failed)$"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(READ)),
) -> list[DeliveryOut]:
    h = _get(db, principal, webhook_id, READ)
    stmt = (
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == h.id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(webhooks.KEEP_PER_WEBHOOK)
    )
    if status:
        stmt = stmt.where(WebhookDelivery.status == status)
    return [DeliveryOut.model_validate(d, from_attributes=True) for d in db.scalars(stmt)]


@router.post(
    "/{webhook_id}/deliveries/{delivery_id}/redeliver",
    response_model=DeliveryOut,
    status_code=201,
)
def redeliver(
    webhook_id: uuid.UUID,
    delivery_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> DeliveryOut:
    h = _get(db, principal, webhook_id, WRITE)
    d = db.get(WebhookDelivery, delivery_id)
    if d is None or d.webhook_id != h.id:
        raise not_found("Delivery")
    copy = webhooks.redeliver(db, d)
    _record(db, principal, ctx, "webhook.redeliver", h, delivery=str(d.id))
    db.commit()
    return DeliveryOut.model_validate(copy, from_attributes=True)
