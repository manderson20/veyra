# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caller block list (docs/CALL_FEATURES.md §4.8): numbers an organization
refuses, how withheld numbers are treated and where blocked calls go. Changes
to numbers reach the engine at once; the policy needs a deployment."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from veyra.api.v1 import destinations
from veyra.api.v1.destinations import DestinationIn, DestinationOut, Resolver, check_destination
from veyra.configmgmt import service as configmgmt
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.models import CallerBlock, CallerBlockPolicy, Organization
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import blacklist

router = APIRouter(prefix="/caller-blocks", tags=["caller-blocks"])

READ = "routing.read"
WRITE = "routing.write"
MAX_IMPORT = 5000


def _validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


# ----------------------------------------------------------------- schemas


class CallerBlockIn(BaseModel):
    organization_id: uuid.UUID
    number: str = Field(min_length=2, max_length=64)
    description: str | None = Field(None, max_length=200)


class CallerBlockPatch(BaseModel):
    description: str | None = Field(None, max_length=200)


class CallerBlockOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    number: str
    description: str | None
    source: str
    hits: int
    last_hit_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PolicyIn(BaseModel):
    organization_id: uuid.UUID
    block_anonymous: bool = False
    destination: DestinationIn = Field(default_factory=lambda: DestinationIn(type="hangup"))


