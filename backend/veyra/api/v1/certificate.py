# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public HTTPS certificates from Let's Encrypt or another ACME authority
(docs/PUBLIC_CERTIFICATES.md, issue #43). Platform administrators only; the
DNS provider's credentials are write-only."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from veyra.api.v1.extensions import installation_key
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, check_recent_auth, request_context, require
from veyra.core.errors import ProblemError, forbidden
from veyra.core.models.base import utcnow
from veyra.core.security.principal import Principal
from veyra.firewall.settings import load_settings as load_firewall_settings
from veyra.system import certificate as cert

router = APIRouter(prefix="/system/certificate", tags=["system"])


class SettingsIn(BaseModel):
    names: list[str] = Field(default_factory=list, max_length=10)
    email: str = ""
    challenge: Literal["http", "dns"] = "dns"
    provider: str | None = None
    # Write-only: a field left out keeps its value, an empty one removes it.
    credentials: dict[str, str | None] = Field(default_factory=dict)
    authority: Literal["letsencrypt", "letsencrypt_staging", "custom"] = "letsencrypt"
    directory_url: str | None = None
    eab_kid: str | None = Field(None, max_length=200)
    # Omitted: unchanged. Null or empty: removed.
    eab_hmac_key: str | None = Field(None, max_length=500)
    propagation_seconds: int = Field(60, ge=10, le=900)


def _directory(request: Request) -> str:
    return str(getattr(request.app.state, "acme_dir", cert.ACME_DIR))


def _platform_admin(principal: Principal) -> None:
    if not principal.is_platform_admin:
        raise forbidden("Only platform administrators manage the HTTPS certificate.")


def _credentials(request: Request, s: cert.PublicCertSettings) -> dict[str, str]:
    if not s.credentials_ciphertext:
        return {}
    plain = installation_key(request).decrypt(s.credentials_ciphertext, cert.CREDENTIALS_PURPOSE)
    data = json.loads(plain)
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _out(request: Request, db: Session, s: cert.PublicCertSettings) -> dict[str, Any]:
    directory = _directory(request)
    provider = cert.PROVIDERS.get(s.provider or "")
    values = _credentials(request, s) if provider else {}
    info = cert.certificate_info(directory)
    now = utcnow()
    fw = load_firewall_settings(db)
    return {
        "settings": {
            "names": s.names,
            "email": s.email,
            "challenge": s.challenge,
            "provider": s.provider,
            "authority": s.authority,
            "directory_url": s.directory_url,
            "eab_kid": s.eab_kid,
            "has_eab_hmac_key": bool(s.eab_hmac_ciphertext),
            "propagation_seconds": s.propagation_seconds,
            # Which fields hold a value; the values of the fields that are
            # not secret (a server address, a key ID) are shown.
            "credentials_set": sorted(values),
            "credentials_public": {
                f.key: values[f.key]
                for f in (provider.fields if provider else ())
                if not f.secret and f.key in values
            },
        },
        "problems": s.problems(),
        "providers": [
            {
                "key": p.key,
                "label": p.label,
                "fields": [
                    {
                        "key": f.key,
                        "label": f.label,
                        "secret": f.secret,
                        "multiline": f.multiline,
                        "optional": f.optional,
                        "default": f.default,
                    }
                    for f in p.fields
                ],
            }
            for p in cert.PROVIDERS.values()
        ],
        "certificate": (
            {**info, "days_left": round(cert.days_left(info, now) or 0, 1)} if info else None
        ),
        "run": cert.run_status(directory),
        "challenge_window_open": cert.challenge_window_open(db, now),
        # HTTP-01 through an allow-list-only web service opens port 80 briefly.
        "web_allow_list_only": bool(fw.enabled and "web" in fw.restricted()),
    }


@router.get("", summary="The public certificate, its settings and the last run")
def get_certificate(
    request: Request,
    principal: Principal = Depends(require("system.settings.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _platform_admin(principal)
    return _out(request, db, cert.load_settings(db))


@router.put("/settings", summary="Change the public certificate's settings")
def put_settings(
    body: SettingsIn,
    request: Request,
    principal: Principal = Depends(require("system.settings.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    _platform_admin(principal)
    current = cert.load_settings(db)
    key = installation_key(request)
    data: dict[str, Any] = body.model_dump(exclude={"credentials", "eab_hmac_key"})
    # Credentials belong to one provider: another provider starts empty.
    old = _credentials(request, current) if current.provider == body.provider else {}
    data["credentials_ciphertext"] = None
    if body.challenge == "dns" and body.provider:
        provider = cert.PROVIDERS.get(body.provider)
        if provider is None:
            raise ProblemError(
                422, "Settings not saved", f"Unknown DNS provider {body.provider!r}.",
                code="validation_failed",
            )  # fmt: skip
        try:
            merged = cert.merge_credentials(provider, old, body.credentials)
        except ValueError as e:
            raise ProblemError(422, "Settings not saved", str(e), code="validation_failed") from e
        if merged:
            data["credentials_ciphertext"] = key.encrypt(
                json.dumps(merged), cert.CREDENTIALS_PURPOSE
            )
    data["eab_hmac_ciphertext"] = current.eab_hmac_ciphertext
    if "eab_hmac_key" in body.model_fields_set:
        data["eab_hmac_ciphertext"] = (
            key.encrypt(body.eab_hmac_key, cert.EAB_PURPOSE) if body.eab_hmac_key else None
        )
    try:
        new = cert.PublicCertSettings.model_validate(data)
    except ValueError as e:
        message = str(e).splitlines()
        detail = message[2].strip() if len(message) > 2 else message[0]
        raise ProblemError(422, "Settings not saved", detail, code="validation_failed") from e
    cert.save_settings(db, new)
    audit.record(
        db,
        action="system.certificate_settings",
        outcome="success",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={
            "names": new.names,
            "challenge": new.challenge,
            "provider": new.provider,
            "authority": new.authority,
            "credentials_changed": bool(body.credentials) or current.provider != new.provider,
        },
    )
    db.commit()
    return _out(request, db, new)


def _start(
    request: Request,
    db: Session,
    principal: Principal,
    ctx: RequestContext,
    mode: str,
) -> dict[str, Any]:
    directory = _directory(request)
    status = cert.run_status(directory)
    if status and status["running"]:
        raise ProblemError(
            409, "Already running", "A certificate run is in progress.", code="running"
        )
    s = cert.load_settings(db)
    now = utcnow()
    if mode == "issue":
        problems = s.problems()
        if problems:
            raise ProblemError(
                422, "Not ready", " ".join(problems), code="validation_failed",
                errors=[{"field": "settings", "message": p} for p in problems],
            )  # fmt: skip
        eab = (
            installation_key(request).decrypt(s.eab_hmac_ciphertext, cert.EAB_PURPOSE)
            if s.eab_hmac_ciphertext
            else None
        )
        provider = cert.PROVIDERS.get(s.provider or "")
        creds = _credentials(request, s)
        if s.challenge == "dns" and provider:
            missing = cert.missing_credentials(provider, creds)
            if missing:
                raise ProblemError(
                    422, "Not ready", "Missing: " + ", ".join(missing) + ".",
                    code="validation_failed",
                )  # fmt: skip
        req = cert.build_request(s, mode, creds, eab, principal.label, now)
        try:
            cert.write_request(directory, req)
        except OSError as e:
            raise ProblemError(
                503, "Not started",
                f"The request could not be written to {directory}: {e.strerror}. "
                "Run the installer's upgrade once (sudo installer/upgrade.sh --yes).",
                code="not_started",
            ) from e  # fmt: skip
    elif mode == "renew" and cert.certificate_info(directory) is None:
        raise ProblemError(409, "Nothing to renew", "No public certificate is in use.", code="none")
    if mode in ("issue", "renew") and s.challenge == "http":
        cert.open_challenge_window(db, now)
    db.commit()
    ok, error = cert.start_unit(mode, getattr(request.app.state, "systemctl_run", None))
    audit.record(
        db,
        action=f"system.certificate_{mode}",
        outcome="success" if ok else "failure",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"names": s.names} if ok else {"names": s.names, "error": error[:300]},
    )
    db.commit()
    if not ok:
        raise ProblemError(
            503, "Not started",
            f"The certificate run could not be started: {error}. "
            "Run the installer's upgrade once (sudo installer/upgrade.sh --yes).",
            code="not_started",
        )  # fmt: skip
    return _out(request, db, s)


@router.post("/request", status_code=202, summary="Get (or replace) the public certificate now")
def request_certificate(
    request: Request,
    principal: Principal = Depends(require("system.settings.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    _platform_admin(principal)
    check_recent_auth(db, principal)
    return _start(request, db, principal, ctx, "issue")


@router.post("/renew", status_code=202, summary="Renew the public certificate if it is due")
def renew_certificate(
    request: Request,
    principal: Principal = Depends(require("system.settings.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    _platform_admin(principal)
    return _start(request, db, principal, ctx, "renew")


@router.post(
    "/remove", status_code=202, summary="Stop using the public certificate (Veyra CA only)"
)
def remove_certificate(
    request: Request,
    principal: Principal = Depends(require("system.settings.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    _platform_admin(principal)
    check_recent_auth(db, principal)
    return _start(request, db, principal, ctx, "remove")
