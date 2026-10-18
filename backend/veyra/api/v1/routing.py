# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call routing: inbound routes (DIDs), outbound routes and time conditions
(docs/TRUNKS_ROUTING.md §3-§5).

Inbound routes and time conditions belong to an organization
(``routing.read`` / ``routing.write``); outbound routes are installation-wide
and edited with ``trunks.write`` until per-tenant contexts exist.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import destinations
from veyra.api.v1.destinations import DestinationIn, DestinationOut, Resolver, check_destination
from veyra.configmgmt import service as configmgmt
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.events import Event, bus
from veyra.core.models import (
    Extension,
    InboundRoute,
    Organization,
    OutboundRoute,
    OutboundRouteTrunk,
    SipTrunk,
    TimeCondition,
)
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import routing

router = APIRouter(prefix="/routing", tags=["routing"])

_PREFIX_RE = re.compile(r"^[\w .'&():-]{1,40}$", re.UNICODE)
_NUMBER_RE = re.compile(r"^\+?[0-9]{1,32}$")


def _validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


def _audit(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    *,
    target_type: str,
    target_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    label: str,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=organization_id,
        target_type=target_type,
        target_id=target_id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=details,
    )
    configmgmt.mark_changed(db, by=principal.label, what=f"{action} {label}")


def _org_filter(stmt: Select[Any], column: Any, principal: Principal, perm: str) -> Select[Any]:
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(column.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _org_for_write(db: Session, principal: Principal, organization_id: uuid.UUID) -> Organization:
    if not principal.has("routing.write", organization_id):
        raise forbidden()
    org = db.get(Organization, organization_id)
    if org is None:
        raise not_found("Organization")
    if not org.is_active:
        raise conflict("This organization is inactive.", "organization_inactive")
    return org


def _org_names(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, Organization]:
    if not ids:
        return {}
    return {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(ids)))}


# =============================================================== time conditions


class TimeRangeIn(BaseModel):
    days: list[str] = Field(min_length=1, max_length=7)
    start: str
    end: str


class TimeConditionIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    timezone: str | None = Field(None, max_length=64)
    ranges: list[TimeRangeIn] = Field(min_length=1, max_length=50)
    holidays: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        return v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        return routing.check_timezone(v) if v and v.strip() else None

    @field_validator("ranges")
    @classmethod
    def _ranges(cls, v: list[TimeRangeIn]) -> list[TimeRangeIn]:
        checked = routing.check_ranges([r.model_dump() for r in v])
        return [TimeRangeIn(**r) for r in checked]

    @field_validator("holidays")
    @classmethod
    def _holidays(cls, v: list[str]) -> list[str]:
        return routing.check_holidays(v)


class TimeConditionPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    timezone: str | None = Field(None, max_length=64)
    ranges: list[TimeRangeIn] | None = Field(None, min_length=1, max_length=50)
    holidays: list[str] | None = Field(None, max_length=100)


class TimeConditionOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    description: str | None
    timezone: str
    ranges: list[TimeRangeIn]
    holidays: list[str]
    open_now: bool
    in_use_by: int
    created_at: datetime
    updated_at: datetime


