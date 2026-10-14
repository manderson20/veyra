# SPDX-License-Identifier: AGPL-3.0-or-later
"""The phone-facing provisioning server (docs/DEVICE_PROVISIONING.md §3):
``GET /provisioning/<file>`` with HTTP Basic authentication renders the
device's files on request; ``PUT`` uploads from phones are accepted and
discarded. Every request is logged for device status and the list of
unregistered phones. Mounted outside ``/api/v1``; NGINX rate-limits it."""

from __future__ import annotations

import base64
import binascii
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.db import get_db
from veyra.core.models import Device, Organization, ProvisioningRequest
from veyra.core.models.base import utcnow
from veyra.core.security.crypto import DecryptionError, InstallationKey, try_load_installation_key
from veyra.provisioning import facts
from veyra.provisioning.spec import TemplateError

log = logging.getLogger("veyra.provisioning")
router = APIRouter(prefix="/provisioning", include_in_schema=False, tags=["provisioning-server"])

_MAC_IN_NAME = re.compile(r"(?<![0-9a-f])([0-9a-f]{12})(?![0-9a-f])")
_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
EMPTY_MASTER = (
    '<?xml version="1.0" standalone="yes"?>\n'
    '<APPLICATION APP_FILE_PATH="" CONFIG_FILES="" MISC_FILES="" LOG_FILE_DIRECTORY="" />\n'
)
MEDIA_TYPES = {"xml": "application/xml", "json": "application/json", "text": "text/plain"}


@dataclass
class Credential:
    kind: str  # organization | device
    organization_id: uuid.UUID | None
    device: Device | None


def _unauthorized() -> Response:
    return Response(
        status_code=401,
        headers={
            "WWW-Authenticate": 'Basic realm="Veyra provisioning"',
            "Cache-Control": "no-store",
        },
    )


def _parse_basic(header: str | None) -> tuple[str, str] | None:
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    user, sep, password = raw.partition(":")
    return (user, password) if sep else None


def _check(key: InstallationKey | None, token: str | None, purpose: str, given: str) -> bool:
    if key is None or not token:
        return False
    try:
        expected = key.decrypt(token, purpose)
    except DecryptionError:
        return False
    return secrets.compare_digest(expected.encode(), given.encode())


def authenticate(db: Session, key: InstallationKey | None, header: str | None) -> Credential | None:
    parsed = _parse_basic(header)
    if parsed is None:
        return None
    user, password = parsed
    if user.startswith("dev-"):
        mac = user[4:].lower()
        device = db.scalar(select(Device).where(Device.mac_address == mac))
        if device is None or not _check(
            key,
            device.provisioning_secret_ciphertext,
            f"device.provisioning_secret:{device.id}",
            password,
        ):
            return None
        return Credential("device", device.organization_id, device)
    org = db.scalar(select(Organization).where(Organization.provisioning_user == user))
    if org is None or not org.is_active:
        return None
    if not _check(
        key,
        org.provisioning_secret_ciphertext,
        f"organization.provisioning_secret:{org.id}",
        password,
    ):
        return None
    return Credential("organization", org.id, None)


def _log(
    db: Session,
    request: Request,
    *,
    filename: str,
    mac: str | None,
    result: str,
    status: int,
    organization_id: uuid.UUID | None = None,
    device: Device | None = None,
) -> None:
    ua = (request.headers.get("user-agent") or "")[:200] or None
    ip = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip()[:45]
    db.add(
        ProvisioningRequest(
            id=uuid.uuid4(),
            at=utcnow(),
            mac=mac,
            filename=filename[:128],
            method=request.method[:8],
            ip_address=ip,
            user_agent=ua,
            organization_id=organization_id,
            device_id=device.id if device else None,
            result=result,
            status=status,
        )
    )
    if device is not None:
        device.last_seen_at = utcnow()
        device.last_seen_ip = ip
        device.last_user_agent = ua
        device.last_result = result
        from veyra.api.v1.devices import parse_user_agent  # local import: API helper

        _m, _model, version = parse_user_agent(ua)
        if version:
            device.firmware_reported = version[:64]
    db.commit()


def _mac_of(filename: str) -> str | None:
    m = _MAC_IN_NAME.search(filename.lower())
    return m.group(1) if m else None


