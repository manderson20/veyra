# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pages (docs/PAGING_RECORDINGS.md §1, §2): a named page over one or more
zones with live or recorded audio, dialable by number, started from the
interface or the API (``send``), logged."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import group_helpers as helpers
from veyra.api.v1.group_helpers import MemberOut
from veyra.configmgmt import service as configmgmt
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import conflict, forbidden, not_found
from veyra.core.events import Event, bus
from veyra.core.models import (
    Organization,
    PageLog,
    PageMember,
    PageZone,
    PagingZone,
    Prompt,
)
from veyra.core.models import (
    Page as PageModel,
)
from veyra.core.models.base import utcnow
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import routing
from veyra.telephony.adapter import Capability, EngineUnavailable, NotSupported
from veyra.telephony.asterisk.generator import CONTEXT_PAGE_PLAY

router = APIRouter(prefix="/pages", tags=["paging"])

READ = "paging.read"
WRITE = "paging.write"
SEND = "paging.send"
Priority = Literal["normal", "priority", "emergency"]
Allowed = Literal["everyone", "members", "administrators"]
MAX_ZONES = 25
MAX_MEMBERS = 64


class PageIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    number: str | None = Field(None, max_length=32)
    zones: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_ZONES)
    audio_id: uuid.UUID | None = None
    pre_tone: bool = True
    repeat: int = Field(1, ge=1, le=5)
    priority: Priority = "normal"
    allowed: Allowed = "everyone"
    members: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_MEMBERS)
    max_seconds: int = Field(120, ge=5, le=600)
    is_enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        routing.slugify(v)
        return v

    @field_validator("number")
    @classmethod
    def _number(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None


class PagePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    number: str | None = Field(None, max_length=32)
    zones: list[uuid.UUID] | None = Field(None, max_length=MAX_ZONES)
    audio_id: uuid.UUID | None = None
    pre_tone: bool | None = None
    repeat: int | None = Field(None, ge=1, le=5)
    priority: Priority | None = None
    allowed: Allowed | None = None
    members: list[uuid.UUID] | None = Field(None, max_length=MAX_MEMBERS)
    max_seconds: int | None = Field(None, ge=5, le=600)
    is_enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return PageIn._name(v) if v is not None else None

    @field_validator("number")
    @classmethod
    def _number(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None


class ZoneRef(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    poly_group: int


class AudioRef(BaseModel):
    id: uuid.UUID
    name: str
    duration_seconds: float


class PageOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    slug: str
    description: str | None
    number: str | None
    zones: list[ZoneRef]
    audio: AudioRef | None
    pre_tone: bool
    repeat: int
    priority: str
    allowed: str
    members: list[MemberOut]
    max_seconds: int
    is_enabled: bool
    last_sent_at: datetime | None
    problems: list[str]
    created_at: datetime
    updated_at: datetime


class SendIn(BaseModel):
    """Overrides for one send (a door controller may name the recording)."""

    audio_id: uuid.UUID | None = None
    zones: list[uuid.UUID] | None = Field(None, max_length=MAX_ZONES)
    repeat: int | None = Field(None, ge=1, le=5)


class SendOut(BaseModel):
    started: bool
    message: str
    channel_id: str | None = None


class PageLogOut(BaseModel):
    id: uuid.UUID
    at: datetime
    page_id: uuid.UUID | None
    page_name: str
    zones: list[str]
    trigger: str
    actor: str | None
    outcome: str
    detail: dict[str, Any]


def _visible(principal: Principal, perm: str) -> Select[PageModel]:
    stmt = select(PageModel)
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(PageModel.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _get(db: Session, principal: Principal, page_id: uuid.UUID, perm: str) -> PageModel:
    page = db.scalar(_visible(principal, perm).where(PageModel.id == page_id))
    if page is None:
        raise not_found("Page")
    return page


def _zones_of(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, list[PagingZone]]:
    out: dict[uuid.UUID, list[PagingZone]] = {i: [] for i in ids}
    if not ids:
        return out
    rows = db.execute(
        select(PageZone.page_id, PagingZone)
        .join(PagingZone, PagingZone.id == PageZone.zone_id)
        .where(PageZone.page_id.in_(ids))
        .order_by(PagingZone.poly_group)
    ).all()
    for page_id, zone in rows:
        out[page_id].append(zone)
    return out


def _members_of(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    out: dict[uuid.UUID, list[uuid.UUID]] = {i: [] for i in ids}
    if ids:
        for m in db.scalars(select(PageMember).where(PageMember.page_id.in_(ids))):
            out[m.page_id].append(m.extension_id)
    return out


def _outs(db: Session, rows: list[PageModel]) -> list[PageOut]:
    if not rows:
        return []
    ids = {r.id for r in rows}
    orgs = helpers.org_names(db, {r.organization_id for r in rows})
    zones = _zones_of(db, ids)
    members = _members_of(db, ids)
    exts = helpers.extensions_by_id(db, {e for ms in members.values() for e in ms})
    audio_ids = {r.audio_id for r in rows if r.audio_id}
    audio = (
        {p.id: p for p in db.scalars(select(Prompt).where(Prompt.id.in_(audio_ids)))}
        if audio_ids
        else {}
    )
    last = dict(
        db.execute(
            select(PageLog.page_id, func.max(PageLog.at))
            .where(PageLog.page_id.in_(ids), PageLog.outcome == "started")
            .group_by(PageLog.page_id)
        ).all()
    )
    out = []
    for r in rows:
        problems = []
        if not zones[r.id]:
            problems.append("No zones: the page reaches nothing.")
        if any(not z.is_enabled for z in zones[r.id]):
            problems.append("A zone of this page is disabled.")
        if r.allowed == "members" and not members[r.id]:
            problems.append("Only members may start this page, and it has none.")
        a = audio.get(r.audio_id) if r.audio_id else None
        if r.audio_id and a is None:
            problems.append("The recording no longer exists.")
        out.append(
            PageOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=orgs.get(r.organization_id, ""),
                name=r.name,
                slug=r.slug,
                description=r.description,
                number=r.number,
                zones=[
                    ZoneRef(id=z.id, name=z.name, slug=z.slug, poly_group=z.poly_group)
                    for z in zones[r.id]
                ],
                audio=AudioRef(id=a.id, name=a.name, duration_seconds=round(a.duration_seconds, 1))
                if a
                else None,
                pre_tone=r.pre_tone,
                repeat=r.repeat,
                priority=r.priority,
                allowed=r.allowed,
                members=sorted(
                    (
                        MemberOut(
                            extension_id=e.id,
                            number=e.number,
                            display_name=e.display_name,
                            is_enabled=e.is_enabled,
                        )
                        for e in (exts.get(i) for i in members[r.id])
                        if e is not None
                    ),
                    key=lambda m: m.number,
                ),
                max_seconds=r.max_seconds,
                is_enabled=r.is_enabled,
                last_sent_at=last.get(r.id),
                problems=problems,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _check_zones(db: Session, org_id: uuid.UUID, ids: list[uuid.UUID]) -> list[PagingZone]:
    if len(set(ids)) != len(ids):
        raise helpers.validation("zones", "a zone is listed twice")
    if not ids:
        return []
    found = {z.id: z for z in db.scalars(select(PagingZone).where(PagingZone.id.in_(ids)))}
    zones = []
    for zid in ids:
        z = found.get(zid)
        if z is None or z.organization_id != org_id:
            raise helpers.validation("zones", "paging zone not found in this organization")
        zones.append(z)
    return zones


def _check_audio(db: Session, org_id: uuid.UUID, audio_id: uuid.UUID | None) -> Prompt | None:
    if audio_id is None:
        return None
    p = db.get(Prompt, audio_id)
    if p is None or p.organization_id != org_id:
        raise helpers.validation("audio_id", "recording not found in this organization")
    return p


def _set_links(
    db: Session, page: PageModel, zones: list[uuid.UUID], members: list[uuid.UUID]
) -> None:
    for old in db.scalars(select(PageZone).where(PageZone.page_id == page.id)):
        db.delete(old)
    for old_m in db.scalars(select(PageMember).where(PageMember.page_id == page.id)):
        db.delete(old_m)
    db.flush()
    for zid in zones:
        db.add(PageZone(page_id=page.id, zone_id=zid))
    for mid in members:
        db.add(PageMember(page_id=page.id, extension_id=mid))
    db.flush()


def _unique_slug(db: Session, org_id: uuid.UUID, name: str) -> str:
    base = routing.slugify(name)[:40]
    slug, n = base, 2
    while (
        db.scalar(
            select(PageModel.id).where(PageModel.organization_id == org_id, PageModel.slug == slug)
        )
        is not None
    ):
        slug = f"{base[: 40 - len(str(n)) - 1]}-{n}"
        n += 1
    return slug


def _record(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    page: PageModel,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=page.organization_id,
        target_type="page",
        target_id=page.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": page.name, **details},
    )
    configmgmt.mark_changed(db, by=principal.label, what=f"{action} {page.name}")


def _conflict(e: IntegrityError, db: Session) -> Exception:
    db.rollback()
    text = str(e.orig).lower() if e.orig else ""
    if "number" in text:
        return conflict("That number is already used.", "number_in_use")
    return conflict("A page with that name exists in this organization.", "name_in_use")


@router.get("", response_model=Page[PageOut], summary="List pages")
def list_pages(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[PageOut]:
    stmt = _visible(principal, READ).order_by(PageModel.name)
    if organization_id:
        stmt = stmt.where(PageModel.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                PageModel.name.ilike(like),
                PageModel.description.ilike(like),
                PageModel.number.ilike(like),
            )
        )
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.get("/log", response_model=Page[PageLogOut], summary="Pages sent (log)")
def page_log(
    organization_id: uuid.UUID | None = None,
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[PageLogOut]:
    stmt = select(PageLog).order_by(PageLog.at.desc())
    orgs = principal.organization_ids_with(READ)
    if orgs is not None:
        stmt = stmt.where(PageLog.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    if organization_id:
        stmt = stmt.where(PageLog.organization_id == organization_id)
    rows, total = paginate(db, stmt, params)
    return Page(
        items=[
            PageLogOut(
                id=r.id,
                at=r.at,
                page_id=r.page_id,
                page_name=r.page_name,
                zones=list(r.zones),
                trigger=r.trigger,
                actor=r.actor,
                outcome=r.outcome,
                detail=dict(r.detail),
            )
            for r in rows
        ],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.post("", response_model=PageOut, status_code=201, summary="Create a page")
def create_page(
    body: PageIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PageOut:
    if not principal.has(WRITE, body.organization_id):
        raise forbidden()
    org = db.get(Organization, body.organization_id)
    if org is None:
        raise not_found("Organization")
    _check_zones(db, org.id, body.zones)
    _check_audio(db, org.id, body.audio_id)
    helpers.load_members(db, org.id, body.members, "members")
    if body.number:
        helpers.check_number(db, body.number, "page", None)
    page = PageModel(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=body.name,
        slug=_unique_slug(db, org.id, body.name),
        description=(body.description or "").strip() or None,
        number=body.number,
        audio_id=body.audio_id,
        pre_tone=body.pre_tone,
        repeat=body.repeat,
        priority=body.priority,
        allowed=body.allowed,
        max_seconds=body.max_seconds,
        is_enabled=body.is_enabled,
    )
    db.add(page)
    try:
        db.flush()
    except IntegrityError as e:
        raise _conflict(e, db) from e
    _set_links(db, page, body.zones, body.members)
    _record(
        db, ctx, principal, "page.create", page, {"number": page.number, "zones": len(body.zones)}
    )
    db.commit()
    bus.publish(Event("page.created", {"id": str(page.id)}))
    return _outs(db, [page])[0]


@router.get("/{page_id}", response_model=PageOut)
def get_page(
    page_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> PageOut:
    return _outs(db, [_get(db, principal, page_id, READ)])[0]


@router.patch("/{page_id}", response_model=PageOut)
def update_page(
    page_id: uuid.UUID,
    body: PagePatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PageOut:
    page = _get(db, principal, page_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    details: dict[str, Any] = {}
    if "number" in changes and changes["number"] != page.number:
        if changes["number"]:
            helpers.check_number(db, changes["number"], "page", page.id)
        details["number"] = {"from": page.number, "to": changes["number"]}
        page.number = changes["number"]
    if "audio_id" in changes and changes["audio_id"] != page.audio_id:
        _check_audio(db, page.organization_id, changes["audio_id"])
        page.audio_id = changes["audio_id"]
        details["audio_id"] = str(changes["audio_id"]) if changes["audio_id"] else None
    if "description" in changes:
        changes["description"] = (changes["description"] or "").strip() or None
    for field in (
        "name",
        "description",
        "pre_tone",
        "repeat",
        "priority",
        "allowed",
        "max_seconds",
        "is_enabled",
    ):
        if (
            field in changes
            and changes[field] is not None
            and changes[field] != getattr(page, field)
        ):
            setattr(page, field, changes[field])
            details[field] = changes[field]
        elif field == "description" and field in changes and changes[field] != page.description:
            page.description = changes[field]
            details[field] = True
    zones = list(changes["zones"]) if changes.get("zones") is not None else None
    members = list(changes["members"]) if changes.get("members") is not None else None
    if zones is not None or members is not None:
        current_zones = [z.id for z in _zones_of(db, {page.id})[page.id]]
        current_members = _members_of(db, {page.id})[page.id]
        zones = current_zones if zones is None else zones
        members = current_members if members is None else members
        _check_zones(db, page.organization_id, zones)
        helpers.load_members(db, page.organization_id, members, "members")
        if sorted(map(str, zones)) != sorted(map(str, current_zones)) or sorted(
            map(str, members)
        ) != sorted(map(str, current_members)):
            _set_links(db, page, zones, members)
            details["zones"] = len(zones)
            details["members"] = len(members)
    if not details:
        return _outs(db, [page])[0]
    try:
        db.flush()
    except IntegrityError as e:
        raise _conflict(e, db) from e
    _record(db, ctx, principal, "page.update", page, details)
    db.commit()
    bus.publish(Event("page.updated", {"id": str(page.id)}))
    return _outs(db, [page])[0]


@router.delete("/{page_id}", status_code=204)
def delete_page(
    page_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    page = _get(db, principal, page_id, WRITE)
    _record(db, ctx, principal, "page.delete", page, {"slug": page.slug})
    db.delete(page)
    db.commit()
    bus.publish(Event("page.deleted", {"id": str(page_id)}))
    return Response(status_code=204)


def start_page(
    db: Session,
    adapter: Any,
    page: PageModel,
    *,
    trigger: str,
    actor: str | None,
    audio: Prompt | None = None,
    zones: list[PagingZone] | None = None,
) -> tuple[bool, str, str | None]:
    """Originate the play leg of a recorded page (docs/PAGING_RECORDINGS.md
    §2.5) and log the attempt. Returns ``(started, message, channel id)``."""
    zone_rows = zones if zones is not None else _zones_of(db, {page.id})[page.id]
    recording = audio or (db.get(Prompt, page.audio_id) if page.audio_id else None)
    log = PageLog(
        id=uuid.uuid4(),
        at=utcnow(),
        organization_id=page.organization_id,
        page_id=page.id,
        page_name=page.name,
        zones=[z.slug for z in zone_rows],
        trigger=trigger,
        actor=actor,
        outcome="failed",
        detail={},
    )
    db.add(log)
    if recording is None:
        log.detail = {"reason": "no_recording"}
        db.commit()
        return False, "This page plays live audio; dial its number from a phone to page.", None
    if not zone_rows:
        log.detail = {"reason": "no_zones"}
        db.commit()
        return False, "The page has no zones.", None
    if not page.is_enabled:
        log.detail = {"reason": "disabled"}
        db.commit()
        return False, "The page is disabled.", None
    try:
        if Capability.CLICK_TO_DIAL not in adapter.capabilities():
            raise NotSupported("the engine cannot originate calls")
        channel = adapter.originate(
            f"play-{page.slug}@{CONTEXT_PAGE_PLAY}",
            page.slug,
            caller_id="Veyra page",
            context=CONTEXT_PAGE_PLAY,
            timeout=15,
        )
    except (EngineUnavailable, NotSupported) as e:
        log.detail = {"reason": "engine", "message": str(e)}
        db.commit()
        return False, f"The telephony engine could not start the page: {e}", None
    log.outcome = "started"
    log.detail = {"channel": channel, "audio": recording.slug}
    db.commit()
    return True, f"Page “{page.name}” started.", channel


@router.post("/{page_id}/send", response_model=SendOut, summary="Start a recorded page now")
def send_page(
    page_id: uuid.UUID,
    body: SendIn,
    request: Request,
    principal: Principal = Depends(require(SEND)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> SendOut:
    page = _get(db, principal, page_id, SEND)
    audio = _check_audio(db, page.organization_id, body.audio_id) if body.audio_id else None
    zones = _check_zones(db, page.organization_id, body.zones) if body.zones else None
    started, message, channel = start_page(
        db,
        request.app.state.telephony,
        page,
        trigger="api" if getattr(principal, "token_scopes", None) else "ui",
        actor=principal.label,
        audio=audio,
        zones=zones,
    )
    audit.record(
        db,
        action="page.send",
        outcome="success" if started else "failure",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=page.organization_id,
        target_type="page",
        target_id=page.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": page.name, "started": started, "message": message},
    )
    db.commit()
    return SendOut(started=started, message=message, channel_id=channel)


def prune_log(db: Session, days: int = 90) -> int:
    from sqlalchemy import delete

    cutoff = utcnow() - timedelta(days=days)
    result = db.execute(delete(PageLog).where(PageLog.at < cutoff))
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)
