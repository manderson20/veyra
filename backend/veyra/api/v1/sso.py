# SPDX-License-Identifier: AGPL-3.0-or-later
"""Single sign-on (docs/INTEGRATIONS.md §1): the public sign-in flow for the
web interface and the Companion, identity provider administration, and the
links between accounts and providers."""

from __future__ import annotations

import html
import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1 import auth as auth_api
from veyra.api.v1.auth_companion import CompanionSessionOut
from veyra.api.v1.auth_companion import _issue as companion_issue
from veyra.api.v1.companion import _info as companion_info
from veyra.api.v1.companion import _origin
from veyra.api.v1.extensions import installation_key
from veyra.core import audit
from veyra.core.config import Settings, get_settings
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, recent_auth, request_context, require
from veyra.core.errors import ProblemError, not_found
from veyra.core.models import IdentityProvider, Organization, User, UserIdentity
from veyra.core.models.base import utcnow
from veyra.core.security import oidc
from veyra.core.security.principal import Principal
from veyra.core.security.ratelimit import SlidingWindowLimiter
from veyra.core.security.sessions import create_session
from veyra.integrations import sso

router = APIRouter(tags=["single sign-on"])

BROWSER_COOKIE = "veyra_sso"
BROWSER_COOKIE_PATH = "/api/v1/auth/sso/"
LOGIN_PATH = "/login/"


_limiter: SlidingWindowLimiter | None = None


def _start_limiter(settings: Settings) -> SlidingWindowLimiter:
    """Starting a sign-in has its own budget (the callback needs none: its
    state is single-use and unguessable)."""
    global _limiter
    if _limiter is None or _limiter.limit != settings.login_rate_limit_per_minute:
        _limiter = SlidingWindowLimiter(settings.login_rate_limit_per_minute, 60)
    return _limiter


def base_url(request: Request, settings: Settings) -> str:
    """The address providers redirect back to: the configured public host when
    there is one, otherwise the address the browser used."""
    if settings.public_host:
        return f"https://{settings.public_host}"
    return _origin(request)


# ----------------------------------------------------------------- schemas


class ProviderPublic(BaseModel):
    id: uuid.UUID
    kind: str
    name: str


