# SPDX-License-Identifier: AGPL-3.0-or-later
"""Audit log (read-only)."""

from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, or_, select
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


EXPORT_LIMIT = 100_000


def _search(
    principal: Principal,
    q: str | None,
    outcome: str | None,
    since: datetime | None,
    until: datetime | None,
) -> Select[AuditEvent]:
    stmt = select(AuditEvent).order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
    orgs = principal.organization_ids_with("audit.read")
    if orgs is not None:
        stmt = stmt.where(AuditEvent.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(AuditEvent.action.ilike(like), AuditEvent.actor_label.ilike(like)))
    if outcome:
        stmt = stmt.where(AuditEvent.outcome == outcome)
    if since:
        stmt = stmt.where(AuditEvent.occurred_at >= since)
    if until:
        stmt = stmt.where(AuditEvent.occurred_at < until)
    return stmt


@router.get("", response_model=Page[AuditOut], summary="Search the audit log")
def list_audit(
    q: str | None = Query(None, max_length=100, description="Match action or actor"),
    outcome: str | None = Query(None, pattern="^(success|failure|denied)$"),
    since: datetime | None = Query(None, alias="from"),
    until: datetime | None = Query(None, alias="to"),
    page: PageParams = Depends(page_params),
    principal: Principal = Depends(require("audit.read")),
    db: Session = Depends(get_db),
) -> Page[AuditOut]:
    rows, total = paginate(db, _search(principal, q, outcome, since, until), page)
    return Page(
        items=[AuditOut.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


CSV_COLUMNS = (
    "occurred_at",
    "actor_type",
    "actor",
    "organization_id",
    "action",
    "target_type",
    "target_id",
    "outcome",
    "ip_address",
    "request_id",
    "details",
)


@router.get("/export.csv", summary="Export the audit log as CSV (same filters)")
def export_audit(
    q: str | None = Query(None, max_length=100),
    outcome: str | None = Query(None, pattern="^(success|failure|denied)$"),
    since: datetime | None = Query(None, alias="from"),
    until: datetime | None = Query(None, alias="to"),
    principal: Principal = Depends(require("audit.read")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    rows = list(db.scalars(_search(principal, q, outcome, since, until).limit(EXPORT_LIMIT)))

    def lines() -> Iterator[str]:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(CSV_COLUMNS)
        for r in rows:
            w.writerow(
                [
                    r.occurred_at.isoformat(),
                    r.actor_type,
                    r.actor_label,
                    str(r.organization_id or ""),
                    r.action,
                    r.target_type or "",
                    r.target_id or "",
                    r.outcome,
                    r.ip_address or "",
                    r.request_id or "",
                    json.dumps(r.details or {}, sort_keys=True, default=str),
                ]
            )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()
        if not rows:
            yield buf.getvalue()

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return StreamingResponse(
        lines(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="audit-{stamp}.csv"'},
    )
