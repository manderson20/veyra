# SPDX-License-Identifier: AGPL-3.0-or-later
"""Companion deployment metadata (docs/COMPANION.md §5): where to get the
extension, its stable ID, and the update manifest that managed browsers
(Google Admin Console, Chrome policies) poll for self-hosted extensions."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from xml.sax.saxutils import quoteattr

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.config import Settings, get_settings
from veyra.core.db import get_db
from veyra.core.deps import current_principal, require
from veyra.core.errors import not_found
from veyra.core.models.base import utcnow
from veyra.core.models.identity import ApiToken, User
from veyra.core.security import api_tokens
from veyra.core.security.principal import Principal
from veyra.system import certificate as cert

router = APIRouter(prefix="/companion", tags=["companion"])

ZIP_PATH = "/downloads/veyra-companion.zip"
CA_PATH = "/downloads/veyra-ca.crt"
CRX_PATH = "/downloads/veyra-companion.crx"
UPDATE_PATH = "/api/v1/companion/update.xml"


class CompanionInfoOut(BaseModel):
    available: bool
    name: str | None = None
    version: str | None = None
    extension_id: str | None = None
    zip_url: str | None = None
    crx_url: str | None = None
    update_url: str | None = None
    install_sources_pattern: str | None = None


class RolloutCertificate(BaseModel):
    # "public": a certificate from a public authority (Let's Encrypt) covers
    # this host name, so browsers trust it as they are; "veyra": the Veyra CA
    # signs it, and browsers trust it only once the CA is pushed to them.
    kind: str
    names: list[str] = []
    issuer: str | None = None
    not_after: str | None = None


class RolloutSignIn(BaseModel):
    email: str
    display_name: str
    device: str
    created_at: datetime
    last_used_at: datetime | None


class RolloutAdoption(BaseModel):
    users: int
    active_7d: int
    recent: list[RolloutSignIn]


class CompanionRolloutOut(BaseModel):
    info: CompanionInfoOut
    host: str
    origin: str
    certificate: RolloutCertificate
    ca_url: str
    adoption: RolloutAdoption


def _info(settings: Settings) -> dict[str, Any] | None:
    path = Path(settings.companion_dir) / "crx-info.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    return data


def _origin(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = (
        request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    )
    return f"{proto}://{host}"


def _covers(names: list[str], host: str) -> bool:
    host = host.lower()
    for name in names:
        name = name.lower()
        if name == host or (
            name.startswith("*.") and host.endswith(name[1:]) and host.count(".") == name.count(".")
        ):
            return True
    return False


@router.get("/info", response_model=CompanionInfoOut, summary="How to install the Companion")
def companion_info(
    request: Request,
    principal: Principal = Depends(current_principal),
    settings: Settings = Depends(get_settings),
) -> CompanionInfoOut:
    return _companion_info(request, settings)


def _companion_info(request: Request, settings: Settings) -> CompanionInfoOut:
    zip_exists = (Path(settings.companion_dir) / "veyra-companion.zip").exists()
    info = _info(settings)
    origin = _origin(request)
    if info is None:
        return CompanionInfoOut(available=zip_exists, zip_url=ZIP_PATH if zip_exists else None)
    return CompanionInfoOut(
        available=True,
        name=str(info.get("name") or "Veyra Companion"),
        version=str(info.get("version") or ""),
        extension_id=str(info["id"]),
        zip_url=ZIP_PATH if zip_exists else None,
        crx_url=CRX_PATH,
        update_url=f"{origin}{UPDATE_PATH}",
        install_sources_pattern=f"{origin}/*",
    )


@router.get(
    "/rollout",
    response_model=CompanionRolloutOut,
    summary="What pushing the Companion to managed browsers needs, and who signed in",
)
def companion_rollout(
    request: Request,
    principal: Principal = Depends(require("system.settings.read")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CompanionRolloutOut:
    """For the rollout guide (System → Companion rollout, docs/COMPANION.md
    §5.1): whether browsers will trust this server as they are, and how many
    users the extension is signed in for, so the last step can show that the
    push worked."""
    origin = _origin(request)
    host = urlsplit(origin).hostname or ""
    info = cert.certificate_info(getattr(request.app.state, "acme_dir", cert.ACME_DIR))
    names = [str(n) for n in (info or {}).get("names") or []]
    certificate = (
        RolloutCertificate(
            kind="public",
            names=names,
            issuer=(info or {}).get("issuer"),
            not_after=(info or {}).get("not_after"),
        )
        if info and _covers(names, host)
        else RolloutCertificate(kind="veyra", names=names)
    )
    now = utcnow()
    rows = db.execute(
        select(ApiToken, User)
        .join(User, User.id == ApiToken.user_id)
        .where(
            ApiToken.kind == api_tokens.KIND_COMPANION,
            ApiToken.revoked_at.is_(None),
            ApiToken.expires_at > now,
        )
        .order_by(ApiToken.last_used_at.desc().nulls_last(), ApiToken.created_at.desc())
    ).all()
    week = now - timedelta(days=7)
    return CompanionRolloutOut(
        info=_companion_info(request, settings),
        host=host,
        origin=origin,
        certificate=certificate,
        ca_url=CA_PATH,
        adoption=RolloutAdoption(
            users=len({u.id for _, u in rows}),
            active_7d=len({u.id for t, u in rows if t.last_used_at and t.last_used_at >= week}),
            recent=[
                RolloutSignIn(
                    email=u.email,
                    display_name=u.display_name,
                    device=t.label,
                    created_at=t.created_at,
                    last_used_at=t.last_used_at,
                )
                for t, u in rows[:25]
            ],
        ),
    )


@router.get("/update.xml", summary="Update manifest for managed browsers", include_in_schema=False)
def update_manifest(request: Request, settings: Settings = Depends(get_settings)) -> Response:
    """Public: Chrome polls it without credentials. It names the extension ID,
    the current version and where the signed package is."""
    info = _info(settings)
    if info is None:
        raise not_found("Companion package")
    codebase = f"{_origin(request)}{CRX_PATH}"
    xml = (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        "<gupdate xmlns='http://www.google.com/update2/response' protocol='2.0'>\n"
        f"  <app appid={quoteattr(str(info['id']))}>\n"
        f"    <updatecheck codebase={quoteattr(codebase)} "
        f"version={quoteattr(str(info.get('version') or '0'))} />\n"
        "  </app>\n"
        "</gupdate>\n"
    )
    return Response(
        content=xml, media_type="application/xml", headers={"Cache-Control": "no-cache"}
    )
