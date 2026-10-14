# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pickup groups (docs/RING_GROUPS_QUEUES.md §4): extensions that may answer
each other's ringing calls with ``*8``. The slug is the Asterisk named group
on every member's endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import group_helpers as helpers
from veyra.api.v1.group_helpers import READ, WRITE, MemberOut
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import conflict, not_found
from veyra.core.events import Event, bus
from veyra.core.models import PickupGroup, PickupGroupMember
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import routing

router = APIRouter(prefix="/pickup-groups", tags=["pickup-groups"])

MAX_MEMBERS = 64


class PickupGroupIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    members: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_MEMBERS)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        routing.slugify(v)
        return v


class PickupGroupPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    members: list[uuid.UUID] | None = Field(None, max_length=MAX_MEMBERS)


class PickupGroupOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    slug: str
    description: str | None
    members: list[MemberOut]
    problems: list[str]
    created_at: datetime
    updated_at: datetime


def _members(db: Session, group_ids: set[uuid.UUID]) -> dict[uuid.UUID, list[PickupGroupMember]]:
    out: dict[uuid.UUID, list[PickupGroupMember]] = {g: [] for g in group_ids}
    if group_ids:
        for m in db.scalars(
            select(PickupGroupMember).where(PickupGroupMember.group_id.in_(group_ids))
        ):
            out[m.group_id].append(m)
    return out


def _outs(db: Session, rows: list[PickupGroup]) -> list[PickupGroupOut]:
    if not rows:
        return []
    orgs = helpers.org_names(db, {r.organization_id for r in rows})
    members = _members(db, {r.id for r in rows})
    exts = helpers.extensions_by_id(
        db, {m.extension_id for rows_ in members.values() for m in rows_}
    )
    out = []
    for r in rows:
        member_outs = sorted(
            (
                MemberOut(
                    extension_id=e.id,
                    number=e.number,
                    display_name=e.display_name,
                    is_enabled=e.is_enabled,
                )
                for e in (exts.get(m.extension_id) for m in members[r.id])
                if e is not None
            ),
            key=lambda m: m.number,
        )
        problems = []
        if len(member_outs) < 2:
            problems.append("A pickup group needs at least two members to be useful.")
        out.append(
            PickupGroupOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=orgs.get(r.organization_id, ""),
                name=r.name,
                slug=r.slug,
                description=r.description,
                members=member_outs,
                problems=problems,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _get(db: Session, principal: Principal, group_id: uuid.UUID, perm: str) -> PickupGroup:
    stmt = helpers.org_filter(select(PickupGroup), PickupGroup.organization_id, principal, perm)
    group = db.scalar(stmt.where(PickupGroup.id == group_id))
    if group is None:
        raise not_found("Pickup group")
    return group


def _set_members(db: Session, group: PickupGroup, extension_ids: list[uuid.UUID]) -> None:
    for old in db.scalars(select(PickupGroupMember).where(PickupGroupMember.group_id == group.id)):
        db.delete(old)
    db.flush()
    for ext_id in extension_ids:
        db.add(PickupGroupMember(group_id=group.id, extension_id=ext_id))
    db.flush()


def _name_conflict(e: IntegrityError, db: Session) -> Exception:
    db.rollback()
    return conflict("A pickup group with that name exists in this organization.", "name_in_use")


@router.get("", response_model=Page[PickupGroupOut], summary="List pickup groups")
def list_groups(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[PickupGroupOut]:
    stmt = helpers.org_filter(
        select(PickupGroup), PickupGroup.organization_id, principal, READ
    ).order_by(PickupGroup.name)
    if organization_id:
        stmt = stmt.where(PickupGroup.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(PickupGroup.name.ilike(like), PickupGroup.description.ilike(like)))
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post("", response_model=PickupGroupOut, status_code=201, summary="Create a pickup group")
def create_group(
    body: PickupGroupIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PickupGroupOut:
    org = helpers.org_for_write(db, principal, body.organization_id)
    helpers.load_members(db, org.id, body.members, "members")
    group = PickupGroup(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=body.name,
        slug=helpers.unique_slug(db, PickupGroup, body.name),
        description=(body.description or "").strip() or None,
    )
    db.add(group)
    try:
        db.flush()
    except IntegrityError as e:
        raise _name_conflict(e, db) from e
    _set_members(db, group, body.members)
    helpers.record(
        db,
        ctx,
        principal,
        "pickup_group.create",
        target_type="pickup_group",
        target=group,
        details={"slug": group.slug, "members": len(body.members)},
    )
    db.commit()
    bus.publish(Event("pickup_group.created", {"id": str(group.id)}))
    return _outs(db, [group])[0]


@router.get("/{group_id}", response_model=PickupGroupOut)
def get_group(
    group_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> PickupGroupOut:
    return _outs(db, [_get(db, principal, group_id, READ)])[0]


@router.patch("/{group_id}", response_model=PickupGroupOut)
def update_group(
    group_id: uuid.UUID,
    body: PickupGroupPatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PickupGroupOut:
    group = _get(db, principal, group_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    details: dict[str, Any] = {}
    if "name" in changes:
        try:
            name = PickupGroupIn._name(changes["name"] or "")
        except ValueError as e:
            raise helpers.validation("name", str(e)) from e
        if name != group.name:
            details["name"] = {"from": group.name, "to": name}
            group.name = name
    if "description" in changes:
        desc = (changes["description"] or "").strip() or None
        if desc != group.description:
            group.description = desc
            details["description"] = True
    if "members" in changes:
        wanted = list(changes["members"] or [])
        helpers.load_members(db, group.organization_id, wanted, "members")
        have = sorted(str(m.extension_id) for m in _members(db, {group.id})[group.id])
        if sorted(str(x) for x in wanted) != have:
            _set_members(db, group, wanted)
            details["members"] = len(wanted)
    if not details:
        return _outs(db, [group])[0]
    try:
        db.flush()
    except IntegrityError as e:
        raise _name_conflict(e, db) from e
    helpers.record(
        db,
        ctx,
        principal,
        "pickup_group.update",
        target_type="pickup_group",
        target=group,
        details=details,
    )
    db.commit()
    bus.publish(Event("pickup_group.updated", {"id": str(group.id)}))
    return _outs(db, [group])[0]


@router.delete("/{group_id}", status_code=204)
def delete_group(
    group_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    group = _get(db, principal, group_id, WRITE)
    helpers.record(
        db,
        ctx,
        principal,
        "pickup_group.delete",
        target_type="pickup_group",
        target=group,
        details={"slug": group.slug},
    )
    for m in db.scalars(select(PickupGroupMember).where(PickupGroupMember.group_id == group.id)):
        db.delete(m)
    db.flush()
    db.delete(group)
    db.commit()
    bus.publish(Event("pickup_group.deleted", {"id": str(group_id)}))
    return Response(status_code=204)
