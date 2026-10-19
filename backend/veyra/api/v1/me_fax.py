# SPDX-License-Identifier: AGPL-3.0-or-later
"""A user's faxes on My Phone (docs/USER_PORTAL.md §9): send a PDF with an
optional cover sheet, follow the job, download, cancel."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1.fax import file_response
from veyra.api.v1.me import require_me
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context
from veyra.core.errors import ProblemError, not_found
from veyra.core.models import Extension, FaxJob, User
from veyra.core.security.principal import Principal
from veyra.fax import service as fax_service
from veyra.fax.service import JobOut

router = APIRouter(prefix="/me/fax", tags=["me"])


def _own_job(db: Session, principal: Principal, job_id: uuid.UUID) -> FaxJob:
    row = db.scalar(select(FaxJob).where(FaxJob.id == job_id, FaxJob.user_id == principal.user_id))
    if row is None:
        raise not_found("Fax")
    return row


def _audit(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    row: FaxJob,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=row.organization_id,
        target_type="fax_job",
        target_id=row.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"self_service": True, "number": row.number, **details},
    )


@router.get("", response_model=list[JobOut], summary="Your faxes")
def my_faxes(
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> list[JobOut]:
    rows = db.scalars(
        select(FaxJob)
        .where(FaxJob.user_id == principal.user_id)
        .order_by(FaxJob.created_at.desc())
        .limit(100)
    ).all()
    return fax_service.outs(db, list(rows))


@router.post("", response_model=JobOut, status_code=201, summary="Send a PDF as a fax")
async def send_fax(
    request: Request,
    number: str = Form(..., max_length=40),
    file: UploadFile = File(...),
    cover: bool = Form(False),
    cover_to: str | None = Form(None, max_length=120),
    cover_from: str | None = Form(None, max_length=120),
    cover_subject: str | None = Form(None, max_length=120),
    cover_note: str | None = Form(None, max_length=2000),
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> JobOut:
    user = db.get(User, principal.user_id) if principal.user_id else None
    if user is None:
        raise not_found("User")
    ext = db.scalar(
        select(Extension)
        .where(Extension.user_id == principal.user_id, Extension.is_enabled.is_(True))
        .order_by(Extension.number)
    )
    if ext is None:
        raise ProblemError(
            409,
            "No phone",
            "Faxes are sent with your extension's caller ID; you have no extension.",
            code="no_extension",
        )
    data = await file.read(fax_service.MAX_PDF_BYTES + 1)
    cover_fields = (
        {
            "to": (cover_to or "").strip(),
            "from": (cover_from or "").strip() or user.display_name,
            "subject": (cover_subject or "").strip(),
            "note": (cover_note or "").strip(),
        }
        if cover
        else None
    )
    job = fax_service.create_outbound(
        db,
        request.app.state.settings,
        user=user,
        extension=ext,
        number=number,
        pdf=data,
        filename=file.filename,
        cover=cover_fields,
    )
    _audit(db, ctx, principal, "fax.send", job, {"pages": job.pages, "filename": file.filename})
    db.commit()
    return fax_service.outs(db, [job])[0]


@router.post("/{job_id}/cancel", response_model=JobOut, summary="Cancel one of your waiting faxes")
def cancel_fax(
    job_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> JobOut:
    row = _own_job(db, principal, job_id)
    fax_service.cancel(db, request.app.state.settings, row)
    _audit(db, ctx, principal, "fax.cancel", row, {})
    db.commit()
    return fax_service.outs(db, [row])[0]


@router.post(
    "/{job_id}/retry", response_model=JobOut, summary="Send one of your failed faxes again"
)
def retry_fax(
    job_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> JobOut:
    row = _own_job(db, principal, job_id)
    fax_service.retry(db, request.app.state.settings, row)
    _audit(db, ctx, principal, "fax.retry", row, {})
    db.commit()
    return fax_service.outs(db, [row])[0]


@router.get("/{job_id}/file", summary="Download one of your faxes as PDF")
def fax_file(
    job_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    row = _own_job(db, principal, job_id)
    _audit(db, ctx, principal, "fax.download", row, {})
    db.commit()
    return file_response(request.app.state.settings, row)
