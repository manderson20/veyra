# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provisioning templates: catalog, validation, preview, import and export.

Official and community templates are read from disk and are never modified
by Veyra. Local templates are stored in the database; they may inherit from
official templates to override settings without changing them.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden
from veyra.core.models import ProvisioningTemplate
from veyra.core.security.principal import Principal
from veyra.provisioning.renderer import (
    MAX_SOURCE_BYTES,
    TemplateCatalog,
    TemplateRecord,
    export_template,
    render,
    validate,
)
from veyra.provisioning.spec import CORE_VARIABLES, TemplateError, parse_template_manifest

router = APIRouter(prefix="/provisioning", tags=["provisioning"])

MAX_IMPORT_FILES = 32


class PreviewIn(BaseModel):
    mac: str = Field(default="0004f2000001", max_length=32)
    model: str = Field(max_length=64)
    values: dict[str, Any] = Field(default_factory=dict)


class ImportIn(BaseModel):
    document: dict[str, Any]
    organization_id: uuid.UUID | None = None


def _catalog(request: Request, db: Session) -> TemplateCatalog:
    base: TemplateCatalog = request.app.state.templates
    catalog = TemplateCatalog()
    catalog.records = dict(base.records)
    catalog.load_errors = dict(base.load_errors)
    for row in db.scalars(select(ProvisioningTemplate)):
        try:
            catalog.add(
                TemplateRecord(parse_template_manifest(row.manifest), row.source, dict(row.files))
            )
        except TemplateError as e:
            catalog.load_errors[f"db:{row.template_key}"] = e.errors
    return catalog


def catalog_for(request: Request, db: Session) -> TemplateCatalog:
    """The catalog with local templates merged in (used by profiles and devices)."""
    return _catalog(request, db)


def _template_error(e: TemplateError) -> ProblemError:
    return ProblemError(
        422,
        "Template error",
        str(e),
        code="template_error",
        errors=[{"message": m} for m in e.errors],
    )


def _summary(rec: TemplateRecord) -> dict[str, Any]:
    t = rec.manifest.template
    return {
        "key": t.key,
        "name": t.name,
        "version": t.version,
        "manufacturer": t.manufacturer,
        "models": t.models,
        "abstract": t.abstract,
        "parent": t.parent,
        "parent_version": t.parent_version,
        "firmware": t.firmware,
        "status": t.status,
        "description": t.description,
        "source": rec.source,
        "features": rec.manifest.features,
    }


@router.get("/variables", summary="Approved template variables")
def variables(principal: Principal = Depends(require("provisioning.read"))) -> list[dict[str, Any]]:
    return [v.model_dump() for v in CORE_VARIABLES]


