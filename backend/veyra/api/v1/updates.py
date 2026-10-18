# SPDX-License-Identifier: AGPL-3.0-or-later
"""Update management API: policies, checks, available updates and history."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
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
from veyra.updates import manager
from veyra.updates.checker import check_for_updates
from veyra.updates.metadata import MetadataError
from veyra.updates.policy import (
    AVAILABLE_MODES,
    COMPONENT_LABELS,
    Component,
    PolicyUpdate,
    availability_problem,
)

router = APIRouter(prefix="/updates", tags=["updates"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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
    downloaded_at: datetime | None
    approved_at: datetime | None
    approved_by: str | None
    install_when: str | None
    install_started_at: datetime | None
    install_finished_at: datetime | None
    error: str | None


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
        "source_configured": bool(manager.source_url(db, settings)),
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


# ------------------------------------------------- Milestone 12: installing


class SourceIn(BaseModel):
    url: str = Field("", max_length=2000)
    token: str | None = Field(
        None, max_length=2000, description="Read-only token; null keeps it, empty removes it"
    )
    recipients: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("recipients")
    @classmethod
    def _emails(cls, v: list[str]) -> list[str]:
        out = []
        for a in (x.strip() for x in v):
            if a and not _EMAIL_RE.match(a):
                raise ValueError(f"{a!r} is not an email address")
            if a:
                out.append(a)
        return sorted(set(out))


def _source_out(db: Session, settings: Settings) -> dict[str, Any]:
    src = manager.load_source(db)
    last = db.scalar(select(UpdateCheck).order_by(UpdateCheck.checked_at.desc()).limit(1))
    return {
        "url": src.get("url", ""),
        "env_url": settings.update_metadata_url,
        "effective_url": manager.source_url(db, settings),
        "token_set": bool(src.get("token")),
        "recipients": src.get("recipients", []),
        "last_check": CheckOut.model_validate(last).model_dump(mode="json") if last else None,
    }


@router.get("/source", summary="Where updates come from")
def get_source(
    principal: Principal = Depends(require("updates.read")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return _source_out(db, settings)


@router.put("/source", summary="Change the update source, token and email recipients")
def put_source(
    body: SourceIn,
    principal: Principal = Depends(require("updates.manage")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    url = body.url.strip()
    if url:
        try:
            manager.check_url(url, settings)
        except manager.UpdateError as e:
            raise ProblemError(422, "Validation failed", str(e), code="invalid_url") from e
    current = manager.load_source(db)
    value: dict[str, Any] = {"url": url, "recipients": [str(r) for r in body.recipients]}
    if body.token is None:
        if current.get("token"):
            value["token"] = current["token"]
    elif body.token.strip():
        from veyra.core.security.crypto import load_installation_key

        value["token"] = load_installation_key(settings).encrypt(
            body.token.strip(), manager.TOKEN_PURPOSE
        )
    manager.save_source(db, value)
    audit.record(
        db,
        action="updates.source_change",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={
            "url": url,
            "token": "changed" if body.token is not None else "unchanged",
            "recipients": value["recipients"],
        },
    )
    db.commit()
    return _source_out(db, settings)


def _update(db: Session, update_id: uuid.UUID) -> AvailableUpdate:
    row = db.get(AvailableUpdate, update_id)
    if row is None:
        raise not_found("Update")
    return row


def _audit(
    db: Session,
    principal: Principal,
    ctx: RequestContext,
    action: str,
    row: AvailableUpdate,
    **details: Any,
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type=row.component,
        target_id=row.target,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"version": row.version, **details},
    )


@router.get("/available/{update_id}", summary="One update with its checks")
def update_detail(
    update_id: uuid.UUID,
    principal: Principal = Depends(require("updates.read")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    row = _update(db, update_id)
    policy = db.get(UpdatePolicy, "veyra_core")
    window = policy.maintenance_window if policy else None
    from veyra.core.models.base import utcnow

    nxt = manager.next_window_start(window, utcnow())
    return {
        **AvailableOut.model_validate(row).model_dump(mode="json"),
        "service_impact": (row.metadata_ or {}).get("service_impact", ""),
        "size": ((row.metadata_ or {}).get("artifact") or {}).get("size"),
        "checks": manager.preflight(db, settings, row) if row.component == "veyra_core" else [],
        "window": window,
        "next_window": nxt.isoformat() if nxt else None,
    }


@router.post(
    "/available/{update_id}/download",
    response_model=AvailableOut,
    summary="Download and verify a release",
)
def download_update(
    update_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("updates.manage")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> AvailableOut:
    row = _update(db, update_id)
    if row.state not in ("available", "failed"):
        raise ProblemError(409, "Conflict", f"The update is {row.state}.", code="wrong_state")
    try:
        manager.download(db, settings, request.app.state.keyring, row)
    except (manager.UpdateError, MetadataError) as e:
        row.error = str(e)[:2000]
        _audit(db, principal, ctx, "updates.download", row, outcome="failed", error=str(e))
        db.commit()
        raise ProblemError(502, "Download failed", str(e), code="download_failed") from e
    _audit(db, principal, ctx, "updates.download", row, sha256=row.metadata_["artifact"]["sha256"])
    db.commit()
    return AvailableOut.model_validate(row)


class ApproveIn(BaseModel):
    when: str = Field(pattern="^(now|window)$")


@router.post(
    "/available/{update_id}/approve",
    response_model=AvailableOut,
    summary="Approve installation now or in the maintenance window",
)
def approve_update(
    update_id: uuid.UUID,
    body: ApproveIn,
    principal: Principal = Depends(require("updates.manage")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> AvailableOut:
    from veyra.core.models.base import utcnow

    row = _update(db, update_id)
    if row.state != "downloaded":
        raise ProblemError(409, "Conflict", "Download the update first.", code="wrong_state")
    problems = manager.blocking_problems(db, settings, row)
    if problems:
        raise ProblemError(409, "Cannot install", "; ".join(problems), code="checks_failed")
    if body.when == "window":
        policy = db.get(UpdatePolicy, "veyra_core")
        if policy is None or not policy.maintenance_window:
            raise ProblemError(
                409,
                "No maintenance window",
                "Set a maintenance window in the policy first.",
                code="no_window",
            )
    row.state, row.install_when = "approved", body.when
    row.approved_at, row.approved_by = utcnow(), principal.label
    row.error = None
    _audit(db, principal, ctx, "updates.approve", row, when=body.when)
    db.commit()
    return AvailableOut.model_validate(row)


@router.post(
    "/available/{update_id}/cancel",
    response_model=AvailableOut,
    summary="Withdraw an approval before the installation starts",
)
def cancel_update(
    update_id: uuid.UUID,
    principal: Principal = Depends(require("updates.manage")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> AvailableOut:
    row = _update(db, update_id)
    if row.state != "approved":
        raise ProblemError(409, "Conflict", f"The update is {row.state}.", code="wrong_state")
    row.state, row.install_when, row.approved_at, row.approved_by = "downloaded", None, None, None
    _audit(db, principal, ctx, "updates.cancel", row)
    db.commit()
    return AvailableOut.model_validate(row)


@router.get("/status", summary="Progress of the pending, running or last installation")
def install_status(
    principal: Principal = Depends(require("updates.read")),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return manager.install_progress(db, settings)


@router.get("/system-packages", summary="Operating system packages that could be upgraded")
def system_packages(
    principal: Principal = Depends(require("updates.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from veyra.core.models import SystemSetting

    row = db.get(SystemSetting, manager.SYSTEM_PACKAGES_KEY)
    value = dict(row.value) if row else {"checked_at": None, "packages": [], "error": None}
    pk = value.get("packages", [])
    value["counts"] = {
        "total": len(pk),
        "security": sum(1 for p in pk if p.get("security")),
        "telephony": sum(1 for p in pk if p.get("telephony")),
    }
    return value
