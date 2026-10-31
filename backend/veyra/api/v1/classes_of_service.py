# SPDX-License-Identifier: AGPL-3.0-or-later
"""Classes of service (docs/CALL_FEATURES.md §3.8): per organization, which
outbound routes and feature codes a phone may use, whether its forwards
and follow-me may leave the building, intercom, and how many outside calls
the class may have up at once. An extension without a class may do
everything, so nothing changes until an administrator restricts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import group_helpers as helpers
from veyra.configmgmt import service as configmgmt
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.events import Event, bus
from veyra.core.models import (
    CallQueue,
    ClassOfService,
    ConferenceRoom,
    Extension,
    Organization,
    OutboundRoute,
    RingGroup,
)
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import features, routing

router = APIRouter(prefix="/classes-of-service", tags=["classes-of-service"])
READ = "routing.read"
WRITE = "routing.write"


def _validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


class ClassIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    allowed_outbound_route_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    # None: every feature code.
    allowed_feature_code_keys: list[str] | None = Field(None, max_length=50)
    allow_external_forwards: bool = True
    allow_external_follow_me: bool = True
    allow_intercom: bool = True
    allow_fax: bool = True
    # Supervisor codes (issue #167).
    allow_monitor: bool = False
    monitor_protected: bool = False
    max_outbound_calls: int | None = Field(None, ge=1, le=500)
    # None: all of them.
    allowed_ring_group_ids: list[uuid.UUID] | None = Field(None, max_length=500)
    allowed_queue_ids: list[uuid.UUID] | None = Field(None, max_length=500)
    allowed_conference_ids: list[uuid.UUID] | None = Field(None, max_length=500)
    allow_paging: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        routing.slugify(v)
        return v

    @field_validator("allowed_feature_code_keys")
    @classmethod
    def _keys(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        out: list[str] = []
        for key in v:
            if key not in features.BY_KEY:
                raise ValueError(f"unknown feature code {key!r}")
            if key not in out:
                out.append(key)
        return out


class ClassPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    allowed_outbound_route_ids: list[uuid.UUID] | None = Field(None, max_length=100)
    allowed_feature_code_keys: list[str] | None = Field(None, max_length=50)
    # Explicitly back to "every code".
    all_feature_codes: bool | None = None
    allow_external_forwards: bool | None = None
    allow_external_follow_me: bool | None = None
    allow_intercom: bool | None = None
    allow_fax: bool | None = None
    allow_monitor: bool | None = None
    monitor_protected: bool | None = None
    max_outbound_calls: int | None = Field(None, ge=1, le=500)
    no_call_limit: bool | None = None
    # An explicit null: back to all of them.
    allowed_ring_group_ids: list[uuid.UUID] | None = Field(None, max_length=500)
    allowed_queue_ids: list[uuid.UUID] | None = Field(None, max_length=500)
    allowed_conference_ids: list[uuid.UUID] | None = Field(None, max_length=500)
    allow_paging: bool | None = None


class RouteRef(BaseModel):
    id: uuid.UUID
    name: str


class ClassOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    slug: str
    description: str | None
    allowed_outbound_routes: list[RouteRef]
    allowed_feature_code_keys: list[str] | None
    allow_external_forwards: bool
    allow_external_follow_me: bool
    allow_intercom: bool
    allow_fax: bool
    allow_monitor: bool = False
    monitor_protected: bool = False
    max_outbound_calls: int | None
    allowed_ring_group_ids: list[uuid.UUID] | None = None
    allowed_queue_ids: list[uuid.UUID] | None = None
    allowed_conference_ids: list[uuid.UUID] | None = None
    allow_paging: bool = True
    extensions: int
    created_at: datetime
    updated_at: datetime


def _uuids(ids: list[str] | None) -> list[uuid.UUID] | None:
    return None if ids is None else [uuid.UUID(x) for x in ids]


def _outs(db: Session, rows: list[ClassOfService]) -> list[ClassOut]:
    if not rows:
        return []
    orgs = helpers.org_names(db, {r.organization_id for r in rows})
    route_ids = {uuid.UUID(x) for r in rows for x in (r.allowed_outbound_route_ids or [])}
    routes = (
        {
            r.id: r.name
            for r in db.scalars(select(OutboundRoute).where(OutboundRoute.id.in_(route_ids)))
        }
        if route_ids
        else {}
    )
    counts = dict(
        db.execute(
            select(Extension.class_of_service_id, func.count())
            .where(Extension.class_of_service_id.in_([r.id for r in rows]))
            .group_by(Extension.class_of_service_id)
        ).all()
    )
    return [
        ClassOut(
            id=r.id,
            organization_id=r.organization_id,
            organization_name=orgs.get(r.organization_id, ""),
            name=r.name,
            slug=r.slug,
            description=r.description,
            allowed_outbound_routes=[
                RouteRef(id=uuid.UUID(x), name=routes[uuid.UUID(x)])
                for x in (r.allowed_outbound_route_ids or [])
                if uuid.UUID(x) in routes
            ],
            allowed_feature_code_keys=r.allowed_feature_code_keys,
            allow_external_forwards=r.allow_external_forwards,
            allow_external_follow_me=r.allow_external_follow_me,
            allow_intercom=r.allow_intercom,
            allow_fax=r.allow_fax,
            allow_monitor=r.allow_monitor,
            monitor_protected=r.monitor_protected,
            max_outbound_calls=r.max_outbound_calls,
            allowed_ring_group_ids=_uuids(r.allowed_ring_group_ids),
            allowed_queue_ids=_uuids(r.allowed_queue_ids),
            allowed_conference_ids=_uuids(r.allowed_conference_ids),
            allow_paging=r.allow_paging,
            extensions=int(counts.get(r.id, 0)),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


def _get(db: Session, principal: Principal, class_id: uuid.UUID, perm: str) -> ClassOfService:
    stmt = helpers.org_filter(
        select(ClassOfService), ClassOfService.organization_id, principal, perm
    )
    row = db.scalar(stmt.where(ClassOfService.id == class_id))
    if row is None:
        raise not_found("Class of service")
    return row


def _org_for_write(db: Session, principal: Principal, organization_id: uuid.UUID) -> Organization:
    if not principal.has(WRITE, organization_id):
        raise forbidden()
    org = db.get(Organization, organization_id)
    if org is None:
        raise not_found("Organization")
    return org


def _check_routes(db: Session, organization_id: uuid.UUID, ids: list[uuid.UUID]) -> list[str]:
    """Routes the organization's phones can use: its own and the shared ones;
    emergency routes are always allowed and not listed."""
    if not ids:
        return []
    rows = {
        r.id: r for r in db.scalars(select(OutboundRoute).where(OutboundRoute.id.in_(set(ids))))
    }
    out: list[str] = []
    for rid in ids:
        r = rows.get(rid)
        if r is None or (r.organization_id is not None and r.organization_id != organization_id):
            raise _validation(
                "allowed_outbound_route_ids", f"route {rid} is not available to this organization"
            )
        if r.is_emergency:
            continue
        if str(rid) not in out:
            out.append(str(rid))
    return out


DESTINATIONS: dict[str, Any] = {
    "allowed_ring_group_ids": RingGroup,
    "allowed_queue_ids": CallQueue,
    "allowed_conference_ids": ConferenceRoom,
}


def _check_destinations(
    db: Session, organization_id: uuid.UUID, field: str, ids: list[uuid.UUID] | None
) -> list[str] | None:
    """The organization's own ring groups, queues or rooms; None stays all."""
    if ids is None:
        return None
    model = DESTINATIONS[field]
    wanted = set(ids)
    found = set(
        db.scalars(
            select(model.id).where(model.id.in_(wanted), model.organization_id == organization_id)
        )
    )
    missing = wanted - found
    if missing:
        raise _validation(
            field, f"{sorted(map(str, missing))[0]} is not available to this organization"
        )
    return [str(x) for x in dict.fromkeys(ids)]


