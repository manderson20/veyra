# SPDX-License-Identifier: AGPL-3.0-or-later
"""Telephony engine: status, SIP settings, configuration revisions and deployment."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1.schemas import MessageOut
from veyra.configmgmt import service
from veyra.configmgmt.revisions import RevisionState, artifacts_to_files_safe, diff
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, not_found
from veyra.core.models import ConfigRevision
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.crypto import InstallationKey, try_load_installation_key
from veyra.core.security.principal import Principal
from veyra.telephony.adapter import Capability, EngineUnavailable, TelephonyAdapter
from veyra.telephony.numbering import NumberingPlan, load_numbering_plan, save_numbering_plan
from veyra.telephony.settings import CODECS, SipSettings, load_sip_settings, save_sip_settings

router = APIRouter(prefix="/telephony", tags=["telephony"])


def _adapter(request: Request) -> TelephonyAdapter:
    return request.app.state.telephony


def _key(request: Request) -> InstallationKey | None:
    """The installation key, or None when it is missing: generation then
    fails with a clear message instead of the API refusing to answer."""
    return try_load_installation_key(request.app.state.settings)


class ModuleStatus(BaseModel):
    name: str
    status: str


class EngineOut(BaseModel):
    engine: str
    state: str
    version: str | None
    message: str
    capabilities: list[str]
    started_at: str | None = None
    last_reload_at: str | None = None
    entity_id: str | None = None
    modules: list[ModuleStatus] = []
    endpoints_total: int | None = None
    endpoints_registered: int | None = None
    active_channels: int | None = None
    config_dir: str | None = None
    deployed_revision: int | None = None
    pending_revision: int | None = None
    # True after any save that may affect the engine until a deployment runs,
    # or when the database differs from the deployed configuration; None
    # without generation.
    changes_pending: bool | None = None
    pending_since: str | None = None
    pending_by: str | None = None
    installation_key_present: bool = True
    # The queued deployment's mode and, for when_idle, what it waits for.
    pending_mode: str | None = None
    pending_requested_at: str | None = None
    pending_active_calls: int | None = None
    active_calls: int | None = None


@router.get("/engine", response_model=EngineOut, summary="Telephony engine status")
def engine_status(
    request: Request,
    principal: Principal = Depends(require("config.read")),
    db: Session = Depends(get_db),
) -> EngineOut:
    adapter = _adapter(request)
    health = adapter.health()
    caps = adapter.capabilities()
    out = EngineOut(
        engine=health.engine,
        state=health.state,
        version=health.version,
        message=health.message,
        capabilities=sorted(c.value for c in caps),
        config_dir=str(request.app.state.settings.asterisk_config_dir)
        if adapter.name == "asterisk"
        else None,
    )
    deployed = service.current_deployed(db, adapter.name)
    queued = service.pending(db, adapter.name)
    out.deployed_revision = deployed.sequence if deployed else None
    out.pending_revision = queued.sequence if queued else None
    key = _key(request)
    out.installation_key_present = key is not None
    out.changes_pending = service.changes_pending(db, adapter, key)
    flag = service.pending_change(db)
    if flag:
        out.pending_since, out.pending_by = flag.get("at"), flag.get("by")
    wait = service.pending_wait(db, adapter)
    if wait:
        out.pending_mode = wait["mode"]
        out.pending_requested_at = wait["requested_at"]
        out.pending_active_calls = wait.get("active_calls")
    if health.state != "running":
        return out
    try:
        info = adapter.info()
        out.started_at, out.last_reload_at, out.entity_id = (
            info.started_at,
            info.last_reload_at,
            info.entity_id,
        )
        out.modules = [ModuleStatus(name=k, status=v) for k, v in info.modules.items()]
        if Capability.ENDPOINT_STATUS in caps:
            eps = adapter.endpoint_statuses()
            out.endpoints_total = len(eps)
            out.endpoints_registered = sum(1 for e in eps if e.registered)
        if Capability.ACTIVE_CALLS in caps:
            out.active_channels = len(adapter.active_calls())
            out.active_calls = out.active_channels
    except EngineUnavailable as e:
        out.message = f"{health.message} Live details unavailable: {e}"
    return out


# ----------------------------------------------------------------- settings


class SipSettingsOut(BaseModel):
    settings: SipSettings
    problems: list[str]
    codecs_available: list[str]


@router.get("/settings", response_model=SipSettingsOut, summary="SIP and media settings")
def get_settings_(
    principal: Principal = Depends(require("system.settings.read")),
    db: Session = Depends(get_db),
) -> SipSettingsOut:
    s = load_sip_settings(db)
    return SipSettingsOut(settings=s, problems=s.problems(), codecs_available=list(CODECS))


@router.put("/settings", response_model=SipSettingsOut, summary="Change SIP and media settings")
def put_settings(
    body: SipSettings,
    principal: Principal = Depends(require("system.settings.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> SipSettingsOut:
    problems = body.problems()
    if problems:
        raise ProblemError(
            422,
            "Settings not saved",
            " ".join(problems),
            code="validation_failed",
            errors=[{"field": "settings", "message": p} for p in problems],
        )
    before = load_sip_settings(db).model_dump(mode="json")
    save_sip_settings(db, body, updated_by=principal.user_id)
    after = body.model_dump(mode="json")
    changed = {k: after[k] for k in after if before.get(k) != after[k]}
    if changed:
        service.mark_changed(db, by=principal.label, what="telephony.settings_update")
    audit.record(
        db,
        action="telephony.settings_update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="settings",
        target_id="telephony.sip",
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"changed": changed},
    )
    db.commit()
    return SipSettingsOut(settings=body, problems=[], codecs_available=list(CODECS))


# ----------------------------------------------------------------- numbering


class NumberingOut(BaseModel):
    plan: NumberingPlan
    problems: list[str]
    description: str


@router.get("/numbering", response_model=NumberingOut, summary="Extension numbering plan")
def get_numbering(
    principal: Principal = Depends(require("extensions.read")),
    db: Session = Depends(get_db),
) -> NumberingOut:
    plan = load_numbering_plan(db)
    return NumberingOut(plan=plan, problems=plan.problems(), description=plan.describe())


@router.put("/numbering", response_model=NumberingOut, summary="Change the numbering plan")
def put_numbering(
    body: NumberingPlan,
    principal: Principal = Depends(require("system.settings.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> NumberingOut:
    problems = body.problems()
    if problems:
        raise ProblemError(
            422,
            "Numbering plan not saved",
            " ".join(problems),
            code="validation_failed",
            errors=[{"field": "plan", "message": p} for p in problems],
        )
    before = load_numbering_plan(db).model_dump(mode="json")
    save_numbering_plan(db, body, updated_by=principal.user_id)
    after = body.model_dump(mode="json")
    audit.record(
        db,
        action="telephony.numbering_update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="settings",
        target_id="telephony.numbering",
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"changed": {k: after[k] for k in after if before.get(k) != after[k]}},
    )
    db.commit()
    return NumberingOut(plan=body, problems=[], description=body.describe())


# ----------------------------------------------------------------- revisions


class RevisionOut(BaseModel):
    id: uuid.UUID
    sequence: int
    engine: str
    state: str
    summary: str
    content_hash: str | None
    created_by: str
    created_at: datetime
    deployed_at: datetime | None
    parent_sequence: int | None = None
    validation_errors: list[Any]
    files: list[dict[str, Any]] = []
    diff: dict[str, Any] | None = None
    unchanged: bool | None = None
    can_deploy: bool = False
    can_rollback: bool = False
    deploy_mode: str | None = None
    deploy_requested_at: datetime | None = None


def _revision_out(
    db: Session,
    rev: ConfigRevision,
    principal: Principal,
    *,
    with_files: bool = False,
    key: InstallationKey | None = None,
) -> RevisionOut:
    parent_seq = None
    if rev.parent_id:
        parent = db.get(ConfigRevision, rev.parent_id)
        parent_seq = parent.sequence if parent else None
    deployed = service.current_deployed(db, rev.engine)
    out = RevisionOut(
        id=rev.id,
        sequence=rev.sequence,
        engine=rev.engine,
        state=rev.state,
        summary=rev.summary,
        content_hash=rev.content_hash,
        created_by=rev.created_by,
        created_at=rev.created_at,
        deployed_at=rev.deployed_at,
        parent_sequence=parent_seq,
        validation_errors=list(rev.validation_errors or []),
        can_deploy=rev.state == RevisionState.VALIDATED,
        can_rollback=rev.state == RevisionState.SUPERSEDED,
        deploy_mode=rev.deploy_mode,
        deploy_requested_at=rev.deploy_requested_at,
    )
    if with_files and principal.is_platform_admin:
        files = artifacts_to_files_safe(rev.artifacts, key, rev.id)
        out.files = [
            {
                "path": f.path,
                "sensitive": f.sensitive,
                "content": None if f.sensitive else f.content,
                "lines": f.content.count("\n"),
            }
            for f in files
        ]
        if deployed is not None and deployed.id != rev.id:
            out.diff = diff(artifacts_to_files_safe(deployed.artifacts, key, deployed.id), files)
        elif deployed is None:
            out.diff = diff([], files)
        else:
            out.diff = {}
    return out


@router.get("/revisions", response_model=Page[RevisionOut], summary="Configuration revisions")
def list_revisions(
    page: PageParams = Depends(page_params),
    principal: Principal = Depends(require("config.read")),
    db: Session = Depends(get_db),
    request: Request = None,  # type: ignore[assignment]
) -> Page[RevisionOut]:
    engine = _adapter(request).name
    stmt = (
        select(ConfigRevision)
        .where(ConfigRevision.engine == engine)
        .order_by(ConfigRevision.sequence.desc())
    )
    rows, total = paginate(db, stmt, page)
    return Page(
        items=[_revision_out(db, r, principal) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/revisions",
    response_model=RevisionOut,
    status_code=201,
    summary="Generate a configuration revision from the database",
)
def generate_revision(
    request: Request,
    principal: Principal = Depends(require("config.deploy")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RevisionOut:
    adapter = _adapter(request)
    if Capability.CONFIG_GENERATION not in adapter.capabilities():
        raise ProblemError(
            409,
            "Not available",
            "The configured telephony engine cannot generate configuration.",
            code="not_available",
        )
    key = _key(request)
    generated = service.create_revision(db, adapter, created_by=principal.label, key=key)
    audit.record(
        db,
        action="telephony.config_generate",
        outcome="failure" if generated.revision.state == RevisionState.FAILED else "success",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="config_revision",
        target_id=generated.revision.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={
            "sequence": generated.revision.sequence,
            "changed_files": sorted(generated.diff),
            "errors": generated.revision.validation_errors,
        },
    )
    db.commit()
    out = _revision_out(db, generated.revision, principal, with_files=True, key=key)
    out.unchanged = generated.unchanged
    return out


class DeployIn(BaseModel):
    # "now" (default) or "when_idle": wait until the engine has no active calls.
    mode: str = Field("now", pattern="^(now|when_idle)$")


class ApplyOut(BaseModel):
    revision: RevisionOut
    # True when a deployment was queued; False when nothing changed or generation failed.
    applied: bool
    unchanged: bool


@router.post(
    "/apply",
    response_model=ApplyOut,
    status_code=202,
    summary="Generate a revision from the database and deploy it in one step",
)
def apply_changes(
    request: Request,
    body: DeployIn | None = None,
    principal: Principal = Depends(require("config.deploy")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ApplyOut:
    mode = body.mode if body else service.DEPLOY_NOW
    """The "apply" button: the same as POST /revisions followed by
    POST /revisions/{id}/deploy. A revision identical to the deployed one is
    discarded instead of queued; a failed generation is returned as such."""
    adapter = _adapter(request)
    if Capability.CONFIG_GENERATION not in adapter.capabilities():
        raise ProblemError(
            409,
            "Not available",
            "The configured telephony engine cannot generate configuration.",
            code="not_available",
        )
    health = adapter.health()
    if health.state != "running":
        raise conflict(
            f"The telephony engine is not running ({health.state}): {health.message}",
            code="engine_not_running",
        )
    if service.pending(db, adapter.name) is not None:
        raise conflict("Another deployment is already in progress.", code="deployment_in_progress")
    key = _key(request)
    generated = service.create_revision(db, adapter, created_by=principal.label, key=key)
    rev = generated.revision
    failed = rev.state == RevisionState.FAILED
    applied = False
    if not failed:
        if generated.unchanged:
            # Nothing for the engine: the saved change had no effect on the
            # files, so the pending flag can go.
            rev.state = RevisionState.SUPERSEDED
            service.clear_changed(db)
        else:
            service.request_deploy(db, rev, mode)
            applied = True
    audit.record(
        db,
        action="telephony.config_apply",
        outcome="failure" if failed else "success",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="config_revision",
        target_id=rev.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={
            "sequence": rev.sequence,
            "applied": applied,
            "mode": mode,
            "unchanged": generated.unchanged,
            "changed_files": sorted(generated.diff),
            "errors": rev.validation_errors,
        },
    )
    db.commit()
    out = _revision_out(db, rev, principal, with_files=False)
    out.unchanged = generated.unchanged
    return ApplyOut(revision=out, applied=applied, unchanged=generated.unchanged)


@router.get("/revisions/{revision_id}", response_model=RevisionOut, summary="One revision")
def get_revision(
    revision_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("config.read")),
    db: Session = Depends(get_db),
) -> RevisionOut:
    rev = db.get(ConfigRevision, revision_id)
    if rev is None:
        raise not_found("Revision")
    return _revision_out(db, rev, principal, with_files=True, key=_key(request))


@router.post(
    "/revisions/{revision_id}/deploy",
    response_model=RevisionOut,
    status_code=202,
    summary="Deploy a revision (or re-deploy an older one to roll back)",
)
def deploy_revision(
    revision_id: uuid.UUID,
    request: Request,
    body: DeployIn | None = None,
    principal: Principal = Depends(require("config.deploy")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RevisionOut:
    mode = body.mode if body else service.DEPLOY_NOW
    rev = db.get(ConfigRevision, revision_id)
    if rev is None:
        raise not_found("Revision")
    if rev.state not in (RevisionState.VALIDATED, RevisionState.SUPERSEDED):
        raise conflict(
            f"A revision in state '{rev.state}' cannot be deployed.", code="invalid_state"
        )
    health = _adapter(request).health()
    if health.state != "running":
        raise conflict(
            f"The telephony engine is not running ({health.state}): {health.message}",
            code="engine_not_running",
        )
    was_superseded = rev.state == RevisionState.SUPERSEDED
    try:
        service.request_deploy(db, rev, mode)
    except RuntimeError as e:
        raise conflict(str(e), code="deployment_in_progress") from e
    audit.record(
        db,
        action="telephony.config_deploy_request",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="config_revision",
        target_id=rev.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"sequence": rev.sequence, "rollback": was_superseded, "mode": mode},
    )
    db.commit()
    return _revision_out(db, rev, principal)


@router.post(
    "/revisions/{revision_id}/discard",
    response_model=MessageOut,
    summary="Discard a validated revision that was never deployed",
)
def discard_revision(
    revision_id: uuid.UUID,
    principal: Principal = Depends(require("config.deploy")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    rev = db.get(ConfigRevision, revision_id)
    if rev is None:
        raise not_found("Revision")
    if rev.state != RevisionState.VALIDATED:
        raise conflict(
            "Only a validated, undeployed revision can be discarded.", code="invalid_state"
        )
    rev.state = RevisionState.SUPERSEDED
    audit.record(
        db,
        action="telephony.config_discard",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="config_revision",
        target_id=rev.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"sequence": rev.sequence},
    )
    db.commit()
    return MessageOut(message=f"Revision {rev.sequence} discarded.")
