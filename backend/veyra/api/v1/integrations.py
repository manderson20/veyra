# SPDX-License-Identifier: AGPL-3.0-or-later
"""Integration tokens (docs/INTEGRATIONS.md §2): API tokens that belong to an
organization, for door controllers, scripts and other systems."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require, require_in_org
from veyra.core.errors import ProblemError, conflict, not_found
from veyra.core.models import ApiToken, Integration, Organization
from veyra.core.models.base import utcnow
from veyra.core.security import api_tokens
from veyra.core.security.principal import Principal
from veyra.integrations import tokens as integration_tokens

router = APIRouter(prefix="/integrations", tags=["integrations"])

READ = "integrations.read"
WRITE = "integrations.write"


class ScopeOut(BaseModel):
    key: str
    description: str


class IntegrationIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1, max_length=20)
    allowed_networks: list[str] = Field(default_factory=list, max_length=50)
    expires_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return v.strip()

    @field_validator("scopes")
    @classmethod
    def _scopes(cls, v: list[str]) -> list[str]:
        unknown = [s for s in v if s not in integration_tokens.SCOPES]
        if unknown:
            raise ValueError(f"unknown scope(s): {', '.join(unknown)}")
        return sorted(set(v))

    @field_validator("allowed_networks")
    @classmethod
    def _networks(cls, v: list[str]) -> list[str]:
        return integration_tokens.check_networks(v)


class IntegrationCreateIn(IntegrationIn):
    organization_id: uuid.UUID


class IntegrationOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    scopes: list[str]
    allowed_networks: list[str]
    expires_at: datetime | None
    expired: bool
    token_prefix: str
    last_used_at: datetime | None
    last_used_ip: str | None
    created_at: datetime
    created_by: str


class IntegrationTokenOut(IntegrationOut):
    # Shown once, when created or rotated.
    token: str


def _out(db: Session, i: Integration) -> IntegrationOut:
    tok = db.get(ApiToken, i.token_id) if i.token_id else None
    return IntegrationOut(
        id=i.id,
        organization_id=i.organization_id,
        name=i.name,
        scopes=list(i.scopes or []),
        allowed_networks=list(i.allowed_networks or []),
        expires_at=i.expires_at,
        expired=bool(i.expires_at and i.expires_at <= utcnow()),
        token_prefix=api_tokens.INTEGRATION_PREFIX,
        last_used_at=tok.last_used_at if tok else None,
        last_used_ip=tok.last_used_ip if tok else None,
        created_at=i.created_at,
        created_by=i.created_by,
    )


def _get(db: Session, principal: Principal, integration_id: uuid.UUID, perm: str) -> Integration:
    i = db.get(Integration, integration_id)
    if i is None or not principal.has(perm, i.organization_id):
        raise not_found("Integration")
    return i


def _check_expiry(expires_at: datetime | None) -> None:
    if expires_at is not None and expires_at <= utcnow():
        raise ProblemError(
            422, "Invalid expiry", "The expiry date is in the past.", code="bad_expiry"
        )


@router.get("/scopes", response_model=list[ScopeOut], summary="What an integration may be allowed")
def scopes(principal: Principal = Depends(require(READ))) -> list[ScopeOut]:
    return [ScopeOut(key=k, description=d) for k, d in integration_tokens.SCOPES.items()]


@router.get("", response_model=list[IntegrationOut], summary="Integrations")
def list_integrations(
    organization_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(READ)),
) -> list[IntegrationOut]:
    stmt = select(Integration).order_by(Integration.name)
    orgs = principal.organization_ids_with(READ)
    if orgs is not None:
        stmt = stmt.where(Integration.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    if organization_id is not None:
        stmt = stmt.where(Integration.organization_id == organization_id)
    return [_out(db, i) for i in db.scalars(stmt)]


@router.post(
    "", response_model=IntegrationTokenOut, status_code=201, summary="Create an integration"
)
def create_integration(
    body: IntegrationCreateIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> IntegrationTokenOut:
    require_in_org(principal, WRITE, body.organization_id)
    if db.get(Organization, body.organization_id) is None:
        raise not_found("Organization")
    _check_expiry(body.expires_at)
    try:
        i, raw = integration_tokens.create(
            db,
            organization_id=body.organization_id,
            name=body.name,
            scopes=body.scopes,
            allowed_networks=body.allowed_networks,
            expires_at=body.expires_at,
            created_by=principal.label,
            ip=ctx.ip,
        )
    except IntegrityError as e:
        db.rollback()
        raise conflict("An integration with this name already exists.") from e
    audit.record(
        db,
        action="integration.create",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=i.organization_id,
        target_type="integration",
        target_id=i.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": i.name, "scopes": i.scopes, "networks": i.allowed_networks},
    )
    db.commit()
    return IntegrationTokenOut(**_out(db, i).model_dump(), token=raw)


@router.get("/{integration_id}", response_model=IntegrationOut)
def get_integration(
    integration_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(READ)),
) -> IntegrationOut:
    return _out(db, _get(db, principal, integration_id, READ))


@router.put("/{integration_id}", response_model=IntegrationOut)
def update_integration(
    integration_id: uuid.UUID,
    body: IntegrationIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> IntegrationOut:
    i = _get(db, principal, integration_id, WRITE)
    _check_expiry(body.expires_at)
    i.name = body.name
    i.scopes = body.scopes
    i.allowed_networks = body.allowed_networks
    i.expires_at = body.expires_at
    integration_tokens.sync_token(db, i)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("An integration with this name already exists.") from e
    audit.record(
        db,
        action="integration.update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=i.organization_id,
        target_type="integration",
        target_id=i.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": i.name, "scopes": i.scopes, "networks": i.allowed_networks},
    )
    db.commit()
    return _out(db, i)


@router.post("/{integration_id}/rotate", response_model=IntegrationTokenOut)
def rotate_integration(
    integration_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> IntegrationTokenOut:
    i = _get(db, principal, integration_id, WRITE)
    raw = integration_tokens.rotate(db, i, ctx.ip)
    audit.record(
        db,
        action="integration.rotate",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=i.organization_id,
        target_type="integration",
        target_id=i.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": i.name},
    )
    db.commit()
    return IntegrationTokenOut(**_out(db, i).model_dump(), token=raw)


@router.delete("/{integration_id}", status_code=204)
def delete_integration(
    integration_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(WRITE)),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    i = _get(db, principal, integration_id, WRITE)
    audit.record(
        db,
        action="integration.delete",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=i.organization_id,
        target_type="integration",
        target_id=i.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": i.name},
    )
    integration_tokens.delete(db, i)
    db.commit()
    return Response(status_code=204)