def _changed(db: Session, principal: Principal, row: ClassOfService) -> None:
    configmgmt.mark_changed(db, by=principal.label, what=f"class of service {row.slug}")


@router.get("", response_model=Page[ClassOut], summary="List classes of service")
def list_classes(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[ClassOut]:
    stmt = helpers.org_filter(
        select(ClassOfService), ClassOfService.organization_id, principal, READ
    ).order_by(ClassOfService.name)
    if organization_id:
        stmt = stmt.where(ClassOfService.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(ClassOfService.name.ilike(like), ClassOfService.description.ilike(like))
        )
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post("", response_model=ClassOut, status_code=201, summary="Create a class of service")
def create_class(
    body: ClassIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ClassOut:
    org = _org_for_write(db, principal, body.organization_id)
    row = ClassOfService(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=body.name,
        slug=helpers.unique_slug(db, ClassOfService, body.name),
        description=(body.description or "").strip() or None,
        allowed_outbound_route_ids=_check_routes(db, org.id, body.allowed_outbound_route_ids),
        allowed_feature_code_keys=body.allowed_feature_code_keys,
        allow_external_forwards=body.allow_external_forwards,
        allow_external_follow_me=body.allow_external_follow_me,
        allow_intercom=body.allow_intercom,
        allow_fax=body.allow_fax,
        allow_monitor=body.allow_monitor,
        monitor_protected=body.monitor_protected,
        max_outbound_calls=body.max_outbound_calls,
        allow_paging=body.allow_paging,
        **{f: _check_destinations(db, org.id, f, getattr(body, f)) for f in DESTINATIONS},
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(
            "A class of service with that name exists in this organization.", "name_in_use"
        ) from e
    helpers.record(
        db,
        ctx,
        principal,
        "class_of_service.create",
        target_type="class_of_service",
        target=row,
        details={"slug": row.slug, "routes": len(row.allowed_outbound_route_ids)},
    )
    _changed(db, principal, row)
    db.commit()
    bus.publish(Event("class_of_service.created", {"id": str(row.id)}))
    return _outs(db, [row])[0]


@router.get("/{class_id}", response_model=ClassOut)
def get_class(
    class_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> ClassOut:
    return _outs(db, [_get(db, principal, class_id, READ)])[0]


@router.patch("/{class_id}", response_model=ClassOut)
def update_class(
    class_id: uuid.UUID,
    body: ClassPatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ClassOut:
    row = _get(db, principal, class_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    details: dict[str, Any] = {}
    if "name" in changes and changes["name"] is not None:
        try:
            name = ClassIn.model_validate(
                {"organization_id": row.organization_id, "name": changes["name"]}
            ).name
        except ValueError as e:
            raise _validation("name", str(e)) from e
        if name != row.name:
            details["name"] = {"from": row.name, "to": name}
            row.name = name
    if "description" in changes:
        row.description = (changes["description"] or "").strip() or None
        details["description"] = True
    if (
        "allowed_outbound_route_ids" in changes
        and changes["allowed_outbound_route_ids"] is not None
    ):
        row.allowed_outbound_route_ids = _check_routes(
            db, row.organization_id, changes["allowed_outbound_route_ids"]
        )
        details["routes"] = len(row.allowed_outbound_route_ids)
    if changes.get("all_feature_codes"):
        row.allowed_feature_code_keys = None
        details["feature_codes"] = "all"
    elif (
        "allowed_feature_code_keys" in changes and changes["allowed_feature_code_keys"] is not None
    ):
        try:
            keys = ClassIn.model_validate(
                {
                    "organization_id": row.organization_id,
                    "name": row.name,
                    "allowed_feature_code_keys": changes["allowed_feature_code_keys"],
                }
            ).allowed_feature_code_keys
        except ValueError as e:
            raise _validation("allowed_feature_code_keys", str(e)) from e
        row.allowed_feature_code_keys = keys
        details["feature_codes"] = len(keys or [])
    for field in (
        "allow_external_forwards",
        "allow_external_follow_me",
        "allow_intercom",
        "allow_fax",
        "allow_monitor",
        "monitor_protected",
        "allow_paging",
    ):
        if changes.get(field) is not None and changes[field] != getattr(row, field):
            setattr(row, field, changes[field])
            details[field] = changes[field]
    for field in DESTINATIONS:
        if field in changes:
            setattr(row, field, _check_destinations(db, row.organization_id, field, changes[field]))
            details[field] = None if changes[field] is None else len(changes[field])
    if changes.get("no_call_limit"):
        row.max_outbound_calls = None
        details["max_outbound_calls"] = None
    elif changes.get("max_outbound_calls") is not None:
        row.max_outbound_calls = changes["max_outbound_calls"]
        details["max_outbound_calls"] = row.max_outbound_calls
    if not details:
        return _outs(db, [row])[0]
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(
            "A class of service with that name exists in this organization.", "name_in_use"
        ) from e
    helpers.record(
        db,
        ctx,
        principal,
        "class_of_service.update",
        target_type="class_of_service",
        target=row,
        details=details,
    )
    _changed(db, principal, row)
    db.commit()
    bus.publish(Event("class_of_service.updated", {"id": str(row.id)}))
    return _outs(db, [row])[0]


@router.delete("/{class_id}", status_code=204)
def delete_class(
    class_id: uuid.UUID,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    row = _get(db, principal, class_id, WRITE)
    members = db.scalar(
        select(func.count()).select_from(Extension).where(Extension.class_of_service_id == row.id)
    )
    if members:
        raise conflict(
            f"{members} extension(s) are in this class; move them first.", "class_in_use"
        )
    helpers.record(
        db,
        ctx,
        principal,
        "class_of_service.delete",
        target_type="class_of_service",
        target=row,
        details={"slug": row.slug},
    )
    _changed(db, principal, row)
    db.delete(row)
    db.commit()
    bus.publish(Event("class_of_service.deleted", {"id": str(class_id)}))
    return Response(status_code=204)
