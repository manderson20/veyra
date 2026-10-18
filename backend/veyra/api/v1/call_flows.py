# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call flows (docs/CALL_FEATURES.md §4.5): a day/night switch between two
destinations, flipped from a phone (``*28<index>``), this API or the
interface; the engine keeps the switch in its store behind a BLF lamp."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import destinations
from veyra.api.v1.destinations import DestinationIn, DestinationOut, Resolver, check_destination
from veyra.api.v1.extensions import installation_key
from veyra.api.v1.group_helpers import unique_slug
from veyra.configmgmt import service as configmgmt
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.events import Event, bus
from veyra.core.models import CallFlow, Organization
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import routing, switches
from veyra.telephony.snapshot import call_flow_pin_purpose

router = APIRouter(prefix="/call-flows", tags=["call-flows"])

READ = "routing.read"
WRITE = "routing.write"
MAX_INDEX = 99
_PIN_RE = re.compile(r"^[0-9]{4,10}$")


def _validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


# ----------------------------------------------------------------- schemas


class CallFlowIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    # The digits dialled after the toggle code: *28<code_index>.
    code_index: int = Field(ge=0, le=MAX_INDEX)
    # Write-only; empty or missing: no PIN.
    pin: str | None = Field(None, max_length=10)
    normal: DestinationIn = Field(default_factory=lambda: DestinationIn(type="hangup"))
    override_destination: DestinationIn = Field(
        default_factory=lambda: DestinationIn(type="hangup")
    )
    is_enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        routing.slugify(v)
        return v

    @field_validator("pin")
    @classmethod
    def _pin(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        if not _PIN_RE.match(v.strip()):
            raise ValueError("4 to 10 digits")
        return v.strip()


class CallFlowPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    code_index: int | None = Field(None, ge=0, le=MAX_INDEX)
    pin: str | None = Field(None, max_length=10)
    normal: DestinationIn | None = None
    override_destination: DestinationIn | None = None
    is_enabled: bool | None = None


class StateIn(BaseModel):
    override: bool


class CallFlowOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    slug: str
    context: str
    description: str | None
    code_index: int
    # The code a phone dials, with the current toggle prefix; None when the
    # prefix is disabled.
    code: str | None
    has_pin: bool
    normal: DestinationOut
    override_destination: DestinationOut
    override: bool
    override_by: str | None
    override_at: datetime | None
    is_enabled: bool
    problems: list[str]
    in_use_by: int
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------- helpers


def _org_filter(stmt: Select[Any], column: Any, principal: Principal, perm: str) -> Select[Any]:
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(column.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _org_for_write(db: Session, principal: Principal, organization_id: uuid.UUID) -> Organization:
    if not principal.has(WRITE, organization_id):
        raise forbidden()
    org = db.get(Organization, organization_id)
    if org is None:
        raise not_found("Organization")
    if not org.is_active:
        raise conflict("This organization is inactive.", "organization_inactive")
    return org


def _outs(db: Session, rows: list[CallFlow]) -> list[CallFlowOut]:
    if not rows:
        return []
    from veyra.telephony import features

    prefix = features.active(db).get("callflow_toggle_prefix")
    org_ids = {r.organization_id for r in rows}
    orgs = {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids)))}
    uses = destinations.count_uses(db, "call_flow", {r.id for r in rows})
    resolver = Resolver(db)
    resolver.load(
        [destinations.ref_of(r, "normal") for r in rows]
        + [destinations.ref_of(r, "override") for r in rows]
    )
    out = []
    for r in rows:
        org = orgs.get(r.organization_id)
        normal = resolver.out_ref(destinations.ref_of(r, "normal"))
        override = resolver.out_ref(destinations.ref_of(r, "override"))
        problems = []
        if normal.missing:
            problems.append("The normal destination no longer exists.")
        if override.missing:
            problems.append("The override destination no longer exists.")
        if prefix is None:
            problems.append("The call flow toggle code is disabled (Telephony → Feature Codes).")
        out.append(
            CallFlowOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=org.name if org else "",
                name=r.name,
                slug=r.slug,
                context=f"veyra-flow-{r.slug}",
                description=r.description,
                code_index=r.code_index,
                code=f"{prefix}{r.code_index}" if prefix else None,
                has_pin=bool(r.pin_ciphertext),
                normal=normal,
                override_destination=override,
                override=bool(r.override),
                override_by=r.override_by,
                override_at=r.override_at,
                is_enabled=r.is_enabled,
                problems=problems,
                in_use_by=uses.get(r.id, 0),
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _get(db: Session, principal: Principal, flow_id: uuid.UUID, perm: str) -> CallFlow:
    stmt = _org_filter(select(CallFlow), CallFlow.organization_id, principal, perm)
    row = db.scalar(stmt.where(CallFlow.id == flow_id))
    if row is None:
        raise not_found("Call flow")
    return row


def _check_all(
    db: Session, org_id: uuid.UUID, body: CallFlowIn, self_id: uuid.UUID | None = None
) -> None:
    for prefix in ("normal", "override_destination"):
        check_destination(
            db,
            org_id,
            getattr(body, prefix),
            field=prefix,
            allow_hangup=True,
            exclude_call_flow=self_id,
        )
    taken = db.scalar(
        select(CallFlow.id).where(
            CallFlow.organization_id == org_id,
            CallFlow.code_index == body.code_index,
            CallFlow.id != (self_id or uuid.UUID(int=0)),
        )
    )
    if taken is not None:
        raise ProblemError(
            409,
            "Code index in use",
            f"Another call flow of this organization already uses the index {body.code_index}.",
            code="code_index_in_use",
            errors=[{"field": "code_index", "message": "already used by another call flow"}],
        )


def _audit(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    row: CallFlow,
    details: dict[str, Any],
    *,
    deploy: bool = True,
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=row.organization_id,
        target_type="call_flow",
        target_id=row.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": row.name, **details},
    )
    if deploy:
        configmgmt.mark_changed(db, by=principal.label, what=f"{action} {row.name}")


def _name_conflict() -> ProblemError:
    return conflict("A call flow with that name exists in this organization.", "name_in_use")


# ----------------------------------------------------------------- routes


@router.get("", response_model=Page[CallFlowOut], summary="List call flows")
def list_flows(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[CallFlowOut]:
    stmt = _org_filter(select(CallFlow), CallFlow.organization_id, principal, READ).order_by(
        CallFlow.code_index
    )
    if organization_id:
        stmt = stmt.where(CallFlow.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(CallFlow.name.ilike(like), CallFlow.description.ilike(like)))
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post("", response_model=CallFlowOut, status_code=201, summary="Create a call flow")
def create_flow(
    body: CallFlowIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> CallFlowOut:
    org = _org_for_write(db, principal, body.organization_id)
    _check_all(db, org.id, body)
    row = CallFlow(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=body.name,
        slug=unique_slug(db, CallFlow, body.name),
        description=(body.description or "").strip() or None,
        code_index=body.code_index,
        override=False,
        is_enabled=body.is_enabled,
    )
    if body.pin:
        row.pin_ciphertext = installation_key(request).encrypt(
            body.pin, call_flow_pin_purpose(row.id)
        )
    destinations.apply(row, "normal", body.normal)
    destinations.apply(row, "override", body.override_destination)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise _name_conflict() from e
    _audit(
        db,
        ctx,
        principal,
        "call_flow.create",
        row,
        {"slug": row.slug, "code_index": row.code_index},
    )
    db.commit()
    bus.publish(Event("call_flow.created", {"id": str(row.id), "name": row.name}))
    return _outs(db, [row])[0]


@router.get("/{flow_id}", response_model=CallFlowOut)
def get_flow(
    flow_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> CallFlowOut:
    return _outs(db, [_get(db, principal, flow_id, READ)])[0]


@router.patch("/{flow_id}", response_model=CallFlowOut)
def update_flow(
    flow_id: uuid.UUID,
    body: CallFlowPatch,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> CallFlowOut:
    row = _get(db, principal, flow_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    current = {
        "organization_id": row.organization_id,
        "name": row.name,
        "description": row.description,
        "code_index": row.code_index,
        "pin": "0000" if row.pin_ciphertext else None,
        "normal": destinations.as_input(destinations.ref_of(row, "normal")),
        "override_destination": destinations.as_input(destinations.ref_of(row, "override")),
        "is_enabled": row.is_enabled,
    }
    try:
        validated = CallFlowIn.model_validate({**current, **changes})
    except ValueError as e:
        raise _validation("call_flow", str(e).splitlines()[0]) from e
    _check_all(db, row.organization_id, validated, self_id=row.id)
    details: dict[str, Any] = {}
    if validated.name != row.name:
        details["name"] = {"from": row.name, "to": validated.name}
        row.name = validated.name
    desc = (validated.description or "").strip() or None
    if desc != row.description:
        row.description = desc
        details["description"] = True
    for field in ("code_index", "is_enabled"):
        value = getattr(validated, field)
        if value != getattr(row, field):
            setattr(row, field, value)
            details[field] = str(value)
    if "pin" in changes:
        pin = validated.pin
        row.pin_ciphertext = (
            installation_key(request).encrypt(pin, call_flow_pin_purpose(row.id)) if pin else None
        )
        details["pin"] = "set" if pin else "removed"
    for prefix, attr in (("normal", "normal"), ("override", "override_destination")):
        d = getattr(validated, attr)
        if destinations.ref_of(row, prefix) != d.as_ref():
            destinations.apply(row, prefix, d)
            details[attr] = d.model_dump(mode="json")
    if not details:
        return _outs(db, [row])[0]
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise _name_conflict() from e
    _audit(db, ctx, principal, "call_flow.update", row, details)
    db.commit()
    bus.publish(Event("call_flow.updated", {"id": str(row.id)}))
    return _outs(db, [row])[0]


@router.post("/{flow_id}/state", response_model=CallFlowOut, summary="Switch a call flow")
def set_state(
    flow_id: uuid.UUID,
    body: StateIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> CallFlowOut:
    """Takes effect at once (the engine's switch is written live); no
    deployment is needed."""
    row = _get(db, principal, flow_id, WRITE)
    changed = switches.set_flow(
        db, row, body.override, by=principal.label, adapter=request.app.state.telephony
    )
    if changed:
        _audit(
            db,
            ctx,
            principal,
            "call_flow.switch",
            row,
            {"override": body.override},
            deploy=False,
        )
        db.commit()
    return _outs(db, [row])[0]


@router.delete("/{flow_id}", status_code=204)
def delete_flow(
    flow_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    row = _get(db, principal, flow_id, WRITE)
    what = destinations.describe_uses(db, "call_flow", row.id, exclude_self=row.id)
    if what:
        raise destinations.in_use_error("Call flow in use", "call_flow_in_use", what)
    _audit(db, ctx, principal, "call_flow.delete", row, {"slug": row.slug})
    if row.override:
        org = db.get(Organization, row.organization_id)
        switches._write(
            request.app.state.telephony, "flow", org.slug if org else "", row.slug, None
        )
    db.delete(row)
    db.commit()
    bus.publish(Event("call_flow.deleted", {"id": str(flow_id)}))
    return Response(status_code=204)
