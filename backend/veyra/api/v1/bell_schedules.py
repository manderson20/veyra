# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bell schedules (docs/PAGING_RECORDINGS.md §4.2): a calendar's events ring a
page; the next rings and the ring history are shown; "ring now" tests the page."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import group_helpers as helpers
from veyra.api.v1.pages import start_page
from veyra.bells import scheduler
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import conflict, forbidden, not_found
from veyra.core.models import (
    BellRing,
    BellSchedule,
    Calendar,
    CalendarEvent,
    Organization,
)
from veyra.core.models import (
    Page as PageModel,
)
from veyra.core.models.base import utcnow
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal

router = APIRouter(prefix="/bell-schedules", tags=["bells"])

READ = "bells.read"
WRITE = "bells.write"
Trigger = Literal["start", "end", "both"]


class ScheduleIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    calendar_id: uuid.UUID
    page_id: uuid.UUID
    match: str = Field("*", max_length=100)
    trigger: Trigger = "start"
    tolerance_seconds: int = Field(90, ge=0, le=900)
    all_day_events: bool = False
    is_enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        return v

    @field_validator("match")
    @classmethod
    def _match(cls, v: str) -> str:
        return v.strip() or "*"


class SchedulePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    calendar_id: uuid.UUID | None = None
    page_id: uuid.UUID | None = None
    match: str | None = Field(None, max_length=100)
    trigger: Trigger | None = None
    tolerance_seconds: int | None = Field(None, ge=0, le=900)
    all_day_events: bool | None = None
    is_enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return ScheduleIn._name(v) if v is not None else None

    @field_validator("match")
    @classmethod
    def _match(cls, v: str | None) -> str | None:
        return (v.strip() or "*") if v is not None else None


class NextRing(BaseModel):
    summary: str
    due_at: datetime
    trigger: str


class ScheduleOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    calendar_id: uuid.UUID
    calendar_name: str
    page_id: uuid.UUID
    page_name: str
    match: str
    trigger: str
    tolerance_seconds: int
    all_day_events: bool
    is_enabled: bool
    next_rings: list[NextRing]
    problems: list[str]
    created_at: datetime
    updated_at: datetime


class RingOut(BaseModel):
    id: uuid.UUID
    summary: str
    due_at: datetime
    rang_at: datetime
    outcome: str
    detail: dict[str, Any]