class PolicyOut(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    block_anonymous: bool
    anonymous_hits: int
    destination: DestinationOut
    blocked_numbers: int
    total_hits: int
    updated_at: datetime | None


class ImportIn(BaseModel):
    organization_id: uuid.UUID
    # CSV or one number per line: "number[,description]".
    text: str = Field(min_length=1, max_length=400_000)


class ImportOut(BaseModel):
    added: int
    updated: int
    skipped: list[str]


# ----------------------------------------------------------------- helpers


def _org_filter(stmt: Select[Any], column: Any, principal: Principal, perm: str) -> Select[Any]:
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(column.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _org_for(
    db: Session, principal: Principal, organization_id: uuid.UUID, perm: str
) -> Organization:
    if not principal.has(perm, organization_id):
        raise forbidden()
    org = db.get(Organization, organization_id)
    if org is None:
        raise not_found("Organization")
    if perm == WRITE and not org.is_active:
        raise conflict("This organization is inactive.", "organization_inactive")
    return org


def _outs(db: Session, rows: list[CallerBlock]) -> list[CallerBlockOut]:
    if not rows:
        return []
    org_ids = {r.organization_id for r in rows}
    orgs = {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids)))}
    return [
        CallerBlockOut(
            id=r.id,
            organization_id=r.organization_id,
            organization_name=orgs[r.organization_id].name if r.organization_id in orgs else "",
            number=r.number,
            description=r.description,
            source=r.source,
            hits=r.hits,
            last_hit_at=r.last_hit_at,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


def _policy_out(db: Session, org: Organization, policy: CallerBlockPolicy | None) -> PolicyOut:
    count, hits = db.execute(
        select(func.count(), func.coalesce(func.sum(CallerBlock.hits), 0)).where(
            CallerBlock.organization_id == org.id
        )
    ).one()
    if policy is None:
        dest = DestinationOut(
            type="hangup", extension_id=None, ivr_id=None, label="Hang up", missing=False
        )
        return PolicyOut(
            organization_id=org.id,
            organization_name=org.name,
            block_anonymous=False,
            anonymous_hits=0,
            destination=dest,
            blocked_numbers=int(count),
            total_hits=int(hits),
            updated_at=None,
        )
    resolver = Resolver(db)
    ref = destinations.ref_of(policy, "destination")
    resolver.load([ref])
    return PolicyOut(
        organization_id=org.id,
        organization_name=org.name,
        block_anonymous=bool(policy.block_anonymous),
        anonymous_hits=int(policy.anonymous_hits or 0),
        destination=resolver.out_ref(ref),
        blocked_numbers=int(count),
        total_hits=int(hits),
        updated_at=policy.updated_at,
    )


def _audit(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    org: Organization,
    target_id: uuid.UUID | None,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=org.id,
        target_type="caller_block",
        target_id=target_id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=details,
    )


# ----------------------------------------------------------------- numbers


@router.get("", response_model=Page[CallerBlockOut], summary="List blocked callers")
def list_blocks(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[CallerBlockOut]:
    stmt = _org_filter(select(CallerBlock), CallerBlock.organization_id, principal, READ).order_by(
        CallerBlock.hits.desc(), CallerBlock.number
    )
    if organization_id:
        stmt = stmt.where(CallerBlock.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(CallerBlock.number.ilike(like), CallerBlock.description.ilike(like)))
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post("", response_model=CallerBlockOut, status_code=201, summary="Block a caller")
def add_block(
    body: CallerBlockIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> CallerBlockOut:
    """Takes effect at once; no deployment is needed."""
    org = _org_for(db, principal, body.organization_id, WRITE)
    try:
        number = blacklist.normalize(body.number)
    except blacklist.BlockError as e:
        raise _validation("number", str(e)) from e
    existing = db.scalar(
        select(CallerBlock).where(
            CallerBlock.organization_id == org.id, CallerBlock.number == number
        )
    )
    if existing is not None:
        raise conflict(f"{number} is already blocked.", "number_already_blocked")
    row, _ = blacklist.add(
        db,
        org,
        number,
        description=(body.description or "").strip() or None,
        source="api",
        adapter=request.app.state.telephony,
    )
    _audit(db, ctx, principal, "caller_block.add", org, row.id, {"number": number})
    db.commit()
    return _outs(db, [row])[0]


@router.patch("/{block_id}", response_model=CallerBlockOut)
def update_block(
    block_id: uuid.UUID,
    body: CallerBlockPatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> CallerBlockOut:
    stmt = _org_filter(select(CallerBlock), CallerBlock.organization_id, principal, WRITE)
    row = db.scalar(stmt.where(CallerBlock.id == block_id))
    if row is None:
        raise not_found("Blocked caller")
    desc = (body.description or "").strip() or None
    if desc != row.description:
        row.description = desc
        org = db.get(Organization, row.organization_id)
        if org is not None:
            _audit(db, ctx, principal, "caller_block.update", org, row.id, {"number": row.number})
        db.commit()
    return _outs(db, [row])[0]


@router.delete("/{block_id}", status_code=204, summary="Unblock a caller")
def delete_block(
    block_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    stmt = _org_filter(select(CallerBlock), CallerBlock.organization_id, principal, WRITE)
    row = db.scalar(stmt.where(CallerBlock.id == block_id))
    if row is None:
        raise not_found("Blocked caller")
    org = db.get(Organization, row.organization_id)
    if org is None:
        raise not_found("Organization")
    number = row.number
    blacklist.remove(db, org, row, adapter=request.app.state.telephony)
    _audit(db, ctx, principal, "caller_block.remove", org, block_id, {"number": number})
    db.commit()
    return Response(status_code=204)


@router.post("/import", response_model=ImportOut, summary="Import blocked callers (CSV)")
def import_blocks(
    body: ImportIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ImportOut:
    """One number per line, optionally followed by a comma and a description;
    a header line starting with "number" is skipped."""
    org = _org_for(db, principal, body.organization_id, WRITE)
    added = updated = 0
    skipped: list[str] = []
    rows = list(csv.reader(io.StringIO(body.text)))
    if len(rows) > MAX_IMPORT:
        raise _validation("text", f"at most {MAX_IMPORT} lines")
    adapter = request.app.state.telephony
    for cells in rows:
        if not cells or not cells[0].strip():
            continue
        raw = cells[0].strip()
        if raw.lower() in ("number", "phone", "caller"):
            continue
        description = cells[1].strip()[:200] if len(cells) > 1 and cells[1].strip() else None
        try:
            number = blacklist.normalize(raw)
        except blacklist.BlockError:
            skipped.append(raw)
            continue
        _, created = blacklist.add(
            db, org, number, description=description, source="csv", adapter=adapter
        )
        if created:
            added += 1
        else:
            updated += 1
    _audit(
        db,
        ctx,
        principal,
        "caller_block.import",
        org,
        None,
        {"added": added, "updated": updated, "skipped": len(skipped)},
    )
    db.commit()
    return ImportOut(added=added, updated=updated, skipped=skipped[:50])


@router.get("/export", summary="Export blocked callers (CSV)")
def export_blocks(
    organization_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Response:
    org = _org_for(db, principal, organization_id, READ)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["number", "description", "hits", "last_hit_at", "source"])
    for row in db.scalars(
        select(CallerBlock)
        .where(CallerBlock.organization_id == org.id)
        .order_by(CallerBlock.number)
    ):
        writer.writerow(
            [
                row.number,
                row.description or "",
                row.hits,
                row.last_hit_at.isoformat() if row.last_hit_at else "",
                row.source,
            ]
        )
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="blocked-callers-{org.slug}.csv"'},
    )


# ----------------------------------------------------------------- policy


@router.get("/policy", response_model=PolicyOut, summary="Block list policy of an organization")
def get_policy(
    organization_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> PolicyOut:
    org = _org_for(db, principal, organization_id, READ)
    return _policy_out(db, org, blacklist.policy_for(db, org.id))


@router.put("/policy", response_model=PolicyOut, summary="Change the block list policy")
def put_policy(
    body: PolicyIn,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PolicyOut:
    """Anonymous-caller blocking and the destination are part of the dialplan:
    a deployment applies them."""
    org = _org_for(db, principal, body.organization_id, WRITE)
    check_destination(db, org.id, body.destination, field="destination", allow_hangup=True)
    policy = blacklist.policy_for(db, org.id, create=True)
    assert policy is not None
    changed = policy.block_anonymous != body.block_anonymous or (
        destinations.ref_of(policy, "destination") != body.destination.as_ref()
    )
    policy.block_anonymous = body.block_anonymous
    destinations.apply(policy, "destination", body.destination)
    db.flush()
    if changed:
        _audit(
            db,
            ctx,
            principal,
            "caller_block.policy",
            org,
            policy.id,
            {
                "block_anonymous": body.block_anonymous,
                "destination": body.destination.model_dump(mode="json"),
            },
        )
        configmgmt.mark_changed(db, by=principal.label, what="caller block policy")
    db.commit()
    return _policy_out(db, org, policy)
