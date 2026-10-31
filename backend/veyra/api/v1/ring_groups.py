# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ring groups (docs/RING_GROUPS_QUEUES.md §2): a number that rings several
extensions at once or in order, then fails over to a destination."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import destinations, hold_music
from veyra.api.v1 import group_helpers as helpers
from veyra.api.v1.destinations import DestinationIn, DestinationOut, Resolver, check_destination
from veyra.api.v1.group_helpers import READ, WRITE, MemberOut
from veyra.core import tenancy
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import conflict, not_found
from veyra.core.events import Event, bus
from veyra.core.models import RingGroup, RingGroupMember
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import extension_state, routing
from veyra.telephony.asterisk.names import Names

router = APIRouter(prefix="/ring-groups", tags=["ring-groups"])

Strategy = Literal["ringall", "sequential", "circular", "roundrobin", "longest_idle"]
_ALERT_INFO_RE = re.compile(r"^[A-Za-z0-9:;=_.<>/@+-]{1,100}$")
_PREFIX_RE = re.compile(r"^[\w .'&():-]{1,40}$", re.UNICODE)
MAX_MEMBERS = 32


# ----------------------------------------------------------------- schemas


class RingGroupIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    number: str = Field(min_length=1, max_length=32)
    description: str | None = Field(None, max_length=2000)
    strategy: Strategy = "ringall"
    ring_seconds: int = Field(20, ge=5, le=120)
    ring_busy_members: bool = False
    # Skip a member who did not answer this many calls in a row, for
    # skip_minutes (issue #166); null: never skipped. One at a time only.
    skip_after_misses: int | None = Field(None, ge=1, le=10)
    skip_minutes: int = Field(15, ge=1, le=1440)
    # Outside numbers rung with the members (docs/CALL_FEATURES.md §3.4).
    external_members: list[str] = Field(default_factory=list, max_length=10)
    confirm_external: bool = False
    caller_id_prefix: str | None = Field(None, max_length=40)
    answered_elsewhere: bool = False
    ignore_forwards: bool = False
    alert_info: str | None = Field(None, max_length=100)
    # What callers hear while members ring: ringing, or hold music (the set
    # below, or the built-in one) (docs/PAGING_RECORDINGS.md §3.2).
    music: Literal["ring", "default"] = "ring"
    moh_class_id: uuid.UUID | None = None
    failover: DestinationIn = Field(default_factory=lambda: DestinationIn(type="hangup"))
    members: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_MEMBERS)
    # Per-member ring time (issue #166), extension id -> seconds; members
    # left out ring for the group's ring time.
    member_ring_seconds: dict[uuid.UUID, int] = Field(default_factory=dict)

    @field_validator("member_ring_seconds")
    @classmethod
    def _member_rings(cls, v: dict[uuid.UUID, int]) -> dict[uuid.UUID, int]:
        for seconds in v.values():
            if not 5 <= seconds <= 120:
                raise ValueError("a member's ring time is 5 to 120 seconds")
        return v

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

    @field_validator("alert_info")
    @classmethod
    def _alert(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        if not _ALERT_INFO_RE.match(v.strip()):
            raise ValueError("one word, such as info=ring2 or <urn:alert:service:normal>")
        return v.strip()

    @field_validator("caller_id_prefix")
    @classmethod
    def _prefix(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        if not _PREFIX_RE.match(v):
            raise ValueError("letters, digits, spaces and . ' & ( ) - : only, at most 40")
        return v

    @field_validator("external_members")
    @classmethod
    def _external(cls, v: list[str]) -> list[str]:
        return _external_numbers(v)


def _external_numbers(values: list[str]) -> list[str]:
    out: list[str] = []
    for i, raw in enumerate(values, start=1):
        try:
            number = extension_state.normalize_number(f"external_members.{i}", raw)
        except extension_state.StateError as e:
            raise ValueError(f"number {i}: {e.message}") from e
        if number and number not in out:
            out.append(number)
    return out


class RingGroupPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    number: str | None = Field(None, min_length=1, max_length=32)
    description: str | None = Field(None, max_length=2000)
    strategy: Strategy | None = None
    ring_seconds: int | None = Field(None, ge=5, le=120)
    ring_busy_members: bool | None = None
    skip_after_misses: int | None = Field(None, ge=1, le=10)
    skip_minutes: int | None = Field(None, ge=1, le=1440)
    external_members: list[str] | None = Field(None, max_length=10)
    confirm_external: bool | None = None
    caller_id_prefix: str | None = Field(None, max_length=40)
    answered_elsewhere: bool | None = None
    ignore_forwards: bool | None = None
    alert_info: str | None = Field(None, max_length=100)
    music: Literal["ring", "default"] | None = None

    @field_validator("alert_info")
    @classmethod
    def _alert(cls, v: str | None) -> str | None:
        return RingGroupIn._alert(v)

    @field_validator("external_members")
    @classmethod
    def _external(cls, v: list[str] | None) -> list[str] | None:
        return _external_numbers(v) if v is not None else None

    moh_class_id: uuid.UUID | None = None
    failover: DestinationIn | None = None
    members: list[uuid.UUID] | None = Field(None, max_length=MAX_MEMBERS)
    member_ring_seconds: dict[uuid.UUID, int] | None = None
    is_enabled: bool | None = None


class RingMemberOut(MemberOut):
    # This member's ring time (issue #166); None: the group's.
    ring_seconds: int | None = None


class RingGroupOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    slug: str
    context: str
    number: str
    description: str | None
    strategy: str
    ring_seconds: int
    ring_busy_members: bool
    skip_after_misses: int | None = None
    skip_minutes: int = 15
    external_members: list[str] = []
    confirm_external: bool = False
    caller_id_prefix: str | None
    answered_elsewhere: bool = False
    ignore_forwards: bool = False
    alert_info: str | None = None
    music: str
    moh_class_id: uuid.UUID | None
    moh_class_name: str | None
    failover: DestinationOut
    members: list[RingMemberOut]
    is_enabled: bool
    # Why the group will not work as configured.
    problems: list[str]
    # Routes, menus, groups and queues that point at this group.
    in_use_by: int
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------- helpers


def _members(db: Session, group_ids: set[uuid.UUID]) -> dict[uuid.UUID, list[RingGroupMember]]:
    out: dict[uuid.UUID, list[RingGroupMember]] = {g: [] for g in group_ids}
    if group_ids:
        for m in db.scalars(
            select(RingGroupMember)
            .where(RingGroupMember.group_id.in_(group_ids))
            .order_by(RingGroupMember.position)
        ):
            out[m.group_id].append(m)
    return out


def _outs(db: Session, rows: list[RingGroup]) -> list[RingGroupOut]:
    spaces = tenancy.namespaces(db)

    def names_of(org_id: uuid.UUID) -> Names:
        return Names(spaces.get(org_id, ""))

    if not rows:
        return []
    orgs = helpers.org_names(db, {r.organization_id for r in rows})
    moh_names = hold_music.set_names(db, {r.moh_class_id for r in rows})
    members = _members(db, {r.id for r in rows})
    exts = helpers.extensions_by_id(
        db, {m.extension_id for rows_ in members.values() for m in rows_}
    )
    uses = destinations.count_uses(db, "ring_group", {r.id for r in rows})
    resolver = Resolver(db)
    resolver.load([destinations.ref_of(r, "failover") for r in rows])
    out = []
    for r in rows:
        failover = resolver.out_ref(destinations.ref_of(r, "failover"))
        member_outs = []
        for m in members[r.id]:
            ext = exts.get(m.extension_id)
            if ext is None:
                continue
            member_outs.append(
                RingMemberOut(
                    extension_id=ext.id,
                    number=ext.number,
                    display_name=ext.display_name,
                    is_enabled=ext.is_enabled,
                    position=m.position,
                    ring_seconds=m.ring_seconds,
                )
            )
        problems = []
        if not member_outs:
            problems.append("The group has no members: callers go straight to the failover.")
        for mo in member_outs:
            if not mo.is_enabled:
                problems.append(f"Member {mo.number} is disabled and will not ring.")
        if failover.missing:
            problems.append("The failover destination no longer exists.")
        out.append(
            RingGroupOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=orgs.get(r.organization_id, ""),
                name=r.name,
                slug=r.slug,
                context=names_of(r.organization_id).ring_group(r.slug),
                number=r.number,
                description=r.description,
                strategy=r.strategy,
                ring_seconds=r.ring_seconds,
                ring_busy_members=r.ring_busy_members,
                skip_after_misses=r.skip_after_misses,
                skip_minutes=r.skip_minutes,
                external_members=list(r.external_members or []),
                confirm_external=r.confirm_external,
                caller_id_prefix=r.caller_id_prefix,
                answered_elsewhere=r.answered_elsewhere,
                ignore_forwards=r.ignore_forwards,
                alert_info=r.alert_info,
                music=r.music,
                moh_class_id=r.moh_class_id,
                moh_class_name=moh_names.get(r.moh_class_id) if r.moh_class_id else None,
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


def _get(db: Session, principal: Principal, group_id: uuid.UUID, perm: str) -> RingGroup:
    stmt = helpers.org_filter(select(RingGroup), RingGroup.organization_id, principal, perm)
    group = db.scalar(stmt.where(RingGroup.id == group_id))
    if group is None:
        raise not_found("Ring group")
    return group


def _set_members(
    db: Session,
    group: RingGroup,
    extension_ids: list[uuid.UUID],
    ring_seconds: dict[uuid.UUID, int] | None = None,
) -> None:
    for old in db.scalars(select(RingGroupMember).where(RingGroupMember.group_id == group.id)):
        db.delete(old)
    db.flush()
    for i, ext_id in enumerate(extension_ids):
        db.add(
            RingGroupMember(
                group_id=group.id,
                extension_id=ext_id,
                position=i,
                ring_seconds=(ring_seconds or {}).get(ext_id),
            )
        )
    db.flush()


def _check(db: Session, org_id: uuid.UUID, body: RingGroupIn, self_id: uuid.UUID | None) -> None:
    helpers.check_number(db, body.number, "ring group", self_id, org_id)
    helpers.load_members(db, org_id, body.members, "members")
    hold_music.check_set(db, org_id, body.moh_class_id, "moh_class_id")
    check_destination(
        db, org_id, body.failover, field="failover", allow_hangup=True, exclude_ring_group=self_id
    )


def _name_conflict(e: IntegrityError, db: Session) -> Exception:
    db.rollback()
    return conflict("A ring group with that name exists in this organization.", "name_in_use")


# ----------------------------------------------------------------- routes


@router.get("", response_model=Page[RingGroupOut], summary="List ring groups")
def list_groups(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[RingGroupOut]:
    stmt = helpers.org_filter(
        select(RingGroup), RingGroup.organization_id, principal, READ
    ).order_by(RingGroup.number)
    if organization_id:
        stmt = stmt.where(RingGroup.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                RingGroup.name.ilike(like),
                RingGroup.number.ilike(like),
                RingGroup.description.ilike(like),
            )
        )
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post("", response_model=RingGroupOut, status_code=201, summary="Create a ring group")
def create_group(
    body: RingGroupIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RingGroupOut:
    org = helpers.org_for_write(db, principal, body.organization_id)
    _check(db, org.id, body, None)
    group = RingGroup(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=body.name,
        slug=helpers.unique_slug(db, RingGroup, body.name),
        number=body.number,
        description=(body.description or "").strip() or None,
        strategy=body.strategy,
        ring_seconds=body.ring_seconds,
        ring_busy_members=body.ring_busy_members,
        skip_after_misses=body.skip_after_misses,
        skip_minutes=body.skip_minutes,
        external_members=body.external_members,
        confirm_external=body.confirm_external,
        caller_id_prefix=body.caller_id_prefix,
        answered_elsewhere=body.answered_elsewhere,
        ignore_forwards=body.ignore_forwards,
        alert_info=body.alert_info,
        music=body.music,
        moh_class_id=body.moh_class_id,
        is_enabled=body.is_enabled,
    )
    destinations.apply(group, "failover", body.failover)
    db.add(group)
    try:
        db.flush()
    except IntegrityError as e:
        raise _name_conflict(e, db) from e
    _set_members(db, group, body.members, body.member_ring_seconds)
    helpers.record(
        db,
        ctx,
        principal,
        "ring_group.create",
        target_type="ring_group",
        target=group,
        details={"number": group.number, "slug": group.slug, "members": len(body.members)},
    )
    db.commit()
    bus.publish(Event("ring_group.created", {"id": str(group.id), "number": group.number}))
    return _outs(db, [group])[0]


@router.get("/{group_id}", response_model=RingGroupOut)
def get_group(
    group_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> RingGroupOut:
    return _outs(db, [_get(db, principal, group_id, READ)])[0]


@router.patch("/{group_id}", response_model=RingGroupOut)
def update_group(
    group_id: uuid.UUID,
    body: RingGroupPatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RingGroupOut:
    group = _get(db, principal, group_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    member_rows = _members(db, {group.id})[group.id]
    current_members = [m.extension_id for m in member_rows]
    current_rings = {m.extension_id: m.ring_seconds for m in member_rows if m.ring_seconds}
    current = {
        "organization_id": group.organization_id,
        "name": group.name,
        "number": group.number,
        "description": group.description,
        "strategy": group.strategy,
        "ring_seconds": group.ring_seconds,
        "ring_busy_members": group.ring_busy_members,
        "skip_after_misses": group.skip_after_misses,
        "skip_minutes": group.skip_minutes,
        "external_members": list(group.external_members or []),
        "confirm_external": group.confirm_external,
        "caller_id_prefix": group.caller_id_prefix,
        "answered_elsewhere": group.answered_elsewhere,
        "ignore_forwards": group.ignore_forwards,
        "alert_info": group.alert_info,
        "music": group.music,
        "moh_class_id": group.moh_class_id,
        "failover": destinations.as_input(destinations.ref_of(group, "failover")),
        "members": current_members,
        "member_ring_seconds": current_rings,
        "is_enabled": group.is_enabled,
    }
    try:
        validated = RingGroupIn.model_validate({**current, **changes})
    except ValueError as e:
        raise helpers.validation("ring_group", str(e).splitlines()[0]) from e
    _check(db, group.organization_id, validated, group.id)
    details: dict[str, Any] = {}
    if validated.name != group.name:
        details["name"] = {"from": group.name, "to": validated.name}
        group.name = validated.name
    desc = (validated.description or "").strip() or None
    if desc != group.description:
        group.description = desc
        details["description"] = True
    for field in (
        "number",
        "strategy",
        "ring_seconds",
        "ring_busy_members",
        "skip_after_misses",
        "skip_minutes",
        "external_members",
        "confirm_external",
        "caller_id_prefix",
        "answered_elsewhere",
        "ignore_forwards",
        "alert_info",
        "music",
        "moh_class_id",
        "is_enabled",
    ):
        value = getattr(validated, field)
        if value != getattr(group, field):
            setattr(group, field, value)
            details[field] = str(value) if value is not None else None
    if destinations.ref_of(group, "failover") != validated.failover.as_ref():
        destinations.apply(group, "failover", validated.failover)
        details["failover"] = validated.failover.model_dump(mode="json")
    rings = {k: v for k, v in validated.member_ring_seconds.items() if k in validated.members}
    if ("members" in changes and validated.members != current_members) or (
        "member_ring_seconds" in changes and rings != current_rings
    ):
        _set_members(db, group, validated.members, rings)
        details["members"] = len(validated.members)
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
        "ring_group.update",
        target_type="ring_group",
        target=group,
        details=details,
    )
    db.commit()
    bus.publish(Event("ring_group.updated", {"id": str(group.id)}))
    return _outs(db, [group])[0]


@router.delete("/{group_id}", status_code=204)
def delete_group(
    group_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    group = _get(db, principal, group_id, WRITE)
    what = destinations.describe_uses(db, "ring_group", group.id, exclude_self=group.id)
    if what:
        raise destinations.in_use_error("Ring group in use", "ring_group_in_use", what)
    helpers.record(
        db,
        ctx,
        principal,
        "ring_group.delete",
        target_type="ring_group",
        target=group,
        details={"number": group.number, "slug": group.slug},
    )
    for m in db.scalars(select(RingGroupMember).where(RingGroupMember.group_id == group.id)):
        db.delete(m)
    db.flush()
    db.delete(group)
    db.commit()
    bus.publish(Event("ring_group.deleted", {"id": str(group_id)}))
    return Response(status_code=204)
