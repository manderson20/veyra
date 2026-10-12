# SPDX-License-Identifier: AGPL-3.0-or-later
"""System health and installation information."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from veyra.core.db import get_db
from veyra.core.deps import require
from veyra.core.models import Installation, InstalledModule
from veyra.core.security.principal import Principal
from veyra.ha.status import cluster_status
from veyra.system import metrics
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

    engine = request.app.state.telephony.health()
    engine_status = {"running": "ok", "not_configured": "unknown", "not_installed": "unknown"}.get(
        engine.state, "failed"
    )
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
        "active_calls": None,  # available once call tracking lands (Milestone 5)
        "registrations": None,  # available once SIP endpoints land (Milestone 5)
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
