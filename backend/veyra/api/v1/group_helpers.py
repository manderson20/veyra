# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared pieces of the ring group, queue and pickup group routers
(docs/RING_GROUPS_QUEUES.md): organization scoping, slugs, numbers from the
shared number space, member loading and audit."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from veyra.configmgmt import service as configmgmt
from veyra.core import audit
from veyra.core.deps import RequestContext
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.models import Extension, Organization
from veyra.core.security.principal import Principal
from veyra.telephony import routing
from veyra.telephony.numbering import load_numbering_plan, number_owner

READ = "groups.read"
WRITE = "groups.write"


def validation(field: str, message: str, code: str = "validation_failed") -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code=code,
        errors=[{"field": field, "message": message}],
    )


class MemberOut(BaseModel):
    extension_id: uuid.UUID
    number: str
    display_name: str
    is_enabled: bool
    position: int | None = None
    penalty: int | None = None


class MembershipOut(BaseModel):
    """A group an extension belongs to (extension API)."""

    id: uuid.UUID
    name: str
    number: str | None = None


def org_filter(stmt: Select[Any], column: Any, principal: Principal, perm: str) -> Select[Any]:
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(column.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def org_for_write(db: Session, principal: Principal, organization_id: uuid.UUID) -> Organization:
    if not principal.has(WRITE, organization_id):
        raise forbidden()
    org = db.get(Organization, organization_id)
    if org is None:
        raise not_found("Organization")
    if not org.is_active:
        raise conflict("This organization is inactive.", "organization_inactive")
    return org


def org_names(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return {o.id: o.name for o in db.scalars(select(Organization).where(Organization.id.in_(ids)))}


def unique_slug(db: Session, model: Any, name: str) -> str:
    base = routing.slugify(name)
    slug = base
    n = 2
    while db.scalar(select(model.id).where(model.slug == slug)) is not None:
        slug = f"{base[: 40 - len(str(n)) - 1]}-{n}"
        n += 1
    return slug


def check_number(db: Session, number: str, kind: str, exclude: uuid.UUID | None) -> None:
    """The number must fit the numbering plan and be free across extensions,
    ring groups and queues (``409 number_in_use``)."""
    plan = load_numbering_plan(db)
    problems = plan.check_number(number)
    if problems:
        raise validation("number", " ".join(problems), code="number_not_in_plan")
    owner = number_owner(db, number, exclude=(kind, exclude) if exclude else None)
    if owner is not None:
        raise ProblemError(
            409,
            "Number in use",
            f"{owner.capitalize()} {number} already exists.",
            code="number_in_use",
            errors=[{"field": "number", "message": f"already used by a {owner}"}],
        )


def load_members(
    db: Session, organization_id: uuid.UUID, extension_ids: list[uuid.UUID], field: str
) -> dict[uuid.UUID, Extension]:
    """The extensions of ``extension_ids``; 422 when one is missing, in another
    organization or listed twice."""
    seen: set[uuid.UUID] = set()
    for ext_id in extension_ids:
        if ext_id in seen:
            raise validation(field, "an extension is listed twice")
        seen.add(ext_id)
    if not seen:
        return {}
    found = {e.id: e for e in db.scalars(select(Extension).where(Extension.id.in_(seen)))}
    for ext_id in seen:
        ext = found.get(ext_id)
        if ext is None or ext.organization_id != organization_id:
            raise validation(field, "extension not found in this organization")
    return found


def extensions_by_id(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, Extension]:
    if not ids:
        return {}
    return {e.id: e for e in db.scalars(select(Extension).where(Extension.id.in_(ids)))}


def record(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    *,
    target_type: str,
    target: Any,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=target.organization_id,
        target_type=target_type,
        target_id=target.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": target.name, **details},
    )
    configmgmt.mark_changed(db, by=principal.label, what=f"{action} {target.name}")
