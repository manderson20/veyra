# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call and queue reports (docs/REPORTING.md §5.1) and the report builder
with saved and scheduled reports (docs/REPORT_BUILDER.md)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.models import (
    CallQueue,
    Extension,
    InboundRoute,
    Organization,
    RingGroup,
    SavedReport,
    SipTrunk,
    TimeCondition,
)
from veyra.core.models.base import utcnow
from veyra.core.security.principal import Principal
from veyra.reporting import builder, reports
from veyra.reporting import schedule as report_schedule

router = APIRouter(prefix="/reports", tags=["reports"])
READ = "reports.read"
MAX_DAYS = 400


def _period(since: datetime | None, until: datetime | None) -> tuple[datetime, datetime]:
    until = until or utcnow()
    since = since or until - timedelta(days=7)
    if since >= until:
        raise ProblemError(
            422, "Validation failed", "'from' must be before 'to'.", code="validation_failed"
        )
    if until - since > timedelta(days=MAX_DAYS):
        raise ProblemError(
            422,
            "Validation failed",
            f"A report covers at most {MAX_DAYS} days.",
            code="validation_failed",
        )
    return since, until


def _scope(
    db: Session, principal: Principal, organization_id: uuid.UUID | None
) -> tuple[set[uuid.UUID] | None, str]:
    orgs = principal.organization_ids_with(READ)
    if organization_id is not None and orgs is not None and organization_id not in orgs:
        raise forbidden()
    tz = "UTC"
    if organization_id is not None:
        org = db.get(Organization, organization_id)
        if org is not None:
            tz = org.timezone or "UTC"
    elif orgs is not None and len(orgs) == 1:
        org = db.get(Organization, next(iter(orgs)))
        tz = org.timezone if org is not None and org.timezone else "UTC"
    return orgs, tz


