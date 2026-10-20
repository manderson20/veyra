# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organizations."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1.schemas import OrganizationIn, OrganizationOut, OrganizationPatch
from veyra.configmgmt import service as configmgmt
from veyra.core import audit, tenancy
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import conflict, forbidden, not_found
from veyra.core.events import Event, bus
from veyra.core.models import Organization
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _visible(principal: Principal) -> Select[Organization]:
    stmt = select(Organization)
    orgs = principal.organization_ids_with("organizations.read")
    if orgs is not None:
        stmt = stmt.where(Organization.id.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


@router.get("", response_model=Page[OrganizationOut], summary="List organizations")
def list_organizations(
    q: str | None = Query(None, max_length=100, description="Search name or slug"),
    page: PageParams = Depends(page_params),
    principal: Principal = Depends(require("organizations.read")),
    db: Session = Depends(get_db),
) -> Page[OrganizationOut]:
    stmt = _visible(principal).order_by(Organization.name)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(Organization.name.ilike(like), Organization.slug.ilike(like)))
    rows, total = paginate(db, stmt, page)
    return Page(
        items=[OrganizationOut.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("", response_model=OrganizationOut, status_code=201, summary="Create an organization")
def create_organization(
    body: OrganizationIn,
    principal: Principal = Depends(require("organizations.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> OrganizationOut:
    tenancy.check_may_activate(db)
    org = Organization(
        id=uuid.uuid4(),
        name=body.name,
        slug=body.slug,
        timezone=body.timezone,
        engine_namespace=tenancy.new_namespace(db, body.slug),
    )
    db.add(org)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(f"An organization with slug {body.slug!r} already exists.") from e
    audit.record(
        db,
        action="organization.create",
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
    bus.publish(Event("organization.created", {"organization_id": str(org.id), "slug": org.slug}))
    return OrganizationOut.model_validate(org)


@router.get("/{organization_id}", response_model=OrganizationOut, summary="Get an organization")
def get_organization(
    organization_id: uuid.UUID,
    principal: Principal = Depends(require("organizations.read")),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    org = db.scalar(_visible(principal).where(Organization.id == organization_id))
    if org is None:
        raise not_found("Organization")
    return OrganizationOut.model_validate(org)


@router.patch(
    "/{organization_id}", response_model=OrganizationOut, summary="Update an organization"
)
def update_organization(
    organization_id: uuid.UUID,
    body: OrganizationPatch,
    principal: Principal = Depends(require("organizations.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> OrganizationOut:
    org = db.get(Organization, organization_id)
    if org is None:
        raise not_found("Organization")
    changes = body.model_dump(exclude_unset=True)
    # The allow list widens what phones may present to the carrier: a routing matter.
    if "caller_id_allow_list" in changes and not principal.has("routing.write", org.id):
        raise forbidden("Changing the caller ID allow list needs routing.write.")
    if changes.get("is_active") and not org.is_active:
        tenancy.check_may_activate(db, exclude=org.id)
    if "is_active" in changes and changes["is_active"] != org.is_active:
        configmgmt.mark_changed(db, by=principal.label, what=f"organization {org.slug}")
    if "moh_class_id" in changes:
        from veyra.api.v1 import hold_music

        hold_music.check_set(db, org.id, changes["moh_class_id"], "moh_class_id")
    for k, v in changes.items():
        setattr(org, k, v)
    if "moh_class_id" in changes:
        configmgmt.mark_changed(db, by=principal.label, what=f"hold music of {org.slug}")
    if "intercom_default" in changes:
        configmgmt.mark_changed(db, by=principal.label, what=f"intercom default of {org.slug}")
    if "directed_pickup" in changes:
        configmgmt.mark_changed(db, by=principal.label, what=f"directed pickup of {org.slug}")
    audit.record(
        db,
        action="organization.update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=org.id,
        target_type="organization",
        target_id=org.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=changes,
    )
    db.commit()
    return OrganizationOut.model_validate(org)
