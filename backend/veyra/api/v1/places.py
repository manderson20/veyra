# SPDX-License-Identifier: AGPL-3.0-or-later
"""Buildings and departments (issue #126).

A building belongs to a site and may carry its own civic address, which the
emergency notification and the readiness check use for the extensions in it
(docs/PRODUCTION_HARDENING.md §6). A department groups extensions of an
organization, optionally at one site; My Phone layout templates can be
assigned to a building or a department (docs/USER_PORTAL.md §8).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1.sites import READ, WRITE
from veyra.api.v1.sites import _get as get_site
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.models import Building, Department, Extension, PortalTemplate, Site
from veyra.core.security.principal import Principal

router = APIRouter(tags=["sites"])


def _text(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class _Address(BaseModel):
    street: str | None = Field(None, max_length=200)
    city: str | None = Field(None, max_length=100)
    region: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    country: str | None = Field(None, max_length=2)

    @field_validator("street", "city", "region", "postal_code")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return _text(v)

    @field_validator("country")
    @classmethod
    def _country(cls, v: str | None) -> str | None:
        v = _text(v)
        if v is not None and not re.match(r"^[A-Za-z]{2}$", v):
            raise ValueError("two-letter country code")
        return v.upper() if v else None


def _name(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        raise ValueError("enter a name")
    return v


class BuildingIn(_Address):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def _n(cls, v: str) -> str:
        return _name(v) or v


class BuildingPatch(_Address):
    name: str | None = Field(None, min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def _n(cls, v: str | None) -> str | None:
        return _name(v)


class BuildingOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    site_id: uuid.UUID
    site_name: str
    name: str
    street: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country: str | None
    # The address emergency notifications give: the building's, else the site's.
    has_own_address: bool
    extensions: int
    created_at: datetime
    updated_at: datetime


class DepartmentIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    site_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def _n(cls, v: str) -> str:
        return _name(v) or v


class DepartmentPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    site_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def _n(cls, v: str | None) -> str | None:
        return _name(v)


class DepartmentOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    site_id: uuid.UUID | None
    site_name: str | None
    extensions: int
    created_at: datetime
    updated_at: datetime


def _record(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    row: Building | Department,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=row.organization_id,
        target_type="building" if isinstance(row, Building) else "department",
        target_id=row.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": row.name, **details},
    )


def _counts(db: Session, col: Any, ids: set[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    return {
        k: int(v)
        for k, v in db.execute(
            select(col, func.count(Extension.id)).where(col.in_(ids)).group_by(col)
        )
    }


def _site_names(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(db.execute(select(Site.id, Site.name).where(Site.id.in_(ids))).all())


def _building_outs(db: Session, rows: list[Building]) -> list[BuildingOut]:
    counts = _counts(db, Extension.building_id, {r.id for r in rows})
    sites = _site_names(db, {r.site_id for r in rows})
    return [
        BuildingOut(
            id=r.id,
            organization_id=r.organization_id,
            site_id=r.site_id,
            site_name=sites.get(r.site_id, ""),
            name=r.name,
            street=r.street,
            city=r.city,
            region=r.region,
            postal_code=r.postal_code,
            country=r.country,
            has_own_address=bool(r.street),
            extensions=counts.get(r.id, 0),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


def _department_outs(db: Session, rows: list[Department]) -> list[DepartmentOut]:
    counts = _counts(db, Extension.department_id, {r.id for r in rows})
    sites = _site_names(db, {r.site_id for r in rows if r.site_id})
    return [
        DepartmentOut(
            id=r.id,
            organization_id=r.organization_id,
            name=r.name,
            site_id=r.site_id,
            site_name=sites.get(r.site_id) if r.site_id else None,
            extensions=counts.get(r.id, 0),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


def _name_taken(name: str) -> ProblemError:
    return conflict(f"The name {name!r} is already used here.", "name_in_use")


def _templates_using(db: Session, scope: str, row_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count(PortalTemplate.id)).where(
                PortalTemplate.scope == scope, PortalTemplate.scope_ref == str(row_id)
            )
        )
        or 0
    )


# ----------------------------------------------------------------- buildings


@router.get("/sites/{site_id}/buildings", response_model=list[BuildingOut], summary="Buildings")
def list_buildings(
    site_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> list[BuildingOut]:
    site = get_site(db, principal, site_id, READ)
    rows = db.scalars(select(Building).where(Building.site_id == site.id).order_by(Building.name))
    return _building_outs(db, list(rows))


@router.get("/buildings", response_model=list[BuildingOut], summary="Buildings of organizations")
def list_all_buildings(
    organization_id: uuid.UUID | None = None,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> list[BuildingOut]:
    """For pickers (extensions, layout templates): every visible building."""
    stmt = select(Building).order_by(Building.name)
    orgs = principal.organization_ids_with(READ)
    if orgs is not None:
        stmt = stmt.where(Building.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    if organization_id:
        stmt = stmt.where(Building.organization_id == organization_id)
    return _building_outs(db, list(db.scalars(stmt.limit(1000))))


@router.post(
    "/sites/{site_id}/buildings",
    response_model=BuildingOut,
    status_code=201,
    summary="Add a building",
)
def create_building(
    site_id: uuid.UUID,
    body: BuildingIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> BuildingOut:
    site = get_site(db, principal, site_id, WRITE)
    if not principal.has(WRITE, site.organization_id):
        raise forbidden()
    row = Building(
        id=uuid.uuid4(),
        organization_id=site.organization_id,
        site_id=site.id,
        **body.model_dump(),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise _name_taken(body.name) from e
    _record(db, ctx, principal, "building.create", row, {"site": site.name})
    db.commit()
    return _building_outs(db, [row])[0]


def _get_building(db: Session, principal: Principal, building_id: uuid.UUID) -> Building:
    row = db.get(Building, building_id)
    if row is None or not principal.has(WRITE, row.organization_id):
        raise not_found("Building")
    return row


@router.patch("/buildings/{building_id}", response_model=BuildingOut)
def update_building(
    building_id: uuid.UUID,
    body: BuildingPatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> BuildingOut:
    row = _get_building(db, principal, building_id)
    details: dict[str, Any] = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "name" and value is None:
            continue
        if value != getattr(row, field):
            details[field] = value
            setattr(row, field, value)
    if details:
        try:
            db.flush()
        except IntegrityError as e:
            db.rollback()
            raise _name_taken(str(body.name)) from e
        _record(db, ctx, principal, "building.update", row, details)
        db.commit()
    return _building_outs(db, [row])[0]


@router.delete("/buildings/{building_id}", status_code=204)
def delete_building(
    building_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    row = _get_building(db, principal, building_id)
    exts = _counts(db, Extension.building_id, {row.id}).get(row.id, 0)
    templates = _templates_using(db, "building", row.id)
    if exts or templates:
        raise ProblemError(
            409,
            "Building in use",
            f"{exts} extension(s) and {templates} My Phone layout template(s) use this "
            "building. Move them first.",
            code="building_in_use",
        )
    _record(db, ctx, principal, "building.delete", row, {})
    db.delete(row)
    db.commit()
    return Response(status_code=204)


# ----------------------------------------------------------------- departments


def _check_site(db: Session, organization_id: uuid.UUID, site_id: uuid.UUID | None) -> None:
    if site_id is None:
        return
    site = db.get(Site, site_id)
    if site is None or site.organization_id != organization_id:
        raise ProblemError(
            422,
            "Validation failed",
            "The site is not in this organization.",
            code="validation_failed",
            errors=[{"field": "site_id", "message": "the site is not in this organization"}],
        )


@router.get("/departments", response_model=list[DepartmentOut], summary="Departments")
def list_departments(
    organization_id: uuid.UUID | None = None,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> list[DepartmentOut]:
    stmt = select(Department).order_by(Department.name)
    orgs = principal.organization_ids_with(READ)
    if orgs is not None:
        stmt = stmt.where(Department.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    if organization_id:
        stmt = stmt.where(Department.organization_id == organization_id)
    return _department_outs(db, list(db.scalars(stmt.limit(1000))))


@router.post(
    "/departments", response_model=DepartmentOut, status_code=201, summary="Add a department"
)
def create_department(
    body: DepartmentIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> DepartmentOut:
    if not principal.has(WRITE, body.organization_id):
        raise forbidden()
    _check_site(db, body.organization_id, body.site_id)
    row = Department(id=uuid.uuid4(), **body.model_dump())
    db.add(row)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise _name_taken(body.name) from e
    _record(db, ctx, principal, "department.create", row, {})
    db.commit()
    return _department_outs(db, [row])[0]


def _get_department(db: Session, principal: Principal, department_id: uuid.UUID) -> Department:
    row = db.get(Department, department_id)
    if row is None or not principal.has(WRITE, row.organization_id):
        raise not_found("Department")
    return row


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
def update_department(
    department_id: uuid.UUID,
    body: DepartmentPatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> DepartmentOut:
    row = _get_department(db, principal, department_id)
    changes = body.model_dump(exclude_unset=True)
    if "site_id" in changes:
        _check_site(db, row.organization_id, changes["site_id"])
    details: dict[str, Any] = {}
    for field, value in changes.items():
        if field == "name" and value is None:
            continue
        if value != getattr(row, field):
            details[field] = str(value) if isinstance(value, uuid.UUID) else value
            setattr(row, field, value)
    if details:
        try:
            db.flush()
        except IntegrityError as e:
            db.rollback()
            raise _name_taken(str(body.name)) from e
        _record(db, ctx, principal, "department.update", row, details)
        db.commit()
    return _department_outs(db, [row])[0]


@router.delete("/departments/{department_id}", status_code=204)
def delete_department(
    department_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    row = _get_department(db, principal, department_id)
    templates = _templates_using(db, "department", row.id)
    if templates:
        raise ProblemError(
            409,
            "Department in use",
            f"{templates} My Phone layout template(s) are assigned to this department.",
            code="department_in_use",
        )
    _record(db, ctx, principal, "department.delete", row, {})
    db.delete(row)  # extensions keep working without a department (SET NULL)
    db.commit()
    return Response(status_code=204)
