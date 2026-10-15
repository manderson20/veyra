# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call recording (docs/REPORTING.md §4): policies that decide what is
recorded, and the recordings with audited playback."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import group_helpers as helpers
from veyra.configmgmt import service as configmgmt
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, current_principal, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.models import (
    CallQueue,
    CallRecord,
    CallRecording,
    Extension,
    InboundRoute,
    Organization,
    Prompt,
    RecordingPolicy,
    RingGroup,
)
from veyra.core.models.base import utcnow
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.reporting import recordings as files

router = APIRouter(tags=["recording"])

P_READ = "recording_policies.read"
P_WRITE = "recording_policies.write"
R_READ = "recordings.read"
R_OWN = "recordings.read_own"
R_MANAGE = "recordings.manage"


# ------------------------------------------------------------------ policies


class PolicyIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    is_enabled: bool = True
    inbound: bool = True
    outbound: bool = False
    internal: bool = False
    scope: Literal["all", "selected"] = "all"
    extension_ids: list[uuid.UUID] = Field(default_factory=list)
    ring_group_ids: list[uuid.UUID] = Field(default_factory=list)
    queue_ids: list[uuid.UUID] = Field(default_factory=list)
    inbound_route_ids: list[uuid.UUID] = Field(default_factory=list)
    announcement_prompt_id: uuid.UUID | None = None
    retention_days: int = Field(90, ge=1, le=3650)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return v.strip()


class PolicyPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    is_enabled: bool | None = None
    inbound: bool | None = None
    outbound: bool | None = None
    internal: bool | None = None
    scope: Literal["all", "selected"] | None = None
    extension_ids: list[uuid.UUID] | None = None
    ring_group_ids: list[uuid.UUID] | None = None
    queue_ids: list[uuid.UUID] | None = None
    inbound_route_ids: list[uuid.UUID] | None = None
    announcement_prompt_id: uuid.UUID | None = None
    retention_days: int | None = Field(None, ge=1, le=3650)


class PolicyOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    is_enabled: bool
    inbound: bool
    outbound: bool
    internal: bool
    scope: str
    extension_ids: list[uuid.UUID]
    ring_group_ids: list[uuid.UUID]
    queue_ids: list[uuid.UUID]
    inbound_route_ids: list[uuid.UUID]
    announcement_prompt_id: uuid.UUID | None
    retention_days: int
    problems: list[str]
    created_at: datetime
    updated_at: datetime


