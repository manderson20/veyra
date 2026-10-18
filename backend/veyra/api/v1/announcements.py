# SPDX-License-Identifier: AGPL-3.0-or-later
"""Announcements (docs/CALL_FEATURES.md §4.1): play a prompt, then send the
call on to a destination. One organization per announcement; the slug names
the dialplan context and is stable."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import destinations
from veyra.api.v1.destinations import DestinationIn, DestinationOut, Resolver, check_destination
from veyra.api.v1.group_helpers import unique_slug
from veyra.configmgmt import service as configmgmt
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.events import Event, bus
from veyra.core.models import Announcement, Organization, Prompt
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import routing

router = APIRouter(prefix="/announcements", tags=["announcements"])

READ = "ivr.read"
WRITE = "ivr.write"


def _validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


# ----------------------------------------------------------------- schemas


class AnnouncementIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    prompt_id: uuid.UUID | None = None
    # Any key ends the prompt early.
    allow_skip: bool = False
    # This key replays the prompt (0-9, * or #); none: no repeat.
    repeat_key: str | None = Field(None, max_length=1)
    destination: DestinationIn = Field(default_factory=lambda: DestinationIn(type="hangup"))
    is_enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        routing.slugify(v)
        return v

    @field_validator("repeat_key")
    @classmethod
    def _repeat(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if v not in routing.IVR_DIGITS:
            raise ValueError("a key 0-9, * or #")
        return v


class AnnouncementPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    prompt_id: uuid.UUID | None = None
    allow_skip: bool | None = None
    repeat_key: str | None = Field(None, max_length=1)
    destination: DestinationIn | None = None
    is_enabled: bool | None = None


class AnnouncementOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    slug: str
    context: str
    description: str | None
    prompt_id: uuid.UUID | None
    prompt_name: str | None
    allow_skip: bool
    repeat_key: str | None
    destination: DestinationOut
    is_enabled: bool
    # Why the announcement will not work as configured.
    problems: list[str]
    # Routes, menus, groups and other announcements that point at it.
    in_use_by: int
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------- helpers


def _org_filter(stmt: Select[Any], column: Any, principal: Principal, perm: str) -> Select[Any]:
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(column.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _org_for_write(db: Session, principal: Principal, organization_id: uuid.UUID) -> Organization:
    if not principal.has(WRITE, organization_id):
        raise forbidden()
    org = db.get(Organization, organization_id)
    if org is None:
        raise not_found("Organization")
    if not org.is_active:
        raise conflict("This organization is inactive.", "organization_inactive")
    return org


def _outs(db: Session, rows: list[Announcement]) -> list[AnnouncementOut]:
    if not rows:
        return []
    org_ids = {r.organization_id for r in rows}
    orgs = {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids)))}
    prompt_ids = {r.prompt_id for r in rows if r.prompt_id}
    prompts = (
        {p.id: p for p in db.scalars(select(Prompt).where(Prompt.id.in_(prompt_ids)))}
        if prompt_ids
        else {}
    )
    uses = destinations.count_uses(db, "announcement", {r.id for r in rows})
    resolver = Resolver(db)
    resolver.load([destinations.ref_of(r, "destination") for r in rows])
    out = []
    for r in rows:
        org = orgs.get(r.organization_id)
        prompt = prompts.get(r.prompt_id) if r.prompt_id else None
        dest = resolver.out_ref(destinations.ref_of(r, "destination"))
        problems = []
        if prompt is None:
            problems.append(
                "No prompt: the announcement answers with congestion until one is chosen."
            )
        if dest.missing:
            problems.append("The destination no longer exists.")
        out.append(
            AnnouncementOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=org.name if org else "",
                name=r.name,
                slug=r.slug,
                context=f"veyra-ann-{r.slug}",
                description=r.description,
                prompt_id=r.prompt_id,
                prompt_name=prompt.name if prompt else None,
                allow_skip=r.allow_skip,
                repeat_key=r.repeat_key,
                destination=dest,
                is_enabled=r.is_enabled,
                problems=problems,
                in_use_by=uses.get(r.id, 0),
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _get(db: Session, principal: Principal, announcement_id: uuid.UUID, perm: str) -> Announcement:
    stmt = _org_filter(select(Announcement), Announcement.organization_id, principal, perm)
    row = db.scalar(stmt.where(Announcement.id == announcement_id))
    if row is None:
        raise not_found("Announcement")
    return row


def _check_all(
    db: Session, org_id: uuid.UUID, body: AnnouncementIn, self_id: uuid.UUID | None = None
) -> None:
    if body.prompt_id is not None:
        p = db.get(Prompt, body.prompt_id)
        if p is None or p.organization_id != org_id:
            raise _validation("prompt_id", "prompt not found in this organization")
    check_destination(
        db,
        org_id,
        body.destination,
        field="destination",
        allow_hangup=True,
        exclude_announcement=self_id,
    )


def _audit(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    row: Announcement,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=row.organization_id,
        target_type="announcement",
        target_id=row.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": row.name, **details},
    )
    configmgmt.mark_changed(db, by=principal.label, what=f"{action} {row.name}")


def _name_conflict(e: IntegrityError) -> ProblemError:
    return conflict("An announcement with that name exists in this organization.", "name_in_use")


# ----------------------------------------------------------------- routes


@router.get("", response_model=Page[AnnouncementOut], summary="List announcements")
def list_announcements(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[AnnouncementOut]:
    stmt = _org_filter(
        select(Announcement), Announcement.organization_id, principal, READ
    ).order_by(Announcement.name)
    if organization_id:
        stmt = stmt.where(Announcement.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Announcement.name.ilike(like), Announcement.description.ilike(like)))
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post("", response_model=AnnouncementOut, status_code=201, summary="Create an announcement")
def create_announcement(
    body: AnnouncementIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> AnnouncementOut:
    org = _org_for_write(db, principal, body.organization_id)
    _check_all(db, org.id, body)
    row = Announcement(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=body.name,
        slug=unique_slug(db, Announcement, body.name),
        description=(body.description or "").strip() or None,
        prompt_id=body.prompt_id,
        allow_skip=body.allow_skip,
        repeat_key=body.repeat_key,
        is_enabled=body.is_enabled,
    )
    destinations.apply(row, "destination", body.destination)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise _name_conflict(e) from e
    _audit(db, ctx, principal, "announcement.create", row, {"slug": row.slug})
    db.commit()
    bus.publish(Event("announcement.created", {"id": str(row.id), "name": row.name}))
    return _outs(db, [row])[0]


@router.get("/{announcement_id}", response_model=AnnouncementOut)
def get_announcement(
    announcement_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> AnnouncementOut:
    return _outs(db, [_get(db, principal, announcement_id, READ)])[0]


@router.patch("/{announcement_id}", response_model=AnnouncementOut)
def update_announcement(
    announcement_id: uuid.UUID,
    body: AnnouncementPatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> AnnouncementOut:
    row = _get(db, principal, announcement_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    current = {
        "organization_id": row.organization_id,
        "name": row.name,
        "description": row.description,
        "prompt_id": row.prompt_id,
        "allow_skip": row.allow_skip,
        "repeat_key": row.repeat_key,
        "destination": destinations.as_input(destinations.ref_of(row, "destination")),
        "is_enabled": row.is_enabled,
    }
    try:
        validated = AnnouncementIn.model_validate({**current, **changes})
    except ValueError as e:
        raise _validation("announcement", str(e).splitlines()[0]) from e
    _check_all(db, row.organization_id, validated, self_id=row.id)
    details: dict[str, Any] = {}
    if validated.name != row.name:
        details["name"] = {"from": row.name, "to": validated.name}
        row.name = validated.name
    desc = (validated.description or "").strip() or None
    if desc != row.description:
        row.description = desc
        details["description"] = True
    for field in ("prompt_id", "allow_skip", "repeat_key", "is_enabled"):
        value = getattr(validated, field)
        if value != getattr(row, field):
            setattr(row, field, value)
            details[field] = str(value) if value is not None else None
    if destinations.ref_of(row, "destination") != validated.destination.as_ref():
        destinations.apply(row, "destination", validated.destination)
        details["destination"] = validated.destination.model_dump(mode="json")
    if not details:
        return _outs(db, [row])[0]
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise _name_conflict(e) from e
    _audit(db, ctx, principal, "announcement.update", row, details)
    db.commit()
    bus.publish(Event("announcement.updated", {"id": str(row.id)}))
    return _outs(db, [row])[0]


@router.delete("/{announcement_id}", status_code=204)
def delete_announcement(
    announcement_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    row = _get(db, principal, announcement_id, WRITE)
    what = destinations.describe_uses(db, "announcement", row.id, exclude_self=row.id)
    if what:
        raise destinations.in_use_error("Announcement in use", "announcement_in_use", what)
    _audit(db, ctx, principal, "announcement.delete", row, {"slug": row.slug})
    db.delete(row)
    db.commit()
    bus.publish(Event("announcement.deleted", {"id": str(announcement_id)}))
    return Response(status_code=204)
