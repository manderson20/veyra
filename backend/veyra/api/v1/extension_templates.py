# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extension templates (issue #172): settings a group of extensions follows,
with locked fields; applied on create and re-applied with a preview."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import group_helpers as helpers
from veyra.configmgmt import service as configmgmt
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.models import Extension, ExtensionTemplate, Organization
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import ext_templates

router = APIRouter(prefix="/extension-templates", tags=["extension-templates"])
READ = "extensions.read"
WRITE = "extensions.write"


class TemplateIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    settings: dict[str, Any] = Field(default_factory=dict)
    locked: list[str] = Field(default_factory=list, max_length=len(ext_templates.FIELDS))


class TemplatePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    settings: dict[str, Any] | None = None
    locked: list[str] | None = Field(None, max_length=len(ext_templates.FIELDS))


class TemplateOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    settings: dict[str, Any]
    locked: list[str]
    extensions: int
    created_at: datetime
    updated_at: datetime


class ApplyIn(BaseModel):
    # True: only list what would change.
    dry_run: bool = True


def _invalid(e: ext_templates.TemplateError) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        e.message,
        code="validation_failed",
        errors=[
            {
                "field": f"settings.{e.field}" if e.field != "locked" else "locked",
                "message": e.message,
            }
        ],
    )


def _outs(db: Session, rows: list[ExtensionTemplate]) -> list[TemplateOut]:
    counts = (
        dict(
            db.execute(
                select(Extension.template_id, func.count())
                .where(Extension.template_id.in_([r.id for r in rows]))
                .group_by(Extension.template_id)
            ).all()
        )
        if rows
        else {}
    )
    return [
        TemplateOut(
            id=r.id,
            organization_id=r.organization_id,
            name=r.name,
            description=r.description,
            settings=dict(r.settings or {}),
            locked=list(r.locked or []),
            extensions=int(counts.get(r.id, 0)),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


def get_template(
    db: Session, principal: Principal, template_id: uuid.UUID, perm: str
) -> ExtensionTemplate:
    stmt = helpers.org_filter(
        select(ExtensionTemplate), ExtensionTemplate.organization_id, principal, perm
    )
    row = db.scalar(stmt.where(ExtensionTemplate.id == template_id))
    if row is None:
        raise not_found("Extension template")
    return row


@router.get("", response_model=Page[TemplateOut], summary="List extension templates")
def list_templates(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[TemplateOut]:
    stmt = helpers.org_filter(
        select(ExtensionTemplate), ExtensionTemplate.organization_id, principal, READ
    ).order_by(ExtensionTemplate.name)
    if organization_id:
        stmt = stmt.where(ExtensionTemplate.organization_id == organization_id)
    if q:
        stmt = stmt.where(ExtensionTemplate.name.ilike(f"%{q.strip()}%"))
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post(
    "", response_model=TemplateOut, status_code=201, summary="Create an extension template"
)
def create_template(
    body: TemplateIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> TemplateOut:
    if not principal.has(WRITE, body.organization_id):
        raise forbidden()
    if db.get(Organization, body.organization_id) is None:
        raise not_found("Organization")
    try:
        settings, locked = ext_templates.normalize(
            db, body.organization_id, body.settings, body.locked
        )
    except ext_templates.TemplateError as e:
        raise _invalid(e) from e
    row = ExtensionTemplate(
        id=uuid.uuid4(),
        organization_id=body.organization_id,
        name=body.name.strip(),
        description=(body.description or "").strip() or None,
        settings=settings,
        locked=locked,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(
            "A template with that name exists in this organization.", "name_in_use"
        ) from e
    helpers.record(
        db,
        ctx,
        principal,
        "extension_template.create",
        target_type="extension_template",
        target=row,
        details={"name": row.name, "settings": settings, "locked": locked},
    )
    db.commit()
    return _outs(db, [row])[0]


@router.get("/{template_id}", response_model=TemplateOut)
def read_template(
    template_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> TemplateOut:
    return _outs(db, [get_template(db, principal, template_id, READ)])[0]


@router.patch("/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: uuid.UUID,
    body: TemplatePatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> TemplateOut:
    """Changes the template only; its extensions change when it is applied."""
    row = get_template(db, principal, template_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    wanted_settings: dict[str, Any] = (
        body.settings if body.settings is not None else dict(row.settings or {})
    )
    wanted_locked: list[str] = body.locked if body.locked is not None else list(row.locked or [])
    try:
        settings, locked = ext_templates.normalize(
            db, row.organization_id, wanted_settings, wanted_locked
        )
    except ext_templates.TemplateError as e:
        raise _invalid(e) from e
    details: dict[str, Any] = {}
    if changes.get("name") and changes["name"].strip() != row.name:
        row.name = changes["name"].strip()
        details["name"] = row.name
    if "description" in changes:
        row.description = (changes["description"] or "").strip() or None
        details["description"] = True
    if settings != row.settings:
        row.settings = settings
        details["settings"] = settings
    if locked != row.locked:
        row.locked = locked
        details["locked"] = locked
    if details:
        try:
            db.flush()
        except IntegrityError as e:
            db.rollback()
            raise conflict(
                "A template with that name exists in this organization.", "name_in_use"
            ) from e
        helpers.record(
            db,
            ctx,
            principal,
            "extension_template.update",
            target_type="extension_template",
            target=row,
            details=details,
        )
        db.commit()
    return _outs(db, [row])[0]


@router.delete("/{template_id}", status_code=204)
def delete_template(
    template_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    """Its extensions keep their settings and stop following it."""
    row = get_template(db, principal, template_id, WRITE)
    for ext in ext_templates.members(db, row):
        ext.template_id = None
    helpers.record(
        db,
        ctx,
        principal,
        "extension_template.delete",
        target_type="extension_template",
        target=row,
        details={"name": row.name},
    )
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.post("/{template_id}/apply", summary="Preview or apply a template to its extensions")
def apply_template(
    template_id: uuid.UUID,
    body: ApplyIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    row = get_template(db, principal, template_id, WRITE)
    changes = []
    deploy = False
    for ext in ext_templates.members(db, row):
        if body.dry_run:
            diff = ext_templates.differences(db, row, ext)
        else:
            diff = ext_templates.apply(
                db,
                row,
                ext,
                by="admin",
                adapter=getattr(request.app.state, "telephony", None),
            )
        if diff:
            deploy = deploy or bool(set(diff) & ext_templates.DEPLOYED)
            changes.append({"extension_id": str(ext.id), "number": ext.number, "changes": diff})
    if not body.dry_run and changes:
        helpers.record(
            db,
            ctx,
            principal,
            "extension_template.apply",
            target_type="extension_template",
            target=row,
            details={"extensions": [c["number"] for c in changes]},
        )
        if deploy:
            configmgmt.mark_changed(db, by=principal.label, what=f"extension template {row.name}")
        db.commit()
    return {"dry_run": body.dry_run, "extensions": changes, "needs_deployment": deploy}