def _visible(principal: Principal, perm: str) -> Select[BellSchedule]:
    stmt = select(BellSchedule)
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(BellSchedule.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _get(db: Session, principal: Principal, schedule_id: uuid.UUID, perm: str) -> BellSchedule:
    row = db.scalar(_visible(principal, perm).where(BellSchedule.id == schedule_id))
    if row is None:
        raise not_found("Bell schedule")
    return row


def _next_rings(db: Session, s: BellSchedule, limit: int = 10) -> list[NextRing]:
    now = utcnow()
    events = db.scalars(
        select(CalendarEvent)
        .where(
            CalendarEvent.calendar_id == s.calendar_id,
            CalendarEvent.starts_at >= now - timedelta(hours=1),
        )
        .order_by(CalendarEvent.starts_at)
        .limit(500)
    ).all()
    out: list[NextRing] = []
    for ev in events:
        if ev.all_day and not s.all_day_events:
            continue
        if not scheduler.matches(s.match, ev.summary):
            continue
        if s.trigger in ("start", "both") and ev.starts_at >= now:
            out.append(NextRing(summary=ev.summary, due_at=ev.starts_at, trigger="start"))
        if s.trigger in ("end", "both") and ev.ends_at and ev.ends_at >= now:
            out.append(NextRing(summary=ev.summary, due_at=ev.ends_at, trigger="end"))
    out.sort(key=lambda r: r.due_at)
    return out[:limit]


def _outs(db: Session, rows: list[BellSchedule]) -> list[ScheduleOut]:
    if not rows:
        return []
    orgs = helpers.org_names(db, {r.organization_id for r in rows})
    cals = {
        c.id: c
        for c in db.scalars(select(Calendar).where(Calendar.id.in_({r.calendar_id for r in rows})))
    }
    pages = {
        p.id: p
        for p in db.scalars(select(PageModel).where(PageModel.id.in_({r.page_id for r in rows})))
    }
    out = []
    for r in rows:
        cal = cals.get(r.calendar_id)
        page = pages.get(r.page_id)
        problems = []
        if cal is None:
            problems.append("The calendar no longer exists.")
        elif not cal.is_enabled:
            problems.append("The calendar is disabled.")
        elif cal.last_status == "failed":
            problems.append(f"The calendar could not be fetched: {cal.last_error}")
        if page is None:
            problems.append("The page no longer exists.")
        elif page.audio_id is None:
            problems.append("The page has no recording; bells need one.")
        elif not page.is_enabled:
            problems.append("The page is disabled.")
        out.append(
            ScheduleOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=orgs.get(r.organization_id, ""),
                name=r.name,
                calendar_id=r.calendar_id,
                calendar_name=cal.name if cal else "",
                page_id=r.page_id,
                page_name=page.name if page else "",
                match=r.match,
                trigger=r.trigger,
                tolerance_seconds=r.tolerance_seconds,
                all_day_events=r.all_day_events,
                is_enabled=r.is_enabled,
                next_rings=_next_rings(db, r),
                problems=problems,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _check_refs(
    db: Session, org_id: uuid.UUID, calendar_id: uuid.UUID | None, page_id: uuid.UUID | None
) -> None:
    if calendar_id is not None:
        cal = db.get(Calendar, calendar_id)
        if cal is None or cal.organization_id != org_id:
            raise helpers.validation("calendar_id", "calendar not found in this organization")
    if page_id is not None:
        page = db.get(PageModel, page_id)
        if page is None or page.organization_id != org_id:
            raise helpers.validation("page_id", "page not found in this organization")


def _record(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    s: BellSchedule,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=s.organization_id,
        target_type="bell_schedule",
        target_id=s.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": s.name, **details},
    )


@router.get("", response_model=Page[ScheduleOut], summary="List bell schedules")
def list_schedules(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[ScheduleOut]:
    stmt = _visible(principal, READ).order_by(BellSchedule.name)
    if organization_id:
        stmt = stmt.where(BellSchedule.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(BellSchedule.name.ilike(like), BellSchedule.match.ilike(like)))
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post("", response_model=ScheduleOut, status_code=201, summary="Create a bell schedule")
def create_schedule(
    body: ScheduleIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ScheduleOut:
    if not principal.has(WRITE, body.organization_id):
        raise forbidden()
    org = db.get(Organization, body.organization_id)
    if org is None:
        raise not_found("Organization")
    _check_refs(db, org.id, body.calendar_id, body.page_id)
    s = BellSchedule(id=uuid.uuid4(), **body.model_dump())
    db.add(s)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(
            "A bell schedule with that name exists in this organization.", "name_in_use"
        ) from e
    _record(db, ctx, principal, "bell_schedule.create", s, {"match": s.match, "trigger": s.trigger})
    db.commit()
    return _outs(db, [s])[0]


@router.get("/{schedule_id}", response_model=ScheduleOut)
def get_schedule(
    schedule_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> ScheduleOut:
    return _outs(db, [_get(db, principal, schedule_id, READ)])[0]


@router.get("/{schedule_id}/rings", response_model=list[RingOut], summary="Recent rings")
def schedule_rings(
    schedule_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> list[RingOut]:
    s = _get(db, principal, schedule_id, READ)
    rows = db.scalars(
        select(BellRing)
        .where(BellRing.schedule_id == s.id)
        .order_by(BellRing.rang_at.desc())
        .limit(50)
    ).all()
    return [
        RingOut(
            id=r.id,
            summary=r.summary,
            due_at=r.due_at,
            rang_at=r.rang_at,
            outcome=r.outcome,
            detail=dict(r.detail),
        )
        for r in rows
    ]


@router.post("/{schedule_id}/ring", summary="Ring the schedule's page now (test)")
def ring_now(
    schedule_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    s = _get(db, principal, schedule_id, WRITE)
    page = db.get(PageModel, s.page_id)
    if page is None:
        raise not_found("Page")
    started, message, channel = start_page(
        db,
        request.app.state.telephony,
        page,
        trigger="ui",
        actor=f"{principal.label} (test of {s.name})",
    )
    _record(db, ctx, principal, "bell_schedule.ring", s, {"started": started, "message": message})
    db.commit()
    return {"started": started, "message": message, "channel_id": channel}


@router.patch("/{schedule_id}", response_model=ScheduleOut)
def update_schedule(
    schedule_id: uuid.UUID,
    body: SchedulePatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ScheduleOut:
    s = _get(db, principal, schedule_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    _check_refs(db, s.organization_id, changes.get("calendar_id"), changes.get("page_id"))
    details: dict[str, Any] = {}
    for field, value in changes.items():
        if value is not None and value != getattr(s, field):
            setattr(s, field, value)
            details[field] = str(value)
    if not details:
        return _outs(db, [s])[0]
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(
            "A bell schedule with that name exists in this organization.", "name_in_use"
        ) from e
    _record(db, ctx, principal, "bell_schedule.update", s, details)
    db.commit()
    return _outs(db, [s])[0]


@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    s = _get(db, principal, schedule_id, WRITE)
    _record(db, ctx, principal, "bell_schedule.delete", s, {})
    db.delete(s)
    db.commit()
    return Response(status_code=204)
