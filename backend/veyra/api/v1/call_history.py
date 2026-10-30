# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call history (docs/REPORTING.md §3.5-3.6): search, detail, CSV export,
and every user's own calls. Calls of an unknown organization are visible to
platform-scope readers only."""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from veyra.api.v1.me import require_me
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError
from veyra.core.models import (
    CallLeg,
    CallRecord,
    CallRecording,
    Extension,
    Organization,
    SipTrunk,
)
from veyra.core.models.base import utcnow
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.portal import contacts as portal_contacts

router = APIRouter(tags=["call history"])

READ = "calls.history.read"
EXPORT = "calls.history.export"
EXPORT_LIMIT = 100_000
Direction = Literal["internal", "inbound", "outbound"]
Outcome = Literal[
    "answered", "missed", "busy", "failed", "voicemail", "abandoned", "blocked", "denied"
]


class ExtensionRef(BaseModel):
    id: uuid.UUID
    number: str
    display_name: str


class CallOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    organization_name: str | None
    direction: str
    outcome: str
    from_number: str | None
    from_name: str | None
    to_number: str | None
    did: str | None
    from_extension: ExtensionRef | None
    to_extension: ExtensionRef | None
    answered_by: ExtensionRef | None
    trunk_name: str | None
    started_at: datetime
    answered_at: datetime | None
    ended_at: datetime | None
    ring_seconds: int
    talk_seconds: int
    leg_count: int
    recorded: bool
    recording_ref: str | None = None
    in_progress: bool
    # On the user's own history: the other party's name from their contacts.
    contact_name: str | None = None


class LegOut(BaseModel):
    start: datetime
    answer: datetime | None
    end: datetime | None
    channel: str
    dstchannel: str
    src: str
    dst: str
    lastapp: str
    disposition: str
    billsec: int


class CallDetailOut(CallOut):
    legs: list[LegOut]
    # The recording, when one exists and has not been deleted (the caller
    # still needs recordings.read to hear it).
    recording_id: uuid.UUID | None = None


def _outs(db: Session, rows: list[CallRecord]) -> list[CallOut]:
    ext_ids = {
        i
        for r in rows
        for i in (r.from_extension_id, r.to_extension_id, r.answered_extension_id)
        if i
    }
    exts = (
        {e.id: e for e in db.scalars(select(Extension).where(Extension.id.in_(ext_ids)))}
        if ext_ids
        else {}
    )
    org_ids = {r.organization_id for r in rows if r.organization_id}
    orgs = (
        {o.id: o.name for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids)))}
        if org_ids
        else {}
    )
    trunk_ids = {r.trunk_id for r in rows if r.trunk_id}
    trunks = (
        {t.id: t.name for t in db.scalars(select(SipTrunk).where(SipTrunk.id.in_(trunk_ids)))}
        if trunk_ids
        else {}
    )

    def ref(i: uuid.UUID | None) -> ExtensionRef | None:
        e = exts.get(i) if i else None
        return ExtensionRef(id=e.id, number=e.number, display_name=e.display_name) if e else None

    return [
        CallOut(
            id=r.id,
            organization_id=r.organization_id,
            organization_name=orgs.get(r.organization_id) if r.organization_id else None,
            direction=r.direction,
            outcome=r.outcome,
            from_number=r.from_number,
            from_name=r.from_name,
            to_number=r.to_number,
            did=r.did,
            from_extension=ref(r.from_extension_id),
            to_extension=ref(r.to_extension_id),
            answered_by=ref(r.answered_extension_id),
            trunk_name=trunks.get(r.trunk_id) if r.trunk_id else None,
            started_at=r.started_at,
            answered_at=r.answered_at,
            ended_at=r.ended_at,
            ring_seconds=r.ring_seconds,
            talk_seconds=r.talk_seconds,
            leg_count=r.leg_count,
            recorded=bool(r.recording_ref),
            recording_ref=r.recording_ref,
            in_progress=not r.is_final,
        )
        for r in rows
    ]


def _visible(principal: Principal, permission: str) -> Select[Any]:
    stmt = select(CallRecord)
    orgs = principal.organization_ids_with(permission)
    if orgs is not None:
        stmt = stmt.where(CallRecord.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _filtered(
    stmt: Select[Any],
    since: datetime | None,
    until: datetime | None,
    organization_id: uuid.UUID | None,
    direction: str | None,
    outcome: str | None,
    q: str | None,
    extension_id: uuid.UUID | None,
    min_seconds: int | None,
    recorded: bool | None,
) -> Select[Any]:
    if since is None and until is None:
        since = utcnow() - timedelta(days=1)
    if since is not None:
        stmt = stmt.where(CallRecord.started_at >= since)
    if until is not None:
        stmt = stmt.where(CallRecord.started_at < until)
    if organization_id is not None:
        stmt = stmt.where(CallRecord.organization_id == organization_id)
    if direction:
        stmt = stmt.where(CallRecord.direction == direction)
    if outcome:
        stmt = stmt.where(CallRecord.outcome == outcome)
    if q:
        like = f"%{q.strip()}%"
        matching = select(Extension.id).where(
            or_(Extension.number.ilike(like), Extension.display_name.ilike(like))
        )
        stmt = stmt.where(
            or_(
                CallRecord.from_number.ilike(like),
                CallRecord.from_name.ilike(like),
                CallRecord.to_number.ilike(like),
                CallRecord.did.ilike(like),
                CallRecord.answered_extension_id.in_(matching),
                CallRecord.to_extension_id.in_(matching),
                CallRecord.from_extension_id.in_(matching),
            )
        )
    if extension_id is not None:
        stmt = stmt.where(
            or_(
                CallRecord.from_extension_id == extension_id,
                CallRecord.to_extension_id == extension_id,
                CallRecord.answered_extension_id == extension_id,
            )
        )
    if min_seconds:
        stmt = stmt.where(CallRecord.talk_seconds >= min_seconds)
    if recorded is not None:
        stmt = stmt.where(
            CallRecord.recording_ref.is_not(None)
            if recorded
            else CallRecord.recording_ref.is_(None)
        )
    return stmt.order_by(CallRecord.started_at.desc(), CallRecord.id)


@router.get("/calls/history", response_model=Page[CallOut], summary="Search the call history")
def list_history(
    since: datetime | None = Query(None, alias="from"),
    until: datetime | None = Query(None, alias="to"),
    organization_id: uuid.UUID | None = None,
    direction: Direction | None = None,
    outcome: Outcome | None = None,
    q: str | None = Query(None, max_length=100),
    extension_id: uuid.UUID | None = None,
    min_seconds: int | None = Query(None, ge=0),
    recorded: bool | None = None,
    page: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[CallOut]:
    stmt = _filtered(
        _visible(principal, READ),
        since,
        until,
        organization_id,
        direction,
        outcome,
        q,
        extension_id,
        min_seconds,
        recorded,
    )
    rows, total = paginate(db, stmt, page)
    return Page(items=_outs(db, rows), total=total, limit=page.limit, offset=page.offset)


CSV_COLUMNS = (
    "started_at",
    "direction",
    "outcome",
    "from_number",
    "from_name",
    "to_number",
    "did",
    "answered_by",
    "trunk",
    "ring_seconds",
    "talk_seconds",
    "organization",
    "legs",
    "recorded",
    "recording_ref",
)


@router.get("/calls/history/export.csv", summary="Export the call history as CSV")
def export_history(
    since: datetime | None = Query(None, alias="from"),
    until: datetime | None = Query(None, alias="to"),
    organization_id: uuid.UUID | None = None,
    direction: Direction | None = None,
    outcome: Outcome | None = None,
    q: str | None = Query(None, max_length=100),
    extension_id: uuid.UUID | None = None,
    min_seconds: int | None = Query(None, ge=0),
    recorded: bool | None = None,
    principal: Principal = Depends(require(EXPORT)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> StreamingResponse:
    # Export only what the caller may both read and export.
    base = _visible(principal, READ)
    export_orgs = principal.organization_ids_with(EXPORT)
    if export_orgs is not None:
        base = base.where(CallRecord.organization_id.in_(export_orgs or {uuid.UUID(int=0)}))
    stmt = _filtered(
        base,
        since,
        until,
        organization_id,
        direction,
        outcome,
        q,
        extension_id,
        min_seconds,
        recorded,
    ).limit(EXPORT_LIMIT)
    rows = list(db.scalars(stmt))
    outs = _outs(db, rows)
    audit.record(
        db,
        action="calls.history_export",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=organization_id,
        target_type="calls",
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"rows": len(outs)},
    )
    db.commit()

    stamp = utcnow().strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        _csv_lines(outs),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="calls-{stamp}.csv"'},
    )


@router.get(
    "/calls/history/{call_id}", response_model=CallDetailOut, summary="One call with its legs"
)
def get_call(
    call_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> CallDetailOut:
    call = db.scalar(_visible(principal, READ).where(CallRecord.id == call_id))
    if call is None:
        raise ProblemError(404, "Not found", "No such call.", code="not_found")
    legs = db.scalars(
        select(CallLeg).where(CallLeg.call_id == call.id).order_by(CallLeg.start)
    ).all()
    base = _outs(db, [call])[0]
    recording = db.scalar(
        select(CallRecording.id).where(
            CallRecording.call_id == call.id, CallRecording.deleted_at.is_(None)
        )
    )
    return CallDetailOut(
        **base.model_dump(),
        recording_id=recording,
        legs=[
            LegOut(
                start=leg.start,
                answer=leg.answer,
                end=leg.end,
                channel=leg.channel,
                dstchannel=leg.dstchannel,
                src=leg.src,
                dst=leg.dst,
                lastapp=leg.lastapp,
                disposition=leg.disposition,
                billsec=leg.billsec,
            )
            for leg in legs
        ],
    )


def _csv_lines(outs: list[CallOut]) -> Iterator[str]:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for c in outs:
        answered = c.answered_by
        w.writerow(
            [
                c.started_at.isoformat(),
                c.direction,
                c.outcome,
                c.from_number or "",
                c.from_name or "",
                c.to_number or "",
                c.did or "",
                f"{answered.number} {answered.display_name}" if answered else "",
                c.trunk_name or "",
                c.ring_seconds,
                c.talk_seconds,
                c.organization_name or "",
                c.leg_count,
                "yes" if c.recorded else "no",
                c.recording_ref or "",
            ]
        )
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate()


@router.get("/me/calls", response_model=Page[CallOut], summary="Your own calls")
def my_calls(
    since: datetime | None = Query(None, alias="from"),
    until: datetime | None = Query(None, alias="to"),
    outcome: Outcome | None = None,
    page: PageParams = Depends(page_params),
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
) -> Page[CallOut]:
    mine = select(Extension.id).where(Extension.user_id == principal.user_id)
    stmt = select(CallRecord).where(
        or_(
            CallRecord.from_extension_id.in_(mine),
            CallRecord.to_extension_id.in_(mine),
            CallRecord.answered_extension_id.in_(mine),
        )
    )
    if since is None and until is None:
        since = utcnow() - timedelta(days=30)
    stmt = _filtered(stmt, since, until, None, None, outcome, None, None, None, None)
    rows, total = paginate(db, stmt, page)
    outs = _with_contacts(db, principal, _outs(db, rows))
    return Page(items=outs, total=total, limit=page.limit, offset=page.offset)


def _own_calls(principal: Principal) -> Select[Any]:
    mine = select(Extension.id).where(Extension.user_id == principal.user_id)
    return select(CallRecord).where(
        or_(
            CallRecord.from_extension_id.in_(mine),
            CallRecord.to_extension_id.in_(mine),
            CallRecord.answered_extension_id.in_(mine),
        )
    )


def _with_contacts(db: Session, principal: Principal, outs: list[CallOut]) -> list[CallOut]:
    """The other party's name from the user's contacts (docs/USER_PORTAL.md §5)."""
    names = portal_contacts.names_by_number(db, principal.user_id)
    if not names:
        return outs
    for c in outs:
        for number in (c.from_number, c.to_number):
            name = portal_contacts.resolve(names, number)
            if name:
                c.contact_name = name
                break
    return outs


@router.get("/me/calls/export.csv", summary="Your own calls as CSV")
def my_calls_export(
    since: datetime | None = Query(None, alias="from"),
    until: datetime | None = Query(None, alias="to"),
    outcome: Outcome | None = None,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> StreamingResponse:
    if since is None and until is None:
        since = utcnow() - timedelta(days=30)
    stmt = _filtered(
        _own_calls(principal), since, until, None, None, outcome, None, None, None, None
    )
    outs = _with_contacts(db, principal, _outs(db, list(db.scalars(stmt.limit(EXPORT_LIMIT)))))
    audit.record(
        db,
        action="calls.history_export",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=None,
        target_type="calls",
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"rows": len(outs), "self_service": True},
    )
    db.commit()
    stamp = utcnow().strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        _csv_lines(outs),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="my-calls-{stamp}.csv"'},
    )


@router.get("/me/calls/{call_id}/recording", summary="Listen to a recording of your own call")
def my_call_recording(
    call_id: uuid.UUID,
    request: Request,
    download: bool = False,
    principal: Principal = Depends(require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    """Only when the organization allows it (``users_play_own_recordings``,
    docs/USER_PORTAL.md §5) and the user's extension took part; audited like
    the administrator's listening."""
    call = db.scalar(_own_calls(principal).where(CallRecord.id == call_id))
    if call is None:
        raise ProblemError(404, "Not found", "No such call of yours.", code="not_found")
    org = db.get(Organization, call.organization_id) if call.organization_id else None
    if org is None or not org.users_play_own_recordings:
        raise ProblemError(
            403,
            "Not allowed",
            "Your organization does not let users play recordings of their calls.",
            code="recordings_not_allowed",
        )
    rec = db.scalar(
        select(CallRecording).where(
            CallRecording.call_id == call.id, CallRecording.deleted_at.is_(None)
        )
    )
    if rec is None:
        raise ProblemError(404, "Not found", "This call has no recording.", code="not_found")
    from veyra.api.v1.recording import audio_response, recording_audio_bytes

    data = recording_audio_bytes(request, rec)
    rng = request.headers.get("range", "")
    if not rng.startswith("bytes=") or rng.startswith("bytes=0-"):
        audit.record(
            db,
            action="recording.download" if download else "recording.play",
            actor_user_id=principal.user_id,
            actor_label=principal.label,
            organization_id=rec.organization_id,
            target_type="recording",
            target_id=rec.id,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"call_id": str(call.id), "self_service": True},
        )
        db.commit()
    return audio_response(request, data, f"recording-{rec.ref}.ogg" if download else None)
