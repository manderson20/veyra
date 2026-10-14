# SPDX-License-Identifier: AGPL-3.0-or-later
"""Firmware images (docs/DEVICE_PROVISIONING.md §3.4): vendor files uploaded
by an administrator, assigned to device profiles or devices, served by NGINX
from ``<data dir>/firmware/<id>/<filename>``."""

from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, not_found
from veyra.core.models import Device, DeviceProfile, FirmwareImage, User
from veyra.core.security.principal import Principal

router = APIRouter(prefix="/provisioning/firmware", tags=["provisioning"])

READ = "provisioning.read"
WRITE = "provisioning.write"
MAX_BYTES = 512 * 1024 * 1024
_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+-]{0,63}$")


class FirmwarePatch(BaseModel):
    models: list[str] | None = Field(None, max_length=32)
    notes: str | None = Field(None, max_length=2000)


class FirmwareOut(BaseModel):
    id: uuid.UUID
    manufacturer: str
    models: list[str]
    version: str
    filename: str
    size: int
    sha256: str
    notes: str | None
    uploaded_by: str | None
    url: str
    profiles: int
    devices: int
    created_at: datetime


def _validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


def _models(raw: str | list[str] | None) -> list[str]:
    items = raw if isinstance(raw, list) else (raw or "").split(",")
    out: list[str] = []
    for m in items:
        m = m.strip()
        if not m:
            continue
        if not _TOKEN_RE.match(m):
            raise _validation("models", "model names: letters, digits, spaces and . _ + -")
        if m not in out:
            out.append(m)
    return out


def _outs(db: Session, rows: list[FirmwareImage]) -> list[FirmwareOut]:
    if not rows:
        return []
    ids = {r.id for r in rows}
    profiles = dict(
        db.execute(
            select(DeviceProfile.firmware_image_id, func.count(DeviceProfile.id))
            .where(DeviceProfile.firmware_image_id.in_(ids))
            .group_by(DeviceProfile.firmware_image_id)
        ).all()
    )
    devices = dict(
        db.execute(
            select(Device.firmware_image_id, func.count(Device.id))
            .where(Device.firmware_image_id.in_(ids))
            .group_by(Device.firmware_image_id)
        ).all()
    )
    user_ids = {r.uploaded_by for r in rows if r.uploaded_by}
    users = (
        {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(user_ids)))}
        if user_ids
        else {}
    )
    return [
        FirmwareOut(
            id=r.id,
            manufacturer=r.manufacturer,
            models=list(r.models),
            version=r.version,
            filename=r.filename,
            size=r.size,
            sha256=r.sha256,
            notes=r.notes,
            uploaded_by=users.get(r.uploaded_by) if r.uploaded_by else None,
            url=f"/provisioning/firmware/{r.id}/{r.filename}",
            profiles=int(profiles.get(r.id, 0)),
            devices=int(devices.get(r.id, 0)),
            created_at=r.created_at,
        )
        for r in rows
    ]


def _record(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    image: FirmwareImage,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="firmware_image",
        target_id=image.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={
            "manufacturer": image.manufacturer,
            "version": image.version,
            "filename": image.filename,
            **details,
        },
    )


@router.get("", summary="List firmware images")
def list_firmware(
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = db.scalars(
        select(FirmwareImage).order_by(
            FirmwareImage.manufacturer, FirmwareImage.version.desc(), FirmwareImage.filename
        )
    ).all()
    return {"items": [o.model_dump(mode="json") for o in _outs(db, list(rows))]}


@router.post("", response_model=FirmwareOut, status_code=201, summary="Upload a firmware image")
async def upload_firmware(
    request: Request,
    file: Annotated[UploadFile, File()],
    manufacturer: Annotated[str, Form(max_length=64)],
    version: Annotated[str, Form(max_length=64)],
    models: Annotated[str, Form(max_length=1000)] = "",
    notes: Annotated[str, Form(max_length=2000)] = "",
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> FirmwareOut:
    manufacturer = manufacturer.strip()
    version = version.strip()
    if not _TOKEN_RE.match(manufacturer):
        raise _validation("manufacturer", "enter the manufacturer")
    if not _TOKEN_RE.match(version):
        raise _validation("version", "enter the firmware version")
    filename = (file.filename or "").strip().split("/")[-1].split("\\")[-1]
    if not _FILENAME_RE.match(filename) or ".." in filename:
        raise _validation("file", "file name: letters, digits, '.', '_' and '-' only")
    model_list = _models(models)
    image = FirmwareImage(
        id=uuid.uuid4(),
        manufacturer=manufacturer,
        models=model_list,
        version=version,
        filename=filename,
        size=0,
        sha256="",
        notes=notes.strip() or None,
        uploaded_by=principal.user_id,
    )
    base = request.app.state.settings.firmware_dir
    target_dir = base / str(image.id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise _validation("file", "the file is larger than 512 MB")
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    if size == 0:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise _validation("file", "the file is empty")
    image.size = size
    image.sha256 = digest.hexdigest()
    db.add(image)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        shutil.rmtree(target_dir, ignore_errors=True)
        raise conflict(
            f"{manufacturer} {version} {filename} is already uploaded.", "firmware_exists"
        ) from e
    _record(db, ctx, principal, "firmware.upload", image, {"size": size, "models": model_list})
    db.commit()
    return _outs(db, [image])[0]


def _get(db: Session, image_id: uuid.UUID) -> FirmwareImage:
    image = db.get(FirmwareImage, image_id)
    if image is None:
        raise not_found("Firmware image")
    return image


@router.get("/{image_id}", response_model=FirmwareOut)
def get_firmware(
    image_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> FirmwareOut:
    return _outs(db, [_get(db, image_id)])[0]


@router.patch("/{image_id}", response_model=FirmwareOut)
def update_firmware(
    image_id: uuid.UUID,
    body: FirmwarePatch,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> FirmwareOut:
    image = _get(db, image_id)
    changes = body.model_dump(exclude_unset=True)
    details: dict[str, Any] = {}
    if "models" in changes:
        models = _models(changes["models"])
        if models != list(image.models):
            image.models = models
            details["models"] = models
    if "notes" in changes:
        notes = (changes["notes"] or "").strip() or None
        if notes != image.notes:
            image.notes = notes
            details["notes"] = True
    if details:
        _record(db, ctx, principal, "firmware.update", image, details)
        db.commit()
    return _outs(db, [image])[0]


@router.delete("/{image_id}", status_code=204)
def delete_firmware(
    image_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    image = _get(db, image_id)
    out = _outs(db, [image])[0]
    if out.profiles or out.devices:
        raise ProblemError(
            409,
            "Firmware in use",
            f"{out.profiles} profile(s) and {out.devices} device(s) are assigned this image.",
            code="firmware_in_use",
        )
    _record(db, ctx, principal, "firmware.delete", image, {})
    db.delete(image)
    db.commit()
    shutil.rmtree(request.app.state.settings.firmware_dir / str(image.id), ignore_errors=True)
    return Response(status_code=204)