class ProviderIn(BaseModel):
    kind: Literal["google", "microsoft", "oidc"]
    name: str = Field(min_length=1, max_length=120)
    issuer: str | None = Field(None, max_length=500)
    client_id: str = Field(min_length=1, max_length=500)
    # Required when creating; omitted when editing keeps the stored secret.
    client_secret: str | None = Field(None, max_length=2000)
    allowed_domains: list[str] = Field(min_length=1, max_length=50)
    organization_id: uuid.UUID
    create_accounts: bool = False
    default_role_key: Literal[
        "standard_user", "read_only", "technician", "site_admin", "org_admin"
    ] = "standard_user"
    enabled: bool = True

    @field_validator("allowed_domains")
    @classmethod
    def _domains(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for d in v:
            d = d.strip().lower().lstrip("@")
            if not d:
                continue
            labels = d.split(".")
            if len(labels) < 2 or not all(
                lbl and len(lbl) <= 63 and all(c.isalnum() or c == "-" for c in lbl)
                for lbl in labels
            ):
                raise ValueError(f"{d!r} is not a domain name")
            if d not in out:
                out.append(d)
        if not out:
            raise ValueError("at least one domain is required")
        return out


class ProviderOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    issuer: str
    client_id: str
    has_secret: bool
    allowed_domains: list[str]
    organization_id: uuid.UUID
    create_accounts: bool
    default_role_key: str
    enabled: bool
    redirect_uri: str
    linked_users: int
    metadata_fetched_at: datetime | None
    created_at: datetime


class ProviderTestOut(BaseModel):
    ok: bool
    message: str
    authorization_endpoint: str | None = None
    keys: int = 0


class PolicyIO(BaseModel):
    require_sso: bool = False


class IdentityOut(BaseModel):
    id: uuid.UUID
    provider_id: uuid.UUID
    provider_name: str
    email: str
    created_at: datetime
    last_used_at: datetime | None


# ----------------------------------------------------------------- helpers


def _provider(db: Session, provider_id: uuid.UUID) -> IdentityProvider:
    p = db.get(IdentityProvider, provider_id)
    if p is None:
        raise not_found("Identity provider")
    return p


def _out(db: Session, p: IdentityProvider, base: str) -> ProviderOut:
    linked = len(db.scalars(select(UserIdentity.id).where(UserIdentity.provider_id == p.id)).all())
    return ProviderOut(
        id=p.id,
        kind=p.kind,
        name=p.name,
        issuer=p.issuer,
        client_id=p.client_id,
        has_secret=bool(p.client_secret_enc),
        allowed_domains=list(p.allowed_domains or []),
        organization_id=p.organization_id,
        create_accounts=p.create_accounts,
        default_role_key=p.default_role_key,
        enabled=p.enabled,
        redirect_uri=sso.callback_url(base),
        linked_users=linked,
        metadata_fetched_at=p.metadata_fetched_at,
        created_at=p.created_at,
    )


def _issuer(body: ProviderIn) -> str:
    if body.kind == "google":
        return oidc.PRESET_ISSUERS["google"]
    if not body.issuer:
        raise ProblemError(
            422, "Issuer required", "Enter the provider's issuer address.", code="issuer_required"
        )
    try:
        return oidc.check_issuer(body.issuer)
    except oidc.OidcError as e:
        raise ProblemError(422, "Invalid issuer", str(e), code="bad_issuer") from e


def _login_redirect(message: str) -> RedirectResponse:
    return RedirectResponse(f"{LOGIN_PATH}?sso_error={quote(message)}", status_code=303)


def _continue_page(target: str) -> HTMLResponse:
    """A same-site hop after the provider's cross-site redirect, so the strict
    session cookie is sent with the next navigation."""
    t = html.escape(target, quote=True)
    return HTMLResponse(
        "<!doctype html><html><head><meta charset=utf-8>"
        f'<meta http-equiv="refresh" content="0;url={t}"><title>Signing in</title></head>'
        f'<body><p>Signing in… <a href="{t}">Continue</a></p></body></html>',
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def _audit_failure(
    db: Session,
    ctx: RequestContext,
    provider: IdentityProvider | None,
    reason: str,
    email: str | None,
) -> None:
    audit.record(
        db,
        action="auth.sso.failed",
        outcome="failure",
        actor_label=email or "unknown",
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        target_type="identity_provider",
        target_id=provider.id if provider else None,
        details={"reason": reason, "provider": provider.name if provider else None},
    )


# ----------------------------------------------------------------- public flow


@router.get(
    "/auth/sso/providers",
    response_model=list[ProviderPublic],
    summary="Enabled sign-in providers (public, for the sign-in page)",
)
def public_providers(db: Session = Depends(get_db)) -> list[ProviderPublic]:
    rows = db.scalars(
        select(IdentityProvider)
        .where(IdentityProvider.enabled.is_(True))
        .order_by(IdentityProvider.name)
    ).all()
    return [ProviderPublic(id=p.id, kind=p.kind, name=p.name) for p in rows]


@router.get("/auth/sso/{provider_id}/start", summary="Begin single sign-on", response_model=None)
def sso_start(
    provider_id: uuid.UUID,
    request: Request,
    client: Literal["web", "companion"] = "web",
    next: str | None = Query(None, max_length=500),
    redirect_uri: str | None = Query(None, max_length=500),
    code_challenge: str | None = Query(None, min_length=43, max_length=128),
    login_hint: str | None = Query(None, max_length=320),
    silent: bool = False,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    if not _start_limiter(settings).hit(ctx.ip or "unknown"):
        raise auth_api._too_many("Too many sign-in attempts. Wait a minute and try again.")
    provider = db.get(IdentityProvider, provider_id)
    if provider is None or not provider.enabled:
        if client == "companion":
            raise not_found("Identity provider")
        return _login_redirect("This sign-in option is not available.")
    if client == "companion":
        info = companion_info(settings)
        allowed = sso.companion_extension_ids(settings, str(info["id"]) if info else None)
        if not redirect_uri or not sso.companion_redirect_ok(redirect_uri, allowed):
            raise ProblemError(
                400,
                "Redirect not allowed",
                "Only the Veyra Companion extension can use this sign-in.",
                code="bad_redirect",
            )
        if not code_challenge:
            raise ProblemError(
                400, "Challenge required", "A PKCE code challenge is required.", code="bad_request"
            )
    try:
        started = sso.start(
            db,
            provider,
            base_url=base_url(request, settings),
            client=client,
            next_path=next,
            redirect_uri=redirect_uri,
            client_challenge=code_challenge,
            login_hint=login_hint,
            silent=silent,
            ip=ctx.ip,
        )
    except oidc.OidcError as e:
        _audit_failure(db, ctx, provider, e.reason, None)
        db.commit()
        if client == "companion":
            raise ProblemError(
                502, "Provider unavailable", str(e), code="provider_unavailable"
            ) from e
        return _login_redirect(f"{provider.name} is not reachable right now. Try again later.")
    db.commit()
    response = RedirectResponse(started.url, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    if started.browser_token:
        # Lax, unlike the session cookie: it must come back on the provider's
        # cross-site redirect to the callback.
        response.set_cookie(
            BROWSER_COOKIE,
            started.browser_token,
            max_age=int(sso.REQUEST_TTL.total_seconds()),
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path=BROWSER_COOKIE_PATH,
        )
    return response


@router.get("/auth/sso/callback", summary="Provider redirect", response_model=None)
def sso_callback(
    request: Request,
    code: str | None = Query(None, max_length=4096),
    state: str | None = Query(None, max_length=200),
    error: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    req = sso.pending_request(db, state) if state else None
    provider = db.get(IdentityProvider, req.provider_id) if req is not None else None
    if provider is None or req is None:
        _audit_failure(db, ctx, provider, "unknown_state", None)
        db.commit()
        return _login_redirect("This sign-in link is not valid. Start again.")

    def fail(reason: str, message: str, email: str | None = None) -> Response:
        req.used_at = req.used_at or utcnow()
        _audit_failure(db, ctx, provider, reason, email)
        db.commit()
        if req.client == "companion" and req.redirect_uri:
            # interaction_required and friends tell the extension to show its button.
            return RedirectResponse(
                f"{req.redirect_uri}?{urlencode({'error': reason, 'message': message})}",
                status_code=303,
            )
        resp = _login_redirect(message)
        resp.delete_cookie(BROWSER_COOKIE, path=BROWSER_COOKIE_PATH)
        return resp

    if error:
        reason = (
            error
            if error
            in {
                "login_required",
                "interaction_required",
                "consent_required",
                "account_selection_required",
                "access_denied",
            }
            else "provider_error"
        )
        return fail(
            reason,
            "Sign-in was cancelled or needs your input."
            if reason != "provider_error"
            else f"{provider.name} reported an error.",
        )
    if not code:
        return fail("no_code", "The provider did not complete the sign-in.")
    if not provider.enabled:
        return fail("disabled", "This sign-in option is not available.")
    try:
        secret = installation_key(request).decrypt(provider.client_secret_enc, sso.SECRET_PURPOSE)
        user, claims = sso.finish(
            db,
            provider,
            req,
            code=code,
            base_url=base_url(request, settings),
            browser_token=request.cookies.get(BROWSER_COOKIE),
            client_secret=secret,
        )
    except sso.SsoFailure as e:
        return fail(e.reason, e.message)

    audit.record(
        db,
        action="auth.sso.login",
        actor_user_id=user.id,
        actor_label=user.email,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        target_type="identity_provider",
        target_id=provider.id,
        details={"provider": provider.name, "client": req.client, "amr": claims.amr},
    )
    if req.client == "companion" and req.redirect_uri:
        one_time = sso.issue_companion_code(db, req, user)
        db.commit()
        return RedirectResponse(
            f"{req.redirect_uri}?{urlencode({'code': one_time})}", status_code=303
        )

    token, csrf, _session = create_session(
        db, user, settings, ip=ctx.ip, user_agent=ctx.user_agent, mfa_pending=False
    )
    db.commit()
    response = _continue_page(req.next_path or "/")
    auth_api._set_cookies(response, settings, token, csrf)
    response.delete_cookie(BROWSER_COOKIE, path=BROWSER_COOKIE_PATH)
    return response


class CompanionSsoIn(BaseModel):
    code: str = Field(min_length=16, max_length=200)
    code_verifier: str = Field(min_length=43, max_length=128)
    device: str = Field("Companion", min_length=1, max_length=120)


@router.post(
    "/auth/companion/sso",
    response_model=CompanionSessionOut,
    summary="Companion: exchange the one-time sign-in code for a token",
)
def companion_sso(
    body: CompanionSsoIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> CompanionSessionOut:
    if not auth_api._limiter(settings).hit(ctx.ip or "unknown"):
        raise auth_api._too_many("Too many sign-in attempts. Wait a minute and try again.")
    user = sso.redeem_companion_code(db, body.code, body.code_verifier)
    if user is None:
        db.commit()  # the code is spent either way
        raise ProblemError(
            401,
            "Sign-in failed",
            "The sign-in code is not valid any more. Sign in again.",
            code="invalid_code",
        )
    return companion_issue(request, db, settings, ctx, user, body.device)


# ----------------------------------------------------------------- administration


@router.get("/identity-providers/policy", response_model=PolicyIO, summary="Sign-in policy")
def get_policy(
    db: Session = Depends(get_db), principal: Principal = Depends(require("sso.read"))
) -> PolicyIO:
    return PolicyIO(require_sso=sso.load_policy(db).require_sso)


@router.put(
    "/identity-providers/policy",
    dependencies=[Depends(recent_auth)],
    response_model=PolicyIO,
    summary="Change the sign-in policy",
)
def put_policy(
    body: PolicyIO,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require("sso.write")),
    ctx: RequestContext = Depends(request_context),
) -> PolicyIO:
    sso.save_policy(db, sso.SsoPolicy(require_sso=body.require_sso), principal.user_id)
    audit.record(
        db,
        action="sso.policy.update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"require_sso": body.require_sso},
    )
    db.commit()
    return body


@router.get("/identity-providers", response_model=list[ProviderOut], summary="Identity providers")
def list_providers(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require("sso.read")),
) -> list[ProviderOut]:
    base = base_url(request, settings)
    rows = db.scalars(select(IdentityProvider).order_by(IdentityProvider.name)).all()
    return [_out(db, p, base) for p in rows]


@router.get("/identity-providers/redirect-uri", summary="The redirect address for every provider")
def redirect_uri(
    request: Request,
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require("sso.read")),
) -> dict[str, str]:
    return {"redirect_uri": sso.callback_url(base_url(request, settings))}


@router.post(
    "/identity-providers", response_model=ProviderOut, status_code=201, summary="Add a provider"
)
def create_provider(
    body: ProviderIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require("sso.write")),
    ctx: RequestContext = Depends(request_context),
) -> ProviderOut:
    if not body.client_secret:
        raise ProblemError(
            422, "Client secret required", "Enter the client secret.", code="secret_required"
        )
    if db.get(Organization, body.organization_id) is None:
        raise not_found("Organization")
    p = IdentityProvider(
        id=uuid.uuid4(),
        kind=body.kind,
        name=body.name.strip(),
        issuer=_issuer(body),
        client_id=body.client_id.strip(),
        client_secret_enc=installation_key(request).encrypt(body.client_secret, sso.SECRET_PURPOSE),
        allowed_domains=body.allowed_domains,
        organization_id=body.organization_id,
        create_accounts=body.create_accounts,
        default_role_key=body.default_role_key,
        enabled=body.enabled,
    )
    db.add(p)
    db.flush()
    audit.record(
        db,
        action="sso.provider.create",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="identity_provider",
        target_id=p.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": p.name, "kind": p.kind, "domains": p.allowed_domains},
    )
    db.commit()
    return _out(db, p, base_url(request, settings))


@router.get("/identity-providers/{provider_id}", response_model=ProviderOut)
def get_provider(
    provider_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require("sso.read")),
) -> ProviderOut:
    return _out(db, _provider(db, provider_id), base_url(request, settings))


@router.put("/identity-providers/{provider_id}", response_model=ProviderOut)
def update_provider(
    provider_id: uuid.UUID,
    body: ProviderIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require("sso.write")),
    ctx: RequestContext = Depends(request_context),
) -> ProviderOut:
    p = _provider(db, provider_id)
    if db.get(Organization, body.organization_id) is None:
        raise not_found("Organization")
    issuer = _issuer(body)
    if issuer != p.issuer or body.client_id.strip() != p.client_id:
        p.discovery = None
        p.jwks = None
        p.metadata_fetched_at = None
    p.kind = body.kind
    p.name = body.name.strip()
    p.issuer = issuer
    p.client_id = body.client_id.strip()
    if body.client_secret:
        p.client_secret_enc = installation_key(request).encrypt(
            body.client_secret, sso.SECRET_PURPOSE
        )
    p.allowed_domains = body.allowed_domains
    p.organization_id = body.organization_id
    p.create_accounts = body.create_accounts
    p.default_role_key = body.default_role_key
    p.enabled = body.enabled
    audit.record(
        db,
        action="sso.provider.update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="identity_provider",
        target_id=p.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={
            "name": p.name,
            "enabled": p.enabled,
            "domains": p.allowed_domains,
            "create_accounts": p.create_accounts,
            "secret_changed": bool(body.client_secret),
        },
    )
    db.commit()
    return _out(db, p, base_url(request, settings))


