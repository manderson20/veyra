# SPDX-License-Identifier: AGPL-3.0-or-later
"""Module Manager API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.db import get_db, get_engine
from veyra.core.deps import RequestContext, current_principal, request_context, require
from veyra.core.errors import ProblemError
from veyra.core.models import InstalledModule
from veyra.core.security.principal import Principal
from veyra.modules import catalog
from veyra.modules.manager import ModuleError, ModuleManager
from veyra.version import MODULE_API_VERSION

router = APIRouter(prefix="/modules", tags=["modules"])


def manager(request: Request) -> ModuleManager:
    mgr: ModuleManager = request.app.state.modules
    return mgr


class UninstallIn(BaseModel):
    purge_data: bool = False
    confirm_module_id: str | None = Field(
        None, description="Required when purge_data is true: type the module id to confirm"
    )


def _previous_version(store: catalog.Store, row: InstalledModule | None) -> str | None:
    """The version "Roll back" would go back to, when one is kept."""
    if row is None or row.state == "removed" or store.active_dir(row.module_id) is None:
        return None
    previous = store.previous(row.module_id)
    return previous[1].module.version if previous else None


def _describe(
    row: InstalledModule | None,
    cand: Any,
    mgr: ModuleManager,
    db: Session,
    store: catalog.Store,
) -> dict[str, Any]:
    manifest = cand.manifest if cand and cand.manifest else None
    m = manifest.model_dump(mode="json") if manifest else (row.manifest if row else None)
    info = (m or {}).get("module", {})
    problems: list[str] = []
    if manifest is not None:
        problems = mgr.trust_problems(manifest, cand.verification) + mgr.compatibility_problems(
            db, manifest
        )
    available_version = manifest.module.version if manifest else None
    health = mgr.health(row.module_id) if row and row.state == "enabled" else None
    return {
        "module_id": row.module_id if row else cand.module_id,
        "name": info.get("name"),
        "description": info.get("description"),
        "author": info.get("author"),
        "license": info.get("license"),
        "installed_version": row.version if row else None,
        "available_version": available_version,
        "update_available": bool(
            row
            and available_version
            and available_version != row.version
            and row.state != "removed"
        ),
        "state": row.state if row else "available",
        "trust_level": (row.trust_level if row else cand.verification.trust_level.value),
        "signature_verified": (row.signature_verified if row else cand.verification.verified),
        "verification_error": cand.verification.error if cand else None,
        "compatible": not problems,
        "problems": problems + (cand.manifest_errors if cand else []),
        "dependencies": (m or {}).get("dependencies", []),
        "permissions": (m or {}).get("permissions", []),
        "compatibility": (m or {}).get("compatibility"),
        "health": {"status": health.status, "message": health.message} if health else None,
        "last_error": row.last_error if row else None,
        "restart_required": bool(row and row.module_id in mgr.restart_required),
        "previous_version": _previous_version(store, row),
    }


@router.get("", summary="Installed and available modules")
def list_modules(
    request: Request,
    principal: Principal = Depends(require("modules.read")),
    db: Session = Depends(get_db),
    mgr: ModuleManager = Depends(manager),
) -> dict[str, Any]:
    discovered = mgr.discover()
    rows = {r.module_id: r for r in db.scalars(select(InstalledModule))}
    ids = sorted(set(discovered) | set(rows))
    store = _store(request)
    return {
        "module_api_version": MODULE_API_VERSION,
        "items": [_describe(rows.get(i), discovered.get(i), mgr, db, store) for i in ids],
    }


@router.get("/ui-extensions", summary="Navigation and views contributed by enabled modules")
def ui_extensions(
    principal: Principal = Depends(current_principal),
    mgr: ModuleManager = Depends(manager),
) -> list[dict[str, Any]]:
    out = []
    for ext in mgr.ui_extensions():
        views = [v for v in ext["views"] if principal.has_any_scope(v["permission"])]
        nav = [n for n in ext["nav"] if principal.has_any_scope(n["permission"])]
        if views:
            out.append({**ext, "views": views, "nav": nav})
    return out


@router.get("/{module_id}", summary="Module details")
def get_module(
    module_id: str,
    request: Request,
    principal: Principal = Depends(require("modules.read")),
    db: Session = Depends(get_db),
    mgr: ModuleManager = Depends(manager),
) -> dict[str, Any]:
    row = db.get(InstalledModule, module_id)
    cand = mgr.discover().get(module_id)
    if row is None and cand is None:
        raise ProblemError(404, "Not found", "Module not found.", code="not_found")
    return _describe(row, cand, mgr, db, _store(request))


def _store(request: Request) -> catalog.Store:
    return catalog.Store(request.app.state.settings.module_store_dir)


def _lifecycle(
    action: str,
    module_id: str,
    principal: Principal,
    db: Session,
    ctx: RequestContext,
    fn: Any,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        fn()
        db.flush()
    except ModuleError as e:
        db.rollback()
        audit.record(
            db,
            action=f"module.{action}",
            outcome="failure",
            actor_user_id=principal.user_id,
            actor_label=principal.label,
            target_type="module",
            target_id=module_id,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"error": e.detail, **(details or {})},
        )
        db.commit()
        raise
    audit.record(
        db,
        action=f"module.{action}",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="module",
        target_id=module_id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=details,
    )
    db.commit()
    return {"module_id": module_id, "result": "ok"}


@router.post("/{module_id}/install", summary="Install a module found in the module paths")
def install(
    module_id: str,
    principal: Principal = Depends(require("modules.manage")),
    db: Session = Depends(get_db),
    mgr: ModuleManager = Depends(manager),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    return _lifecycle(
        "install", module_id, principal, db, ctx, lambda: mgr.install(db, get_engine(), module_id)
    )


@router.post("/{module_id}/enable", summary="Enable an installed module")
def enable(
    module_id: str,
    principal: Principal = Depends(require("modules.manage")),
    db: Session = Depends(get_db),
    mgr: ModuleManager = Depends(manager),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    return _lifecycle("enable", module_id, principal, db, ctx, lambda: mgr.enable(db, module_id))


@router.post("/{module_id}/disable", summary="Disable a module (keeps its data)")
def disable(
    module_id: str,
    principal: Principal = Depends(require("modules.manage")),
    db: Session = Depends(get_db),
    mgr: ModuleManager = Depends(manager),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    return _lifecycle("disable", module_id, principal, db, ctx, lambda: mgr.disable(db, module_id))


@router.post("/{module_id}/update", summary="Apply a newer module version present on disk")
def update(
    module_id: str,
    principal: Principal = Depends(require("modules.manage")),
    db: Session = Depends(get_db),
    mgr: ModuleManager = Depends(manager),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    return _lifecycle(
        "update",
        module_id,
        principal,
        db,
        ctx,
        lambda: mgr.apply_update(db, get_engine(), module_id),
    )


def _uninstall(
    request: Request, db: Session, mgr: ModuleManager, module_id: str, purge: bool
) -> None:
    mgr.uninstall(db, get_engine(), module_id, purge=purge)
    if purge:
        # Copies from a catalog or an upload go with the data
        # (docs/MODULE_CATALOG.md §3).
        from veyra.modules.catalog import Store

        Store(request.app.state.settings.module_store_dir).remove(module_id)


@router.post("/{module_id}/uninstall", summary="Uninstall a module")
def uninstall(
    module_id: str,
    body: UninstallIn,
    request: Request,
    principal: Principal = Depends(require("modules.manage")),
    db: Session = Depends(get_db),
    mgr: ModuleManager = Depends(manager),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    if body.purge_data and body.confirm_module_id != module_id:
        raise ProblemError(
            422,
            "Confirmation required",
            "Deleting a module's data requires typing the module id to confirm.",
            code="confirmation_required",
        )
    return _lifecycle(
        "uninstall",
        module_id,
        principal,
        db,
        ctx,
        lambda: _uninstall(request, db, mgr, module_id, body.purge_data),
        details={"purge_data": body.purge_data},
    )
