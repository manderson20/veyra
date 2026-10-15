# SPDX-License-Identifier: AGPL-3.0-or-later
"""Centralized instance management (docs/CENTRAL_MANAGEMENT.md): the signed
endpoints instances call, the console's administration, and this
installation's own membership of a console."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1.companion import _origin
from veyra.api.v1.extensions import installation_key
from veyra.central import console, member, protocol
from veyra.central import policy as central_policy
from veyra.core import audit
from veyra.core.config import Settings, get_settings
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, current_principal, request_context, require
from veyra.core.errors import ProblemError, not_found
from veyra.core.models import (
    CentralCommand,
    CentralEnrollmentToken,
    CentralInstance,
    CentralPolicy,
    CentralSample,
)
from veyra.core.models.base import utcnow
from veyra.core.security.principal import Principal
from veyra.core.security.ratelimit import SlidingWindowLimiter

router = APIRouter(prefix="/central", tags=["central management"])

READ = "central.read"
WRITE = "central.write"
_limiter = SlidingWindowLimiter(240, 60)


def _problem(e: console.CentralError) -> JSONResponse:
    return JSONResponse(
        status_code=e.status,
        content={
            "title": "Central console",
            "status": e.status,
            "code": e.code,
            "detail": e.message,
        },
        media_type="application/problem+json",
    )


def _headers(request: Request) -> dict[str, str]:
    return {k.lower(): v for k, v in request.headers.items()}


# ----------------------------------------------------------------- signed endpoints


@router.post("/enroll", include_in_schema=False)
async def enroll_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    if not _limiter.hit(f"enroll:{ctx.ip}"):
        return _problem(console.CentralError(429, "rate_limited", "Too many requests."))
    body = await request.body()
    if len(body) > 64 * 1024:
        return _problem(console.CentralError(413, "too_large", "The request is too large."))
    try:
        out, headers, inst = console.enroll(
            db, installation_key(request), body, _headers(request), ctx.ip
        )
    except console.CentralError as e:
        db.rollback()
        audit.record(
            db,
            action="central.enroll",
            outcome="failure",
            actor_type="system",
            actor_label="instance",
            ip_address=ctx.ip,
            details={"code": e.code},
        )
        db.commit()
        return _problem(e)
    audit.record(
        db,
        action="central.enroll",
        actor_type="system",
        actor_label=f"instance {inst.name}",
        target_type="central_instance",
        target_id=inst.instance_id,
        ip_address=ctx.ip,
        details={"label": inst.label},
    )
    db.commit()
    return Response(content=out, media_type="application/json", headers=headers)


@router.post("/check-in", include_in_schema=False)
async def check_in_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    if not _limiter.hit(f"check-in:{ctx.ip}"):
        return _problem(console.CentralError(429, "rate_limited", "Too many requests."))
    body = await request.body()
    if len(body) > 512 * 1024:
        return _problem(console.CentralError(413, "too_large", "The report is too large."))
    try:
        out, headers = console.check_in(
            db, installation_key(request), body, _headers(request), ctx.ip
        )
    except console.CentralError as e:
        db.rollback()
        return _problem(e)
    db.commit()
    return Response(content=out, media_type="application/json", headers=headers)


# ----------------------------------------------------------------- console


class ConsoleIn(BaseModel):
    enabled: bool
    offline_minutes: int | None = Field(None, ge=2, le=1440)


def _console_out(db: Session, request: Request, settings: Settings) -> dict[str, Any]:
    st = console.state(db)
    pub = st.get("public_key")
    base = f"https://{settings.public_host}" if settings.public_host else _origin(request)
    return {
        "enabled": bool(st.get("enabled")),
        "fingerprint": protocol.fingerprint(pub) if pub else None,
        "address": base,
        "offline_minutes": int(st.get("offline_minutes") or console.DEFAULT_OFFLINE_MINUTES),
        "instances": len(db.scalars(select(CentralInstance.instance_id)).all()),
    }


@router.get("/console", summary="The central console of this installation")
def get_console(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require(READ)),
) -> dict[str, Any]:
    return _console_out(db, request, settings)


@router.put("/console", summary="Turn the central console on or off")
def put_console(
    body: ConsoleIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    console.set_enabled(db, body.enabled, installation_key(request))
    if body.offline_minutes is not None:
        console.set_offline_minutes(db, body.offline_minutes)
    _audit(db, principal, ctx, "central.console", None, enabled=body.enabled)
    db.commit()
    return _console_out(db, request, settings)


def _audit(
    db: Session,
    principal: Principal,
    ctx: RequestContext,
    action: str,
    target: uuid.UUID | None,
    **details: Any,
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="central_instance" if target else None,
        target_id=target,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=details,
    )


# --- tokens


class TokenIn(BaseModel):
    label: str | None = Field(None, max_length=120)
    policy_id: uuid.UUID | None = None


class TokenOut(BaseModel):
    id: uuid.UUID
    label: str | None
    policy_id: uuid.UUID | None
    created_by: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None


@router.get("/tokens", response_model=list[TokenOut], summary="Enrollment tokens")
def list_tokens(
    db: Session = Depends(get_db), principal: Principal = Depends(require(READ))
) -> list[TokenOut]:
    rows = db.scalars(
        select(CentralEnrollmentToken)
        .where(CentralEnrollmentToken.created_at > utcnow() - timedelta(days=7))
        .order_by(CentralEnrollmentToken.created_at.desc())
    )
    return [TokenOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/tokens", status_code=201, summary="Create an enrollment token (shown once)")
def create_token(
    body: TokenIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    if not console.enabled(db):
        raise ProblemError(
            409, "Console off", "Turn the central console on first.", code="console_off"
        )
    if body.policy_id and db.get(CentralPolicy, body.policy_id) is None:
        raise not_found("Policy")
    raw, row = console.create_token(
        db,
        label=(body.label or "").strip() or None,
        policy_id=body.policy_id,
        created_by=principal.label,
    )
    _audit(db, principal, ctx, "central.token_create", None, label=row.label)
    db.commit()
    out = _console_out(db, request, settings)
    return {
        **TokenOut.model_validate(row, from_attributes=True).model_dump(mode="json"),
        "token": raw,
        "address": out["address"],
        "fingerprint": out["fingerprint"],
    }


@router.delete("/tokens/{token_id}", status_code=204)
def delete_token(
    token_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
) -> Response:
    row = db.get(CentralEnrollmentToken, token_id)
    if row is None:
        raise not_found("Token")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


# --- instances


class InstanceOut(BaseModel):
    instance_id: uuid.UUID
    label: str | None
    name: str
    version: str | None
    status: str
    policy_id: uuid.UUID | None
    policy_name: str | None
    policy_state: str | None
    enrolled_at: datetime
    last_seen_at: datetime | None
    last_address: str | None
    registered: int | None
    active_calls: int | None
    extensions: int | None
    alerts: int
    update_available: str | None
    notice: str | None = None


def _instance_out(db: Session, inst: CentralInstance, offline: int) -> InstanceOut:
    rep = inst.last_report or {}
    tel = rep.get("telephony") or {}
    pol = console.policy_of(db, inst)
    applied = rep.get("policy") or {}
    results = applied.get("results") or {}
    if pol is None:
        policy_state = None
    elif (applied.get("id"), applied.get("version")) != (str(pol.id), pol.version):
        policy_state = "pending"
    elif any(str(v).startswith("error") for v in results.values()):
        policy_state = "error"
    elif any(v == "refused" for v in results.values()):
        policy_state = "partly refused"
    else:
        policy_state = "applied"
    available = [
        u for u in (rep.get("updates") or {}).get("available") or [] if isinstance(u, dict)
    ]
    return InstanceOut(
        instance_id=inst.instance_id,
        label=inst.label,
        name=inst.name,
        version=inst.version,
        status=console.status_of(inst, offline),
        policy_id=pol.id if pol else None,
        policy_name=pol.name if pol else None,
        policy_state=policy_state,
        enrolled_at=inst.enrolled_at,
        last_seen_at=inst.last_seen_at,
        last_address=inst.last_address,
        registered=tel.get("registered"),
        active_calls=tel.get("active_calls"),
        extensions=tel.get("extensions"),
        alerts=len(rep.get("alerts") or []),
        update_available=available[0].get("version") if available else None,
    )


def _offline(db: Session) -> int:
    return int(console.state(db).get("offline_minutes") or console.DEFAULT_OFFLINE_MINUTES)


def _get_instance(db: Session, instance_id: uuid.UUID) -> CentralInstance:
    inst = db.get(CentralInstance, instance_id)
    if inst is None:
        raise not_found("Instance")
    return inst


@router.get("/instances", response_model=list[InstanceOut], summary="Enrolled instances")
def list_instances(
    db: Session = Depends(get_db), principal: Principal = Depends(require(READ))
) -> list[InstanceOut]:
    offline = _offline(db)
    rows = db.scalars(select(CentralInstance).order_by(CentralInstance.label, CentralInstance.name))
    return [_instance_out(db, i, offline) for i in rows]


class CommandOut(BaseModel):
    id: uuid.UUID
    kind: str
    arguments: dict[str, Any]
    created_by: str
    created_at: datetime
    expires_at: datetime
    delivered_at: datetime | None
    completed_at: datetime | None
    outcome: str | None
    message: str | None


@router.get("/instances/{instance_id}", summary="One instance with its last report")
def get_instance(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(READ)),
) -> dict[str, Any]:
    inst = _get_instance(db, instance_id)
    since = utcnow() - timedelta(days=30)
    samples = db.scalars(
        select(CentralSample)
        .where(CentralSample.instance_id == inst.instance_id, CentralSample.at > since)
        .order_by(CentralSample.at)
    ).all()
    commands = db.scalars(
        select(CentralCommand)
        .where(CentralCommand.instance_id == inst.instance_id)
        .order_by(CentralCommand.created_at.desc())
        .limit(50)
    )
    return {
        **_instance_out(db, inst, _offline(db)).model_dump(mode="json"),
        "report": inst.last_report,
        "fingerprint": protocol.fingerprint(inst.public_key),
        "revoked_at": inst.revoked_at,
        "samples": [
            {
                "at": s.at,
                "registered": s.registered,
                "active_calls": s.active_calls,
                "alerts": s.alerts,
                "status": s.status,
            }
            for s in samples
        ],
        "commands": [
            CommandOut.model_validate(c, from_attributes=True).model_dump(mode="json")
            for c in commands
        ],
    }


class InstancePatch(BaseModel):
    label: str | None = Field(None, max_length=120)
    policy_id: uuid.UUID | None = None


@router.patch("/instances/{instance_id}", response_model=InstanceOut)
def patch_instance(
    instance_id: uuid.UUID,
    body: InstancePatch,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> InstanceOut:
    inst = _get_instance(db, instance_id)
    changes = body.model_dump(exclude_unset=True)
    if "label" in changes:
        inst.label = (changes["label"] or "").strip() or None
    if "policy_id" in changes:
        if changes["policy_id"] and db.get(CentralPolicy, changes["policy_id"]) is None:
            raise not_found("Policy")
        inst.policy_id = changes["policy_id"]
    _audit(
        db,
        principal,
        ctx,
        "central.instance_update",
        inst.instance_id,
        **{k: str(v) if isinstance(v, uuid.UUID) else v for k, v in changes.items()},
    )
    db.commit()
    return _instance_out(db, inst, _offline(db))


@router.post("/instances/{instance_id}/revoke", response_model=InstanceOut)
def revoke_instance(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> InstanceOut:
    inst = _get_instance(db, instance_id)
    inst.revoked_at = inst.revoked_at or utcnow()
    _audit(db, principal, ctx, "central.instance_revoke", inst.instance_id, name=inst.name)
    db.commit()
    return _instance_out(db, inst, _offline(db))


@router.delete("/instances/{instance_id}", status_code=204)
def delete_instance(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    inst = _get_instance(db, instance_id)
    if inst.revoked_at is None:
        raise ProblemError(
            409, "Revoke first", "Revoke the instance before removing it.", code="not_revoked"
        )
    _audit(db, principal, ctx, "central.instance_delete", inst.instance_id, name=inst.name)
    db.delete(inst)
    db.commit()
    return Response(status_code=204)


class CommandIn(BaseModel):
    kind: Literal["check_updates", "download_update", "approve_update", "refresh_catalogs"]
    arguments: dict[str, Any] = Field(default_factory=dict)


class BulkCommandIn(CommandIn):
    instance_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


def _queue(
    db: Session, principal: Principal, ctx: RequestContext, inst: CentralInstance, body: CommandIn
) -> CentralCommand:
    try:
        cmd = console.queue_command(db, inst, body.kind, body.arguments, principal.label)
    except console.CentralError as e:
        raise ProblemError(e.status, "Command refused", e.message, code=e.code) from e
    _audit(
        db,
        principal,
        ctx,
        "central.command",
        inst.instance_id,
        kind=body.kind,
        arguments=cmd.arguments,
    )
    return cmd


@router.post("/instances/{instance_id}/commands", response_model=CommandOut, status_code=201)
def queue_command(
    instance_id: uuid.UUID,
    body: CommandIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> CommandOut:
    cmd = _queue(db, principal, ctx, _get_instance(db, instance_id), body)
    db.commit()
    return CommandOut.model_validate(cmd, from_attributes=True)


@router.post("/commands", summary="Queue one command for several instances")
def queue_bulk(
    body: BulkCommandIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    queued, skipped = 0, []
    for iid in body.instance_ids:
        inst = db.get(CentralInstance, iid)
        if inst is None or inst.revoked_at is not None:
            skipped.append(str(iid))
            continue
        _queue(db, principal, ctx, inst, body)
        queued += 1
    db.commit()
    return {"queued": queued, "skipped": skipped}


# --- policies


class PolicyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)
    document: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False


class PolicyOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    document: dict[str, Any]
    version: int
    is_default: bool
    instances: int
    updated_at: datetime


def _policy_out(db: Session, p: CentralPolicy) -> PolicyOut:
    users = sum(
        1
        for i in db.scalars(select(CentralInstance))
        if (i.policy_id or console.default_policy_id(db)) == p.id
    )
    return PolicyOut(
        id=p.id,
        name=p.name,
        description=p.description,
        document=p.document,
        version=p.version,
        is_default=p.is_default,
        instances=users,
        updated_at=p.updated_at,
    )


@router.get("/policies", response_model=list[PolicyOut])
def list_policies(
    db: Session = Depends(get_db), principal: Principal = Depends(require(READ))
) -> list[PolicyOut]:
    return [
        _policy_out(db, p) for p in db.scalars(select(CentralPolicy).order_by(CentralPolicy.name))
    ]


def _save_policy(db: Session, p: CentralPolicy | None, body: PolicyIn) -> CentralPolicy:
    clash = db.scalar(select(CentralPolicy).where(CentralPolicy.name == body.name.strip()))
    if clash is not None and (p is None or clash.id != p.id):
        raise ProblemError(
            409, "Name in use", "A policy with this name exists.", code="name_in_use"
        )
    try:
        return console.save_policy(
            db,
            p,
            name=body.name.strip(),
            description=(body.description or "").strip() or None,
            document=body.document,
            is_default=body.is_default,
        )
    except console.CentralError as e:
        raise ProblemError(e.status, "Invalid policy", e.message, code=e.code) from e


@router.post("/policies", response_model=PolicyOut, status_code=201)
def create_policy(
    body: PolicyIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> PolicyOut:
    p = _save_policy(db, None, body)
    _audit(db, principal, ctx, "central.policy_create", None, name=p.name)
    db.commit()
    return _policy_out(db, p)


@router.put("/policies/{policy_id}", response_model=PolicyOut)
def update_policy(
    policy_id: uuid.UUID,
    body: PolicyIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> PolicyOut:
    p = db.get(CentralPolicy, policy_id)
    if p is None:
        raise not_found("Policy")
    p = _save_policy(db, p, body)
    _audit(db, principal, ctx, "central.policy_update", None, name=p.name, version=p.version)
    db.commit()
    return _policy_out(db, p)


@router.delete("/policies/{policy_id}", status_code=204)
def delete_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    p = db.get(CentralPolicy, policy_id)
    if p is None:
        raise not_found("Policy")
    _audit(db, principal, ctx, "central.policy_delete", None, name=p.name)
    db.delete(p)
    db.commit()
    return Response(status_code=204)


@router.get("/policy-sections", summary="What a policy can set")
def policy_sections(principal: Principal = Depends(require(READ))) -> dict[str, Any]:
    return {
        "sections": list(central_policy.SECTIONS),
        "schema": central_policy.PolicyDocument.model_json_schema(),
        "commands": list(console.COMMANDS),
    }


# ----------------------------------------------------------------- membership


class EnrollIn(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    token: str = Field(min_length=10, max_length=200)
    fingerprint: str = Field(min_length=16, max_length=80)
    ca_pem: str | None = Field(None, max_length=20000)


class AcceptedIn(BaseModel):
    updates: bool | None = None
    firewall_allow: bool | None = None
    alert_recipients: bool | None = None
    notice: bool | None = None
    commands: bool | None = None


def _membership_out(db: Session) -> dict[str, Any]:
    m = member.membership(db)
    if not m.get("console_url"):
        return {"enrolled": False}
    pol = m.get("policy") or {}
    return {
        "enrolled": True,
        "console_url": m.get("console_url"),
        "console_name": m.get("console_name"),
        "console_fingerprint": protocol.fingerprint(m["console_public_key"])
        if m.get("console_public_key")
        else None,
        "fingerprint": protocol.fingerprint(m["public_key"]) if m.get("public_key") else None,
        "enrolled_at": m.get("enrolled_at"),
        "last_contact": m.get("last_contact"),
        "last_attempt": m.get("last_attempt"),
        "last_error": m.get("last_error"),
        "revoked": bool(m.get("revoked")),
        "accepted": {**member.DEFAULT_ACCEPTED, **(m.get("accepted") or {})},
        "policy": {
            "name": pol.get("name"),
            "version": pol.get("version"),
            "results": pol.get("results") or {},
            "document": pol.get("document") or {},
            "applied_at": pol.get("applied_at"),
        }
        if pol
        else None,
        "log": m.get("log") or [],
    }


@router.get("/membership", summary="This installation's central console, if any")
def get_membership(
    db: Session = Depends(get_db), principal: Principal = Depends(require("system.settings.read"))
) -> dict[str, Any]:
    return _membership_out(db)


@router.post("/membership/enroll", summary="Enroll with a central console")
def enroll_membership(
    body: EnrollIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require("system.settings.write")),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    try:
        member.enroll(
            db,
            installation_key(request),
            url=body.url,
            token=body.token,
            fingerprint=body.fingerprint,
            ca_pem=(body.ca_pem or "").strip() or None,
        )
    except member.MemberError as e:
        db.rollback()
        audit.record(
            db,
            action="central.membership_enroll",
            outcome="failure",
            actor_user_id=principal.user_id,
            actor_label=principal.label,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"console": body.url, "error": str(e)[:300]},
        )
        db.commit()
        raise ProblemError(409, "Enrollment failed", str(e), code="enroll_failed") from e
    audit.record(
        db,
        action="central.membership_enroll",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"console": body.url},
    )
    db.commit()
    return _membership_out(db)


@router.post("/membership/leave", summary="Leave the central console")
def leave_membership(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require("system.settings.write")),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    url = member.membership(db).get("console_url")
    member.leave(db)
    audit.record(
        db,
        action="central.membership_leave",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"console": url},
    )
    db.commit()
    return _membership_out(db)


@router.put("/membership/accepted", summary="What this installation accepts from the console")
def put_accepted(
    body: AcceptedIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require("system.settings.write")),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    changes = body.model_dump(exclude_none=True)
    try:
        member.set_accepted(db, changes)
    except member.MemberError as e:
        raise ProblemError(409, "Not enrolled", str(e), code="not_enrolled") from e
    audit.record(
        db,
        action="central.membership_accepted",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=changes,
    )
    db.commit()
    return _membership_out(db)


@router.post("/membership/check-in", summary="Check in with the console now")
def check_in_now(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require("system.settings.write")),
) -> dict[str, Any]:
    try:
        member.check_in(
            db,
            settings,
            installation_key(request),
            request.app.state.telephony,
            request.app.state.keyring,
        )
    except member.MemberError as e:
        raise ProblemError(409, "Not enrolled", str(e), code="not_enrolled") from e
    db.commit()
    return _membership_out(db)


@router.get("/notice", summary="The notice from the central console, if any")
def get_notice(
    db: Session = Depends(get_db), principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    m = member.membership(db)
    # Managed: the console's policy sets the section and this installation accepts it.
    document = (m.get("policy") or {}).get("document") or {}
    return {
        "text": central_policy.notice(db),
        "console_name": m.get("console_name"),
        "managed": {
            k: v
            for k, v in {**member.DEFAULT_ACCEPTED, **(m.get("accepted") or {})}.items()
            if m.get("console_url") and v and k in central_policy.SECTIONS and k in document
        },
    }
