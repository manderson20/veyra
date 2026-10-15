# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call and queue reports (docs/REPORTING.md §5.1)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from veyra.core.db import get_db
from veyra.core.deps import require
from veyra.core.errors import ProblemError, forbidden
from veyra.core.models import Organization
from veyra.core.models.base import utcnow
from veyra.core.security.principal import Principal
from veyra.reporting import reports

router = APIRouter(prefix="/reports", tags=["reports"])
READ = "reports.read"
MAX_DAYS = 400


def _period(since: datetime | None, until: datetime | None) -> tuple[datetime, datetime]:
    until = until or utcnow()
    since = since or until - timedelta(days=7)
    if since >= until:
        raise ProblemError(
            422, "Validation failed", "'from' must be before 'to'.", code="validation_failed"
        )
    if until - since > timedelta(days=MAX_DAYS):
        raise ProblemError(
            422,
            "Validation failed",
            f"A report covers at most {MAX_DAYS} days.",
            code="validation_failed",
        )
    return since, until


def _scope(
    db: Session, principal: Principal, organization_id: uuid.UUID | None
) -> tuple[set[uuid.UUID] | None, str]:
    orgs = principal.organization_ids_with(READ)
    if organization_id is not None and orgs is not None and organization_id not in orgs:
        raise forbidden()
    tz = "UTC"
    if organization_id is not None:
        org = db.get(Organization, organization_id)
        if org is not None:
            tz = org.timezone or "UTC"
    elif orgs is not None and len(orgs) == 1:
        org = db.get(Organization, next(iter(orgs)))
        tz = org.timezone if org is not None and org.timezone else "UTC"
    return orgs, tz


@router.get("/calls", summary="Calls by day, hour, extension and trunk")
def calls(
    organization_id: uuid.UUID | None = None,
    since: datetime | None = Query(None, alias="from"),
    until: datetime | None = Query(None, alias="to"),
    tz: str | None = Query(None, max_length=64, description="Time zone for days and hours"),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    start, end = _period(since, until)
    orgs, default_tz = _scope(db, principal, organization_id)
    zone = tz or default_tz
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ProblemError(
            422, "Validation failed", f"Unknown time zone {zone!r}.", code="validation_failed"
        ) from e
    return {
        "from": start,
        "to": end,
        **reports.calls_report(
            db, since=start, until=end, tz=zone, org_ids=orgs, organization_id=organization_id
        ),
    }


@router.get("/queues", summary="Queue offered, answered, abandoned, wait and agents")
def queues(
    organization_id: uuid.UUID | None = None,
    since: datetime | None = Query(None, alias="from"),
    until: datetime | None = Query(None, alias="to"),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    start, end = _period(since, until)
    orgs, _ = _scope(db, principal, organization_id)
    return {
        "from": start,
        "to": end,
        "queues": reports.queues_report(
            db, since=start, until=end, org_ids=orgs, organization_id=organization_id
        ),
    }
