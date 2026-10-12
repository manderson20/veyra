# SPDX-License-Identifier: AGPL-3.0-or-later
"""Audit log (read-only)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from veyra.api.v1.schemas import ORM
from veyra.core.db import get_db
from veyra.core.deps import require
from veyra.core.models import AuditEvent
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditOut(ORM):
    id: int
    occurred_at: datetime
    actor_type: str
    actor_label: str
    organization_id: uuid.UUID | None
    action: str
    target_type: str | None
    target_id: str | None
    outcome: str
    ip_address: str | None
    request_id: str | None
    details: dict[str, Any]


@router.get("", response_model=Page[AuditOut], summary="Search the audit log")
def list_audit(
    q: str | None = Query(None, max_length=100, description="Match action or actor"),
    outcome: str | None = Query(None, pattern="^(success|failure|denied)$"),
    page: PageParams = Depends(page_params),
    principal: Principal = Depends(require("audit.read")),
    db: Session = Depends(get_db),
) -> Page[AuditOut]:
    stmt = select(AuditEvent).order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
    orgs = principal.organization_ids_with("audit.read")
    if orgs is not None:
        stmt = stmt.where(AuditEvent.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(AuditEvent.action.ilike(like), AuditEvent.actor_label.ilike(like)))
    if outcome:
        stmt = stmt.where(AuditEvent.outcome == outcome)
    rows, total = paginate(db, stmt, page)
    return Page(
        items=[AuditOut.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
