# SPDX-License-Identifier: AGPL-3.0-or-later
"""Update management API: policies, checks, available updates and history."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1.schemas import ORM
from veyra.core import audit
from veyra.core.config import Settings, get_settings
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, not_found
from veyra.core.models import AvailableUpdate, UpdateCheck, UpdateHistory, UpdatePolicy
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.updates.checker import check_for_updates
from veyra.updates.policy import (
    AVAILABLE_MODES,
    COMPONENT_LABELS,
    Component,
    PolicyUpdate,
    availability_problem,
)

router = APIRouter(prefix="/updates", tags=["updates"])


class PolicyOut(ORM):
    component: str
    mode: str
    channel: str
    check_enabled: bool
    check_interval_hours: int
    auto_download: bool
    auto_install_categories: list[str]
    require_approval: bool
    notify_admins: bool
    maintenance_window: dict[str, Any] | None
    updated_at: datetime


class AvailableOut(ORM):
    id: uuid.UUID
    component: str
    target: str
    version: str
    current_version: str | None
    channel: str
    category: str
    release_notes: str | None
    state: str
    created_at: datetime


class HistoryOut(ORM):
    id: uuid.UUID
    component: str
    target: str
    from_version: str | None
    to_version: str
    started_at: datetime
    finished_at: datetime | None
    outcome: str
    initiated_by: str


class CheckOut(ORM):
    checked_at: datetime
    source: str
    outcome: str
    message: str | None


@router.get("/policies", summary="Update policies per component")
def get_policies(
    principal: Principal = Depends(require("updates.read")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    policies = {p.component: p for p in db.scalars(select(UpdatePolicy))}
    return {
        "source_configured": bool(settings.update_metadata_url),
        "available_modes": sorted(m.value for m in AVAILABLE_MODES),
        "items": [
            {
                **PolicyOut.model_validate(policies[c.value]).model_dump(mode="json"),
                "label": COMPONENT_LABELS[c],
            }
            for c in Component
            if c.value in policies
        ],
    }


@router.put("/policies/{component}", response_model=PolicyOut, summary="Change an update policy")
def put_policy(
    component: Component,
    body: PolicyUpdate,
    principal: Principal = Depends(require("updates.manage")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PolicyOut:
    policy = db.get(UpdatePolicy, component.value)
    if policy is None:
        raise not_found("Update policy")
    problem = availability_problem(component, body)
    if problem:
        raise ProblemError(422, "Not available", problem, code="not_available")
    before = PolicyOut.model_validate(policy).model_dump(mode="json")
    data = body.model_dump(mode="json")
    for k, v in data.items():
        setattr(policy, k, v)
    policy.updated_by = principal.user_id
    audit.record(
        db,
        action="updates.policy_change",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="update_policy",
        target_id=component.value,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"before": {k: before[k] for k in data}, "after": data},
    )
    db.commit()
    return PolicyOut.model_validate(policy)


@router.post("/check", response_model=CheckOut, summary="Check for updates now (never installs)")
def check_now(
    request: Request,
    principal: Principal = Depends(require("updates.manage")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> CheckOut:
    check = check_for_updates(db, settings, request.app.state.keyring)
    audit.record(
        db,
        action="updates.check",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        outcome="success" if check.outcome in ("ok", "not_configured") else "failure",
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"outcome": check.outcome},
    )
    db.commit()
    return CheckOut.model_validate(check)


@router.get("/checks/latest", response_model=CheckOut | None, summary="Most recent update check")
def latest_check(
    principal: Principal = Depends(require("updates.read")),
    db: Session = Depends(get_db),
) -> CheckOut | None:
    row = db.scalar(select(UpdateCheck).order_by(UpdateCheck.checked_at.desc()).limit(1))
    return CheckOut.model_validate(row) if row else None


@router.get("/available", response_model=list[AvailableOut], summary="Updates found by checks")
def available(
    principal: Principal = Depends(require("updates.read")),
    db: Session = Depends(get_db),
) -> list[AvailableOut]:
    rows = db.scalars(
        select(AvailableUpdate)
        .where(AvailableUpdate.state != "dismissed")
        .order_by(AvailableUpdate.created_at.desc())
    )
    return [AvailableOut.model_validate(r) for r in rows]


@router.get("/history", response_model=Page[HistoryOut], summary="Update history")
def history(
    page: PageParams = Depends(page_params),
    principal: Principal = Depends(require("updates.read")),
    db: Session = Depends(get_db),
) -> Page[HistoryOut]:
    rows, total = paginate(
        db, select(UpdateHistory).order_by(UpdateHistory.started_at.desc()), page
    )
    return Page(
        items=[HistoryOut.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
