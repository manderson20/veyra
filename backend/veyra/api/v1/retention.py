# SPDX-License-Identifier: AGPL-3.0-or-later
"""Retention (docs/PRODUCTION_HARDENING.md §4): the per-class days, the
inventory, and running the job now."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from veyra.core import audit, retention
from veyra.core.config import Settings, get_settings
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError
from veyra.core.security.principal import Principal

router = APIRouter(prefix="/retention", tags=["retention"])
READ = "system.settings.read"
WRITE = "system.settings.write"
SHORT_DAYS = 30


@router.get("", summary="Retention per data class and the last run")
def get_retention(
    principal: Principal = Depends(require(READ)), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return {"rules": retention.rules_out(db), "last_run": retention.last_run(db)}


class RetentionIn(BaseModel):
    days: dict[str, int] = Field(default_factory=dict)
    # Shortening a class below 30 days needs the typed confirmation on the page.
    confirm_short: bool = False


@router.put("", summary="Change retention (days per data class)")
def put_retention(
    body: RetentionIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    if not principal.is_platform_admin:
        raise ProblemError(403, "Forbidden", "Retention is set by platform administrators.")
    if any(v < SHORT_DAYS for v in body.days.values()) and not body.confirm_short:
        raise ProblemError(
            400,
            "Confirmation needed",
            f"Keeping a class for less than {SHORT_DAYS} days needs confirmation.",
            code="confirm_short",
        )
    before = retention.settings(db)
    try:
        after = retention.save_settings(db, body.days, principal.user_id)
    except ValueError as e:
        raise ProblemError(400, "Invalid retention", str(e), code="bad_retention") from e
    audit.record(
        db,
        action="retention.settings_update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={
            k: {"from": before.get(k), "to": v} for k, v in after.items() if before.get(k) != v
        },
    )
    db.commit()
    return {"rules": retention.rules_out(db), "last_run": retention.last_run(db)}


@router.get("/inventory", summary="Rows, bytes and the oldest record per data class")
def get_inventory(
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    return retention.inventory(db, settings)


@router.post("/run", summary="Apply retention now")
def run_now(
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    if not principal.is_platform_admin:
        raise ProblemError(403, "Forbidden", "Retention is run by platform administrators.")
    removed = retention.run(db, actor=principal.label)
    audit.record(
        db,
        action="retention.run",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"removed": {k: v for k, v in removed.items() if v}},
    )
    db.commit()
    return {"removed": removed}
