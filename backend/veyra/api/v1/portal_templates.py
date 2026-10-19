# SPDX-License-Identifier: AGPL-3.0-or-later
"""Administrator's portal layout templates (docs/USER_PORTAL.md §10)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, forbidden, not_found
from veyra.core.models import Building, Department, Organization, PortalTemplate, UserPreference
from veyra.core.models.identity import Role
from veyra.core.security.principal import Principal
from veyra.portal import layouts

router = APIRouter(prefix="/portal-templates", tags=["portal"])
PERM = "portal.templates"


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # None with scope "system": every organization (platform administrators).
    organization_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    scope: layouts.Scope = "organization"
    scope_ref: str | None = Field(None, max_length=64)
    layout: dict[str, Any]
    locked_widgets: list[str] = Field(default_factory=list, max_length=20)
    priority: int = Field(0, ge=0, le=100)
    is_enabled: bool = True

    @field_validator("layout")
    @classmethod
    def _layout(cls, v: dict[str, Any]) -> dict[str, Any]:
        return layouts.validate_layout(v)


class TemplatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    scope: layouts.Scope | None = None
    scope_ref: str | None = Field(None, max_length=64)
    layout: dict[str, Any] | None = None
    locked_widgets: list[str] | None = Field(None, max_length=20)
    priority: int | None = Field(None, ge=0, le=100)
    is_enabled: bool | None = None

    @field_validator("layout")
    @classmethod
    def _layout(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return layouts.validate_layout(v) if v is not None else None


class TemplateOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    organization_name: str | None
    name: str
    description: str | None
    scope: str
    scope_ref: str | None
    scope_label: str | None
    layout: dict[str, Any]
    locked_widgets: list[str]
    priority: int
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


def _scope_label(db: Session, scope: str, ref: str | None) -> str | None:
    if scope == "building" and ref:
        try:
            b = db.get(Building, uuid.UUID(ref))
        except ValueError:
            return None
        return b.name if b else None
    if scope == "department" and ref:
        try:
            d = db.get(Department, uuid.UUID(ref))
        except ValueError:
            return None
        return d.name if d else None
    if scope == "role" and ref:
        r = db.scalar(select(Role).where(Role.key == ref))
        return r.name if r else ref
    return None


def _out(db: Session, t: PortalTemplate) -> TemplateOut:
    org = db.get(Organization, t.organization_id) if t.organization_id else None
    return TemplateOut(
        id=t.id,
        organization_id=t.organization_id,
        organization_name=org.name if org else None,
        name=t.name,
        description=t.description,
        scope=t.scope,
        scope_ref=t.scope_ref,
        scope_label=_scope_label(db, t.scope, t.scope_ref),
        layout=dict(t.layout or {}),
        locked_widgets=list(t.locked_widgets or []),
        priority=t.priority,
        is_enabled=t.is_enabled,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def _check_scope(
    db: Session, principal: Principal, org_id: uuid.UUID | None, scope: str, ref: str | None
) -> None:
    if scope == "system":
        if org_id is not None:
            raise ProblemError(
                422, "Scope", "A system template has no organization.", code="validation_failed"
            )
        if not principal.is_platform_admin:
            raise forbidden("System-wide templates need a platform administrator.")
        return
    if org_id is None:
        raise ProblemError(
            422, "Scope", "This scope needs an organization.", code="validation_failed"
        )
    if not principal.has(PERM, org_id):
        raise forbidden()
    if scope == "organization":
        return
    if not ref:
        raise ProblemError(
            422, "Scope", f"A {scope} template names the {scope}.", code="validation_failed"
        )
    if scope == "role":
        if db.scalar(select(Role.id).where(Role.key == ref)) is None:
            raise ProblemError(422, "Scope", f"Unknown role {ref!r}.", code="validation_failed")
        return
    row: Building | Department | None
    try:
        key = uuid.UUID(ref)
        row = db.get(Building, key) if scope == "building" else db.get(Department, key)
    except ValueError:
        row = None
    if row is None or row.organization_id != org_id:
        raise ProblemError(
            422, "Scope", f"The {scope} is not in this organization.", code="validation_failed"
        )


def _get(db: Session, principal: Principal, template_id: uuid.UUID) -> PortalTemplate:
    t = db.get(PortalTemplate, template_id)
    if t is None:
        raise not_found("Portal template")
    if t.organization_id is None:
        if not principal.has_any_scope(PERM):
            raise not_found("Portal template")
    elif not principal.has(PERM, t.organization_id):
        raise not_found("Portal template")
    return t


def _audit(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    t: PortalTemplate,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=t.organization_id,
        target_type="portal_template",
        target_id=t.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": t.name, "scope": t.scope, **details},
    )


@router.get("", response_model=list[TemplateOut], summary="Portal layout templates")
def list_templates(
    organization_id: uuid.UUID | None = None,
    principal: Principal = Depends(require(PERM)),
    db: Session = Depends(get_db),
) -> list[TemplateOut]:
    orgs = principal.organization_ids_with(PERM)
    stmt = select(PortalTemplate)
    if orgs is not None:
        stmt = stmt.where(
            PortalTemplate.organization_id.in_(orgs or {uuid.UUID(int=0)})
            | PortalTemplate.organization_id.is_(None)
        )
    if organization_id is not None:
        stmt = stmt.where(PortalTemplate.organization_id == organization_id)
    rows = db.scalars(stmt.order_by(PortalTemplate.scope, PortalTemplate.name)).all()
    return [_out(db, t) for t in rows]


@router.post("", response_model=TemplateOut, status_code=201, summary="Create a template")
def create_template(
    body: TemplateIn,
    principal: Principal = Depends(require(PERM)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> TemplateOut:
    _check_scope(db, principal, body.organization_id, body.scope, body.scope_ref)
    t = PortalTemplate(
        organization_id=body.organization_id,
        name=body.name,
        description=body.description,
        scope=body.scope,
        scope_ref=body.scope_ref,
        layout=body.layout,
        locked_widgets=body.locked_widgets,
        priority=body.priority,
        is_enabled=body.is_enabled,
    )
    db.add(t)
    db.flush()
    _audit(db, ctx, principal, "portal_template.create", t, {})
    db.commit()
    db.refresh(t)
    return _out(db, t)


@router.get("/{template_id}", response_model=TemplateOut, summary="One template")
def get_template(
    template_id: uuid.UUID,
    principal: Principal = Depends(require(PERM)),
    db: Session = Depends(get_db),
) -> TemplateOut:
    return _out(db, _get(db, principal, template_id))


@router.patch("/{template_id}", response_model=TemplateOut, summary="Change a template")
def patch_template(
    template_id: uuid.UUID,
    body: TemplatePatch,
    principal: Principal = Depends(require(PERM)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> TemplateOut:
    t = _get(db, principal, template_id)
    fields = body.model_dump(exclude_unset=True)
    scope = fields.get("scope", t.scope)
    ref = fields.get("scope_ref", t.scope_ref)
    if "scope" in fields or "scope_ref" in fields:
        _check_scope(db, principal, t.organization_id, scope, ref)
    for key, value in fields.items():
        setattr(t, key, value)
    _audit(db, ctx, principal, "portal_template.update", t, {"fields": sorted(fields)})
    db.commit()
    db.refresh(t)
    return _out(db, t)


@router.delete("/{template_id}", status_code=204, summary="Delete a template")
def delete_template(
    template_id: uuid.UUID,
    principal: Principal = Depends(require(PERM)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> None:
    t = _get(db, principal, template_id)
    _audit(db, ctx, principal, "portal_template.delete", t, {})
    db.delete(t)
    db.commit()


class PushOut(BaseModel):
    reset: int


@router.post(
    "/{template_id}/push",
    response_model=PushOut,
    summary="Reset the users' own layouts under this template's scope",
)
def push_template(
    template_id: uuid.UUID,
    principal: Principal = Depends(require(PERM)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PushOut:
    """Drops the saved layout of every user who currently resolves to this
    template, so they see it on their next visit (their other preferences
    stay)."""
    t = _get(db, principal, template_id)
    reset = 0
    for pref in db.scalars(select(UserPreference)).all():
        data = dict(pref.data or {})
        portal = dict(data.get("portal") or {})
        if not portal.get("layout"):
            continue
        resolved = layouts.resolve_template(db, pref.user_id, t.organization_id)
        if resolved is None or resolved.id != t.id:
            continue
        portal.pop("layout", None)
        data["portal"] = portal
        pref.data = data
        reset += 1
    _audit(db, ctx, principal, "portal_template.push", t, {"reset": reset})
    db.commit()
    return PushOut(reset=reset)
