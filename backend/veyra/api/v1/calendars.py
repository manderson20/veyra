# SPDX-License-Identifier: AGPL-3.0-or-later
"""Calendar subscriptions (docs/PAGING_RECORDINGS.md §4.1): an iCal feed polled
by the worker; the address is a secret for Google calendars and is stored
encrypted and never shown again."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import group_helpers as helpers
from veyra.api.v1.extensions import installation_key
from veyra.bells import calendars
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import conflict, forbidden, not_found
from veyra.core.models import BellSchedule, Calendar, CalendarEvent, Organization
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.crypto import try_load_installation_key
from veyra.core.security.principal import Principal

router = APIRouter(prefix="/calendars", tags=["bells"])

READ = "bells.read"
WRITE = "bells.write"


def _tz(v: str | None) -> str | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError("enter an IANA time zone such as America/Chicago") from e
    return v


class CalendarIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=8, max_length=2000)
    poll_minutes: int = Field(3, ge=1, le=60)
    timezone: str | None = Field(None, max_length=64)
    is_enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        try:
            return calendars.check_url(v)
        except calendars.CalendarError as e:
            raise ValueError(str(e)) from e

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, v: str | None) -> str | None:
        return _tz(v)


class CalendarPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    url: str | None = Field(None, min_length=8, max_length=2000)
    poll_minutes: int | None = Field(None, ge=1, le=60)
    timezone: str | None = Field(None, max_length=64)
    is_enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return CalendarIn._name(v) if v is not None else None

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return CalendarIn._url(v) if v is not None else None

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, v: str | None) -> str | None:
        return _tz(v)


class CalendarOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    kind: str
    url_display: str
    poll_minutes: int
    timezone: str | None
    is_enabled: bool
    last_polled_at: datetime | None
    last_status: str | None
    last_error: str | None
    event_count: int
    schedules: int
    created_at: datetime
    updated_at: datetime


class EventOut(BaseModel):
    uid: str
    summary: str
    starts_at: datetime
    ends_at: datetime | None
    all_day: bool


def _visible(principal: Principal, perm: str) -> Select[Calendar]:
    stmt = select(Calendar)
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(Calendar.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _get(db: Session, principal: Principal, calendar_id: uuid.UUID, perm: str) -> Calendar:
    cal = db.scalar(_visible(principal, perm).where(Calendar.id == calendar_id))
    if cal is None:
        raise not_found("Calendar")
    return cal


def _outs(db: Session, rows: list[Calendar]) -> list[CalendarOut]:
    if not rows:
        return []
    orgs = helpers.org_names(db, {r.organization_id for r in rows})
    counts = dict(
        db.execute(
            select(BellSchedule.calendar_id, func.count(BellSchedule.id))
            .where(BellSchedule.calendar_id.in_({r.id for r in rows}))
            .group_by(BellSchedule.calendar_id)
        ).all()
    )
    return [
        CalendarOut(
            id=r.id,
            organization_id=r.organization_id,
            organization_name=orgs.get(r.organization_id, ""),
            name=r.name,
            kind=r.kind,
            url_display=r.url_display,
            poll_minutes=r.poll_minutes,
            timezone=r.timezone,
            is_enabled=r.is_enabled,
            last_polled_at=r.last_polled_at,
            last_status=r.last_status,
            last_error=r.last_error,
            event_count=r.event_count,
            schedules=int(counts.get(r.id, 0)),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


def _record(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    cal: Calendar,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=cal.organization_id,
        target_type="calendar",
        target_id=cal.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": cal.name, **details},
    )


@router.get("", response_model=Page[CalendarOut], summary="List calendars")
def list_calendars(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[CalendarOut]:
    stmt = _visible(principal, READ).order_by(Calendar.name)
    if organization_id:
        stmt = stmt.where(Calendar.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Calendar.name.ilike(like), Calendar.url_display.ilike(like)))
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post("", response_model=CalendarOut, status_code=201, summary="Subscribe to a calendar")
def create_calendar(
    body: CalendarIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> CalendarOut:
    if not principal.has(WRITE, body.organization_id):
        raise forbidden()
    org = db.get(Organization, body.organization_id)
    if org is None:
        raise not_found("Organization")
    key = installation_key(request)
    cal = Calendar(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=body.name,
        kind="ical",
        url_ciphertext="",
        url_display=calendars.display_url(body.url),
        poll_minutes=body.poll_minutes,
        timezone=body.timezone,
        is_enabled=body.is_enabled,
    )
    cal.url_ciphertext = key.encrypt(body.url, calendars.url_purpose(cal.id))
    db.add(cal)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(
            "A calendar with that name exists in this organization.", "name_in_use"
        ) from e
    _record(db, ctx, principal, "calendar.create", cal, {"url": cal.url_display})
    db.commit()
    return _outs(db, [cal])[0]


@router.get("/{calendar_id}", response_model=CalendarOut)
def get_calendar(
    calendar_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> CalendarOut:
    return _outs(db, [_get(db, principal, calendar_id, READ)])[0]


@router.get(
    "/{calendar_id}/events", response_model=list[EventOut], summary="Cached upcoming events"
)
def calendar_events(
    calendar_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> list[EventOut]:
    cal = _get(db, principal, calendar_id, READ)
    rows = db.scalars(
        select(CalendarEvent)
        .where(CalendarEvent.calendar_id == cal.id)
        .order_by(CalendarEvent.starts_at)
        .limit(500)
    ).all()
    return [
        EventOut(
            uid=r.uid,
            summary=r.summary,
            starts_at=r.starts_at,
            ends_at=r.ends_at,
            all_day=r.all_day,
        )
        for r in rows
    ]


@router.post("/{calendar_id}/poll", response_model=CalendarOut, summary="Fetch the calendar now")
def poll_calendar(
    calendar_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> CalendarOut:
    cal = _get(db, principal, calendar_id, WRITE)
    n = calendars.poll(db, cal, try_load_installation_key(request.app.state.settings))
    _record(db, ctx, principal, "calendar.poll", cal, {"events": n, "status": cal.last_status})
    db.commit()
    return _outs(db, [cal])[0]


@router.patch("/{calendar_id}", response_model=CalendarOut)
def update_calendar(
    calendar_id: uuid.UUID,
    body: CalendarPatch,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> CalendarOut:
    cal = _get(db, principal, calendar_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    details: dict[str, Any] = {}
    if changes.get("url"):
        key = installation_key(request)
        cal.url_ciphertext = key.encrypt(changes["url"], calendars.url_purpose(cal.id))
        cal.url_display = calendars.display_url(changes["url"])
        cal.last_polled_at = None  # poll again at once
        details["url"] = cal.url_display
    for field in ("name", "poll_minutes", "timezone", "is_enabled"):
        present = field in changes and (changes[field] is not None or field == "timezone")
        if present and changes[field] != getattr(cal, field):
            setattr(cal, field, changes[field])
            details[field] = changes[field]
    if not details:
        return _outs(db, [cal])[0]
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(
            "A calendar with that name exists in this organization.", "name_in_use"
        ) from e
    _record(db, ctx, principal, "calendar.update", cal, details)
    db.commit()
    return _outs(db, [cal])[0]


@router.delete("/{calendar_id}", status_code=204)
def delete_calendar(
    calendar_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    cal = _get(db, principal, calendar_id, WRITE)
    _record(db, ctx, principal, "calendar.delete", cal, {})
    db.delete(cal)  # schedules and events cascade
    db.commit()
    return Response(status_code=204)
