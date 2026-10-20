# SPDX-License-Identifier: AGPL-3.0-or-later
"""Automation rules (issue #117; docs/INTEGRATIONS.md §3.8): "when X happens,
do Y" for an organization, and the public address a ``hook`` rule listens on."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.models import AutomationRule, AutomationRun, Organization, Page, Prompt
from veyra.core.security.principal import Principal
from veyra.integrations import automation, webhooks

router = APIRouter(prefix="/automation", tags=["automation"])
hooks_router = APIRouter(prefix="/automation/hooks", tags=["automation"])

READ = "webhooks.read"
WRITE = "webhooks.write"
PAGE_SEND = "paging.send"
_EMAIL_RE_MAX = 20

# Example fields per trigger, for the rule editor (what conditions can test).
TRIGGER_FIELDS: dict[str, list[str]] = {
    "call.ended": [
        "outcome",
        "direction",
        "from.number",
        "from.name",
        "to.number",
        "did",
        "to_extension.number",
        "answered_by.number",
        "queue",
        "ring_group",
        "trunk",
    ],
    "call.ringing": ["extension.number", "remote_number", "direction"],
    "call.answered": ["extension.number", "remote_number", "direction"],
    "voicemail.message": ["box.number", "box.name", "message.caller_number", "message.urgent"],
    "page.sent": ["page.name", "trigger", "started_by"],
    "bell.rang": ["schedule.name"],
    "alert.raised": ["alert.kind", "alert.severity", "alert.title"],
    "alert.resolved": ["alert.kind", "alert.title"],
    "registration.changed": ["extension.number", "registered"],
    "deployment.finished": ["status"],
    automation.HOOK: ["(any field of the JSON body)"],
}


class ConditionIn(BaseModel):
    field: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.]+$")
    equals: str | None = Field(None, max_length=200)
    contains: str | None = Field(None, max_length=200)


class ActionIn(BaseModel):
    type: str = Field(pattern="^(email|page)$")
    to: list[str] = Field(default_factory=list, max_length=_EMAIL_RE_MAX)
    subject: str | None = Field(None, max_length=200)
    page_id: uuid.UUID | None = None
    audio_id: uuid.UUID | None = None

    @field_validator("to")
    @classmethod
    def _to(cls, v: list[str]) -> list[str]:
        from veyra.telephony.routing import check_email

        return [check_email(a) for a in v if a.strip()]


class RuleIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    trigger: str = Field(min_length=1, max_length=64)
    conditions: list[ConditionIn] = Field(
        default_factory=list, max_length=automation.MAX_CONDITIONS
    )
    actions: list[ActionIn] = Field(min_length=1, max_length=automation.MAX_ACTIONS)
    cooldown_seconds: int = Field(60, ge=0, le=86400)


class RulePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    enabled: bool | None = None
    conditions: list[ConditionIn] | None = Field(None, max_length=automation.MAX_CONDITIONS)
    actions: list[ActionIn] | None = Field(None, min_length=1, max_length=automation.MAX_ACTIONS)
    cooldown_seconds: int | None = Field(None, ge=0, le=86400)


class RuleOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    enabled: bool
    trigger: str
    conditions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    cooldown_seconds: int
    last_fired_at: datetime | None
    fire_count: int
    last_error: str | None
    created_by: str
    # Only when the token was just made: the address to give the device.
    hook_url: str | None = None


class RunOut(BaseModel):
    id: uuid.UUID
    event: str
    status: str
    results: list[dict[str, Any]]
    created_at: datetime
    finished_at: datetime | None


def _out(rule: AutomationRule, hook_url: str | None = None) -> RuleOut:
    return RuleOut(
        id=rule.id,
        organization_id=rule.organization_id,
        name=rule.name,
        enabled=rule.enabled,
        trigger=rule.trigger,
        conditions=list(rule.conditions or []),
        actions=list(rule.actions or []),
        cooldown_seconds=rule.cooldown_seconds,
        last_fired_at=rule.last_fired_at,
        fire_count=rule.fire_count or 0,
        last_error=rule.last_error,
        created_by=rule.created_by,
        hook_url=hook_url,
    )


def _hook_url(request: Request, token: str) -> str:
    host = request.headers.get("host") or "veyra"
    return f"https://{host}/api/v1/automation/hooks/{token}"


def _get(db: Session, principal: Principal, rule_id: uuid.UUID, perm: str) -> AutomationRule:
    rule = db.get(AutomationRule, rule_id)
    if rule is None or not principal.has(perm, rule.organization_id):
        raise not_found("Rule")
    return rule


def _triggers(db: Session) -> set[str]:
    return webhooks.EVENT_NAMES | {automation.HOOK}


def _check_actions(
    db: Session, principal: Principal, org_id: uuid.UUID, actions: list[ActionIn]
) -> list[dict[str, Any]]:
    out = []
    for a in actions:
        if a.type == "email":
            if not a.to:
                raise ProblemError(
                    422,
                    "Validation failed",
                    "An email action needs an address.",
                    code="validation_failed",
                )
            out.append(
                {"type": "email", "to": a.to, **({"subject": a.subject} if a.subject else {})}
            )
        else:
            # Paging from a rule needs the right to page (no escalation).
            if not principal.has(PAGE_SEND, org_id):
                raise forbidden("You may not start pages, so a rule of yours may not either.")
            page = db.get(Page, a.page_id) if a.page_id else None
            if page is None or page.organization_id != org_id:
                raise not_found("Page")
            entry: dict[str, Any] = {"type": "page", "page_id": str(page.id)}
            if a.audio_id:
                audio = db.get(Prompt, a.audio_id)
                if audio is None or audio.organization_id != org_id:
                    raise not_found("Recording")
                entry["audio_id"] = str(audio.id)
            elif page.audio_id is None:
                raise ProblemError(
                    422,
                    "Validation failed",
                    "This page plays live audio; choose a recording for the rule to play.",
                    code="validation_failed",
                )
            out.append(entry)
    return out


def _conditions(conditions: list[ConditionIn]) -> list[dict[str, Any]]:
    out = []
    for c in conditions:
        if c.equals is None and c.contains is None:
            raise ProblemError(
                422,
                "Validation failed",
                f"Condition {c.field}: give a value.",
                code="validation_failed",
            )
        entry: dict[str, Any] = {"field": c.field}
        if c.equals is not None:
            entry["equals"] = c.equals
        if c.contains is not None:
            entry["contains"] = c.contains
        out.append(entry)
    return out


def _audit(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    rule: AutomationRule,
    **details: Any,
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=rule.organization_id,
        target_type="automation_rule",
        target_id=rule.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": rule.name, **details},
    )


@router.get("/triggers", summary="What a rule can listen to, with example fields")
def triggers(principal: Principal = Depends(require(READ))) -> list[dict[str, Any]]:
    out = [
        {
            "name": e.name,
            "group": e.group,
            "description": e.description,
            "fields": TRIGGER_FIELDS.get(e.name, []),
        }
        for e in webhooks.EVENTS
    ]
    out.append(
        {
            "name": automation.HOOK,
            "group": "Devices",
            "description": "A request to the rule's own address (a door controller, a script)",
            "fields": TRIGGER_FIELDS[automation.HOOK],
        }
    )
    return out


@router.get("/rules", response_model=list[RuleOut], summary="Automation rules")
def list_rules(
    organization_id: uuid.UUID | None = Query(None),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> list[RuleOut]:
    stmt = select(AutomationRule).order_by(AutomationRule.name)
    if organization_id is not None:
        stmt = stmt.where(AutomationRule.organization_id == organization_id)
    return [_out(r) for r in db.scalars(stmt) if principal.has(READ, r.organization_id)]


@router.post("/rules", response_model=RuleOut, status_code=201, summary="Create a rule")
def create_rule(
    body: RuleIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RuleOut:
    if not principal.has(WRITE, body.organization_id):
        raise forbidden()
    if db.get(Organization, body.organization_id) is None:
        raise not_found("Organization")
    if body.trigger not in _triggers(db):
        raise ProblemError(
            422, "Validation failed", f"Unknown trigger {body.trigger!r}.", code="validation_failed"
        )
    token = hashed = None
    if body.trigger == automation.HOOK:
        token, hashed = automation.new_hook_token()
    rule = AutomationRule(
        id=uuid.uuid4(),
        organization_id=body.organization_id,
        name=body.name.strip(),
        enabled=body.enabled,
        trigger=body.trigger,
        conditions=_conditions(body.conditions),
        actions=_check_actions(db, principal, body.organization_id, body.actions),
        cooldown_seconds=body.cooldown_seconds,
        hook_token_hash=hashed,
        fire_count=0,
        created_by=principal.label,
    )
    db.add(rule)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("A rule with that name exists in this organization.", "name_in_use") from e
    _audit(db, ctx, principal, "automation.create", rule, trigger=rule.trigger)
    db.commit()
    return _out(rule, _hook_url(request, token) if token else None)


@router.patch("/rules/{rule_id}", response_model=RuleOut, summary="Change a rule")
def update_rule(
    rule_id: uuid.UUID,
    body: RulePatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RuleOut:
    rule = _get(db, principal, rule_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and body.name:
        rule.name = body.name.strip()
    if body.enabled is not None:
        rule.enabled = body.enabled
    if body.conditions is not None:
        rule.conditions = _conditions(body.conditions)
    if body.actions is not None:
        rule.actions = _check_actions(db, principal, rule.organization_id, body.actions)
    if body.cooldown_seconds is not None:
        rule.cooldown_seconds = body.cooldown_seconds
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("A rule with that name exists in this organization.", "name_in_use") from e
    _audit(db, ctx, principal, "automation.update", rule, fields=sorted(changes))
    db.commit()
    return _out(rule)


@router.delete("/rules/{rule_id}", status_code=204, summary="Delete a rule")
def delete_rule(
    rule_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> None:
    rule = _get(db, principal, rule_id, WRITE)
    _audit(db, ctx, principal, "automation.delete", rule)
    db.delete(rule)
    db.commit()


@router.post(
    "/rules/{rule_id}/rotate-hook", response_model=RuleOut, summary="New address for a hook rule"
)
def rotate_hook(
    rule_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RuleOut:
    rule = _get(db, principal, rule_id, WRITE)
    if rule.trigger != automation.HOOK:
        raise conflict("Only rules triggered by a request have an address.", "not_a_hook")
    token, rule.hook_token_hash = automation.new_hook_token()
    _audit(db, ctx, principal, "automation.rotate_hook", rule)
    db.commit()
    return _out(rule, _hook_url(request, token))


@router.post(
    "/rules/{rule_id}/test", response_model=RunOut, status_code=202, summary="Fire a rule now"
)
def test_rule(
    rule_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RunOut:
    """Queue a run with test data, past the conditions and the cooldown;
    the worker runs it within seconds."""
    from veyra.core.models.base import utcnow

    rule = _get(db, principal, rule_id, WRITE)
    run = AutomationRun(
        id=uuid.uuid4(),
        rule_id=rule.id,
        event=rule.trigger,
        data={"test": True, "by": principal.label},
        status="pending",
        results=[],
        created_at=utcnow(),
    )
    db.add(run)
    _audit(db, ctx, principal, "automation.test", rule)
    db.commit()
    return RunOut.model_validate(run, from_attributes=True)


@router.get("/rules/{rule_id}/runs", response_model=list[RunOut], summary="The last runs of a rule")
def rule_runs(
    rule_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> list[RunOut]:
    rule = _get(db, principal, rule_id, READ)
    rows = db.scalars(
        select(AutomationRun)
        .where(AutomationRun.rule_id == rule.id)
        .order_by(AutomationRun.created_at.desc())
        .limit(20)
    )
    return [RunOut.model_validate(r, from_attributes=True) for r in rows]


@hooks_router.post(
    "/{token}", status_code=202, summary="Trigger a hook rule (no sign-in; the token is the secret)"
)
def hook(
    token: str,
    payload: Any = Body(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """For devices that can only call an address: a door controller, a fire
    panel. An optional JSON body becomes the event's fields."""
    rule = db.scalar(
        select(AutomationRule).where(AutomationRule.hook_token_hash == automation.hash_token(token))
    )
    if rule is None or rule.trigger != automation.HOOK:
        raise not_found("Hook")
    if isinstance(payload, dict):
        data: dict[str, Any] = payload
    else:
        data = {} if payload is None else {"body": payload}
    if len(json.dumps(data, default=str)) > automation.MAX_HOOK_BYTES:
        raise ProblemError(413, "Too large", "The request body is too large.", code="too_large")
    if not rule.enabled:
        return {"queued": 0, "reason": "the rule is disabled"}
    queued = automation.enqueue(db, rule.organization_id, automation.HOOK, data, rule_id=rule.id)
    db.commit()
    return {"queued": queued}
