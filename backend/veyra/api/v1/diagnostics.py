# SPDX-License-Identifier: AGPL-3.0-or-later
"""Diagnostics (docs/CALL_FEATURES.md §2.2): packet captures started from
validated targets, stopped, downloaded (audited), summarised and deleted.
Platform administrators only."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, not_found
from veyra.core.models import Capture
from veyra.core.security.principal import Principal
from veyra.diagnostics import captures, pcap
from veyra.telephony.settings import load_sip_settings

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])
READ = "diagnostics.read"
CAPTURE = "diagnostics.capture"


def _problem(e: captures.CaptureError) -> ProblemError:
    return ProblemError(e.status, "Captures", e.message, code=e.code)


def _audit(
    db: Session,
    principal: Principal,
    ctx: RequestContext,
    action: str,
    row: Capture | None = None,
    **details: Any,
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="capture",
        target_id=row.id if row else None,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={**({"label": row.label} if row else {}), **details},
    )


def _row(db: Session, capture_id: uuid.UUID) -> Capture:
    row = db.get(Capture, capture_id)
    if row is None or row.state == "deleted":
        raise not_found("Capture")
    return row


class StartIn(BaseModel):
    target: str = Field(pattern=r"^(all_sip|extension|trunk|address)$")
    extension_id: uuid.UUID | None = None
    trunk_id: uuid.UUID | None = None
    address: str | None = Field(None, max_length=253)
    rtp: bool = False
    duration_seconds: int = Field(
        captures.DEFAULT_SECONDS, ge=captures.MIN_SECONDS, le=captures.MAX_SECONDS
    )
    size_limit_mb: int = Field(captures.DEFAULT_MB, ge=captures.MIN_MB, le=captures.MAX_MB)


@router.get("/captures", summary="Captures, newest first")
def list_captures(
    principal: Principal = Depends(require(READ)), db: Session = Depends(get_db)
) -> dict[str, Any]:
    rows = captures.rows(db)
    db.commit()  # stale rows marked
    return {
        "captures": [captures.row_out(c) for c in rows if c.state != "deleted"],
        "running": sum(1 for c in rows if c.state in captures.ACTIVE),
        "max_running": captures.MAX_RUNNING,
        "limits": {
            "seconds": [captures.MIN_SECONDS, captures.MAX_SECONDS],
            "mb": [captures.MIN_MB, captures.MAX_MB],
        },
    }


@router.get("/captures/targets", summary="What a capture can be filtered on")
def capture_targets(
    request: Request,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return captures.targets(
        db, getattr(request.app.state, "telephony", None), load_sip_settings(db)
    )


@router.post("/captures", status_code=202, summary="Start a capture")
def start_capture(
    body: StartIn,
    request: Request,
    principal: Principal = Depends(require(CAPTURE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    try:
        spec, label = captures.resolve(
            db,
            getattr(request.app.state, "telephony", None),
            load_sip_settings(db),
            target=body.target,
            extension_id=body.extension_id,
            trunk_id=body.trunk_id,
            address=body.address,
            rtp=body.rtp,
        )
        row = captures.start(
            db,
            spec=spec,
            label=label,
            directory=request.app.state.settings.captures_dir,
            duration_seconds=body.duration_seconds,
            size_limit_mb=body.size_limit_mb,
            created_by=principal.label,
            created_by_user_id=principal.user_id,
        )
    except captures.CaptureError as e:
        db.rollback()
        raise _problem(e) from e
    _audit(
        db,
        principal,
        ctx,
        "capture.start",
        row,
        target=body.target,
        expression=row.expression,
        rtp=body.rtp,
        duration_seconds=body.duration_seconds,
        size_limit_mb=body.size_limit_mb,
    )
    db.commit()
    return captures.row_out(row)


@router.get("/captures/{capture_id}", summary="One capture")
def get_capture(
    capture_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return captures.row_out(_row(db, capture_id))


@router.post("/captures/{capture_id}/stop", status_code=202, summary="Stop a running capture")
def stop_capture(
    capture_id: uuid.UUID,
    principal: Principal = Depends(require(CAPTURE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    row = _row(db, capture_id)
    try:
        captures.stop(db, row)
    except captures.CaptureError as e:
        raise _problem(e) from e
    _audit(db, principal, ctx, "capture.stop", row)
    db.commit()
    return {"stopping": True}


@router.get("/captures/{capture_id}/download", summary="The .pcap file (audited)")
def download_capture(
    capture_id: uuid.UUID,
    principal: Principal = Depends(require(CAPTURE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> FileResponse:
    row = _row(db, capture_id)
    path = captures.file_of(row)
    if path is None:
        raise ProblemError(
            409 if row.state in captures.ACTIVE else 404,
            "No file",
            "The capture is still running."
            if row.state in captures.ACTIVE
            else "The capture file is missing.",
            code="no_file",
        )
    _audit(db, principal, ctx, "capture.download", row, bytes=row.bytes)
    db.commit()
    stamp = row.started_at.strftime("%Y%m%d-%H%M%S")
    return FileResponse(
        path,
        media_type="application/vnd.tcpdump.pcap",
        filename=f"veyra-capture-{stamp}.pcap",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/captures/{capture_id}/sip", summary="SIP messages and dialogs in the capture")
def capture_sip(
    capture_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    row = _row(db, capture_id)
    path = captures.file_of(row)
    if path is None:
        raise ProblemError(
            409 if row.state in captures.ACTIVE else 404,
            "No file",
            "The capture is still running."
            if row.state in captures.ACTIVE
            else "The capture file is missing.",
            code="no_file",
        )
    try:
        out = pcap.summary(path)
    except pcap.PcapError as e:
        raise ProblemError(422, "Unreadable", str(e), code="bad_pcap") from e
    _audit(db, principal, ctx, "capture.view", row, messages=len(out["messages"]))
    db.commit()
    return out


@router.delete("/captures/{capture_id}", summary="Delete a capture and its file")
def delete_capture(
    capture_id: uuid.UUID,
    principal: Principal = Depends(require(CAPTURE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    row = _row(db, capture_id)
    try:
        captures.delete(db, row)
    except captures.CaptureError as e:
        raise _problem(e) from e
    _audit(db, principal, ctx, "capture.delete", row)
    db.commit()
    return {"deleted": True}