@router.get("/models", summary="Manufacturers and models known to the template catalog")
def models(
    request: Request,
    principal: Principal = Depends(require("provisioning.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    out: dict[str, set[str]] = {}
    for rec in _catalog(request, db).records.values():
        t = rec.manifest.template
        if not t.abstract:
            out.setdefault(t.manufacturer, set()).update(t.models)
    return {"manufacturers": [{"name": m, "models": sorted(v)} for m, v in sorted(out.items())]}


@router.get("/templates", summary="List provisioning templates")
def list_templates(
    request: Request,
    principal: Principal = Depends(require("provisioning.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    catalog = _catalog(request, db)
    items = sorted(
        (_summary(r) for r in catalog.records.values()),
        key=lambda s: (s["manufacturer"], s["abstract"], s["name"]),
    )
    for item in items:
        parent = catalog.records.get(item["parent"]) if item["parent"] else None
        item["parent_updated"] = bool(
            parent
            and item["parent_version"]
            and parent.manifest.template.version != item["parent_version"]
        )
    return {"items": items, "load_errors": catalog.load_errors}


@router.get("/templates/{key}", summary="Template details with resolved inheritance")
def get_template(
    key: str,
    request: Request,
    principal: Principal = Depends(require("provisioning.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        resolved = _catalog(request, db).resolve(key)
    except TemplateError as e:
        raise ProblemError(404, "Not found", str(e), code="not_found") from e
    return {
        **_summary(resolved.record),
        "chain": [r.key for r in resolved.chain],
        "files": [f.model_dump() for f in resolved.files],
        "variables": [v.model_dump() for v in resolved.variables.values()],
        "defaults": {
            k: v
            for k, v in resolved.defaults.items()
            if not resolved.variables.get(k) or not resolved.variables[k].sensitive
        },
        "validation": validate(resolved),
    }


@router.post(
    "/templates/{key}/preview", summary="Render a template with sample values (secrets masked)"
)
def preview(
    key: str,
    body: PreviewIn,
    request: Request,
    principal: Principal = Depends(require("provisioning.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        resolved = _catalog(request, db).resolve(key)
        files = render(resolved, body.values, mac=body.mac, model=body.model, mask_secrets=True)
    except TemplateError as e:
        raise _template_error(e) from e
    return {
        "files": [{"filename": f.filename, "format": f.format, "content": f.content} for f in files]
    }


@router.get("/templates/{key}/export", summary="Export a template (never includes secrets)")
def export(
    key: str,
    request: Request,
    principal: Principal = Depends(require("provisioning.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rec = _catalog(request, db).records.get(key)
    if rec is None:
        raise ProblemError(404, "Not found", f"Template {key!r} not found", code="not_found")
    return export_template(rec)


def _parse_import(catalog: TemplateCatalog, document: dict[str, Any]) -> TemplateRecord:
    if (
        document.get("format") != "veyra-provisioning-template"
        or document.get("format_version") != 1
    ):
        raise TemplateError("Not a Veyra provisioning template export (format version 1)")
    sources = document.get("sources")
    if not isinstance(sources, dict) or len(sources) > MAX_IMPORT_FILES:
        raise TemplateError(f"'sources' must be an object with at most {MAX_IMPORT_FILES} files")
    for name, text in sources.items():
        if not isinstance(name, str) or not isinstance(text, str):
            raise TemplateError("Template sources must be text")
        if len(text.encode()) > MAX_SOURCE_BYTES:
            raise TemplateError(f"{name} is too large")
    manifest = parse_template_manifest(copy.deepcopy(document.get("manifest") or {}))
    existing = catalog.records.get(manifest.template.key)
    if existing and existing.source != "local":
        raise TemplateError(
            f"{manifest.template.key!r} is an {existing.source} template. Import your changes "
            "under a new key with this template as its parent instead of replacing it."
        )
    record = TemplateRecord(manifest, "local", dict(sources))
    trial = TemplateCatalog()
    trial.records = {**catalog.records, record.key: record}
    problems = validate(trial.resolve(record.key))
    if problems:
        raise TemplateError("Template validation failed", problems)
    return record


@router.post("/templates/validate", summary="Validate a template export without importing it")
def validate_import(
    body: ImportIn,
    request: Request,
    principal: Principal = Depends(require("provisioning.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        record = _parse_import(_catalog(request, db), body.document)
    except TemplateError as e:
        return {"valid": False, "errors": e.errors}
    return {"valid": True, "errors": [], "template": _summary(record)}


@router.post("/templates/import", status_code=201, summary="Import a template as a local template")
def import_template(
    body: ImportIn,
    request: Request,
    principal: Principal = Depends(require("provisioning.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    if body.organization_id is None and not principal.is_platform_admin:
        raise forbidden("Choose an organization for this template.")
    if body.organization_id is not None and not principal.has(
        "provisioning.write", body.organization_id
    ):
        raise forbidden()
    try:
        record = _parse_import(_catalog(request, db), body.document)
    except TemplateError as e:
        raise _template_error(e) from e
    t = record.manifest.template
    db.add(
        ProvisioningTemplate(
            id=uuid.uuid4(),
            template_key=t.key,
            version=t.version,
            source="local",
            organization_id=body.organization_id,
            manifest=record.manifest.model_dump(mode="json"),
            files=record.sources,
        )
    )
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(f"Local template {t.key} version {t.version} already exists.") from e
    audit.record(
        db,
        action="provisioning.template_import",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=body.organization_id,
        target_type="provisioning_template",
        target_id=t.key,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"version": t.version, "parent": t.parent},
    )
    db.commit()
    return _summary(record)
