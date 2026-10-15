# SPDX-License-Identifier: AGPL-3.0-or-later
"""Module catalog, upload, updates, rollback, settings and service restart
(docs/MODULE_CATALOG.md §3-5). Platform administrators (``modules.manage``);
reading the catalog needs ``modules.read``. Registered before the module
router so ``/modules/catalog`` is not taken for a module id."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1.modules import manager
from veyra.core import audit
from veyra.core.db import get_db, get_engine
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, not_found
from veyra.core.models import CatalogSource, InstalledModule, ModuleConfig, SystemSetting
from veyra.core.models.base import utcnow
from veyra.core.security.crypto import load_installation_key
from veyra.core.security.principal import Principal
from veyra.core.semver import Version, VersionRange
from veyra.modules import catalog
from veyra.modules.manager import ModuleError, ModuleManager
from veyra.version import MODULE_API_VERSION

router = APIRouter(prefix="/modules", tags=["modules"])

MANAGE = "modules.manage"
READ = "modules.read"
RESTART_KEY = catalog.RESTART_KEY
MAX_UPLOAD = catalog.MAX_PACKAGE_BYTES


def _audit(
    db: Session,
    principal: Principal,
    ctx: RequestContext,
    action: str,
    target: str,
    details: dict[str, Any],
    outcome: str = "success",
) -> None:
    audit.record(
        db,
        action=action,
        outcome=outcome,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="module",
        target_id=target,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=details,
    )


def _store(request: Request) -> catalog.Store:
    return catalog.Store(request.app.state.settings.module_store_dir)


# ----------------------------------------------------------------- sources


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=8, max_length=500)
    is_enabled: bool = True


class SourceOut(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    is_enabled: bool
    signed_by: str | None
    modules: int
    last_fetched_at: datetime | None
    last_status: str | None
    last_error: str | None


def _source_out(s: CatalogSource) -> SourceOut:
    return SourceOut(
        id=s.id,
        name=s.name,
        url=s.url,
        is_enabled=s.is_enabled,
        signed_by=s.signed_by,
        modules=len((s.index or {}).get("modules", [])),
        last_fetched_at=s.last_fetched_at,
        last_status=s.last_status,
        last_error=s.last_error,
    )


@router.get("/catalog-sources", response_model=list[SourceOut], summary="Module catalog sources")
def list_sources(
    principal: Principal = Depends(require(READ)), db: Session = Depends(get_db)
) -> list[SourceOut]:
    return [_source_out(s) for s in db.scalars(select(CatalogSource).order_by(CatalogSource.name))]


@router.post(
    "/catalog-sources", response_model=SourceOut, status_code=201, summary="Add a catalog source"
)
def add_source(
    body: SourceIn,
    request: Request,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> SourceOut:
    try:
        catalog._check_url(body.url)
    except catalog.CatalogError as e:
        raise ProblemError(422, "Validation failed", str(e), code="validation_failed") from e
    s = CatalogSource(
        id=uuid.uuid4(), name=body.name.strip(), url=body.url.strip(), is_enabled=body.is_enabled
    )
    db.add(s)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("A source with that name or address exists.", "duplicate") from e
    catalog.refresh_source(s, request.app.state.settings.trust_dir)
    _audit(
        db,
        principal,
        ctx,
        "module.catalog_source_add",
        s.name,
        {"url": s.url, "status": s.last_status},
    )
    db.commit()
    return _source_out(s)


@router.delete("/catalog-sources/{source_id}", status_code=204, summary="Remove a catalog source")
def delete_source(
    source_id: uuid.UUID,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    s = db.get(CatalogSource, source_id)
    if s is None:
        raise not_found("Catalog source")
    _audit(db, principal, ctx, "module.catalog_source_delete", s.name, {"url": s.url})
    db.delete(s)
    db.commit()
    return Response(status_code=204)


@router.post("/catalog/refresh", response_model=list[SourceOut], summary="Fetch every catalog now")
def refresh_all(
    request: Request,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
) -> list[SourceOut]:
    sources = db.scalars(select(CatalogSource).where(CatalogSource.is_enabled.is_(True))).all()
    for s in sources:
        catalog.refresh_source(s, request.app.state.settings.trust_dir)
    db.commit()
    return [_source_out(s) for s in sources]


# ----------------------------------------------------------------- catalog


def _versions(
    db: Session,
) -> dict[str, list[tuple[CatalogSource, dict[str, Any], catalog.CatalogVersion]]]:
    """module id -> (source, module entry, version) for every verified index."""
    out: dict[str, list[tuple[CatalogSource, dict[str, Any], catalog.CatalogVersion]]] = {}
    for s in db.scalars(select(CatalogSource).where(CatalogSource.is_enabled.is_(True))):
        if not s.index:
            continue
        idx = catalog.CatalogIndex.model_validate(s.index)
        for m in idx.modules:
            for v in m.versions:
                out.setdefault(m.id, []).append((s, m.model_dump(exclude={"versions"}), v))
    return out


@router.get("/catalog", summary="Modules offered by the catalogs, with compatibility")
def list_catalog(
    request: Request,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    installed = {r.module_id: r for r in db.scalars(select(InstalledModule))}
    api = Version.parse(MODULE_API_VERSION)
    out = []
    for module_id, entries in sorted(_versions(db).items()):
        entries.sort(key=lambda e: Version.parse(e[2].version), reverse=True)
        source, info, _ = entries[0]
        row = installed.get(module_id)
        versions = []
        for s, _, v in entries:
            compatible = VersionRange.parse(v.core_api).contains(api)
            versions.append(
                {
                    **v.model_dump(),
                    "source": s.name,
                    "compatible": compatible,
                    "problem": None
                    if compatible
                    else f"needs module API {v.core_api}; this Veyra has {MODULE_API_VERSION}",
                }
            )
        latest = next((v for v in versions if v["compatible"]), None)
        current = row.version if row and row.state != "removed" else None
        out.append(
            {
                **info,
                "source": source.name,
                "installed_version": current,
                "state": row.state if row else "available",
                "latest_compatible": latest["version"] if latest else None,
                "update_available": bool(
                    current and latest and Version.parse(latest["version"]) > Version.parse(current)
                ),
                "versions": versions,
            }
        )
    return out


class InstallIn(BaseModel):
    module_id: str = Field(max_length=128)
    version: str | None = None  # default: the latest compatible
    enable: bool = True


def _activate_and_apply(
    request: Request,
    db: Session,
    mgr: ModuleManager,
    package: bytes,
    expect_id: str | None,
    enable: bool,
) -> tuple[str, str, str]:
    """Verify into the store, check, activate, then install or update.
    Returns (module id, version, what happened)."""
    settings = request.app.state.settings
    store = _store(request)
    try:
        manifest, verification = store.add(
            package, mgr.keyring, settings.unsigned_modules_permitted
        )
    except catalog.CatalogError as e:
        raise ProblemError(422, "Package refused", str(e), code="package_refused") from e
    if expect_id is not None and manifest.id != expect_id:
        raise ProblemError(
            422,
            "Package refused",
            f"The package is {manifest.id}, not {expect_id}.",
            code="package_refused",
        )
    problems = mgr.trust_problems(manifest, verification) + mgr.compatibility_problems(db, manifest)
    row = db.get(InstalledModule, manifest.id)
    current = row.version if row is not None and row.state != "removed" else None
    if current is not None and Version.parse(manifest.module.version) <= Version.parse(current):
        problems.append(
            f"Version {manifest.module.version} is not newer than the installed {current}."
        )
    if problems:
        raise ProblemError(
            409,
            "Cannot install",
            " ".join(problems),
            code="module_not_installable",
            errors=[{"field": "package", "message": p} for p in problems],
        )
    store.activate(manifest.id, manifest.module.version)
    try:
        if current is None:
            mgr.install(db, get_engine(), manifest.id)
            what = "installed"
            if enable:
                mgr.enable(db, manifest.id)
                what = "installed and enabled"
        else:
            mgr.apply_update(db, get_engine(), manifest.id)
            what = f"updated from {current}"
    except ModuleError as e:
        raise ProblemError(
            e.status,
            "Module operation failed",
            e.detail,
            code="module_error",
            errors=[{"field": "module", "message": p} for p in e.errors or []],
        ) from e
    return manifest.id, manifest.module.version, what


@router.post("/catalog/install", summary="Install or update a module from a catalog")
def install_from_catalog(
    body: InstallIn,
    request: Request,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    mgr: ModuleManager = Depends(manager),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    api = Version.parse(MODULE_API_VERSION)
    entries = [
        e
        for e in _versions(db).get(body.module_id, [])
        if VersionRange.parse(e[2].core_api).contains(api)
    ]
    if body.version:
        entries = [e for e in entries if e[2].version == body.version]
    if not entries:
        raise not_found("A compatible catalog version of this module")
    source, _, v = max(entries, key=lambda e: Version.parse(e[2].version))
    try:
        package = catalog.download_package(v)
    except catalog.CatalogError as e:
        _audit(
            db,
            principal,
            ctx,
            "module.catalog_install",
            body.module_id,
            {"version": v.version, "error": str(e)},
            "failure",
        )
        db.commit()
        raise ProblemError(502, "Download failed", str(e), code="download_failed") from e
    try:
        module_id, version, what = _activate_and_apply(
            request, db, mgr, package, body.module_id, body.enable
        )
    except ProblemError as e:
        db.rollback()
        _audit(
            db,
            principal,
            ctx,
            "module.catalog_install",
            body.module_id,
            {"version": v.version, "error": e.detail},
            "failure",
        )
        db.commit()
        raise
    _audit(
        db,
        principal,
        ctx,
        "module.catalog_install",
        module_id,
        {
            "version": version,
            "result": what,
            "source": source.name,
            "url": v.url,
            "sha256": v.sha256,
        },
    )
    db.commit()
    return {
        "module_id": module_id,
        "version": version,
        "result": what,
        "restart_required": module_id in mgr.restart_required,
    }


@router.post("/upload", summary="Upload a module package (.vmod)")
async def upload_module(
    request: Request,
    file: UploadFile = File(...),
    enable: bool = False,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    mgr: ModuleManager = Depends(manager),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise ProblemError(
            413, "Too large", "Module packages are limited to 200 MB.", code="too_large"
        )
    try:
        module_id, version, what = _activate_and_apply(request, db, mgr, data, None, enable)
    except ProblemError as e:
        db.rollback()
        _audit(
            db,
            principal,
            ctx,
            "module.upload",
            file.filename or "?",
            {"error": e.detail},
            "failure",
        )
        db.commit()
        raise
    _audit(
        db,
        principal,
        ctx,
        "module.upload",
        module_id,
        {"version": version, "result": what, "filename": file.filename},
    )
    db.commit()
    return {
        "module_id": module_id,
        "version": version,
        "result": what,
        "restart_required": module_id in mgr.restart_required,
    }


@router.post("/{module_id}/rollback", summary="Go back to the previous version in the store")
def rollback(
    module_id: str,
    request: Request,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    mgr: ModuleManager = Depends(manager),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    store = _store(request)
    row = db.get(InstalledModule, module_id)
    current = store.active_dir(module_id)
    previous = store.previous(module_id)
    if row is None or row.state == "removed" or current is None or previous is None:
        raise ProblemError(
            409,
            "Nothing to roll back to",
            "No previous version of this module is kept.",
            code="no_previous_version",
        )
    added = catalog.migration_files(current) - catalog.migration_files(previous[0])
    if added:
        raise ProblemError(
            409,
            "Cannot roll back",
            "The current version changed the module's database; it cannot go back automatically.",
            code="rollback_blocked",
        )
    old = row.version
    store.activate(module_id, previous[1].module.version)
    row.version = previous[1].module.version
    row.manifest = previous[1].model_dump(mode="json")
    if module_id in mgr.loaded:
        mgr.restart_required.add(module_id)
    _audit(db, principal, ctx, "module.rollback", module_id, {"from": old, "to": row.version})
    db.commit()
    return {"module_id": module_id, "version": row.version, "restart_required": True}


# ---------------------------------------------------------------- settings


def _fields(db: Session, module_id: str) -> list[dict[str, Any]]:
    row = db.get(InstalledModule, module_id)
    if row is None or row.state == "removed":
        raise not_found("Installed module")
    return list((row.manifest or {}).get("config", []))


def _purpose(module_id: str) -> str:
    return f"module:{module_id}"


@router.get("/{module_id}/config", summary="Module settings (secrets are never returned)")
def get_config(
    module_id: str,
    organization_id: uuid.UUID | None = None,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    fields = [
        f
        for f in _fields(db, module_id)
        if (f.get("scope") == "organization") == (organization_id is not None)
    ]
    row = db.scalar(
        select(ModuleConfig).where(
            ModuleConfig.module_id == module_id,
            ModuleConfig.organization_id == organization_id
            if organization_id
            else ModuleConfig.organization_id.is_(None),
        )
    )
    stored = dict(row.config) if row else {}
    values: dict[str, Any] = {}
    for f in fields:
        if f["type"] == "secret":
            values[f["key"]] = {"has_value": bool(stored.get(f["key"]))}
        else:
            values[f["key"]] = stored.get(f["key"], f.get("default"))
    return {"fields": fields, "values": values}


class ConfigIn(BaseModel):
    values: dict[str, Any]
    organization_id: uuid.UUID | None = None


def _validate(f: dict[str, Any], v: Any) -> Any:
    t, key = f["type"], f["key"]

    def bad(msg: str) -> ProblemError:
        return ProblemError(
            422,
            "Validation failed",
            f"{f['label']}: {msg}",
            code="validation_failed",
            errors=[{"field": key, "message": msg}],
        )

    if v is None or v == "":
        if f.get("required") and t != "secret":
            raise bad("required")
        return None
    if t == "integer":
        try:
            v = int(v)
        except (TypeError, ValueError) as e:
            raise bad("must be a whole number") from e
        if f.get("min") is not None and v < f["min"]:
            raise bad(f"at least {f['min']}")
        if f.get("max") is not None and v > f["max"]:
            raise bad(f"at most {f['max']}")
        return v
    if t == "boolean":
        if not isinstance(v, bool):
            raise bad("must be true or false")
        return v
    v = str(v)
    if f.get("max_length") and len(v) > f["max_length"]:
        raise bad(f"at most {f['max_length']} characters")
    if t == "choice" and v not in (f.get("choices") or []):
        raise bad("not one of the choices")
    return v


@router.put("/{module_id}/config", summary="Change module settings")
def put_config(
    module_id: str,
    body: ConfigIn,
    request: Request,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    fields = {
        f["key"]: f
        for f in _fields(db, module_id)
        if (f.get("scope") == "organization") == (body.organization_id is not None)
    }
    unknown = set(body.values) - set(fields)
    if unknown:
        raise ProblemError(
            422,
            "Validation failed",
            f"Unknown setting {sorted(unknown)[0]!r}.",
            code="validation_failed",
        )
    row = db.scalar(
        select(ModuleConfig).where(
            ModuleConfig.module_id == module_id,
            ModuleConfig.organization_id == body.organization_id
            if body.organization_id
            else ModuleConfig.organization_id.is_(None),
        )
    )
    stored = dict(row.config) if row else {}
    key = None
    for k, v in body.values.items():
        f = fields[k]
        if f["type"] == "secret":
            if v is None:
                continue  # unchanged
            if v == "":
                stored.pop(k, None)  # removed
                continue
            key = key or load_installation_key(request.app.state.settings)
            stored[k] = key.encrypt(str(v), _purpose(module_id))
        else:
            stored[k] = _validate(f, v)
    for k, f in fields.items():
        if f.get("required") and f["type"] == "secret" and not stored.get(k):
            raise ProblemError(
                422,
                "Validation failed",
                f"{f['label']}: required",
                code="validation_failed",
                errors=[{"field": k, "message": "required"}],
            )
    if row is None:
        db.add(
            ModuleConfig(module_id=module_id, organization_id=body.organization_id, config=stored)
        )
    else:
        row.config = stored
    _audit(db, principal, ctx, "module.config", module_id, {"changed": sorted(body.values)})
    db.commit()
    return get_config(module_id, body.organization_id, principal, db)


# ----------------------------------------------------------------- restart


@router.post(
    "/restart-services", status_code=202, summary="Restart Veyra's services (new module code)"
)
def restart_services(
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    """The worker restarts the units on its next pass (docs/MODULE_CATALOG.md
    §4); calls are not affected (Asterisk keeps running)."""
    row = db.get(SystemSetting, RESTART_KEY)
    value = {"requested_at": utcnow().isoformat(), "by": principal.label}
    if row is None:
        db.add(SystemSetting(key=RESTART_KEY, value=value, updated_by=principal.user_id))
    else:
        row.value = value
    audit.record(
        db,
        action="system.restart_services",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="system",
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={},
    )
    db.commit()
    return {"requested": True}
