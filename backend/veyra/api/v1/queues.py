# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call queues (docs/RING_GROUPS_QUEUES.md §3): a number that holds callers
with music and announcements and distributes them to agents."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import destinations
from veyra.api.v1 import group_helpers as helpers
from veyra.api.v1.destinations import DestinationIn, DestinationOut, Resolver, check_destination
from veyra.api.v1.group_helpers import READ, WRITE, MemberOut
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import conflict, not_found
from veyra.core.events import Event, bus
from veyra.core.models import CallQueue, Prompt, QueueMember
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import routing

router = APIRouter(prefix="/queues", tags=["queues"])

Strategy = Literal["ringall", "rrmemory", "leastrecent", "fewestcalls", "random", "linear"]
Music = Literal["default", "ring"]
MAX_MEMBERS = 64


# ----------------------------------------------------------------- schemas


class AgentIn(BaseModel):
    extension_id: uuid.UUID
    penalty: int = Field(0, ge=0, le=9)


class QueueIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    number: str = Field(min_length=1, max_length=32)
    description: str | None = Field(None, max_length=2000)
    strategy: Strategy = "ringall"
    member_timeout: int = Field(15, ge=5, le=60)
    retry_seconds: int = Field(5, ge=1, le=30)
    wrapup_seconds: int = Field(0, ge=0, le=600)
    max_wait_seconds: int = Field(300, ge=0, le=3600)
    max_callers: int = Field(0, ge=0, le=100)
    join_when_empty: bool = False
    announce_position: bool = False
    announce_frequency: int = Field(60, ge=15, le=600)
    announcement_prompt_id: uuid.UUID | None = None
    periodic_prompt_id: uuid.UUID | None = None
    periodic_seconds: int = Field(60, ge=15, le=600)
    music: Music = "default"
    failover: DestinationIn = Field(default_factory=lambda: DestinationIn(type="hangup"))
    members: list[AgentIn] = Field(default_factory=list, max_length=MAX_MEMBERS)
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
    def _number(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit():
            raise ValueError("digits only")
        return v

    @field_validator("max_wait_seconds")
    @classmethod
    def _wait(cls, v: int) -> int:
        if 0 < v < 30:
            raise ValueError("0 (unlimited) or at least 30 seconds")
        return v


class QueuePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    number: str | None = Field(None, min_length=1, max_length=32)
    description: str | None = Field(None, max_length=2000)
    strategy: Strategy | None = None
    member_timeout: int | None = Field(None, ge=5, le=60)
    retry_seconds: int | None = Field(None, ge=1, le=30)
    wrapup_seconds: int | None = Field(None, ge=0, le=600)
    max_wait_seconds: int | None = Field(None, ge=0, le=3600)
    max_callers: int | None = Field(None, ge=0, le=100)
    join_when_empty: bool | None = None
    announce_position: bool | None = None
    announce_frequency: int | None = Field(None, ge=15, le=600)
    announcement_prompt_id: uuid.UUID | None = None
    periodic_prompt_id: uuid.UUID | None = None
    periodic_seconds: int | None = Field(None, ge=15, le=600)
    music: Music | None = None
    failover: DestinationIn | None = None
    members: list[AgentIn] | None = Field(None, max_length=MAX_MEMBERS)
    is_enabled: bool | None = None


class QueueOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    slug: str
    queue_name: str
    context: str
    number: str
    description: str | None
    strategy: str
    member_timeout: int
    retry_seconds: int
    wrapup_seconds: int
    max_wait_seconds: int
    max_callers: int
    join_when_empty: bool
    announce_position: bool
    announce_frequency: int
    announcement_prompt_id: uuid.UUID | None
    announcement_prompt_name: str | None
    periodic_prompt_id: uuid.UUID | None
    periodic_prompt_name: str | None
    periodic_seconds: int
    music: str
    failover: DestinationOut
    members: list[MemberOut]
    is_enabled: bool
    problems: list[str]
    in_use_by: int
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------- helpers


def _members(db: Session, queue_ids: set[uuid.UUID]) -> dict[uuid.UUID, list[QueueMember]]:
    out: dict[uuid.UUID, list[QueueMember]] = {q: [] for q in queue_ids}
    if queue_ids:
        for m in db.scalars(select(QueueMember).where(QueueMember.queue_id.in_(queue_ids))):
            out[m.queue_id].append(m)
    return out


def _outs(db: Session, rows: list[CallQueue]) -> list[QueueOut]:
    if not rows:
        return []
    orgs = helpers.org_names(db, {r.organization_id for r in rows})
    members = _members(db, {r.id for r in rows})
    exts = helpers.extensions_by_id(
        db, {m.extension_id for rows_ in members.values() for m in rows_}
    )
    prompt_ids = {r.announcement_prompt_id for r in rows} | {r.periodic_prompt_id for r in rows}
    prompt_ids.discard(None)
    prompts = (
        {p.id: p for p in db.scalars(select(Prompt).where(Prompt.id.in_(prompt_ids)))}
        if prompt_ids
        else {}
    )
    uses = destinations.count_uses(db, "queue", {r.id for r in rows})
    resolver = Resolver(db)
    resolver.load([destinations.ref_of(r, "failover") for r in rows])
    out = []
    for r in rows:
        failover = resolver.out_ref(destinations.ref_of(r, "failover"))
        member_outs = []
        for m in sorted(members[r.id], key=lambda m: m.penalty):
            ext = exts.get(m.extension_id)
            if ext is None:
                continue
            member_outs.append(
                MemberOut(
                    extension_id=ext.id,
                    number=ext.number,
                    display_name=ext.display_name,
                    is_enabled=ext.is_enabled,
                    penalty=m.penalty,
                )
            )
        member_outs.sort(key=lambda mo: (mo.penalty or 0, mo.number))
        problems = []
        if not member_outs:
            problems.append("The queue has no agents: callers go straight to the failover.")
        for mo in member_outs:
            if not mo.is_enabled:
                problems.append(f"Agent {mo.number} is disabled and will not be called.")
        if failover.missing:
            problems.append("The failover destination no longer exists.")
        ann = prompts.get(r.announcement_prompt_id) if r.announcement_prompt_id else None
        per = prompts.get(r.periodic_prompt_id) if r.periodic_prompt_id else None
        out.append(
            QueueOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=orgs.get(r.organization_id, ""),
                name=r.name,
                slug=r.slug,
                queue_name=f"veyra-{r.slug}",
                context=f"veyra-queue-{r.slug}",
                number=r.number,
                description=r.description,
                strategy=r.strategy,
                member_timeout=r.member_timeout,
                retry_seconds=r.retry_seconds,
                wrapup_seconds=r.wrapup_seconds,
                max_wait_seconds=r.max_wait_seconds,
                max_callers=r.max_callers,
                join_when_empty=r.join_when_empty,
                announce_position=r.announce_position,
                announce_frequency=r.announce_frequency,
                announcement_prompt_id=r.announcement_prompt_id,
                announcement_prompt_name=ann.name if ann else None,
                periodic_prompt_id=r.periodic_prompt_id,
                periodic_prompt_name=per.name if per else None,
                periodic_seconds=r.periodic_seconds,
                music=r.music,
                failover=failover,
                members=member_outs,
                is_enabled=r.is_enabled,
                problems=problems,
                in_use_by=uses.get(r.id, 0),
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _get(db: Session, principal: Principal, queue_id: uuid.UUID, perm: str) -> CallQueue:
    stmt = helpers.org_filter(select(CallQueue), CallQueue.organization_id, principal, perm)
    queue = db.scalar(stmt.where(CallQueue.id == queue_id))
    if queue is None:
        raise not_found("Queue")
    return queue


def _set_members(db: Session, queue: CallQueue, agents: list[AgentIn]) -> None:
    for old in db.scalars(select(QueueMember).where(QueueMember.queue_id == queue.id)):
        db.delete(old)
    db.flush()
    for a in agents:
        db.add(QueueMember(queue_id=queue.id, extension_id=a.extension_id, penalty=a.penalty))
    db.flush()


def _check_prompt(db: Session, org_id: uuid.UUID, prompt_id: uuid.UUID | None, field: str) -> None:
    if prompt_id is None:
        return
    p = db.get(Prompt, prompt_id)
    if p is None or p.organization_id != org_id:
        raise helpers.validation(field, "prompt not found in this organization")


def _check(db: Session, org_id: uuid.UUID, body: QueueIn, self_id: uuid.UUID | None) -> None:
    helpers.check_number(db, body.number, "queue", self_id)
    helpers.load_members(db, org_id, [a.extension_id for a in body.members], "members")
    _check_prompt(db, org_id, body.announcement_prompt_id, "announcement_prompt_id")
    _check_prompt(db, org_id, body.periodic_prompt_id, "periodic_prompt_id")
    check_destination(
        db, org_id, body.failover, field="failover", allow_hangup=True, exclude_queue=self_id
    )


def _name_conflict(e: IntegrityError, db: Session) -> Exception:
    db.rollback()
    return conflict("A queue with that name exists in this organization.", "name_in_use")


_FIELDS = (
    "number",
    "strategy",
    "member_timeout",
    "retry_seconds",
    "wrapup_seconds",
    "max_wait_seconds",
    "max_callers",
    "join_when_empty",
    "announce_position",
    "announce_frequency",
    "announcement_prompt_id",
    "periodic_prompt_id",
    "periodic_seconds",
    "music",
    "is_enabled",
)


# ----------------------------------------------------------------- routes


@router.get("", response_model=Page[QueueOut], summary="List call queues")
def list_queues(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[QueueOut]:
    stmt = helpers.org_filter(
        select(CallQueue), CallQueue.organization_id, principal, READ
    ).order_by(CallQueue.number)
    if organization_id:
        stmt = stmt.where(CallQueue.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                CallQueue.name.ilike(like),
                CallQueue.number.ilike(like),
                CallQueue.description.ilike(like),
            )
        )
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post("", response_model=QueueOut, status_code=201, summary="Create a call queue")
def create_queue(
    body: QueueIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> QueueOut:
    org = helpers.org_for_write(db, principal, body.organization_id)
    _check(db, org.id, body, None)
    queue = CallQueue(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=body.name,
        slug=helpers.unique_slug(db, CallQueue, body.name),
        description=(body.description or "").strip() or None,
        **{f: getattr(body, f) for f in _FIELDS},
    )
    destinations.apply(queue, "failover", body.failover)
    db.add(queue)
    try:
        db.flush()
    except IntegrityError as e:
        raise _name_conflict(e, db) from e
    _set_members(db, queue, body.members)
    helpers.record(
        db,
        ctx,
        principal,
        "queue.create",
        target_type="queue",
        target=queue,
        details={"number": queue.number, "slug": queue.slug, "agents": len(body.members)},
    )
    db.commit()
    bus.publish(Event("queue.created", {"id": str(queue.id), "number": queue.number}))
    return _outs(db, [queue])[0]


@router.get("/{queue_id}", response_model=QueueOut)
def get_queue(
    queue_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> QueueOut:
    return _outs(db, [_get(db, principal, queue_id, READ)])[0]


@router.patch("/{queue_id}", response_model=QueueOut)
def update_queue(
    queue_id: uuid.UUID,
    body: QueuePatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> QueueOut:
    queue = _get(db, principal, queue_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    current_members = sorted(
        (
            {"extension_id": m.extension_id, "penalty": m.penalty}
            for m in _members(db, {queue.id})[queue.id]
        ),
        key=lambda m: str(m["extension_id"]),
    )
    current = {
        "organization_id": queue.organization_id,
        "name": queue.name,
        "description": queue.description,
        "failover": destinations.as_input(destinations.ref_of(queue, "failover")),
        "members": current_members,
        **{f: getattr(queue, f) for f in _FIELDS},
    }
    try:
        validated = QueueIn.model_validate({**current, **changes})
    except ValueError as e:
        raise helpers.validation("queue", str(e).splitlines()[0]) from e
    _check(db, queue.organization_id, validated, queue.id)
    details: dict[str, Any] = {}
    if validated.name != queue.name:
        details["name"] = {"from": queue.name, "to": validated.name}
        queue.name = validated.name
    desc = (validated.description or "").strip() or None
    if desc != queue.description:
        queue.description = desc
        details["description"] = True
    for field in _FIELDS:
        value = getattr(validated, field)
        if value != getattr(queue, field):
            setattr(queue, field, value)
            details[field] = str(value) if value is not None else None
    if destinations.ref_of(queue, "failover") != validated.failover.as_ref():
        destinations.apply(queue, "failover", validated.failover)
        details["failover"] = validated.failover.model_dump(mode="json")
    if "members" in changes:
        wanted = sorted(
            (a.model_dump() for a in validated.members), key=lambda m: str(m["extension_id"])
        )
        if wanted != current_members:
            _set_members(db, queue, validated.members)
            details["agents"] = len(validated.members)
    if not details:
        return _outs(db, [queue])[0]
    try:
        db.flush()
    except IntegrityError as e:
        raise _name_conflict(e, db) from e
    helpers.record(
        db, ctx, principal, "queue.update", target_type="queue", target=queue, details=details
    )
    db.commit()
    bus.publish(Event("queue.updated", {"id": str(queue.id)}))
    return _outs(db, [queue])[0]


@router.delete("/{queue_id}", status_code=204)
def delete_queue(
    queue_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    queue = _get(db, principal, queue_id, WRITE)
    what = destinations.describe_uses(db, "queue", queue.id, exclude_self=queue.id)
    if what:
        raise destinations.in_use_error("Queue in use", "queue_in_use", what)
    helpers.record(
        db,
        ctx,
        principal,
        "queue.delete",
        target_type="queue",
        target=queue,
        details={"number": queue.number, "slug": queue.slug},
    )
    for m in db.scalars(select(QueueMember).where(QueueMember.queue_id == queue.id)):
        db.delete(m)
    db.flush()
    db.delete(queue)
    db.commit()
    bus.publish(Event("queue.deleted", {"id": str(queue_id)}))
    return Response(status_code=204)
