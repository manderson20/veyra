# SPDX-License-Identifier: AGPL-3.0-or-later
"""Companion deployment metadata (docs/COMPANION.md §5): where to get the
extension, its stable ID, and the update manifest that managed browsers
(Google Admin Console, Chrome policies) poll for self-hosted extensions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from veyra.core.config import Settings, get_settings
from veyra.core.deps import current_principal
from veyra.core.errors import not_found
from veyra.core.security.principal import Principal

router = APIRouter(prefix="/companion", tags=["companion"])

ZIP_PATH = "/downloads/veyra-companion.zip"
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


@router.get("/info", response_model=CompanionInfoOut, summary="How to install the Companion")
def companion_info(
    request: Request,
    principal: Principal = Depends(current_principal),
    settings: Settings = Depends(get_settings),
) -> CompanionInfoOut:
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
