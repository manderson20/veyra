# SPDX-License-Identifier: AGPL-3.0-or-later
"""Limits per organization (docs/MULTI_TENANCY_MSP.md §8): what a platform
administrator allows an organization, and the checks on create."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.core.errors import conflict
from veyra.core.models import Device, Extension, OrganizationLimits


def of(db: Session, organization_id: uuid.UUID) -> OrganizationLimits | None:
    return db.get(OrganizationLimits, organization_id)


def count(db: Session, organization_id: uuid.UUID, kind: str) -> int:
    column = {"extensions": Extension.organization_id, "devices": Device.organization_id}[kind]
    return int(db.scalar(select(func.count()).where(column == organization_id)) or 0)


def check_room(db: Session, organization_id: uuid.UUID, kind: str, adding: int = 1) -> None:
    """409 ``limit_reached`` when ``adding`` more would pass the organization's limit."""
    row = of(db, organization_id)
    limit = getattr(row, f"max_{kind}", None) if row is not None else None
    if limit is None:
        return
    now = count(db, organization_id, kind)
    if now + adding > limit:
        raise conflict(
            f"This organization may have at most {limit} {kind} ({now} now). "
            "A platform administrator can raise the limit.",
            "limit_reached",
        )