@router.delete("/identity-providers/{provider_id}", status_code=204)
def delete_provider(
    provider_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require("sso.write")),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    p = _provider(db, provider_id)
    audit.record(
        db,
        action="sso.provider.delete",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="identity_provider",
        target_id=p.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": p.name},
    )
    db.delete(p)
    db.commit()
    return Response(status_code=204)


@router.post("/identity-providers/{provider_id}/test", response_model=ProviderTestOut)
def test_provider(
    provider_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require("sso.write")),
) -> ProviderTestOut:
    p = _provider(db, provider_id)
    try:
        doc, jwks = sso.metadata(db, p, force=True)
    except oidc.OidcError as e:
        db.rollback()
        return ProviderTestOut(ok=False, message=str(e))
    db.commit()
    return ProviderTestOut(
        ok=True,
        message="Discovery and signing keys are reachable.",
        authorization_endpoint=str(doc.get("authorization_endpoint")),
        keys=len(jwks.get("keys", [])),
    )


# ----------------------------------------------------------------- account links


def _user_in_reach(db: Session, principal: Principal, user_id: uuid.UUID, perm: str) -> User:
    user = db.get(User, user_id)
    if user is None or user.auth_source == "integration":
        raise not_found("User")
    if not principal.has(perm, user.home_organization_id) and not principal.has(perm):
        raise not_found("User")
    return user


