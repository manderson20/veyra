# SPDX-License-Identifier: AGPL-3.0-or-later
"""System health and installation information."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from veyra.core import audit, tenancy
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import forbidden
from veyra.core.models import Installation, InstalledModule
from veyra.core.security.principal import Principal
from veyra.ha.status import cluster_status
from veyra.system import metrics
from veyra.telephony.adapter import Capability, EngineUnavailable
from veyra.version import MODULE_API_VERSION, __version__

router = APIRouter(prefix="/system", tags=["system"])


class Ping(BaseModel):
    status: str


@router.get("/ping", response_model=Ping, summary="Liveness check (no details, no authentication)")
def ping() -> Ping:
    return Ping(status="ok")


def _component(status: str, message: str = "", **details: Any) -> dict[str, Any]:
    return {"status": status, "message": message, "details": details}


@router.get("/health", summary="Detailed health of every component")
def health(
    request: Request,
    principal: Principal = Depends(require("system.health.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    components: dict[str, Any] = {}

    started = time.perf_counter()
    try:
        server_version = db.scalar(text("SHOW server_version"))
        latency = round((time.perf_counter() - started) * 1000, 1)
        components["database"] = _component(
            "ok", "PostgreSQL is reachable.", version=server_version, latency_ms=latency
        )
    except Exception as e:
        db.rollback()
        components["database"] = _component("failed", f"Database error: {type(e).__name__}")

    adapter = request.app.state.telephony
    engine = adapter.health()
    engine_status = {"running": "ok", "not_configured": "unknown", "not_installed": "unknown"}.get(
        engine.state, "failed"
    )
    active_calls = registrations = None
    if engine.state == "running":
        try:
            caps = adapter.capabilities()
            if Capability.ACTIVE_CALLS in caps:
                active_calls = len(adapter.active_calls())
            if Capability.ENDPOINT_STATUS in caps:
                registrations = sum(1 for e in adapter.endpoint_statuses() if e.registered)
        except EngineUnavailable:
            active_calls = registrations = None
    components["telephony"] = _component(
        engine_status,
        engine.message,
        engine=engine.engine,
        state=engine.state,
        version=engine.version,
    )

    manager = request.app.state.modules
    module_rows = []
    for row in db.scalars(select(InstalledModule).order_by(InstalledModule.module_id)):
        h = manager.health(row.module_id) if row.state == "enabled" else None
        module_rows.append(
            {
                "module_id": row.module_id,
                "state": row.state,
                "health": h.status if h else ("failed" if row.state == "failed" else "unknown"),
                "message": h.message if h else (row.last_error or ""),
            }
        )
    components["modules"] = _component(
        "failed" if any(m["health"] == "failed" for m in module_rows) else "ok",
        f"{len(module_rows)} module(s) installed.",
        modules=module_rows,
    )

    host = metrics.collect("/")
    statuses = [c["status"] for c in components.values()]
    overall = "failed" if "failed" in statuses else "degraded" if "degraded" in statuses else "ok"
    return {
        "status": overall,
        "version": __version__,
        "components": components,
        "host": host.as_dict(),
        "cluster": cluster_status(db),
        # Live counts from the engine; None when the engine cannot report them.
        # With multi-tenancy they cover every organization, so only platform
        # administrators see them (docs/MULTI_TENANCY.md §6).
        "active_calls": active_calls if _installation_wide(db, principal) else None,
        "registrations": registrations if _installation_wide(db, principal) else None,
    }


def _installation_wide(db: Session, principal: Principal) -> bool:
    return principal.is_platform_admin or not tenancy.enabled(db)


@router.get("/metrics/calls", summary="Channel and call history for the dashboard graphs")
def call_metrics(
    request: Request,
    range: str = Query("1h", pattern="^(1h|6h|24h|7d)$"),
    principal: Principal = Depends(require("system.health.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from veyra.telephony import metrics

    if not _installation_wide(db, principal):
        raise forbidden(
            "With multi-tenancy the call graphs cover every organization; "
            "only platform administrators see them."
        )
    current = metrics.read(request.app.state.telephony)
    return {
        **metrics.series(db, range),
        "current": current.as_dict() if current else None,
        "available": current is not None,
    }


@router.get("/info", summary="Installation identity and versions")
def info(
    principal: Principal = Depends(require("system.health.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    inst = db.scalar(select(Installation))
    return {
        "name": inst.name if inst else None,
        "instance_id": str(inst.instance_id) if inst else None,
        "deployment_mode": inst.deployment_mode if inst else None,
        "multi_tenancy_enabled": inst.multi_tenancy_enabled if inst else False,
        "central_management_enabled": inst.central_management_enabled if inst else False,
        "version": __version__,
        "module_api_version": MODULE_API_VERSION,
    }


# ----------------------------------------------------------------- multi-tenancy


class MultiTenancyIn(BaseModel):
    enabled: bool


@router.get("/multi-tenancy", summary="The multi-tenancy switch and what is shared")
def get_multi_tenancy(
    principal: Principal = Depends(require("system.settings.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return tenancy.status(db)


@router.post("/multi-tenancy", summary="Turn multi-tenancy on (after the checks) or off")
def set_multi_tenancy(
    body: MultiTenancyIn,
    request: Request,
    principal: Principal = Depends(require("system.settings.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    from veyra.core.security.crypto import try_load_installation_key

    checks = tenancy.switch(
        db,
        body.enabled,
        try_load_installation_key(request.app.state.settings),
    )
    audit.record(
        db,
        action="system.multi_tenancy",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"enabled": body.enabled, "checks": [c["name"] for c in checks if c["ok"]]},
    )
    db.commit()
    return {**tenancy.status(db), "checks": checks}
