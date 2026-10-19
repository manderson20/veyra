# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provisioning variables (docs/PROVISIONING_BREADTH.md §2): the control
plane of named values templates and key lists reference. Lists the core
variables (facts every template has) with the defined ones; a change
re-provisions the phones it reaches."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.models import DeviceProfile, Organization, ProvisioningVariable, Site
from veyra.core.security.principal import Principal
from veyra.provisioning import variables as varsvc
from veyra.provisioning.spec import CORE_VARIABLES
from veyra.telephony.asterisk import cli

router = APIRouter(prefix="/provisioning/variables", tags=["provisioning"])

READ = "provisioning.read"
WRITE = "provisioning.write"
Scope = Literal["installation", "organization", "site", "profile"]


class VariableIn(BaseModel):
    scope: Scope
    scope_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=40)
    value: str = Field("", max_length=varsvc.MAX_VALUE)
    sensitive: bool = False
    description: str | None = Field(None, max_length=500)


class VariablePatch(BaseModel):
    value: str | None = Field(None, max_length=varsvc.MAX_VALUE)
    sensitive: bool | None = None
    description: str | None = Field(None, max_length=500)


class VariableOut(BaseModel):
    id: uuid.UUID | None
    source: Literal["core", "defined"]
    scope: Scope | None
    scope_id: uuid.UUID | None
    scope_name: str | None
    organization_id: uuid.UUID | None
    name: str
    value: str | None
    sensitive: bool
    description: str | None
    type: str | None = None
    default: str | int | bool | None = None
    affected_devices: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


def _validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


def _scope_target(
    db: Session, principal: Principal, scope: str, scope_id: uuid.UUID | None, perm: str
) -> tuple[uuid.UUID | None, str | None]:
    """(organization id, display name) of a scope target, after the permission
    check for that organization; installation scope is for platform
    administrators."""
    if scope == "installation":
        if scope_id is not None:
            raise _validation("scope_id", "installation variables have no target")
        if not principal.is_platform_admin:
            raise forbidden()
        return None, "Installation"
    if scope_id is None:
        raise _validation("scope_id", f"choose the {scope}")
    if scope == "organization":
        org = db.get(Organization, scope_id)
        if org is None:
            raise not_found("Organization")
        if not principal.has(perm, org.id):
            raise forbidden()
        return org.id, org.name
    if scope == "site":
        site = db.get(Site, scope_id)
        if site is None:
            raise not_found("Site")
        if not principal.has(perm, site.organization_id):
            raise forbidden()
        return site.organization_id, site.name
    profile = db.get(DeviceProfile, scope_id)
    if profile is None:
        raise not_found("Device profile")
    if not principal.has(perm, profile.organization_id):
        raise forbidden()
    return profile.organization_id, profile.name


def _scope_names(db: Session, rows: list[ProvisioningVariable]) -> dict[uuid.UUID, str]:
    names: dict[uuid.UUID, str] = {}
    by_scope: dict[str, set[uuid.UUID]] = {}
    for r in rows:
        if r.scope_id is not None:
            by_scope.setdefault(r.scope, set()).add(r.scope_id)
    if ids := by_scope.get("organization"):
        for o in db.scalars(select(Organization).where(Organization.id.in_(ids))):
            names[o.id] = o.name
    if ids := by_scope.get("site"):
        for st in db.scalars(select(Site).where(Site.id.in_(ids))):
            names[st.id] = st.name
    if ids := by_scope.get("profile"):
        for p in db.scalars(select(DeviceProfile).where(DeviceProfile.id.in_(ids))):
            names[p.id] = p.name
    return names


