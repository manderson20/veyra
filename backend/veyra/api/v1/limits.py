# SPDX-License-Identifier: AGPL-3.0-or-later
"""Limits per organization (docs/MULTI_TENANCY_MSP.md §8). Platform
administrators set them; an organization's own administrators see them."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from veyra.configmgmt import service as configmgmt
from veyra.core import audit, limits
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import not_found
from veyra.core.models import Organization, OrganizationLimits
from veyra.core.models.base import utcnow
from veyra.core.security.principal import Principal

router = APIRouter(tags=["organizations"])


class LimitsIn(BaseModel):
    max_outside_calls: int | None = Field(None, ge=1, le=10000)
    max_extensions: int | None = Field(None, ge=1, le=100000)
    max_devices: int | None = Field(None, ge=1, le=100000)


class LimitsOut(LimitsIn):
    organization_id: uuid.UUID
    extensions: int
    devices: int
    updated_at: datetime | None = None
    updated_by: str | None = None


def _out(db: Session, org_id: uuid.UUID) -> LimitsOut:
    row = limits.of(db, org_id)
    return LimitsOut(
        organization_id=org_id,
        max_outside_calls=row.max_outside_calls if row else None,
        max_extensions=row.max_extensions if row else None,
        max_devices=row.max_devices if row else None,
        extensions=limits.count(db, org_id, "extensions"),
        devices=limits.count(db, org_id, "devices"),
        updated_at=row.updated_at if row else None,
        updated_by=row.updated_by if row else None,
    )


@router.get(
    "/organizations/{organization_id}/limits",
    response_model=LimitsOut,
    summary="What the organization may use",
)
def get_limits(
    organization_id: uuid.UUID,
    principal: Principal = Depends(require("organizations.read")),
    db: Session = Depends(get_db),
) -> LimitsOut:
    if db.get(Organization, organization_id) is None or not principal.has(
        "organizations.read", organization_id
    ):
        raise not_found("Organization")
    return _out(db, organization_id)


@router.put(
    "/organizations/{organization_id}/limits",
    response_model=LimitsOut,
    summary="Set what the organization may use",
)
def put_limits(
    organization_id: uuid.UUID,
    body: LimitsIn,
    principal: Principal = Depends(require("organizations.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> LimitsOut:
    org = db.get(Organization, organization_id)
    if org is None:
        raise not_found("Organization")
    row = limits.of(db, org.id)
    before = (row.max_outside_calls, row.max_extensions, row.max_devices) if row else None
    if row is None:
        row = OrganizationLimits(organization_id=org.id)
        db.add(row)
    row.max_outside_calls = body.max_outside_calls
    row.max_extensions = body.max_extensions
    row.max_devices = body.max_devices
    row.updated_at, row.updated_by = utcnow(), principal.label
    if before is None or before[0] != body.max_outside_calls:
        # The concurrent call limit is in the dialplan.
        configmgmt.mark_changed(
            db, by=principal.label, what=f"limits of {org.slug}", organization_id=org.id
        )
    audit.record(
        db,
        action="organization.limits",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=org.id,
        target_type="organization",
        target_id=org.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=body.model_dump(),
    )
    db.commit()
    return _out(db, org.id)