@router.get("/calls", summary="Calls by day, hour, extension and trunk")
def calls(
    organization_id: uuid.UUID | None = None,
    since: datetime | None = Query(None, alias="from"),
    until: datetime | None = Query(None, alias="to"),
    tz: str | None = Query(None, max_length=64, description="Time zone for days and hours"),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    start, end = _period(since, until)
    orgs, default_tz = _scope(db, principal, organization_id)
    zone = tz or default_tz
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ProblemError(
            422, "Validation failed", f"Unknown time zone {zone!r}.", code="validation_failed"
        ) from e
    return {
        "from": start,
        "to": end,
        **reports.calls_report(
            db, since=start, until=end, tz=zone, org_ids=orgs, organization_id=organization_id
        ),
    }


@router.get("/queues", summary="Queue offered, answered, abandoned, wait and agents")
def queues(
    organization_id: uuid.UUID | None = None,
    since: datetime | None = Query(None, alias="from"),
    until: datetime | None = Query(None, alias="to"),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    start, end = _period(since, until)
    orgs, _ = _scope(db, principal, organization_id)
    return {
        "from": start,
        "to": end,
        "queues": reports.queues_report(
            db, since=start, until=end, org_ids=orgs, organization_id=organization_id
        ),
    }


# ------------------------------------------------- report builder (M10b)

WRITE = "reports.write"


def _orgs(principal: Principal) -> set[uuid.UUID] | None:
    return principal.organization_ids_with(READ)


def _run(db: Session, principal: Principal, d: builder.Definition) -> dict[str, Any]:
    try:
        return builder.run(db, d, _orgs(principal))
    except builder.ReportError as e:
        raise ProblemError(422, "Validation failed", str(e), code="validation_failed") from e


@router.post("/run", summary="Run a report definition")
def run_report(
    body: builder.Definition,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _run(db, principal, body)


def _csv(result: dict[str, Any], name: str) -> PlainTextResponse:
    stamp = utcnow().strftime("%Y%m%d-%H%M")
    return PlainTextResponse(
        builder.to_csv(result),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}-{stamp}.csv"'},
    )


@router.post("/run.csv", summary="Run a report definition as CSV")
def run_report_csv(
    body: builder.Definition,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    return _csv(_run(db, principal, body), "report")


@router.get("/options", summary="What a report can be filtered by")
def report_options(
    organization_id: uuid.UUID | None = None,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    orgs = _orgs(principal)
    if organization_id is not None and orgs is not None and organization_id not in orgs:
        raise forbidden()
    wanted = {organization_id} if organization_id else orgs

    def scoped(model: Any) -> Any:
        stmt = select(model)
        if wanted is not None:
            stmt = stmt.where(model.organization_id.in_(wanted or {uuid.UUID(int=0)}))
        return db.scalars(stmt).all()

    return {
        "extensions": sorted(
            ({"id": str(e.id), "label": f"{e.number} {e.display_name}"} for e in scoped(Extension)),
            key=lambda x: x["label"],
        ),
        "dids": sorted({r.did for r in scoped(InboundRoute) if r.did}),
        "trunks": sorted(
            ({"id": str(t.id), "label": t.name} for t in db.scalars(select(SipTrunk))),
            key=lambda x: x["label"],
        ),
        "queues": [{"id": q.slug, "label": f"{q.number} {q.name}"} for q in scoped(CallQueue)],
        "ring_groups": [{"id": g.slug, "label": f"{g.number} {g.name}"} for g in scoped(RingGroup)],
        "time_conditions": [{"id": str(t.id), "label": t.name} for t in scoped(TimeCondition)],
        "groups": builder.GROUP_LABELS,
        "measures": {k: {"label": v[0], "unit": v[1]} for k, v in builder.MEASURE_LABELS.items()},
    }


saved_router = APIRouter(prefix="/saved-reports", tags=["reports"])


class SavedIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    definition: builder.Definition
    shared: bool = True
    schedule: report_schedule.Schedule | None = None


class SavedPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    definition: builder.Definition | None = None
    shared: bool | None = None
    schedule: report_schedule.Schedule | None = None


class SavedOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    definition: dict[str, Any]
    owner_user_id: uuid.UUID | None
    shared: bool
    schedule: dict[str, Any] | None
    next_run_at: datetime | None
    last_sent_at: datetime | None
    last_error: str | None
    can_edit: bool
    created_at: datetime
    updated_at: datetime


def _saved_out(r: SavedReport, principal: Principal) -> SavedOut:
    return SavedOut(
        id=r.id,
        organization_id=r.organization_id,
        name=r.name,
        description=r.description,
        definition=r.definition,
        owner_user_id=r.owner_user_id,
        shared=r.shared,
        schedule=r.schedule,
        next_run_at=r.next_run_at,
        last_sent_at=r.last_sent_at,
        last_error=r.last_error,
        can_edit=principal.has(WRITE, r.organization_id),
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _visible(principal: Principal) -> Any:
    stmt = select(SavedReport)
    orgs = _orgs(principal)
    if orgs is not None:
        stmt = stmt.where(SavedReport.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    writers = principal.organization_ids_with(WRITE)
    if writers is None:
        return stmt  # platform scope sees every report
    return stmt.where(
        or_(
            SavedReport.shared.is_(True),
            SavedReport.owner_user_id == principal.user_id,
            SavedReport.organization_id.in_(writers or {uuid.UUID(int=0)}),
        )
    )


def _get(db: Session, principal: Principal, report_id: uuid.UUID) -> SavedReport:
    r = db.scalar(_visible(principal).where(SavedReport.id == report_id))
    if r is None:
        raise not_found("Report")
    return r


def _check_definition(
    principal: Principal, org_id: uuid.UUID, d: builder.Definition
) -> dict[str, Any]:
    if d.organization_id is not None and d.organization_id != org_id:
        raise ProblemError(
            422,
            "Validation failed",
            "The report belongs to another organization.",
            code="validation_failed",
        )
    return {**d.model_dump(mode="json"), "organization_id": str(org_id)}


def _record(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    r: SavedReport,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=r.organization_id,
        target_type="saved_report",
        target_id=r.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": r.name, **details},
    )


def _reschedule(db: Session, r: SavedReport) -> None:
    if r.schedule:
        r.next_run_at = report_schedule.next_run(
            report_schedule.Schedule.model_validate(r.schedule),
            report_schedule.org_tz(db, r.organization_id),
            utcnow(),
        )
    else:
        r.next_run_at = None


@saved_router.get("", response_model=list[SavedOut], summary="Saved reports")
def list_saved(
    organization_id: uuid.UUID | None = None,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> list[SavedOut]:
    stmt = _visible(principal).order_by(SavedReport.name)
    if organization_id:
        stmt = stmt.where(SavedReport.organization_id == organization_id)
    return [_saved_out(r, principal) for r in db.scalars(stmt)]


@saved_router.post("", response_model=SavedOut, status_code=201, summary="Save a report")
def create_saved(
    body: SavedIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> SavedOut:
    if not principal.has(WRITE, body.organization_id):
        raise forbidden()
    r = SavedReport(
        id=uuid.uuid4(),
        organization_id=body.organization_id,
        name=body.name.strip(),
        description=(body.description or "").strip() or None,
        definition=_check_definition(principal, body.organization_id, body.definition),
        owner_user_id=principal.user_id,
        shared=body.shared,
        schedule=body.schedule.model_dump() if body.schedule else None,
    )
    _reschedule(db, r)
    db.add(r)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("A report with that name exists in this organization.", "name_in_use") from e
    _record(db, ctx, principal, "report.save", r, {"scheduled": bool(r.schedule)})
    db.commit()
    return _saved_out(r, principal)


@saved_router.get("/{report_id}", response_model=SavedOut)
def get_saved(
    report_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> SavedOut:
    return _saved_out(_get(db, principal, report_id), principal)


@saved_router.patch("/{report_id}", response_model=SavedOut)
def update_saved(
    report_id: uuid.UUID,
    body: SavedPatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> SavedOut:
    r = _get(db, principal, report_id)
    if not principal.has(WRITE, r.organization_id):
        raise forbidden()
    fields = body.model_fields_set
    if "name" in fields and body.name:
        r.name = body.name.strip()
    if "description" in fields:
        r.description = (body.description or "").strip() or None
    if "definition" in fields and body.definition is not None:
        r.definition = _check_definition(principal, r.organization_id, body.definition)
    if "shared" in fields and body.shared is not None:
        r.shared = body.shared
    if "schedule" in fields:
        r.schedule = body.schedule.model_dump() if body.schedule else None
        r.last_error = None
        _reschedule(db, r)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("A report with that name exists in this organization.", "name_in_use") from e
    _record(db, ctx, principal, "report.update", r, {"changed": sorted(fields)})
    db.commit()
    return _saved_out(r, principal)


@saved_router.delete("/{report_id}", status_code=204)
def delete_saved(
    report_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    r = _get(db, principal, report_id)
    if not principal.has(WRITE, r.organization_id):
        raise forbidden()
    _record(db, ctx, principal, "report.delete", r, {})
    db.delete(r)
    db.commit()
    return Response(status_code=204)


def _definition_of(r: SavedReport) -> builder.Definition:
    return builder.Definition.model_validate(
        {**r.definition, "organization_id": str(r.organization_id)}
    )


@saved_router.post("/{report_id}/run", summary="Run a saved report")
def run_saved(
    report_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _run(db, principal, _definition_of(_get(db, principal, report_id)))


@saved_router.post("/{report_id}/run.csv", summary="Run a saved report as CSV")
def run_saved_csv(
    report_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    r = _get(db, principal, report_id)
    return _csv(_run(db, principal, _definition_of(r)), "report")


@saved_router.post("/{report_id}/send", response_model=SavedOut, summary="Email the report now")
def send_saved(
    report_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> SavedOut:
    r = _get(db, principal, report_id)
    if not principal.has(WRITE, r.organization_id):
        raise forbidden()
    try:
        report_schedule.send(db, r, request.app.state.settings.mailqueue_dir)
    except Exception as e:
        r.last_error = str(e)[:500]
        db.commit()
        raise ProblemError(409, "Not sent", str(e), code="report_not_sent") from e
    r.last_sent_at, r.last_error = utcnow(), None
    _record(
        db,
        ctx,
        principal,
        "report.send",
        r,
        {"recipients": len((r.schedule or {}).get("recipients", []))},
    )
    db.commit()
    return _saved_out(r, principal)
