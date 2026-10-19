# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fax administration (docs/USER_PORTAL.md §9): inboxes ("Fax to email"
destinations) and the organization's jobs, with retry, cancel and download."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from veyra.api.v1 import destinations
from veyra.api.v1.group_helpers import unique_slug
from veyra.configmgmt import service as configmgmt
from veyra.core import audit, tenancy
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import conflict, forbidden, not_found
from veyra.core.events import Event, bus
from veyra.core.models import FaxInbox, FaxJob, Organization
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.fax import service as fax_service
from veyra.fax.service import JobOut

router = APIRouter(prefix="/fax", tags=["fax"])

READ = "fax.read"
MANAGE = "fax.manage"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_STATION_RE = re.compile(r"^[0-9+ ]{0,32}$")


class InboxIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    recipients: list[str] = Field(default_factory=list, max_length=20)
    station_id: str | None = Field(None, max_length=32)
    header: str | None = Field(None, max_length=64)
    is_enabled: bool = True

    @field_validator("recipients")
    @classmethod
    def _emails(cls, v: list[str]) -> list[str]:
        out = []
        for a in (x.strip().lower() for x in v):
            if a and not _EMAIL_RE.match(a):
                raise ValueError(f"{a!r} is not an email address")
            if a and a not in out:
                out.append(a)
        return out

    @field_validator("station_id")
    @classmethod
    def _station(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if v and not _STATION_RE.match(v):
            raise ValueError("digits, + and spaces only")
        return v or None


class InboxPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    recipients: list[str] | None = Field(None, max_length=20)
    station_id: str | None = Field(None, max_length=32)
    header: str | None = Field(None, max_length=64)
    is_enabled: bool | None = None

    _emails = field_validator("recipients")(InboxIn._emails.__func__)  # type: ignore[attr-defined]
    _station = field_validator("station_id")(InboxIn._station.__func__)  # type: ignore[attr-defined]


class InboxOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    slug: str
    context: str
    recipients: list[str]
    station_id: str | None
    header: str | None
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


def _org_filter(stmt: Select[Any], column: Any, principal: Principal, perm: str) -> Select[Any]:
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(column.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _org_for_write(db: Session, principal: Principal, organization_id: uuid.UUID) -> Organization:
    if not principal.has(MANAGE, organization_id):
        raise forbidden()
    org = db.get(Organization, organization_id)
    if org is None:
        raise not_found("Organization")
    if not org.is_active:
        raise conflict("This organization is inactive.", "organization_inactive")
    return org


def _inbox_outs(db: Session, rows: list[FaxInbox]) -> list[InboxOut]:
    org_ids = {r.organization_id for r in rows}
    orgs = (
        {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids)))}
        if org_ids
        else {}
    )
    out = []
    for r in rows:
        org = orgs.get(r.organization_id)
        out.append(
            InboxOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=org.name if org else "",
                name=r.name,
                slug=r.slug,
                context=tenancy.names_of(db, r.organization_id).fax_in(r.slug),
                recipients=list(r.recipients or []),
                station_id=r.station_id,
                header=r.header,
                is_enabled=r.is_enabled,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _inbox(db: Session, principal: Principal, inbox_id: uuid.UUID, perm: str) -> FaxInbox:
    stmt = _org_filter(select(FaxInbox), FaxInbox.organization_id, principal, perm)
    row = db.scalar(stmt.where(FaxInbox.id == inbox_id))
    if row is None:
        raise not_found("Fax inbox")
    return row


def _audit(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    target_type: str,
    row: Any,
    details: dict[str, Any],
    *,
    changed: bool = False,
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=row.organization_id,
        target_type=target_type,
        target_id=row.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=details,
    )
    if changed:
        configmgmt.mark_changed(db, by=principal.label, what=f"{action} {details.get('name', '')}")


# ----------------------------------------------------------------- inboxes


@router.get("/inboxes", response_model=Page[InboxOut], summary="Fax inboxes")
def list_inboxes(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[InboxOut]:
    stmt = _org_filter(select(FaxInbox), FaxInbox.organization_id, principal, READ).order_by(
        FaxInbox.name
    )
    if organization_id:
        stmt = stmt.where(FaxInbox.organization_id == organization_id)
    if q:
        stmt = stmt.where(FaxInbox.name.ilike(f"%{q.strip()}%"))
    rows, total = paginate(db, stmt, params)
    return Page(items=_inbox_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post("/inboxes", response_model=InboxOut, status_code=201, summary="Create a fax inbox")
def create_inbox(
    body: InboxIn,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> InboxOut:
    org = _org_for_write(db, principal, body.organization_id)
    row = FaxInbox(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=body.name.strip(),
        slug=unique_slug(db, FaxInbox, body.name),
        recipients=body.recipients,
        station_id=body.station_id,
        header=(body.header or "").strip() or None,
        is_enabled=body.is_enabled,
    )
    db.add(row)
    db.flush()
    _audit(
        db, ctx, principal, "fax.inbox_create", "fax_inbox", row, {"name": row.name}, changed=True
    )
    db.commit()
    bus.publish(Event("fax.inbox_created", {"id": str(row.id), "name": row.name}))
    return _inbox_outs(db, [row])[0]


@router.get("/inboxes/{inbox_id}", response_model=InboxOut, summary="One fax inbox")
def get_inbox(
    inbox_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> InboxOut:
    return _inbox_outs(db, [_inbox(db, principal, inbox_id, READ)])[0]


@router.patch("/inboxes/{inbox_id}", response_model=InboxOut, summary="Change a fax inbox")
def update_inbox(
    inbox_id: uuid.UUID,
    body: InboxPatch,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> InboxOut:
    row = _inbox(db, principal, inbox_id, MANAGE)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if k in ("name", "header") and isinstance(v, str):
            v = v.strip() or None
            if k == "name" and v is None:
                continue
        setattr(row, k, v)
    _audit(
        db,
        ctx,
        principal,
        "fax.inbox_update",
        "fax_inbox",
        row,
        {"name": row.name, "fields": sorted(changes)},
        changed=True,
    )
    db.commit()
    return _inbox_outs(db, [row])[0]


@router.delete("/inboxes/{inbox_id}", status_code=204, summary="Delete a fax inbox")
def delete_inbox(
    inbox_id: uuid.UUID,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    row = _inbox(db, principal, inbox_id, MANAGE)
    what = destinations.describe_uses(db, "fax", row.id)
    if what:
        raise destinations.in_use_error("Fax inbox in use", "fax_inbox_in_use", what)
    _audit(
        db, ctx, principal, "fax.inbox_delete", "fax_inbox", row, {"name": row.name}, changed=True
    )
    db.delete(row)
    db.commit()
    bus.publish(Event("fax.inbox_deleted", {"id": str(inbox_id)}))
    return Response(status_code=204)


# ----------------------------------------------------------------- jobs


@router.get(
    "/jobs", response_model=Page[JobOut], summary="Fax jobs of the organizations you manage"
)
def list_jobs(
    organization_id: uuid.UUID | None = None,
    state: str | None = Query(None, max_length=16),
    direction: str | None = Query(None, pattern="^(in|out)$"),
    q: str | None = Query(None, max_length=64),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[JobOut]:
    stmt = _org_filter(select(FaxJob), FaxJob.organization_id, principal, READ).order_by(
        FaxJob.created_at.desc()
    )
    if organization_id:
        stmt = stmt.where(FaxJob.organization_id == organization_id)
    if state:
        stmt = stmt.where(FaxJob.state == state)
    if direction:
        stmt = stmt.where(FaxJob.direction == direction)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(FaxJob.number.ilike(like), FaxJob.original_name.ilike(like)))
    rows, total = paginate(db, stmt, params)
    return Page(
        items=fax_service.outs(db, rows), total=total, limit=params.limit, offset=params.offset
    )


def _job(db: Session, principal: Principal, job_id: uuid.UUID, perm: str) -> FaxJob:
    stmt = _org_filter(select(FaxJob), FaxJob.organization_id, principal, perm)
    row = db.scalar(stmt.where(FaxJob.id == job_id))
    if row is None:
        raise not_found("Fax")
    return row


@router.post("/jobs/{job_id}/retry", response_model=JobOut, summary="Send a failed fax again")
def retry_job(
    job_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> JobOut:
    row = _job(db, principal, job_id, MANAGE)
    fax_service.retry(db, request.app.state.settings, row)
    _audit(db, ctx, principal, "fax.retry", "fax_job", row, {"number": row.number})
    db.commit()
    return fax_service.outs(db, [row])[0]


@router.post("/jobs/{job_id}/cancel", response_model=JobOut, summary="Cancel a waiting fax")
def cancel_job(
    job_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> JobOut:
    row = _job(db, principal, job_id, MANAGE)
    fax_service.cancel(db, request.app.state.settings, row)
    _audit(db, ctx, principal, "fax.cancel", "fax_job", row, {"number": row.number})
    db.commit()
    return fax_service.outs(db, [row])[0]


def file_response(settings: Any, row: FaxJob) -> Response:
    pdf = fax_service.file_path(settings, row.pdf_file)
    if pdf is not None:
        name = f"fax-{row.created_at:%Y%m%d-%H%M}-{row.number}.pdf"
        return Response(
            content=pdf.read_bytes(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "Cache-Control": "private, no-store",
            },
        )
    tiff = fax_service.file_path(settings, row.file)
    if tiff is None:
        raise not_found("Fax file")
    return Response(
        content=tiff.read_bytes(),
        media_type="image/tiff",
        headers={
            "Content-Disposition": f'attachment; filename="fax-{row.id}.tiff"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/jobs/{job_id}/file", summary="Download a fax as PDF")
def job_file(
    job_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    row = _job(db, principal, job_id, MANAGE)
    _audit(db, ctx, principal, "fax.download", "fax_job", row, {"number": row.number})
    db.commit()
    return file_response(request.app.state.settings, row)
