# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bulk CSV import and export (issue #41; docs/BULK_IMPORT.md)."""

from __future__ import annotations

import tarfile
import uuid
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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
from veyra.core.events import Event, bus
from veyra.core.models import MohClass, Organization, Prompt
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
    queue_agents: UploadFile | None = File(None),
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
    agents_text = None
    if queue_agents is not None:
        agents_text = (await queue_agents.read(1024 * 1024)).decode("utf-8", errors="replace")
    try:
        conv = freepbx.convert(freepbx.read_upload(data, file.filename), vm_text, agents_text)
    except freepbx.FreepbxError as e:
        raise ProblemError(422, "Not a usable FreePBX dump", str(e), code="freepbx_invalid") from e
    return {"csv": conv.csv, "counts": conv.counts, "warnings": conv.warnings[:200]}


@router.post("/freepbx/audio", summary="Bring a FreePBX server's recordings and hold music over")
def freepbx_audio(
    request: Request,
    organization_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    dump: UploadFile | None = File(None),
    principal: Principal = Depends(require("ivr.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    """Issue #42: an archive of ``sounds/<lang>/custom`` and ``moh`` → library
    recordings and hold music sets. With the database dump the recordings keep
    the names the converted IVR menus refer to. Only adds: a name already in
    the library is left as it is, so the import can be run again. A plain
    ``def``: it converts audio for minutes, on a worker thread."""
    from veyra.api.v1 import hold_music, prompts
    from veyra.bulk import freepbx
    from veyra.telephony import audio

    if not principal.has("ivr.write", organization_id):
        raise forbidden()
    org = db.get(Organization, organization_id)
    if org is None:
        raise not_found("Organization")
    if (file.size or 0) > freepbx.MAX_AUDIO_BYTES:
        raise ProblemError(
            413, "Archive too large", "The archive is larger than 1000 MB.", code="file_too_large"
        )

    def add(
        tar: Any, item: freepbx.AudioFile, kind: Any, taken: dict[str, Prompt]
    ) -> Prompt | None:
        if item.name.lower() in taken:
            return taken[item.name.lower()]
        member = item.member
        if member.size > audio.MAX_COMPRESSED_BYTES:
            warnings.append(f"{item.name}: larger than 25 MB; not imported")
            return None
        source = tar.extractfile(member)
        if source is None:
            return None
        try:
            prompt = prompts.import_prompt(
                db,
                prompts.prompts_dir(request),
                org,
                item.name,
                source.read(),
                member.name,
                kind,
            )
        except (audio.AudioError, ProblemError) as e:
            db.rollback()
            warnings.append(f"{item.name}: {getattr(e, 'detail', None) or e}; not imported")
            return None
        # Committed one by one: a run cut short keeps what it finished.
        db.commit()
        taken[item.name.lower()] = prompt
        counts[kind] += 1
        return prompt

    counts = {"prompt": 0, "music": 0, "sets": 0, "already_there": 0}
    warnings: list[str] = []
    try:
        dump_text = None
        if dump is not None:
            dump_text = freepbx.read_upload(
                dump.file.read(freepbx.MAX_DUMP_BYTES + 1), dump.filename
            )
        with freepbx.open_audio(file.file) as tar:
            plan = freepbx.plan_audio(tar, dump_text)
            warnings.extend(plan.warnings)
            taken = {
                p.name.lower(): p
                for p in db.scalars(select(Prompt).where(Prompt.organization_id == org.id))
            }
            counts["already_there"] = sum(
                1
                for item in [*plan.recordings, *(f for t in plan.hold_music.values() for f in t)]
                if item.name.lower() in taken
            )
            # In archive order: going backwards in a gzipped tar unpacks it again.
            for item in sorted(plan.recordings, key=lambda f: f.member.offset):
                add(tar, item, "prompt", taken)
            for name, tracks in plan.hold_music.items():
                for item in sorted(tracks, key=lambda f: f.member.offset):
                    add(tar, item, "music", taken)
                kept = [taken[f.name.lower()] for f in tracks if f.name.lower() in taken]
                exists = db.scalar(
                    select(MohClass.id).where(
                        MohClass.organization_id == org.id,
                        func.lower(MohClass.name) == name.lower(),
                    )
                )
                if exists is not None:
                    warnings.append(f"hold music set {name}: already exists; left as it is")
                    continue
                if not kept:
                    continue
                if len(kept) > hold_music.MAX_TRACKS:
                    warnings.append(
                        f"hold music set {name}: only the first {hold_music.MAX_TRACKS} of "
                        f"{len(kept)} tracks are in the set; the rest are in the library"
                    )
                hold_music.import_set(request, db, org, name, kept)
                db.commit()
                counts["sets"] += 1
    except (freepbx.FreepbxError, tarfile.TarError, EOFError, OSError) as e:
        db.rollback()
        raise ProblemError(422, "Not a usable audio archive", str(e), code="freepbx_invalid") from e
    audit.record(
        db,
        action="bulk.freepbx_audio",
        outcome="success",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=org.id,
        target_type="bulk",
        target_id="freepbx_audio",
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=counts,
    )
    db.commit()
    if counts["prompt"] or counts["music"]:
        bus.publish(Event("prompt.created", {"organization_id": str(org.id)}))
    if counts["sets"]:
        bus.publish(Event("hold_music.created", {"organization_id": str(org.id)}))
    return {
        "recordings": counts["prompt"],
        "music_tracks": counts["music"],
        "hold_music_sets": counts["sets"],
        "already_there": counts["already_there"],
        "warnings": warnings[:200],
    }