def _policy_out(db: Session, p: RecordingPolicy) -> PolicyOut:
    org = db.get(Organization, p.organization_id)
    problems = []
    if not (p.inbound or p.outbound or p.internal):
        problems.append("No direction is chosen: nothing is recorded.")
    if p.scope == "selected" and not (
        p.extension_ids or p.ring_group_ids or p.queue_ids or p.inbound_route_ids
    ):
        problems.append("Nothing is selected: nothing is recorded.")
    if p.inbound and p.announcement_prompt_id is None:
        problems.append("Inbound callers hear no announcement that the call is recorded.")
    return PolicyOut(
        id=p.id,
        organization_id=p.organization_id,
        organization_name=org.name if org else "",
        name=p.name,
        is_enabled=p.is_enabled,
        inbound=p.inbound,
        outbound=p.outbound,
        internal=p.internal,
        scope=p.scope,
        extension_ids=list(p.extension_ids or []),
        ring_group_ids=list(p.ring_group_ids or []),
        queue_ids=list(p.queue_ids or []),
        inbound_route_ids=list(p.inbound_route_ids or []),
        announcement_prompt_id=p.announcement_prompt_id,
        retention_days=p.retention_days,
        problems=problems,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _check_targets(db: Session, org_id: uuid.UUID, data: dict[str, Any]) -> None:
    """Every chosen target exists and belongs to the policy's organization."""
    for field, model in (
        ("extension_ids", Extension),
        ("ring_group_ids", RingGroup),
        ("queue_ids", CallQueue),
        ("inbound_route_ids", InboundRoute),
    ):
        ids = set(data.get(field) or [])
        if not ids:
            continue
        found = set(
            db.scalars(select(model.id).where(model.id.in_(ids), model.organization_id == org_id))
        )
        if found != ids:
            raise helpers.validation(field, "not found in this organization")
    prompt_id = data.get("announcement_prompt_id")
    if prompt_id is not None:
        prompt = db.get(Prompt, prompt_id)
        if prompt is None or prompt.organization_id != org_id:
            raise helpers.validation(
                "announcement_prompt_id", "recording not found in this organization"
            )


def _policy(db: Session, principal: Principal, policy_id: uuid.UUID, perm: str) -> RecordingPolicy:
    stmt = helpers.org_filter(
        select(RecordingPolicy), RecordingPolicy.organization_id, principal, perm
    )
    row = db.scalar(stmt.where(RecordingPolicy.id == policy_id))
    if row is None:
        raise not_found("Recording policy")
    return row


def _audit(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    target_type: str,
    target_id: Any,
    org_id: uuid.UUID | None,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=org_id,
        target_type=target_type,
        target_id=target_id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=details,
    )


@router.get("/recording-policies", response_model=Page[PolicyOut], summary="Recording policies")
def list_policies(
    organization_id: uuid.UUID | None = None,
    page: PageParams = Depends(page_params),
    principal: Principal = Depends(require(P_READ)),
    db: Session = Depends(get_db),
) -> Page[PolicyOut]:
    stmt = helpers.org_filter(
        select(RecordingPolicy), RecordingPolicy.organization_id, principal, P_READ
    ).order_by(RecordingPolicy.name)
    if organization_id:
        stmt = stmt.where(RecordingPolicy.organization_id == organization_id)
    rows, total = paginate(db, stmt, page)
    return Page(
        items=[_policy_out(db, r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/recording-policies", response_model=PolicyOut, status_code=201, summary="Add a policy"
)
def create_policy(
    body: PolicyIn,
    principal: Principal = Depends(require(P_WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PolicyOut:
    if not principal.has(P_WRITE, body.organization_id):
        raise forbidden()
    org = db.get(Organization, body.organization_id)
    if org is None:
        raise not_found("Organization")
    data = body.model_dump()
    _check_targets(db, org.id, data)
    policy = RecordingPolicy(id=uuid.uuid4(), **data)
    db.add(policy)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("A policy with that name exists in this organization.", "name_in_use") from e
    _audit(
        db,
        ctx,
        principal,
        "recording_policy.create",
        "recording_policy",
        policy.id,
        org.id,
        {"name": policy.name},
    )
    configmgmt.mark_changed(db, by=principal.label, what=f"recording policy {policy.name}")
    db.commit()
    return _policy_out(db, policy)


@router.get("/recording-policies/{policy_id}", response_model=PolicyOut)
def get_policy(
    policy_id: uuid.UUID,
    principal: Principal = Depends(require(P_READ)),
    db: Session = Depends(get_db),
) -> PolicyOut:
    return _policy_out(db, _policy(db, principal, policy_id, P_READ))


@router.patch("/recording-policies/{policy_id}", response_model=PolicyOut)
def update_policy(
    policy_id: uuid.UUID,
    body: PolicyPatch,
    principal: Principal = Depends(require(P_WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PolicyOut:
    policy = _policy(db, principal, policy_id, P_WRITE)
    changes = body.model_dump(exclude_unset=True)
    for key in ("name", "is_enabled", "inbound", "outbound", "internal", "scope", "retention_days"):
        if key in changes and changes[key] is None:
            raise helpers.validation(key, "may not be empty")
    _check_targets(db, policy.organization_id, changes)
    for k, v in changes.items():
        setattr(policy, k, v if v is not None or k == "announcement_prompt_id" else [])
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("A policy with that name exists in this organization.", "name_in_use") from e
    _audit(
        db,
        ctx,
        principal,
        "recording_policy.update",
        "recording_policy",
        policy.id,
        policy.organization_id,
        {"changed": sorted(changes)},
    )
    configmgmt.mark_changed(db, by=principal.label, what=f"recording policy {policy.name}")
    db.commit()
    return _policy_out(db, policy)


@router.delete("/recording-policies/{policy_id}", status_code=204)
def delete_policy(
    policy_id: uuid.UUID,
    principal: Principal = Depends(require(P_WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    policy = _policy(db, principal, policy_id, P_WRITE)
    _audit(
        db,
        ctx,
        principal,
        "recording_policy.delete",
        "recording_policy",
        policy.id,
        policy.organization_id,
        {"name": policy.name},
    )
    configmgmt.mark_changed(db, by=principal.label, what=f"recording policy {policy.name}")
    db.delete(policy)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- recordings


class RecordingOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    call_id: uuid.UUID | None
    policy_name: str | None
    started_at: datetime | None
    direction: str | None
    from_number: str | None
    from_name: str | None
    to_number: str | None
    duration_seconds: int
    size_bytes: int
    created_at: datetime
    delete_after: datetime | None
    held: bool
    held_by: str | None
    deleted_at: datetime | None


def _mine(principal: Principal) -> Any:
    own = select(Extension.id).where(Extension.user_id == principal.user_id)
    return CallRecording.call_id.in_(
        select(CallRecord.id).where(
            or_(
                CallRecord.from_extension_id.in_(own),
                CallRecord.to_extension_id.in_(own),
                CallRecord.answered_extension_id.in_(own),
            )
        )
    )


def _visible(principal: Principal) -> Any:
    """Recordings the caller may hear: their organizations' with
    recordings.read, plus their own calls' with recordings.read_own."""
    stmt = select(CallRecording)
    orgs = principal.organization_ids_with(R_READ) if principal.has_any_scope(R_READ) else set()
    if orgs is None:
        return stmt
    conds = [CallRecording.organization_id.in_(orgs or {uuid.UUID(int=0)})]
    if principal.has_any_scope(R_OWN):
        conds.append(_mine(principal))
    return stmt.where(or_(*conds))


def _rec_outs(db: Session, rows: list[CallRecording]) -> list[RecordingOut]:
    calls = {
        c.id: c
        for c in db.scalars(
            select(CallRecord).where(CallRecord.id.in_({r.call_id for r in rows if r.call_id}))
        )
    }
    policies = {
        p.id: p.name
        for p in db.scalars(
            select(RecordingPolicy).where(
                RecordingPolicy.id.in_({r.policy_id for r in rows if r.policy_id})
            )
        )
    }
    out = []
    for r in rows:
        c = calls.get(r.call_id) if r.call_id else None
        out.append(
            RecordingOut(
                id=r.id,
                organization_id=r.organization_id,
                call_id=r.call_id,
                policy_name=policies.get(r.policy_id) if r.policy_id else None,
                started_at=c.started_at if c else None,
                direction=c.direction if c else None,
                from_number=c.from_number if c else None,
                from_name=c.from_name if c else None,
                to_number=c.to_number if c else None,
                duration_seconds=r.duration_seconds,
                size_bytes=r.size_bytes,
                created_at=r.created_at,
                delete_after=r.delete_after,
                held=r.held,
                held_by=r.held_by,
                deleted_at=r.deleted_at,
            )
        )
    return out


def _require_listen(principal: Principal) -> None:
    if not (principal.has_any_scope(R_READ) or principal.has_any_scope(R_OWN)):
        raise forbidden()


@router.get("/recordings", response_model=Page[RecordingOut], summary="Call recordings")
def list_recordings(
    organization_id: uuid.UUID | None = None,
    call_id: uuid.UUID | None = None,
    include_deleted: bool = False,
    since: datetime | None = Query(None, alias="from"),
    page: PageParams = Depends(page_params),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
) -> Page[RecordingOut]:
    _require_listen(principal)
    stmt = _visible(principal).order_by(CallRecording.created_at.desc())
    if organization_id:
        stmt = stmt.where(CallRecording.organization_id == organization_id)
    if call_id:
        stmt = stmt.where(CallRecording.call_id == call_id)
    if not include_deleted:
        stmt = stmt.where(CallRecording.deleted_at.is_(None))
    if since:
        stmt = stmt.where(CallRecording.created_at >= since)
    rows, total = paginate(db, stmt, page)
    return Page(items=_rec_outs(db, rows), total=total, limit=page.limit, offset=page.offset)


def _recording(db: Session, principal: Principal, rec_id: uuid.UUID) -> CallRecording:
    _require_listen(principal)
    rec = db.scalar(_visible(principal).where(CallRecording.id == rec_id))
    if rec is None:
        raise not_found("Recording")
    return rec


@router.get("/recordings/{rec_id}/audio", summary="Listen (audited; byte ranges)")
def recording_audio(
    rec_id: uuid.UUID,
    request: Request,
    download: bool = False,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> FileResponse:
    rec = _recording(db, principal, rec_id)
    if rec.deleted_at is not None:
        raise ProblemError(410, "Deleted", "This recording was deleted.", code="recording_deleted")
    path = files.file_of(request.app.state.settings.recordings_dir, rec)
    if path is None:
        raise ProblemError(404, "Missing", "The recording file is missing.", code="file_missing")
    # One audit entry per listening, not per byte range the player asks for.
    if not request.headers.get("range", "").startswith("bytes=") or request.headers.get(
        "range", ""
    ).startswith("bytes=0-"):
        _audit(
            db,
            ctx,
            principal,
            "recording.download" if download else "recording.play",
            "recording",
            rec.id,
            rec.organization_id,
            {"call_id": str(rec.call_id) if rec.call_id else None},
        )
        db.commit()
    return FileResponse(
        path,
        media_type="audio/ogg",
        filename=f"recording-{rec.ref}.ogg" if download else None,
        headers={"Cache-Control": "private, no-store"},
    )


class HoldIn(BaseModel):
    held: bool


@router.post("/recordings/{rec_id}/hold", response_model=RecordingOut, summary="Hold or release")
def hold_recording(
    rec_id: uuid.UUID,
    body: HoldIn,
    principal: Principal = Depends(require(R_MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RecordingOut:
    rec = db.get(CallRecording, rec_id)
    if rec is None or not principal.has(R_MANAGE, rec.organization_id):
        raise not_found("Recording")
    if rec.deleted_at is not None:
        raise ProblemError(410, "Deleted", "This recording was deleted.", code="recording_deleted")
    rec.held = body.held
    rec.held_by = principal.label if body.held else None
    if not body.held and rec.delete_after is not None and rec.delete_after < utcnow():
        # Released after its date: kept one more day so it is not lost by surprise.
        rec.delete_after = utcnow() + timedelta(days=1)
    _audit(
        db,
        ctx,
        principal,
        "recording.hold" if body.held else "recording.release",
        "recording",
        rec.id,
        rec.organization_id,
        {},
    )
    db.commit()
    return _rec_outs(db, [rec])[0]


@router.delete("/recordings/{rec_id}", status_code=204, summary="Delete a recording now")
def delete_recording(
    rec_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(R_MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    rec = db.get(CallRecording, rec_id)
    if rec is None or not principal.has(R_MANAGE, rec.organization_id):
        raise not_found("Recording")
    if rec.held:
        raise conflict("Release the hold before deleting this recording.", "recording_held")
    if rec.deleted_at is None:
        files.delete_file(request.app.state.settings.recordings_dir, rec)
        rec.deleted_at = utcnow()
        rec.deleted_by = principal.label
        _audit(db, ctx, principal, "recording.delete", "recording", rec.id, rec.organization_id, {})
        db.commit()
    return Response(status_code=204)
