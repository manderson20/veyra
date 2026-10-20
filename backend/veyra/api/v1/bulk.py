# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bulk CSV import and export (issue #41; docs/BULK_IMPORT.md)."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from veyra.bulk import service
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import (
    RequestContext,
    check_recent_auth,
    current_principal,
    request_context,
    require,
)
from veyra.core.errors import ProblemError, forbidden, not_found
from veyra.core.models import Organization
from veyra.core.security.principal import Principal

router = APIRouter(prefix="/bulk", tags=["bulk"])


def _kind(name: str) -> Any:
    kind = service.KINDS.get(name)
    if kind is None:
        raise not_found("Import kind")
    return kind


def _org(db: Session, principal: Principal, organization_id: uuid.UUID, perm: str) -> Organization:
    if not principal.has(perm, organization_id):
        raise forbidden()
    org = db.get(Organization, organization_id)
    if org is None:
        raise not_found("Organization")
    return org


@router.get("/kinds", summary="What can be imported and exported, with the columns")
def kinds(principal: Principal = Depends(current_principal)) -> list[dict[str, Any]]:
    return [
        {
            "name": k.name,
            "label": k.label,
            "key": k.key,
            "columns": k.columns,
            "permission": k.permission,
        }
        for k in service.KINDS.values()
    ]


@router.get("/{kind}/export.csv", summary="Export as CSV (template=true: the header only)")
def export_csv(
    kind: str,
    organization_id: uuid.UUID,
    template: bool = False,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
) -> Response:
    k = _kind(kind)
    org = _org(db, principal, organization_id, k.permission.replace(".write", ".read"))
    rows = [] if template else k.export(db, org)
    name = f"veyra-{k.name.replace('_', '-')}-{org.slug}{'-template' if template else ''}.csv"
    return Response(
        content=service.to_csv(k, rows),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",
        },
    )


class ImportIn(BaseModel):
    csv: str = Field(max_length=service.MAX_BYTES)


class RowOut(BaseModel):
    row: int
    key: str
    action: str
    message: str | None
    notes: list[str]


class ImportOut(BaseModel):
    dry_run: bool
    counts: dict[str, int]
    rows: list[RowOut]


@router.post(
    "/{kind}/import", response_model=ImportOut, summary="Validate (dry run) or import a CSV"
)
def import_csv(
    kind: str,
    body: ImportIn,
    request: Request,
    organization_id: uuid.UUID,
    dry_run: bool = Query(True, description="Validate only; nothing is saved"),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ImportOut:
    k = _kind(kind)
    org = _org(db, principal, organization_id, k.permission)
    if k.name == "users" and not dry_run:
        # Granting roles is a sensitive action (issue #137).
        check_recent_auth(db, principal)
    rows = service.parse_csv(k, body.csv)
    if not rows:
        raise ProblemError(422, "Empty file", "The file has no rows.", code="empty")
    results = service.run_import(
        k, rows, principal=principal, request=request, rctx=ctx, org=org, dry_run=dry_run
    )
    counts = {a: 0 for a in ("create", "update", "unchanged", "error")}
    for r in results:
        counts[r.action] = counts.get(r.action, 0) + 1
    if not dry_run:
        audit.record(
            db,
            action="bulk.import",
            outcome="success" if not counts["error"] else "partial",
            actor_user_id=principal.user_id,
            actor_label=principal.label,
            organization_id=org.id,
            target_type="bulk",
            target_id=k.name,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"kind": k.name, "rows": len(rows), **counts},
        )
        db.commit()
    return ImportOut(dry_run=dry_run, counts=counts, rows=[RowOut(**asdict(r)) for r in results])


@router.post("/freepbx/convert", summary="Turn a FreePBX database dump into import files")
async def freepbx_convert(
    file: UploadFile = File(...),
    voicemail: UploadFile | None = File(None),
    principal: Principal = Depends(require("extensions.write")),
) -> dict[str, Any]:
    """Issue #42: ``mysqldump asterisk`` of a FreePBX server (``.sql``,
    ``.sql.gz``, or a FreePBX 14 backup) → the CSV files of the extensions,
    ring groups and inbound routes, to check and import here. Nothing is
    saved by this call."""
    from veyra.bulk import freepbx

    data = await file.read(freepbx.MAX_DUMP_BYTES + 1)
    vm_text = None
    if voicemail is not None:
        vm_text = (await voicemail.read(1024 * 1024)).decode("utf-8", errors="replace")
    try:
        conv = freepbx.convert(freepbx.read_upload(data, file.filename), vm_text)
    except freepbx.FreepbxError as e:
        raise ProblemError(422, "Not a usable FreePBX dump", str(e), code="freepbx_invalid") from e
    return {"csv": conv.csv, "counts": conv.counts, "warnings": conv.warnings[:200]}