def _scheme(request: Request) -> str:
    return (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").lower()


@router.get("/{filename}")
def get_file(filename: str, request: Request, db: Session = Depends(get_db)) -> Response:
    settings = request.app.state.settings
    key = try_load_installation_key(settings)
    if not _FILENAME_RE.match(filename):
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    cred = authenticate(db, key, request.headers.get("authorization"))
    mac = _mac_of(filename)
    if cred is None:
        _log(db, request, filename=filename, mac=mac, result="unauthorized", status=401)
        return _unauthorized()
    if filename == "000000000000.cfg":
        _log(
            db,
            request,
            filename=filename,
            mac=None,
            result="ok",
            status=200,
            organization_id=cred.organization_id,
            device=cred.device,
        )
        return Response(
            EMPTY_MASTER, media_type="application/xml", headers={"Cache-Control": "no-store"}
        )
    device = cred.device
    if device is None and mac:
        device = db.scalar(select(Device).where(Device.mac_address == mac))
    if device is None or (mac and device.mac_address != mac):
        _log(
            db,
            request,
            filename=filename,
            mac=mac,
            result="unknown_device",
            status=404,
            organization_id=cred.organization_id,
        )
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    if cred.kind == "organization" and device.organization_id != cred.organization_id:
        _log(
            db,
            request,
            filename=filename,
            mac=mac,
            result="unauthorized",
            status=401,
            organization_id=cred.organization_id,
        )
        return _unauthorized()
    if not device.is_enabled:
        _log(
            db,
            request,
            filename=filename,
            mac=mac,
            result="disabled",
            status=403,
            organization_id=device.organization_id,
            device=device,
        )
        return Response(status_code=403, headers={"Cache-Control": "no-store"})
    try:
        files = facts.render_device(
            db,
            settings,
            _catalog(request, db),
            device,
            key=key,
            host=request.headers.get("host"),
            scheme=_scheme(request),
        )
    except (facts.ProvisioningError, TemplateError) as e:
        log.warning("provisioning %s for %s failed: %s", filename, device.mac_address, e)
        _log(
            db,
            request,
            filename=filename,
            mac=mac,
            result="render_error",
            status=500,
            organization_id=device.organization_id,
            device=device,
        )
        return Response(status_code=500, headers={"Cache-Control": "no-store"})
    wanted = next((f for f in files if f.filename == filename), None)
    if wanted is None:
        _log(
            db,
            request,
            filename=filename,
            mac=mac,
            result="not_found",
            status=404,
            organization_id=device.organization_id,
            device=device,
        )
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    _log(
        db,
        request,
        filename=filename,
        mac=mac,
        result="ok",
        status=200,
        organization_id=device.organization_id,
        device=device,
    )
    return Response(
        wanted.content,
        media_type=MEDIA_TYPES.get(wanted.format, "text/plain"),
        headers={"Cache-Control": "no-store"},
    )


@router.put("/{filename}")
async def put_file(filename: str, request: Request, db: Session = Depends(get_db)) -> Response:
    """Phones upload logs, call lists and overrides; accepted and discarded."""
    key = try_load_installation_key(request.app.state.settings)
    if not _FILENAME_RE.match(filename):
        return Response(status_code=404)
    cred = authenticate(db, key, request.headers.get("authorization"))
    mac = _mac_of(filename)
    if cred is None:
        _log(db, request, filename=filename, mac=mac, result="unauthorized", status=401)
        return _unauthorized()
    # Drain the body without keeping it.
    async for _chunk in request.stream():
        pass
    device = cred.device
    if device is None and mac:
        device = db.scalar(select(Device).where(Device.mac_address == mac))
        if device is not None and device.organization_id != cred.organization_id:
            device = None
    _log(
        db,
        request,
        filename=filename,
        mac=mac,
        result="uploaded",
        status=200,
        organization_id=cred.organization_id,
        device=device,
    )
    return Response(status_code=200, headers={"Cache-Control": "no-store"})


def _catalog(request: Request, db: Session) -> Any:
    from veyra.api.v1.provisioning import catalog_for  # local import: API helper

    return catalog_for(request, db)