@router.get("/users/{user_id}/identities", response_model=list[IdentityOut])
def list_identities(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require("users.read")),
) -> list[IdentityOut]:
    _user_in_reach(db, principal, user_id, "users.read")
    rows = db.execute(
        select(UserIdentity, IdentityProvider.name)
        .join(IdentityProvider, IdentityProvider.id == UserIdentity.provider_id)
        .where(UserIdentity.user_id == user_id)
        .order_by(UserIdentity.created_at)
    ).all()
    return [
        IdentityOut(
            id=i.id,
            provider_id=i.provider_id,
            provider_name=name,
            email=i.email,
            created_at=i.created_at,
            last_used_at=i.last_used_at,
        )
        for i, name in rows
    ]


@router.delete("/users/{user_id}/identities/{identity_id}", status_code=204)
def unlink_identity(
    user_id: uuid.UUID,
    identity_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require("users.write")),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    user = _user_in_reach(db, principal, user_id, "users.write")
    link = db.get(UserIdentity, identity_id)
    if link is None or link.user_id != user.id:
        raise not_found("Linked identity")
    audit.record(
        db,
        action="sso.identity.unlink",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="user",
        target_id=user.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"email": link.email, "provider_id": str(link.provider_id)},
    )
    db.delete(link)
    db.commit()
    return Response(status_code=204)
