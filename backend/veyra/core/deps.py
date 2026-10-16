# SPDX-License-Identifier: AGPL-3.0-or-later
"""FastAPI dependencies shared across routers."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.config import Settings, get_settings
from veyra.core.db import get_db
from veyra.core.errors import ProblemError, forbidden
from veyra.core.models import User
from veyra.core.security import api_tokens, tokens
from veyra.core.security.principal import Principal
from veyra.core.security.sessions import load_principal, resolve_session

SESSION_COOKIE = "veyra_session"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# A user who must change a temporary password may only use these routes.
FORCED_CHANGE_ALLOWED_PREFIX = "/api/v1/auth/"
# A pre-authentication session (second factor pending) may only use these.
# An explicit list, not a prefix, so nothing under /auth/mfa/ (such as the
# policy) is reachable before the factor is verified.
PRE_AUTH_ALLOWED_PATHS = frozenset(
    {
        "/api/v1/auth/mfa/challenge",
        "/api/v1/auth/mfa/verify",
        "/api/v1/auth/mfa/totp/begin",
        "/api/v1/auth/mfa/totp/confirm",
        "/api/v1/auth/logout",
    }
)


@dataclass
class RequestContext:
    ip: str | None
    request_id: str | None
    user_agent: str | None


def client_ip(request: Request, settings: Settings) -> str | None:
    """Client address, honouring X-Forwarded-For only for the configured number
    of trusted reverse proxies (NGINX in front of the API)."""
    peer = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded or settings.trusted_proxy_count <= 0:
        return peer
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    if len(hops) >= settings.trusted_proxy_count:
        return hops[-settings.trusted_proxy_count]
    return peer


def request_context(request: Request, settings: Settings = Depends(get_settings)) -> RequestContext:
    return RequestContext(
        ip=client_ip(request, settings),
        request_id=getattr(request.state, "request_id", None),
        user_agent=request.headers.get("user-agent"),
    )


def unauthorized(detail: str = "Sign in to continue.") -> ProblemError:
    return ProblemError(401, "Unauthorized", detail, code="unauthorized")


def bearer_token(request: Request) -> str | None:
    """The bearer token of the request, if it carries one (ADR 0015)."""
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _token_principal(request: Request, db: Session, settings: Settings, raw: str) -> Principal:
    """A bearer caller: no cookie, no CSRF, no pre-authentication state. The
    token's scopes cap the permissions; the user's grants still decide."""
    if not api_tokens.looks_like_token(raw):
        raise unauthorized("The token is not valid.")
    resolved = api_tokens.resolve(db, raw, settings, ip=client_ip(request, settings))
    if resolved is None:
        raise unauthorized("The token has expired or was revoked. Sign in again.")
    token, user = resolved
    if token.kind == api_tokens.KIND_INTEGRATION:
        from veyra.integrations import tokens as integration_tokens

        integration = integration_tokens.by_token(db, token)
        if integration is None:
            raise unauthorized("The token has expired or was revoked.")
        if not integration_tokens.address_allowed(integration, client_ip(request, settings)):
            raise ProblemError(
                403,
                "Address not allowed",
                "This integration token may not be used from this address.",
                code="address_not_allowed",
            )
        principal = integration_tokens.principal_for(integration, token)
        request.state.principal = principal
        return principal
    if user.must_change_password:
        raise ProblemError(
            403,
            "Password change required",
            "Choose a new password in the web interface before continuing.",
            code="password_change_required",
        )
    principal = load_principal(db, user, None)
    principal.token_scopes = frozenset(token.scopes or [])
    principal.token_id = token.id
    request.state.principal = principal
    return principal


def current_principal(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Principal:
    bearer = bearer_token(request)
    if bearer is not None:
        return _token_principal(request, db, settings, bearer)
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise unauthorized()
    standby = getattr(request.app.state, "standby_sessions", None)
    if standby is not None and (ss := standby.resolve(token)) is not None:
        # The standby's in-memory session (docs/HIGH_AVAILABILITY.md §9).
        if request.method not in SAFE_METHODS and not standby.csrf_ok(
            ss, request.headers.get(CSRF_HEADER, "")
        ):
            raise ProblemError(
                403, "Forbidden", "Missing or invalid CSRF token.", code="csrf_failed"
            )
        standby_user = db.get(User, ss.user_id)
        if standby_user is None or not standby_user.is_active:
            raise unauthorized("Your session has expired. Sign in again.")
        principal = load_principal(db, standby_user, None)
        request.state.principal = principal
        return principal
    resolved = resolve_session(db, token, settings)
    if resolved is None:
        raise unauthorized("Your session has expired. Sign in again.")
    session, user = resolved
    if request.method not in SAFE_METHODS:
        csrf = request.headers.get(CSRF_HEADER, "")
        if not csrf or not tokens.matches(csrf, session.csrf_token_hash):
            raise ProblemError(
                403, "Forbidden", "Missing or invalid CSRF token.", code="csrf_failed"
            )
    if session.mfa_verified_at is None and request.url.path not in PRE_AUTH_ALLOWED_PATHS:
        raise ProblemError(
            403,
            "Second factor required",
            "Complete two-factor sign-in to continue.",
            code="mfa_required",
        )
    if user.must_change_password and not request.url.path.startswith(FORCED_CHANGE_ALLOWED_PREFIX):
        raise ProblemError(
            403,
            "Password change required",
            "Choose a new password before continuing.",
            code="password_change_required",
        )
    principal = load_principal(db, user, session.id)
    request.state.principal = principal
    return principal


def require(permission: str) -> Callable[..., Principal]:
    """Dependency factory: the caller must hold ``permission`` in at least one
    scope. Handlers that act on a specific organization must additionally call
    ``principal.has(permission, organization_id)``."""

    def dependency(
        request: Request,
        principal: Principal = Depends(current_principal),
        db: Session = Depends(get_db),
        ctx: RequestContext = Depends(request_context),
    ) -> Principal:
        if not principal.has_any_scope(permission):
            if request.method not in SAFE_METHODS:
                audit.record(
                    db,
                    action=f"permission.denied:{permission}",
                    outcome="denied",
                    actor_user_id=principal.user_id,
                    actor_label=principal.label,
                    ip_address=ctx.ip,
                    request_id=ctx.request_id,
                    details={"method": request.method, "path": request.url.path},
                )
                db.commit()
            raise forbidden()
        return principal

    dependency.__name__ = f"require_{permission.replace('.', '_')}"
    return dependency


def require_in_org(
    principal: Principal, permission: str, organization_id: uuid.UUID | None
) -> None:
    if not principal.has(permission, organization_id):
        raise forbidden()
