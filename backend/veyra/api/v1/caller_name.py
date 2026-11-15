# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caller name lookup (issue #392): the platform setting, a test, and the
internal lookup the dialplan calls on 127.0.0.1."""

from __future__ import annotations

import hmac
import time
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from veyra.api.v1.extensions import installation_key
from veyra.configmgmt import service
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, forbidden
from veyra.core.security.crypto import try_load_installation_key
from veyra.core.security.principal import Principal
from veyra.telephony import caller_name as cn

router = APIRouter(tags=["telephony"])

READ = "system.settings.read"
WRITE = "system.settings.write"


class CallerNameOut(BaseModel):
    enabled: bool
    url: str | None
    header_name: str | None
    has_header_value: bool
    json_field: str | None
    timeout_ms: int
    cache_minutes: int


class CallerNameIn(BaseModel):
    enabled: bool = False
    url: str | None = Field(None, max_length=1000)
    header_name: str | None = Field(None, max_length=100, pattern=r"^[A-Za-z0-9-]+$")
    # Write-only: missing keeps it, "" or null removes it.
    header_value: str | None = Field(None, max_length=1000)
    json_field: str | None = Field(None, max_length=200, pattern=r"^[A-Za-z0-9_.]+$")
    timeout_ms: int = Field(1500, ge=200, le=2500)
    cache_minutes: int = Field(1440, ge=0, le=43200)


class TestIn(BaseModel):
    number: str = Field(min_length=3, max_length=32)


class TestOut(BaseModel):
    name: str
    milliseconds: int


def _platform(principal: Principal) -> None:
    if not principal.is_platform_admin:
        raise forbidden("Only a platform administrator may change caller name lookup.")


def _out(s: cn.CallerNameSettings) -> CallerNameOut:
    return CallerNameOut(
        enabled=s.enabled,
        url=s.url,
        header_name=s.header_name,
        has_header_value=bool(s.header_value_ciphertext),
        json_field=s.json_field,
        timeout_ms=s.timeout_ms,
        cache_minutes=s.cache_minutes,
    )


def _header_value(request: Request, s: cn.CallerNameSettings) -> str | None:
    if not s.header_value_ciphertext:
        return None
    key = try_load_installation_key(request.app.state.settings)
    if key is None:
        return None
    try:
        return key.decrypt(s.header_value_ciphertext, cn.HEADER_PURPOSE)
    except Exception:
        return None


@router.get(
    "/telephony/caller-name", response_model=CallerNameOut, summary="Caller name lookup settings"
)
def get_caller_name(
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> CallerNameOut:
    return _out(cn.load(db))


@router.put(
    "/telephony/caller-name", response_model=CallerNameOut, summary="Change caller name lookup"
)
def put_caller_name(
    body: CallerNameIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> CallerNameOut:
    _platform(principal)
    current = cn.load(db)
    url = None
    if body.url and body.url.strip():
        try:
            url = cn.check_url(body.url)
        except ValueError as e:
            raise ProblemError(
                422,
                "Validation failed",
                str(e),
                code="validation_failed",
                errors=[{"field": "url", "message": str(e)}],
            ) from e
    if body.enabled and not url:
        raise ProblemError(
            422,
            "Validation failed",
            "Enter the lookup service's address to turn it on.",
            code="validation_failed",
            errors=[{"field": "url", "message": "required"}],
        )
    sent = body.model_fields_set
    cipher = current.header_value_ciphertext
    if "header_value" in sent:
        cipher = (
            installation_key(request).encrypt(body.header_value, cn.HEADER_PURPOSE)
            if body.header_value
            else None
        )
    new = cn.CallerNameSettings(
        enabled=body.enabled,
        url=url,
        header_name=body.header_name or None,
        header_value_ciphertext=cipher,
        json_field=body.json_field or None,
        timeout_ms=body.timeout_ms,
        cache_minutes=body.cache_minutes,
        token=current.token,
    )
    before, after = _out(current).model_dump(), _out(new).model_dump()
    changed = {k: after[k] for k in after if before[k] != after[k]}
    if "header_value" in sent:
        changed["header_value"] = "set" if cipher else "removed"
    cn.save(db, new, updated_by=principal.user_id)
    if changed.keys() & {"enabled", "url"}:
        # The dialplan carries the lookup only while it is on.
        service.mark_changed(db, by=principal.label, what="telephony.caller_name")
    audit.record(
        db,
        action="telephony.caller_name_update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="settings",
        target_id=cn.KEY,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"changed": changed},
    )
    db.commit()
    return _out(new)


@router.post("/telephony/caller-name/test", response_model=TestOut, summary="Look a number up now")
def test_caller_name(
    body: TestIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
) -> TestOut:
    _platform(principal)
    s = cn.load(db).model_copy(update={"enabled": True, "cache_minutes": 0})
    if not s.url:
        raise ProblemError(422, "Not set", "Save the lookup service first.", code="not_set")
    start = time.monotonic()
    name = cn.lookup(s, body.number, _header_value(request, s))
    return TestOut(name=name, milliseconds=int((time.monotonic() - start) * 1000))


@router.get("/internal/caller-name", include_in_schema=False)
def internal_caller_name(
    request: Request,
    number: str = Query("", max_length=32),
    token: str = Query("", max_length=100),
    db: Session = Depends(get_db),
) -> Any:
    """For the dialplan on this server only: 127.0.0.1 and the token."""
    client = request.client.host if request.client else ""
    s = cn.load(db)
    if (
        client not in ("127.0.0.1", "::1")
        or not s.enabled
        or not s.token
        or not hmac.compare_digest(token, s.token)
    ):
        return PlainTextResponse("", status_code=403)
    return PlainTextResponse(cn.lookup(s, number, _header_value(request, s)))
