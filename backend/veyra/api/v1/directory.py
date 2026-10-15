# SPDX-License-Identifier: AGPL-3.0-or-later
"""Directory lookup for every signed-in user (docs/COMPANION.md §4): the
enabled extensions, the people they belong to, and the ring groups and queues
(docs/INTEGRATIONS.md §4), in the organizations the caller holds
``directory.read`` in."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from veyra.api.v1.extensions import _registrations
from veyra.core.db import get_db
from veyra.core.deps import require
from veyra.core.models import CallQueue, Extension, Organization, RingGroup, User
from veyra.core.security.principal import Principal

router = APIRouter(prefix="/directory", tags=["directory"])

LIMIT = 50


class DirectoryEntry(BaseModel):
    type: str = "extension"  # extension | ring_group | queue
    id: uuid.UUID
    number: str
    name: str
    organization: str
    user_display_name: str | None
    user_email: str | None
    registered: bool | None


class DirectoryOut(BaseModel):
    results: list[DirectoryEntry]
    total: int


@router.get("", response_model=DirectoryOut, summary="Look up extensions and people")
def directory(
    request: Request,
    q: str | None = Query(None, max_length=100),
    principal: Principal = Depends(require("directory.read")),
    db: Session = Depends(get_db),
) -> DirectoryOut:
    orgs = principal.organization_ids_with("directory.read")
    stmt = (
        select(Extension, Organization, User)
        .join(Organization, Organization.id == Extension.organization_id)
        .outerjoin(User, User.id == Extension.user_id)
        .where(Extension.is_enabled.is_(True), Organization.is_active.is_(True))
    )
    if orgs is not None:
        stmt = stmt.where(Extension.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Extension.number.ilike(like),
                Extension.display_name.ilike(like),
                User.display_name.ilike(like),
                User.email.ilike(like),
            )
        )
    rows = db.execute(stmt.order_by(Extension.number).limit(LIMIT + 1)).all()
    live = _registrations(request)
    results = [
        DirectoryEntry(
            id=e.id,
            number=e.number,
            name=e.display_name,
            organization=o.name,
            user_display_name=u.display_name if u else None,
            user_email=u.email if u else None,
            registered=(live.get(e.endpoint_name) or None) is not None
            and live[e.endpoint_name].registered
            if live is not None
            else None,
        )
        for e, o, u in rows[:LIMIT]
    ]
    # Ring groups and queues (docs/INTEGRATIONS.md §4), after the people.
    room = LIMIT - len(results)
    groups: list[tuple[type[RingGroup] | type[CallQueue], str]] = [
        (RingGroup, "ring_group"),
        (CallQueue, "queue"),
    ]
    for model, kind in groups:
        if room <= 0:
            break
        gstmt = (
            select(model.id, model.number, model.name, Organization.name)
            .join(Organization, Organization.id == model.organization_id)
            .where(Organization.is_active.is_(True), model.is_enabled.is_(True))
        )
        if orgs is not None:
            gstmt = gstmt.where(model.organization_id.in_(orgs or {uuid.UUID(int=0)}))
        if q and q.strip():
            like = f"%{q.strip()}%"
            gstmt = gstmt.where(or_(model.number.ilike(like), model.name.ilike(like)))
        for gid, number, name, org_name in db.execute(
            gstmt.order_by(model.number).limit(room)
        ).all():
            results.append(
                DirectoryEntry(
                    type=kind,
                    id=gid,
                    number=number,
                    name=name,
                    organization=org_name,
                    user_display_name=None,
                    user_email=None,
                    registered=None,
                )
            )
        room = LIMIT - len(results)
    return DirectoryOut(results=results, total=len(results))
