# SPDX-License-Identifier: AGPL-3.0-or-later
"""Portal layouts (docs/USER_PORTAL.md §10): the layout document's shape,
and which template a user resolves to (role, department, building,
organization, system; the nearest scope wins, then the highest priority)."""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from veyra.core.models import Extension, PortalTemplate, RoleAssignment
from veyra.core.models.identity import Role

COLS = 12
MAX_TABS = 8
MAX_WIDGETS = 40
SCOPES = ("system", "organization", "building", "department", "role")
Scope = Literal["system", "organization", "building", "department", "role"]
_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class PlacedWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=_KEY_RE.pattern)
    instance: str = Field("default", max_length=64)
    x: int = Field(ge=0, le=COLS - 1)
    y: int = Field(ge=0, le=10_000)
    w: int = Field(ge=1, le=COLS)
    h: int = Field(ge=1, le=200)
    settings: dict[str, Any] | None = None

    @field_validator("settings")
    @classmethod
    def _small(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and len(str(v)) > 4000:
            raise ValueError("widget settings are too large")
        return v


class LayoutTab(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=_ID_RE.pattern)
    name: str = Field(min_length=1, max_length=40)
    widgets: list[PlacedWidget] = Field(default_factory=list, max_length=MAX_WIDGETS)


class LayoutDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    tabs: list[LayoutTab] = Field(min_length=1, max_length=MAX_TABS)

    @field_validator("tabs")
    @classmethod
    def _unique_tabs(cls, v: list[LayoutTab]) -> list[LayoutTab]:
        ids = [t.id for t in v]
        if len(set(ids)) != len(ids):
            raise ValueError("tab ids must be unique")
        for t in v:
            for w in t.widgets:
                if w.x + w.w > COLS:
                    raise ValueError(f"widget {w.key} runs past the grid")
        return v


def validate_layout(data: Any) -> dict[str, Any]:
    return LayoutDoc.model_validate(data).model_dump(mode="json", exclude_none=True)


def _primary_extension(db: Session, user_id: uuid.UUID) -> Extension | None:
    return db.scalar(
        select(Extension).where(Extension.user_id == user_id).order_by(Extension.number).limit(1)
    )


def resolve_template(
    db: Session, user_id: uuid.UUID, organization_id: uuid.UUID | None
) -> PortalTemplate | None:
    """The template for a user: the nearest enabled scope wins — a role of
    theirs in the organization, their primary extension's department, its
    building, the organization, the system — ties by priority then name."""
    ext = _primary_extension(db, user_id)
    org_id = organization_id or (ext.organization_id if ext else None)
    role_keys = set(
        db.scalars(
            select(Role.key)
            .join(RoleAssignment, RoleAssignment.role_id == Role.id)
            .where(RoleAssignment.user_id == user_id)
        )
    )
    rows = db.scalars(
        select(PortalTemplate).where(
            PortalTemplate.is_enabled.is_(True),
            or_(
                PortalTemplate.organization_id.is_(None),
                PortalTemplate.organization_id == org_id,
            ),
        )
    ).all()
    rank: dict[str, int] = {
        "role": 0,
        "department": 1,
        "building": 2,
        "organization": 3,
        "system": 4,
    }

    def matches(t: PortalTemplate) -> bool:
        if t.scope == "system":
            return t.organization_id is None
        if t.organization_id != org_id or org_id is None:
            return False
        if t.scope == "organization":
            return True
        if t.scope == "role":
            return t.scope_ref in role_keys
        if ext is None or not t.scope_ref:
            return False
        if t.scope == "department":
            return str(ext.department_id) == t.scope_ref
        if t.scope == "building":
            return str(ext.building_id) == t.scope_ref
        return False

    candidates = [t for t in rows if matches(t)]
    candidates.sort(key=lambda t: (rank.get(t.scope, 9), -t.priority, t.name.lower()))
    return candidates[0] if candidates else None
