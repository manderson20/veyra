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

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden
from veyra.core.models import DeviceProfile, ProvisioningTemplate
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
        # No facts given: the renderer builds sample facts from the masked values.
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


class TemplateUpdateIn(BaseModel):
    """Editor save (docs/DEVICE_PROVISIONING.md §7): the manifest and sources of
    a local template, stored as a new version row when ``version`` changes."""

    manifest: dict[str, Any]
    sources: dict[str, str]


class CustomizeIn(BaseModel):
    key: str = Field(min_length=3, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    organization_id: uuid.UUID | None = None


def _local_rows(db: Session, key: str) -> list[ProvisioningTemplate]:
    return list(
        db.scalars(
            select(ProvisioningTemplate)
            .where(ProvisioningTemplate.template_key == key)
            .order_by(ProvisioningTemplate.created_at.desc())
        )
    )


@router.put("/templates/{key}", summary="Save a local template (editor)")
def update_template(
    key: str,
    body: TemplateUpdateIn,
    request: Request,
    principal: Principal = Depends(require("provisioning.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    rows = _local_rows(db, key)
    if not rows:
        catalog = _catalog(request, db)
        if key in catalog.records:
            raise ProblemError(
                409,
                "Not editable",
                f"{key!r} is an {catalog.records[key].source} template; use Customize to "
                "create an editable copy.",
                code="template_read_only",
            )
        raise ProblemError(404, "Not found", f"Template {key!r} not found", code="not_found")
    row = rows[0]
    if row.organization_id is not None and not principal.has(
        "provisioning.write", row.organization_id
    ):
        raise forbidden()
    if row.organization_id is None and not principal.is_platform_admin:
        raise forbidden()
    manifest = copy.deepcopy(body.manifest)
    manifest.setdefault("template", {})["key"] = key
    document = {
        "format": "veyra-provisioning-template",
        "format_version": 1,
        "manifest": manifest,
        "sources": body.sources,
    }
    catalog = _catalog(request, db)
    catalog.records.pop(key, None)  # validate the new content in place of the old
    try:
        record = _parse_import(catalog, document)
    except TemplateError as e:
        raise _template_error(e) from e
    t = record.manifest.template
    if t.version != row.version:
        row = ProvisioningTemplate(
            id=uuid.uuid4(),
            template_key=key,
            version=t.version,
            source="local",
            organization_id=rows[0].organization_id,
            manifest=record.manifest.model_dump(mode="json"),
            files=record.sources,
        )
        db.add(row)
        for old in rows:
            db.delete(old)
    else:
        row.manifest = record.manifest.model_dump(mode="json")
        row.files = record.sources
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(f"Local template {key} version {t.version} already exists.") from e
    audit.record(
        db,
        action="provisioning.template.update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=row.organization_id,
        target_type="provisioning_template",
        target_id=key,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"version": t.version, "files": sorted(record.sources)},
    )
    db.commit()
    return get_template(key, request, principal, db)


@router.post(
    "/templates/{key}/customize",
    status_code=201,
    summary="Create an editable local child of a template",
)
def customize_template(
    key: str,
    body: CustomizeIn,
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
    catalog = _catalog(request, db)
    parent = catalog.records.get(key)
    if parent is None:
        raise ProblemError(404, "Not found", f"Template {key!r} not found", code="not_found")
    if body.key in catalog.records:
        raise conflict(f"Template key {body.key!r} is already used.", "template_key_in_use")
    pt = parent.manifest.template
    sources = {}
    files = []
    for f in parent.manifest.files:
        if f.name == "{mac}.cfg":
            continue  # the master file is inherited unchanged
        files.append({"name": f.name, "source": f.source, "format": f.format})
        sources[f.source] = (
            f'{{% extends "{pt.key}/{f.source}" %}}\n'
            "{% block model_settings %}\n"
            "  <!-- Your changes go here. Override other blocks of the parent as needed. -->\n"
            "{% endblock %}\n"
        )
    manifest = {
        "spec_version": parent.manifest.spec_version,
        "template": {
            "key": body.key,
            "name": body.name.strip(),
            "version": "0.1.0",
            "manufacturer": pt.manufacturer,
            "models": list(pt.models),
            "abstract": pt.abstract,
            "parent": pt.key,
            "parent_version": pt.version,
            "firmware": pt.firmware,
            "status": "experimental",
            "description": f"Local customization of {pt.name} ({pt.key} {pt.version}).",
        },
        "files": files,
        "variables": [],
        "defaults": {},
        "features": list(parent.manifest.features),
    }
    try:
        record = _parse_import(
            catalog,
            {
                "format": "veyra-provisioning-template",
                "format_version": 1,
                "manifest": manifest,
                "sources": sources,
            },
        )
    except TemplateError as e:
        raise _template_error(e) from e
    db.add(
        ProvisioningTemplate(
            id=uuid.uuid4(),
            template_key=body.key,
            version="0.1.0",
            source="local",
            organization_id=body.organization_id,
            manifest=record.manifest.model_dump(mode="json"),
            files=record.sources,
        )
    )
    created = [body.key]
    if pt.abstract:
        # A customized family needs its own model templates: the official ones
        # inherit from the official family, not from the copy. One local child
        # per concrete descendant, extending the new family's files.
        catalog.records[body.key] = record
        for child in list(catalog.records.values()):
            ct = child.manifest.template
            if ct.parent != key or ct.abstract:
                continue
            child_key = f"{body.key}.{ct.key.rsplit('.', 1)[-1]}"
            if child_key in catalog.records:
                continue
            child_sources = {
                name: text.replace(f'"{key}/', f'"{body.key}/').replace(f"'{key}/", f"'{body.key}/")
                for name, text in child.sources.items()
            }
            child_manifest = child.manifest.model_dump(mode="json")
            child_manifest["template"].update(
                {
                    "key": child_key,
                    "name": f"{body.name.strip()}: {ct.name}",
                    "version": "0.1.0",
                    "parent": body.key,
                    "parent_version": "0.1.0",
                    "status": "experimental",
                    "description": f"Local customization of {ct.name} ({ct.key} {ct.version}).",
                }
            )
            try:
                child_record = _parse_import(
                    catalog,
                    {
                        "format": "veyra-provisioning-template",
                        "format_version": 1,
                        "manifest": child_manifest,
                        "sources": child_sources,
                    },
                )
            except TemplateError as e:
                raise _template_error(e) from e
            catalog.records[child_key] = child_record
            db.add(
                ProvisioningTemplate(
                    id=uuid.uuid4(),
                    template_key=child_key,
                    version="0.1.0",
                    source="local",
                    organization_id=body.organization_id,
                    manifest=child_record.manifest.model_dump(mode="json"),
                    files=child_record.sources,
                )
            )
            created.append(child_key)
    db.flush()
    audit.record(
        db,
        action="provisioning.template.customize",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=body.organization_id,
        target_type="provisioning_template",
        target_id=body.key,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"parent": key, "created": created},
    )
    db.commit()
    return get_template(body.key, request, principal, db)


@router.delete("/templates/{key}", status_code=204, summary="Delete a local template")
def delete_template(
    key: str,
    request: Request,
    principal: Principal = Depends(require("provisioning.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    rows = _local_rows(db, key)
    if not rows:
        raise ProblemError(404, "Not found", f"Local template {key!r} not found", code="not_found")
    if rows[0].organization_id is not None and not principal.has(
        "provisioning.write", rows[0].organization_id
    ):
        raise forbidden()
    if rows[0].organization_id is None and not principal.is_platform_admin:
        raise forbidden()
    used = db.scalar(select(func.count(DeviceProfile.id)).where(DeviceProfile.template_key == key))
    children = [
        r.key for r in _catalog(request, db).records.values() if r.manifest.template.parent == key
    ]
    if used or children:
        raise ProblemError(
            409,
            "Template in use",
            f"{used} device profile(s) and {len(children)} template(s) depend on {key}.",
            code="template_in_use",
        )
    for row in rows:
        db.delete(row)
    audit.record(
        db,
        action="provisioning.template.delete",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=rows[0].organization_id,
        target_type="provisioning_template",
        target_id=key,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={},
    )
    db.commit()
    return Response(status_code=204)