def _tc_outs(db: Session, rows: list[TimeCondition]) -> list[TimeConditionOut]:
    orgs = _org_names(db, {r.organization_id for r in rows})
    ids = [r.id for r in rows]
    counts: dict[uuid.UUID, int] = {}
    if ids:
        for cid, n in db.execute(
            select(InboundRoute.time_condition_id, func.count())
            .where(InboundRoute.time_condition_id.in_(ids))
            .group_by(InboundRoute.time_condition_id)
        ):
            if cid is not None:
                counts[cid] = n
    return [
        TimeConditionOut(
            id=r.id,
            organization_id=r.organization_id,
            organization_name=orgs[r.organization_id].name if r.organization_id in orgs else "",
            name=r.name,
            description=r.description,
            timezone=r.timezone,
            ranges=[TimeRangeIn(**x) for x in (r.ranges or [])],
            holidays=list(r.holidays or []),
            open_now=routing.is_open(list(r.ranges or []), list(r.holidays or []), r.timezone),
            in_use_by=counts.get(r.id, 0),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


def _get_tc(db: Session, principal: Principal, tc_id: uuid.UUID, perm: str) -> TimeCondition:
    stmt = _org_filter(select(TimeCondition), TimeCondition.organization_id, principal, perm)
    tc = db.scalar(stmt.where(TimeCondition.id == tc_id))
    if tc is None:
        raise not_found("Time condition")
    return tc


@router.get(
    "/time-conditions", response_model=Page[TimeConditionOut], summary="List time conditions"
)
def list_time_conditions(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require("routing.read")),
    db: Session = Depends(get_db),
) -> Page[TimeConditionOut]:
    stmt = _org_filter(
        select(TimeCondition), TimeCondition.organization_id, principal, "routing.read"
    ).order_by(TimeCondition.name)
    if organization_id:
        stmt = stmt.where(TimeCondition.organization_id == organization_id)
    if q:
        stmt = stmt.where(TimeCondition.name.ilike(f"%{q.strip()}%"))
    rows, total = paginate(db, stmt, params)
    return Page(items=_tc_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post(
    "/time-conditions",
    response_model=TimeConditionOut,
    status_code=201,
    summary="Create a time condition",
)
def create_time_condition(
    body: TimeConditionIn,
    principal: Principal = Depends(require("routing.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> TimeConditionOut:
    org = _org_for_write(db, principal, body.organization_id)
    tc = TimeCondition(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=body.name,
        description=body.description,
        timezone=body.timezone or org.timezone or "UTC",
        ranges=[r.model_dump() for r in body.ranges],
        holidays=body.holidays,
    )
    db.add(tc)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(
            "A time condition with that name exists in this organization.", "name_in_use"
        ) from e
    _audit(
        db,
        ctx,
        principal,
        "time_condition.create",
        target_type="time_condition",
        target_id=tc.id,
        organization_id=org.id,
        label=tc.name,
        details={"name": tc.name, "timezone": tc.timezone, "ranges": len(tc.ranges)},
    )
    db.commit()
    bus.publish(Event("time_condition.created", {"id": str(tc.id)}))
    return _tc_outs(db, [tc])[0]


@router.get("/time-conditions/{tc_id}", response_model=TimeConditionOut)
def get_time_condition(
    tc_id: uuid.UUID,
    principal: Principal = Depends(require("routing.read")),
    db: Session = Depends(get_db),
) -> TimeConditionOut:
    return _tc_outs(db, [_get_tc(db, principal, tc_id, "routing.read")])[0]


@router.patch("/time-conditions/{tc_id}", response_model=TimeConditionOut)
def update_time_condition(
    tc_id: uuid.UUID,
    body: TimeConditionPatch,
    principal: Principal = Depends(require("routing.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> TimeConditionOut:
    tc = _get_tc(db, principal, tc_id, "routing.write")
    changes = body.model_dump(exclude_unset=True)
    details: dict[str, Any] = {}
    if "name" in changes:
        name = (changes["name"] or "").strip()
        if not name:
            raise _validation("name", "enter a name")
        if name != tc.name:
            details["name"] = {"from": tc.name, "to": name}
            tc.name = name
    if "description" in changes and changes["description"] != tc.description:
        tc.description = (changes["description"] or "").strip() or None
        details["description"] = True
    if "timezone" in changes:
        try:
            tz = routing.check_timezone(changes["timezone"] or "") if changes["timezone"] else None
        except ValueError as e:
            raise _validation("timezone", str(e)) from e
        if tz is None:
            org = db.get(Organization, tc.organization_id)
            tz = (org.timezone if org else None) or "UTC"
        if tz != tc.timezone:
            details["timezone"] = tz
            tc.timezone = tz
    if "ranges" in changes:
        try:
            ranges = routing.check_ranges(changes["ranges"] or [])
        except ValueError as e:
            raise _validation("ranges", str(e)) from e
        if not ranges:
            raise _validation("ranges", "add at least one range")
        if ranges != tc.ranges:
            tc.ranges = ranges
            details["ranges"] = len(ranges)
    if "holidays" in changes:
        try:
            holidays = routing.check_holidays(changes["holidays"] or [])
        except ValueError as e:
            raise _validation("holidays", str(e)) from e
        if holidays != tc.holidays:
            tc.holidays = holidays
            details["holidays"] = len(holidays)
    if not details:
        return _tc_outs(db, [tc])[0]
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(
            "A time condition with that name exists in this organization.", "name_in_use"
        ) from e
    _audit(
        db,
        ctx,
        principal,
        "time_condition.update",
        target_type="time_condition",
        target_id=tc.id,
        organization_id=tc.organization_id,
        label=tc.name,
        details={"name": tc.name, **details},
    )
    db.commit()
    bus.publish(Event("time_condition.updated", {"id": str(tc.id)}))
    return _tc_outs(db, [tc])[0]


@router.delete("/time-conditions/{tc_id}", status_code=204)
def delete_time_condition(
    tc_id: uuid.UUID,
    principal: Principal = Depends(require("routing.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    tc = _get_tc(db, principal, tc_id, "routing.write")
    used = db.scalars(
        select(InboundRoute.did)
        .where(InboundRoute.time_condition_id == tc.id)
        .order_by(InboundRoute.did)
    ).all()
    if used:
        raise ProblemError(
            409,
            "Time condition in use",
            f"These inbound routes use it: {', '.join(used)}.",
            code="time_condition_in_use",
            errors=[{"field": "routes", "message": d} for d in used],
        )
    _audit(
        db,
        ctx,
        principal,
        "time_condition.delete",
        target_type="time_condition",
        target_id=tc.id,
        organization_id=tc.organization_id,
        label=tc.name,
        details={"name": tc.name},
    )
    db.delete(tc)
    db.commit()
    bus.publish(Event("time_condition.deleted", {"id": str(tc_id)}))
    return Response(status_code=204)


# =============================================================== inbound routes


DestinationType = Literal["extension", "voicemail", "voicemail_box", "ivr", "ring_group", "queue"]


class InboundRouteIn(BaseModel):
    organization_id: uuid.UUID
    did: str = Field(min_length=1, max_length=40)
    trunk_id: uuid.UUID | None = None
    description: str | None = Field(None, max_length=2000)
    # The destination (docs/VOICEMAIL_IVR.md §6, RING_GROUPS_QUEUES.md §5): an
    # extension, the voicemail of an extension, an IVR menu, a ring group or a
    # queue; the after-hours branch has the same shape.
    destination_type: DestinationType = "extension"
    destination_extension_id: uuid.UUID | None = None
    destination_ivr_id: uuid.UUID | None = None
    destination_ring_group_id: uuid.UUID | None = None
    destination_queue_id: uuid.UUID | None = None
    destination_voicemail_box_id: uuid.UUID | None = None
    time_condition_id: uuid.UUID | None = None
    after_hours_type: DestinationType = "extension"
    after_hours_extension_id: uuid.UUID | None = None
    after_hours_ivr_id: uuid.UUID | None = None
    after_hours_ring_group_id: uuid.UUID | None = None
    after_hours_queue_id: uuid.UUID | None = None
    after_hours_voicemail_box_id: uuid.UUID | None = None
    caller_id_prefix: str | None = Field(None, max_length=40)
    is_enabled: bool = True

    @field_validator("did")
    @classmethod
    def _did(cls, v: str) -> str:
        return routing.normalize_did(v)

    @field_validator("caller_id_prefix")
    @classmethod
    def _prefix(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        if not _PREFIX_RE.match(v):
            raise ValueError("letters, digits, spaces and . ' & ( ) - : only, at most 40")
        return v


class InboundRoutePatch(BaseModel):
    did: str | None = Field(None, min_length=1, max_length=40)
    trunk_id: uuid.UUID | None = None
    description: str | None = Field(None, max_length=2000)
    destination_type: DestinationType | None = None
    destination_extension_id: uuid.UUID | None = None
    destination_ivr_id: uuid.UUID | None = None
    destination_ring_group_id: uuid.UUID | None = None
    destination_queue_id: uuid.UUID | None = None
    destination_voicemail_box_id: uuid.UUID | None = None
    time_condition_id: uuid.UUID | None = None
    after_hours_type: DestinationType | None = None
    after_hours_extension_id: uuid.UUID | None = None
    after_hours_ivr_id: uuid.UUID | None = None
    after_hours_ring_group_id: uuid.UUID | None = None
    after_hours_queue_id: uuid.UUID | None = None
    after_hours_voicemail_box_id: uuid.UUID | None = None
    caller_id_prefix: str | None = Field(None, max_length=40)
    is_enabled: bool | None = None


class InboundRouteOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    did: str
    did_canonical: str
    aliases: list[str]
    trunk_id: uuid.UUID | None
    trunk_name: str | None
    description: str | None
    destination_type: str
    destination_extension_id: uuid.UUID | None
    destination_ivr_id: uuid.UUID | None
    destination_ring_group_id: uuid.UUID | None
    destination_queue_id: uuid.UUID | None
    destination_voicemail_box_id: uuid.UUID | None
    # Extension number and name for extension and voicemail destinations.
    destination_number: str | None
    destination_name: str | None
    destination: DestinationOut
    destination_missing: bool
    time_condition_id: uuid.UUID | None
    time_condition_name: str | None
    after_hours_type: str
    after_hours_extension_id: uuid.UUID | None
    after_hours_ivr_id: uuid.UUID | None
    after_hours_ring_group_id: uuid.UUID | None
    after_hours_queue_id: uuid.UUID | None
    after_hours_voicemail_box_id: uuid.UUID | None
    after_hours_number: str | None
    after_hours_name: str | None
    after_hours: DestinationOut | None
    caller_id_prefix: str | None
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


def _ir_outs(db: Session, rows: list[InboundRoute]) -> list[InboundRouteOut]:
    orgs = _org_names(db, {r.organization_id for r in rows})
    resolver = Resolver(db)
    resolver.load(
        [destinations.ref_of(r, "destination") for r in rows]
        + [destinations.ref_of(r, "after_hours") for r in rows]
    )
    exts = resolver.extensions
    trunk_ids = {r.trunk_id for r in rows if r.trunk_id}
    trunks = (
        {t.id: t for t in db.scalars(select(SipTrunk).where(SipTrunk.id.in_(trunk_ids)))}
        if trunk_ids
        else {}
    )
    tc_ids = {r.time_condition_id for r in rows if r.time_condition_id}
    tcs = (
        {t.id: t for t in db.scalars(select(TimeCondition).where(TimeCondition.id.in_(tc_ids)))}
        if tc_ids
        else {}
    )
    out = []
    for r in rows:
        dest = exts.get(r.destination_extension_id) if r.destination_extension_id else None
        after = exts.get(r.after_hours_extension_id) if r.after_hours_extension_id else None
        trunk = trunks.get(r.trunk_id) if r.trunk_id else None
        tc = tcs.get(r.time_condition_id) if r.time_condition_id else None
        dest_out = resolver.out_ref(destinations.ref_of(r, "destination"))
        after_out = (
            resolver.out_ref(destinations.ref_of(r, "after_hours"))
            if r.time_condition_id is not None
            else None
        )
        out.append(
            InboundRouteOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=orgs[r.organization_id].name if r.organization_id in orgs else "",
                did=r.did,
                did_canonical=r.did_canonical,
                aliases=routing.did_aliases(r.did),
                trunk_id=r.trunk_id,
                trunk_name=trunk.name if trunk else None,
                description=r.description,
                destination_type=r.destination_type,
                destination_extension_id=r.destination_extension_id,
                destination_ivr_id=r.destination_ivr_id,
                destination_ring_group_id=r.destination_ring_group_id,
                destination_queue_id=r.destination_queue_id,
                destination_voicemail_box_id=r.destination_voicemail_box_id,
                destination_number=dest.number if dest else None,
                destination_name=dest.display_name if dest else None,
                destination=dest_out,
                destination_missing=dest_out.missing
                or (after_out is not None and after_out.missing),
                time_condition_id=r.time_condition_id,
                time_condition_name=tc.name if tc else None,
                after_hours_type=r.after_hours_type,
                after_hours_extension_id=r.after_hours_extension_id,
                after_hours_ivr_id=r.after_hours_ivr_id,
                after_hours_ring_group_id=r.after_hours_ring_group_id,
                after_hours_queue_id=r.after_hours_queue_id,
                after_hours_voicemail_box_id=r.after_hours_voicemail_box_id,
                after_hours_number=after.number if after else None,
                after_hours_name=after.display_name if after else None,
                after_hours=after_out,
                caller_id_prefix=r.caller_id_prefix,
                is_enabled=r.is_enabled,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _get_ir(db: Session, principal: Principal, route_id: uuid.UUID, perm: str) -> InboundRoute:
    stmt = _org_filter(select(InboundRoute), InboundRoute.organization_id, principal, perm)
    route = db.scalar(stmt.where(InboundRoute.id == route_id))
    if route is None:
        raise not_found("Inbound route")
    return route


def _dest_field(kind: str, prefix: str) -> str:
    return f"{prefix}_{destinations.TARGET_FIELDS.get(kind, 'extension_id')}"


def _has_target(route: InboundRoute, prefix: str) -> bool:
    return any(t is not None for t in destinations.ref_of(route, prefix)[1:])


def _check_destinations(db: Session, org_id: uuid.UUID, route: InboundRoute) -> None:
    dest = DestinationIn(**destinations.as_input(destinations.ref_of(route, "destination")))
    check_destination(
        db,
        org_id,
        dest,
        field=_dest_field(route.destination_type, "destination"),
        allow_hangup=False,
    )
    if route.time_condition_id is not None:
        tc = db.get(TimeCondition, route.time_condition_id)
        if tc is None or tc.organization_id != org_id:
            raise _validation("time_condition_id", "time condition not found in this organization")
        after = DestinationIn(**destinations.as_input(destinations.ref_of(route, "after_hours")))
        if not _has_target(route, "after_hours"):
            raise _validation(
                _dest_field(route.after_hours_type, "after_hours"),
                "choose where calls go outside the hours",
            )
        check_destination(
            db,
            org_id,
            after,
            field=_dest_field(route.after_hours_type, "after_hours"),
            allow_hangup=False,
        )
    elif _has_target(route, "after_hours"):
        raise _validation(
            _dest_field(route.after_hours_type, "after_hours"),
            "an after-hours destination needs a time condition",
        )
    if route.trunk_id is not None and db.get(SipTrunk, route.trunk_id) is None:
        raise _validation("trunk_id", "trunk not found")


def _did_conflict(did: str) -> ProblemError:
    return conflict(f"DID {did} is already routed (for this trunk restriction).", "did_in_use")


@router.get("/inbound", response_model=Page[InboundRouteOut], summary="List inbound routes")
def list_inbound(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require("routing.read")),
    db: Session = Depends(get_db),
) -> Page[InboundRouteOut]:
    stmt = _org_filter(
        select(InboundRoute), InboundRoute.organization_id, principal, "routing.read"
    ).order_by(InboundRoute.did_canonical, InboundRoute.trunk_id)
    if organization_id:
        stmt = stmt.where(InboundRoute.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(InboundRoute.did.ilike(like), InboundRoute.description.ilike(like)))
    rows, total = paginate(db, stmt, params)
    return Page(items=_ir_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post(
    "/inbound", response_model=InboundRouteOut, status_code=201, summary="Create an inbound route"
)
def create_inbound(
    body: InboundRouteIn,
    principal: Principal = Depends(require("routing.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> InboundRouteOut:
    org = _org_for_write(db, principal, body.organization_id)
    route = InboundRoute(
        id=uuid.uuid4(),
        organization_id=org.id,
        did=body.did,
        did_canonical=routing.canonical_did(body.did),
        trunk_id=body.trunk_id,
        description=(body.description or "").strip() or None,
        destination_type=body.destination_type,
        destination_extension_id=body.destination_extension_id,
        destination_ivr_id=body.destination_ivr_id,
        destination_ring_group_id=body.destination_ring_group_id,
        destination_queue_id=body.destination_queue_id,
        destination_voicemail_box_id=body.destination_voicemail_box_id,
        time_condition_id=body.time_condition_id,
        after_hours_type=body.after_hours_type,
        after_hours_extension_id=body.after_hours_extension_id,
        after_hours_ivr_id=body.after_hours_ivr_id,
        after_hours_ring_group_id=body.after_hours_ring_group_id,
        after_hours_queue_id=body.after_hours_queue_id,
        after_hours_voicemail_box_id=body.after_hours_voicemail_box_id,
        caller_id_prefix=body.caller_id_prefix,
        is_enabled=body.is_enabled,
    )
    _check_destinations(db, org.id, route)
    db.add(route)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise _did_conflict(body.did) from e
    _audit(
        db,
        ctx,
        principal,
        "inbound_route.create",
        target_type="inbound_route",
        target_id=route.id,
        organization_id=org.id,
        label=route.did,
        details={
            "did": route.did,
            "trunk_id": str(route.trunk_id) if route.trunk_id else None,
            "destination_type": route.destination_type,
            "destination_extension_id": (
                str(route.destination_extension_id) if route.destination_extension_id else None
            ),
            "destination_ivr_id": (
                str(route.destination_ivr_id) if route.destination_ivr_id else None
            ),
            "destination_ring_group_id": (
                str(route.destination_ring_group_id) if route.destination_ring_group_id else None
            ),
            "destination_queue_id": (
                str(route.destination_queue_id) if route.destination_queue_id else None
            ),
            "destination_voicemail_box_id": (
                str(route.destination_voicemail_box_id)
                if route.destination_voicemail_box_id
                else None
            ),
        },
    )
    db.commit()
    bus.publish(Event("inbound_route.created", {"id": str(route.id), "did": route.did}))
    return _ir_outs(db, [route])[0]


@router.get("/inbound/{route_id}", response_model=InboundRouteOut)
def get_inbound(
    route_id: uuid.UUID,
    principal: Principal = Depends(require("routing.read")),
    db: Session = Depends(get_db),
) -> InboundRouteOut:
    return _ir_outs(db, [_get_ir(db, principal, route_id, "routing.read")])[0]


@router.patch("/inbound/{route_id}", response_model=InboundRouteOut)
def update_inbound(
    route_id: uuid.UUID,
    body: InboundRoutePatch,
    principal: Principal = Depends(require("routing.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> InboundRouteOut:
    route = _get_ir(db, principal, route_id, "routing.write")
    changes = body.model_dump(exclude_unset=True)
    details: dict[str, Any] = {}
    if "did" in changes:
        try:
            did = routing.normalize_did(changes["did"] or "")
        except ValueError as e:
            raise _validation("did", str(e)) from e
        if did != route.did:
            details["did"] = {"from": route.did, "to": did}
            route.did = did
            route.did_canonical = routing.canonical_did(did)
    if "caller_id_prefix" in changes:
        prefix = changes["caller_id_prefix"]
        if prefix is not None and prefix.strip() and not _PREFIX_RE.match(prefix):
            raise _validation("caller_id_prefix", "letters, digits, spaces and . ' & ( ) - : only")
        prefix = prefix if prefix and prefix.strip() else None
        if prefix != route.caller_id_prefix:
            route.caller_id_prefix = prefix
            details["caller_id_prefix"] = prefix
    for field in (
        "trunk_id",
        "destination_type",
        "destination_extension_id",
        "destination_ivr_id",
        "destination_ring_group_id",
        "destination_queue_id",
        "destination_voicemail_box_id",
        "time_condition_id",
        "after_hours_type",
        "after_hours_extension_id",
        "after_hours_ivr_id",
        "after_hours_ring_group_id",
        "after_hours_queue_id",
        "after_hours_voicemail_box_id",
        "is_enabled",
    ):
        if field in changes and changes[field] != getattr(route, field):
            setattr(route, field, changes[field])
            details[field] = str(changes[field]) if changes[field] is not None else None
    # Only the target column of each destination type is meaningful.
    destinations.apply(
        route,
        "destination",
        DestinationIn(**destinations.as_input(destinations.ref_of(route, "destination"))),
    )
    if route.time_condition_id is None:
        route.after_hours_extension_id = route.after_hours_ivr_id = None
        route.after_hours_ring_group_id = route.after_hours_queue_id = None
        route.after_hours_voicemail_box_id = None
    else:
        destinations.apply(
            route,
            "after_hours",
            DestinationIn(**destinations.as_input(destinations.ref_of(route, "after_hours"))),
        )
    if "description" in changes:
        desc = (changes["description"] or "").strip() or None
        if desc != route.description:
            route.description = desc
            details["description"] = True
    _check_destinations(db, route.organization_id, route)
    if not details:
        return _ir_outs(db, [route])[0]
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise _did_conflict(route.did) from e
    _audit(
        db,
        ctx,
        principal,
        "inbound_route.update",
        target_type="inbound_route",
        target_id=route.id,
        organization_id=route.organization_id,
        label=route.did,
        details={"did": route.did, **details},
    )
    db.commit()
    bus.publish(Event("inbound_route.updated", {"id": str(route.id)}))
    return _ir_outs(db, [route])[0]


@router.delete("/inbound/{route_id}", status_code=204)
def delete_inbound(
    route_id: uuid.UUID,
    principal: Principal = Depends(require("routing.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    route = _get_ir(db, principal, route_id, "routing.write")
    _audit(
        db,
        ctx,
        principal,
        "inbound_route.delete",
        target_type="inbound_route",
        target_id=route.id,
        organization_id=route.organization_id,
        label=route.did,
        details={"did": route.did},
    )
    db.delete(route)
    db.commit()
    bus.publish(Event("inbound_route.deleted", {"id": str(route_id)}))
    return Response(status_code=204)


# =============================================================== outbound routes


class PatternIn(BaseModel):
    prefix: str = Field("", max_length=15)
    match: str = Field(min_length=1, max_length=40)
    prepend: str = Field("", max_length=16)


class OutboundRouteIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    is_emergency: bool = False
    # An emergency route bound to one site (docs/PRODUCTION_HARDENING.md §6).
    site_id: uuid.UUID | None = None
    is_enabled: bool = True
    patterns: list[PatternIn] = Field(min_length=1, max_length=50)
    trunk_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    caller_id_number: str | None = Field(None, max_length=32)
    # The route's caller ID also replaces an extension's outbound caller ID
    # (docs/CALL_FEATURES.md §3.5).
    caller_id_force: bool = False
    # Only this organization's phones use the route; none: every organization
    # (docs/MULTI_TENANCY.md §4).
    organization_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        routing.slugify(v)
        return v

    @field_validator("patterns")
    @classmethod
    def _patterns(cls, v: list[PatternIn]) -> list[PatternIn]:
        out = []
        seen = set()
        for i, p in enumerate(v):
            try:
                prefix, match, prepend = routing.check_pattern(p.prefix, p.match, p.prepend)
            except ValueError as e:
                raise ValueError(f"pattern {i + 1}: {e}") from e
            key = routing.exten_for(prefix, match)
            if key in seen:
                raise ValueError(f"pattern {i + 1}: duplicate of an earlier pattern")
            seen.add(key)
            out.append(PatternIn(prefix=prefix, match=match, prepend=prepend))
        return out

    @field_validator("trunk_ids")
    @classmethod
    def _trunks(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(v)) != len(v):
            raise ValueError("each trunk may appear once")
        return v

    @field_validator("caller_id_number")
    @classmethod
    def _cid(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not _NUMBER_RE.match(v):
            raise ValueError("digits (and a leading +) only")
        return v


class OutboundRoutePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    is_emergency: bool | None = None
    site_id: uuid.UUID | None = None
    is_enabled: bool | None = None
    patterns: list[PatternIn] | None = Field(None, min_length=1, max_length=50)
    trunk_ids: list[uuid.UUID] | None = Field(None, min_length=1, max_length=20)
    caller_id_number: str | None = Field(None, max_length=32)
    caller_id_force: bool | None = None
    organization_id: uuid.UUID | None = None


class RouteTrunkOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    is_enabled: bool


class OutboundRouteOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    position: int
    is_emergency: bool
    site_id: uuid.UUID | None = None
    is_enabled: bool
    patterns: list[PatternIn]
    examples: list[str]
    trunks: list[RouteTrunkOut]
    caller_id_number: str | None
    caller_id_force: bool = False
    organization_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class OutboundRoutesOut(BaseModel):
    items: list[OutboundRouteOut]
    warnings: list[str]


class OrderIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


def _route_trunks(db: Session, routes: list[OutboundRoute]) -> dict[uuid.UUID, list[SipTrunk]]:
    if not routes:
        return {}
    links = db.scalars(
        select(OutboundRouteTrunk)
        .where(OutboundRouteTrunk.route_id.in_([r.id for r in routes]))
        .order_by(OutboundRouteTrunk.position)
    ).all()
    trunk_ids = {link.trunk_id for link in links}
    trunks = (
        {t.id: t for t in db.scalars(select(SipTrunk).where(SipTrunk.id.in_(trunk_ids)))}
        if trunk_ids
        else {}
    )
    out: dict[uuid.UUID, list[SipTrunk]] = {r.id: [] for r in routes}
    for link in links:
        if link.trunk_id in trunks:
            out[link.route_id].append(trunks[link.trunk_id])
    return out


def _or_outs(db: Session, rows: list[OutboundRoute]) -> list[OutboundRouteOut]:
    by_route = _route_trunks(db, rows)
    return [
        OutboundRouteOut(
            id=r.id,
            name=r.name,
            slug=r.slug,
            description=r.description,
            position=r.position,
            is_emergency=r.is_emergency,
            site_id=r.site_id,
            is_enabled=r.is_enabled,
            patterns=[PatternIn(**p) for p in (r.patterns or [])],
            examples=[routing.exten_for(p["prefix"], p["match"]) for p in (r.patterns or [])],
            trunks=[
                RouteTrunkOut(id=t.id, name=t.name, slug=t.slug, is_enabled=t.is_enabled)
                for t in by_route.get(r.id, [])
            ],
            caller_id_number=r.caller_id_number,
            caller_id_force=r.caller_id_force,
            organization_id=r.organization_id,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


def _check_route_org(db: Session, organization_id: uuid.UUID | None) -> None:
    if organization_id is not None and db.get(Organization, organization_id) is None:
        raise _validation("organization_id", "organization not found")


def _ordered_routes(db: Session) -> list[OutboundRoute]:
    return list(
        db.scalars(
            select(OutboundRoute).order_by(
                OutboundRoute.is_emergency.desc(), OutboundRoute.position, OutboundRoute.name
            )
        ).all()
    )


def _warnings(db: Session, outs: list[OutboundRouteOut]) -> list[str]:
    warnings = []
    emergency = [r for r in outs if r.is_emergency and r.is_enabled]
    if not emergency:
        warnings.append(
            "No enabled emergency route: 911 dialled from a phone will not reach a carrier "
            "through Veyra."
        )
    elif any(r.caller_id_number is None for r in emergency):
        # Without a route number, the extension's emergency caller ID or the
        # trunk default is presented (docs/TRUNKS_ROUTING.md §7).
        missing = db.scalar(
            select(func.count(Extension.id)).where(
                Extension.is_enabled.is_(True), Extension.emergency_caller_id_number.is_(None)
            )
        )
        if missing:
            warnings.append(
                f"{missing} enabled extension(s) have no emergency caller ID and an emergency "
                "route has no caller ID number: the trunk's default number is presented for "
                "their emergency calls."
            )
    for r in outs:
        if r.is_enabled and not any(t.is_enabled for t in r.trunks):
            warnings.append(f"Route {r.name} has no enabled trunk; its calls will fail.")
    return warnings


def _get_or(db: Session, route_id: uuid.UUID) -> OutboundRoute:
    route = db.get(OutboundRoute, route_id)
    if route is None:
        raise not_found("Outbound route")
    return route


def _set_trunks(db: Session, route: OutboundRoute, trunk_ids: list[uuid.UUID]) -> list[str]:
    trunks = {t.id: t for t in db.scalars(select(SipTrunk).where(SipTrunk.id.in_(trunk_ids)))}
    missing = [str(t) for t in trunk_ids if t not in trunks]
    if missing:
        raise _validation("trunk_ids", "trunk not found: " + ", ".join(missing))
    for link in db.scalars(
        select(OutboundRouteTrunk).where(OutboundRouteTrunk.route_id == route.id)
    ).all():
        db.delete(link)
    db.flush()
    for i, tid in enumerate(trunk_ids):
        db.add(OutboundRouteTrunk(route_id=route.id, trunk_id=tid, position=i))
    return [trunks[t].name for t in trunk_ids]


def _unique_route_slug(db: Session, name: str) -> str:
    base = routing.slugify(name)
    slug = base
    n = 2
    while db.scalar(select(OutboundRoute.id).where(OutboundRoute.slug == slug)) is not None:
        slug = f"{base[: 40 - len(str(n)) - 1]}-{n}"
        n += 1
    return slug


@router.get("/outbound", response_model=OutboundRoutesOut, summary="List outbound routes in order")
def list_outbound(
    principal: Principal = Depends(require("routing.read")),
    db: Session = Depends(get_db),
) -> OutboundRoutesOut:
    outs = _or_outs(db, _ordered_routes(db))
    return OutboundRoutesOut(items=outs, warnings=_warnings(db, outs))


@router.post(
    "/outbound",
    response_model=OutboundRouteOut,
    status_code=201,
    summary="Create an outbound route",
)
def create_outbound(
    body: OutboundRouteIn,
    principal: Principal = Depends(require("trunks.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> OutboundRouteOut:
    if db.scalar(select(OutboundRoute.id).where(OutboundRoute.name == body.name)) is not None:
        raise conflict(f"An outbound route named {body.name!r} already exists.", "name_in_use")
    _check_route_org(db, body.organization_id)
    position = (db.scalar(select(func.max(OutboundRoute.position))) or 0) + 1
    route = OutboundRoute(
        id=uuid.uuid4(),
        name=body.name,
        slug=_unique_route_slug(db, body.name),
        description=(body.description or "").strip() or None,
        position=position,
        is_emergency=body.is_emergency,
        site_id=body.site_id,
        is_enabled=body.is_enabled,
        patterns=[p.model_dump() for p in body.patterns],
        caller_id_number=body.caller_id_number,
        caller_id_force=body.caller_id_force,
        organization_id=body.organization_id,
    )
    db.add(route)
    db.flush()
    trunk_names = _set_trunks(db, route, body.trunk_ids)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("An outbound route with that name already exists.", "name_in_use") from e
    _audit(
        db,
        ctx,
        principal,
        "outbound_route.create",
        target_type="outbound_route",
        target_id=route.id,
        organization_id=None,
        label=route.name,
        details={
            "name": route.name,
            "patterns": len(route.patterns),
            "trunks": trunk_names,
            "is_emergency": route.is_emergency,
        },
    )
    db.commit()
    bus.publish(Event("outbound_route.created", {"id": str(route.id), "name": route.name}))
    return _or_outs(db, [route])[0]


@router.put("/outbound/order", response_model=OutboundRoutesOut, summary="Reorder outbound routes")
def reorder_outbound(
    body: OrderIn,
    principal: Principal = Depends(require("trunks.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> OutboundRoutesOut:
    routes = {r.id: r for r in db.scalars(select(OutboundRoute)).all()}
    if set(body.ids) != set(routes) or len(body.ids) != len(routes):
        raise _validation("ids", "send every route id exactly once")
    changed = False
    for i, rid in enumerate(body.ids, start=1):
        if routes[rid].position != i:
            routes[rid].position = i
            changed = True
    if changed:
        _audit(
            db,
            ctx,
            principal,
            "outbound_route.reorder",
            target_type="outbound_route",
            target_id=body.ids[0],
            organization_id=None,
            label="routes",
            details={"order": [routes[r].name for r in body.ids]},
        )
        db.commit()
    outs = _or_outs(db, _ordered_routes(db))
    return OutboundRoutesOut(items=outs, warnings=_warnings(db, outs))


@router.get("/outbound/{route_id}", response_model=OutboundRouteOut)
def get_outbound(
    route_id: uuid.UUID,
    principal: Principal = Depends(require("routing.read")),
    db: Session = Depends(get_db),
) -> OutboundRouteOut:
    return _or_outs(db, [_get_or(db, route_id)])[0]


@router.patch("/outbound/{route_id}", response_model=OutboundRouteOut)
def update_outbound(
    route_id: uuid.UUID,
    body: OutboundRoutePatch,
    principal: Principal = Depends(require("trunks.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> OutboundRouteOut:
    route = _get_or(db, route_id)
    changes = body.model_dump(exclude_unset=True)
    current = {
        "name": route.name,
        "description": route.description,
        "is_emergency": route.is_emergency,
        "is_enabled": route.is_enabled,
        "patterns": route.patterns,
        "trunk_ids": [t.id for t in _route_trunks(db, [route])[route.id]],
        "caller_id_number": route.caller_id_number,
        "caller_id_force": route.caller_id_force,
        "organization_id": route.organization_id,
    }
    try:
        validated = OutboundRouteIn.model_validate({**current, **changes})
    except ValueError as e:
        raise _validation("route", _first_error(e)) from e
    details: dict[str, Any] = {}
    if "name" in changes and validated.name != route.name:
        details["name"] = {"from": route.name, "to": validated.name}
        route.name = validated.name
    if "description" in changes and validated.description != route.description:
        route.description = (validated.description or "").strip() or None
        details["description"] = True
    if "organization_id" in changes:
        _check_route_org(db, validated.organization_id)
    for field in (
        "is_emergency",
        "is_enabled",
        "caller_id_number",
        "caller_id_force",
        "organization_id",
        "site_id",
    ):
        if field in changes and getattr(validated, field) != getattr(route, field):
            value = getattr(validated, field)
            setattr(route, field, value)
            details[field] = str(value) if isinstance(value, uuid.UUID) else value
    if "patterns" in changes:
        patterns = [p.model_dump() for p in validated.patterns]
        if patterns != route.patterns:
            route.patterns = patterns
            details["patterns"] = len(patterns)
    if "trunk_ids" in changes and validated.trunk_ids != current["trunk_ids"]:
        details["trunks"] = _set_trunks(db, route, validated.trunk_ids)
    if not details:
        return _or_outs(db, [route])[0]
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("An outbound route with that name already exists.", "name_in_use") from e
    _audit(
        db,
        ctx,
        principal,
        "outbound_route.update",
        target_type="outbound_route",
        target_id=route.id,
        organization_id=None,
        label=route.name,
        details={"name": route.name, **details},
    )
    db.commit()
    bus.publish(Event("outbound_route.updated", {"id": str(route.id)}))
    return _or_outs(db, [route])[0]


def _first_error(e: ValueError) -> str:
    errors = getattr(e, "errors", None)
    if callable(errors):
        try:
            first = errors()[0]
            loc = ".".join(str(p) for p in first.get("loc", ()))
            msg = str(first.get("msg", "")).removeprefix("Value error, ")
            return f"{loc}: {msg}" if loc else msg
        except (IndexError, KeyError, TypeError):
            pass
    return str(e)


@router.delete("/outbound/{route_id}", status_code=204)
def delete_outbound(
    route_id: uuid.UUID,
    principal: Principal = Depends(require("trunks.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    route = _get_or(db, route_id)
    _audit(
        db,
        ctx,
        principal,
        "outbound_route.delete",
        target_type="outbound_route",
        target_id=route.id,
        organization_id=None,
        label=route.name,
        details={"name": route.name},
    )
    db.delete(route)
    db.commit()
    bus.publish(Event("outbound_route.deleted", {"id": str(route_id)}))
    return Response(status_code=204)