def _out(
    row: ProvisioningVariable,
    names: dict[uuid.UUID, str],
    *,
    reveal: bool,
    affected: int | None = None,
) -> VariableOut:
    return VariableOut(
        id=row.id,
        source="defined",
        scope=row.scope,
        scope_id=row.scope_id,
        scope_name="Installation"
        if row.scope == "installation"
        else (names.get(row.scope_id) if row.scope_id else None),
        organization_id=row.organization_id,
        name=row.name,
        value=varsvc.MASK if row.sensitive and not reveal else row.value,
        sensitive=row.sensitive,
        description=row.description,
        affected_devices=affected,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _get(
    db: Session, principal: Principal, variable_id: uuid.UUID, perm: str
) -> ProvisioningVariable:
    row = db.get(ProvisioningVariable, variable_id)
    if row is None:
        raise not_found("Variable")
    if row.scope == "installation":
        if not principal.is_platform_admin and perm == WRITE:
            raise forbidden()
    elif row.organization_id is None or not principal.has(perm, row.organization_id):
        raise not_found("Variable")
    return row


def _audit(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    row: ProvisioningVariable,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=row.organization_id,
        target_type="provisioning_variable",
        target_id=row.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": row.name, "scope": row.scope, **details},
    )


def _notify(request: Request) -> varsvc.Notify:
    custom = getattr(request.app.state, "notify_phone", None)
    return custom or cli.send_notify


def _reprovision(db: Session, request: Request, row: ProvisioningVariable) -> int:
    return varsvc.reprovision(db, varsvc.devices_in_scope(db, row), _notify(request))


@router.get("", response_model=list[VariableOut], summary="Template variables: core and defined")
def list_variables(
    organization_id: uuid.UUID | None = None,
    scope: Scope | None = Query(None),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> list[VariableOut]:
    out = [
        VariableOut(
            id=None,
            source="core",
            scope=None,
            scope_id=None,
            scope_name=None,
            organization_id=None,
            name=v.name,
            value=None,
            sensitive=v.sensitive,
            description=v.description,
            type=v.type,
            default=v.default,
        )
        for v in CORE_VARIABLES
    ]
    stmt = select(ProvisioningVariable)
    orgs = principal.organization_ids_with(READ)
    if orgs is not None:
        stmt = stmt.where(
            (ProvisioningVariable.scope == "installation")
            | ProvisioningVariable.organization_id.in_(orgs or {uuid.UUID(int=0)})
        )
    if organization_id is not None:
        stmt = stmt.where(
            (ProvisioningVariable.scope == "installation")
            | (ProvisioningVariable.organization_id == organization_id)
        )
    if scope is not None:
        stmt = stmt.where(ProvisioningVariable.scope == scope)
    rows = list(db.scalars(stmt.order_by(ProvisioningVariable.name)))
    names = _scope_names(db, rows)
    for r in rows:
        reveal = (
            principal.is_platform_admin
            if r.scope == "installation"
            else (r.organization_id is not None and principal.has(WRITE, r.organization_id))
        )
        out.append(_out(r, names, reveal=reveal))
    return out


@router.post("", response_model=VariableOut, status_code=201, summary="Define a variable")
def create_variable(
    body: VariableIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> VariableOut:
    try:
        name = varsvc.check_name(body.name)
    except varsvc.VariableError as e:
        raise _validation("name", str(e)) from e
    org_id, scope_name = _scope_target(db, principal, body.scope, body.scope_id, WRITE)
    exists = db.scalar(
        select(ProvisioningVariable).where(
            ProvisioningVariable.scope == body.scope,
            ProvisioningVariable.scope_id == body.scope_id,
            ProvisioningVariable.name == name,
        )
    )
    if exists is not None:
        raise conflict(f"{name} is already defined at this scope.", "variable_exists")
    row = ProvisioningVariable(
        id=uuid.uuid4(),
        scope=body.scope,
        scope_id=body.scope_id,
        organization_id=org_id,
        name=name,
        value=body.value,
        sensitive=body.sensitive,
        description=(body.description or "").strip() or None,
    )
    db.add(row)
    db.flush()
    affected = _reprovision(db, request, row)
    _audit(db, ctx, principal, "provisioning.variable_create", row, {"reprovisioned": affected})
    db.commit()
    names = {row.scope_id: scope_name} if row.scope_id and scope_name else {}
    return _out(row, names, reveal=True, affected=affected)


@router.patch("/{variable_id}", response_model=VariableOut, summary="Change a variable")
def update_variable(
    variable_id: uuid.UUID,
    body: VariablePatch,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> VariableOut:
    row = _get(db, principal, variable_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    changed_value = "value" in changes and changes["value"] != row.value
    for k, v in changes.items():
        if k == "description":
            v = (v or "").strip() or None
        setattr(row, k, v)
    affected = _reprovision(db, request, row) if changed_value else 0
    _audit(
        db,
        ctx,
        principal,
        "provisioning.variable_update",
        row,
        {"fields": sorted(changes), "reprovisioned": affected},
    )
    db.commit()
    return _out(row, _scope_names(db, [row]), reveal=True, affected=affected)


@router.delete("/{variable_id}", status_code=204, summary="Remove a variable")
def delete_variable(
    variable_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    row = _get(db, principal, variable_id, WRITE)
    used = varsvc.references_in_use(db, row)
    if used:
        raise ProblemError(
            409,
            "Variable in use",
            f"Key lists refer to ${row.name}: {', '.join(used)}.",
            code="variable_in_use",
            errors=[{"field": "references", "message": u} for u in used],
        )
    affected = _reprovision(db, request, row)
    _audit(db, ctx, principal, "provisioning.variable_delete", row, {"reprovisioned": affected})
    db.delete(row)
    db.commit()
    return Response(status_code=204)
