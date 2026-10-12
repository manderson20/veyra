# SPDX-License-Identifier: AGPL-3.0-or-later
"""Global search across objects the caller may see."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from veyra.api.v1.extensions import _visible as visible_extensions
from veyra.api.v1.organizations import _visible as visible_orgs
from veyra.api.v1.users import _user_scope
from veyra.core.db import get_db
from veyra.core.deps import current_principal
from veyra.core.models import Extension, Organization, User
from veyra.core.security.principal import Principal

router = APIRouter(tags=["search"])

LIMIT = 8


@router.get("/search", summary="Search organizations, users and extensions")
def search(
    q: str = Query(..., min_length=2, max_length=100),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    like = f"%{q.lower()}%"
    results: list[dict[str, Any]] = []
    if principal.has_any_scope("organizations.read"):
        stmt = (
            visible_orgs(principal)
            .where(or_(Organization.name.ilike(like), Organization.slug.ilike(like)))
            .limit(LIMIT)
        )
        results += [
            {
                "type": "organization",
                "id": str(o.id),
                "title": o.name,
                "subtitle": o.slug,
                "href": f"/organizations/view/?id={o.id}",
            }
            for o in db.scalars(stmt)
        ]
    if principal.has_any_scope("users.read"):
        user_stmt = (
            _user_scope(principal, "users.read")
            .where(or_(User.email.ilike(like), User.display_name.ilike(like)))
            .limit(LIMIT)
        )
        results += [
            {
                "type": "user",
                "id": str(u.id),
                "title": u.display_name,
                "subtitle": u.email,
                "href": f"/users/view/?id={u.id}",
            }
            for u in db.scalars(user_stmt)
        ]
    if principal.has_any_scope("extensions.read"):
        ext_stmt = (
            visible_extensions(principal, "extensions.read")
            .where(or_(Extension.number.ilike(like), Extension.display_name.ilike(like)))
            .order_by(Extension.number)
            .limit(LIMIT)
        )
        results += [
            {
                "type": "extension",
                "id": str(e.id),
                "title": f"{e.number} {e.display_name}",
                "subtitle": e.endpoint_name,
                "href": f"/extensions/view/?id={e.id}",
            }
            for e in db.scalars(ext_stmt)
        ]
    return {"results": results}
