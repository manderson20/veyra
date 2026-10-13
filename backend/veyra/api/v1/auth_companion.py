# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cookie-less sign-in for the Companion extension and bearer-token management
(docs/COMPANION.md §3, ADR 0015).

The password, lockout, rate-limit and second-factor logic is the web flow's
(``auth.check_credentials``, ``auth_mfa.attempt_second_factor``); only the
credential handed back differs: a scoped bearer token instead of cookies.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from veyra.api.v1 import auth as auth_api
from veyra.api.v1.auth import check_credentials, mfa_challenge, mfa_decision
from veyra.api.v1.auth_mfa import attempt_second_factor
from veyra.api.v1.me import MyExtensionOut, my_extensions
from veyra.core import audit
from veyra.core.config import Settings, get_settings
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, current_principal, request_context
from veyra.core.errors import ProblemError, forbidden, not_found
from veyra.core.models import ApiToken, User
from veyra.core.models.base import utcnow
from veyra.core.security import api_tokens
from veyra.core.security.principal import Principal
from veyra.core.security.sessions import create_session, resolve_session

router = APIRouter(prefix="/auth", tags=["auth"])


# ----------------------------------------------------------------- schemas


class CompanionLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    device: str = Field("Companion", min_length=1, max_length=120)


class CompanionVerifyIn(BaseModel):
    challenge: str = Field(min_length=16, max_length=128)
    code: str = Field(min_length=4, max_length=64)
    device: str = Field("Companion", min_length=1, max_length=120)


class CompanionUserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str


class CompanionSessionOut(BaseModel):
    token: str
    token_id: uuid.UUID
    expires_at: datetime
    user: CompanionUserOut
    permissions: list[str]
    extensions: list[MyExtensionOut]
    installation_name: str
    version: str


class CompanionChallengeOut(BaseModel):
    challenge: str
    enrol: bool
    methods: int
    expires_at: datetime


class ApiTokenOut(BaseModel):
    id: uuid.UUID
    kind: str
    label: str
    scopes: list[str]
    created_at: datetime
    created_ip: str | None
    expires_at: datetime
    last_used_at: datetime | None
    last_used_ip: str | None
    is_current: bool = False


def token_summary(t: ApiToken, current: uuid.UUID | None) -> ApiTokenOut:
    return ApiTokenOut(
        id=t.id,
        kind=t.kind,
        label=t.label,
        scopes=list(t.scopes or []),
        created_at=t.created_at,
        created_ip=t.created_ip,
        expires_at=t.expires_at,
        last_used_at=t.last_used_at,
        last_used_ip=t.last_used_ip,
        is_current=t.id == current,
    )


# ----------------------------------------------------------------- helpers


def _issue(
    request: Request,
    db: Session,
    settings: Settings,
    ctx: RequestContext,
    user: User,
    device: str,
) -> CompanionSessionOut:
    from veyra.core.security.sessions import load_principal
    from veyra.version import __version__

    raw, token = api_tokens.issue(
        db,
        user,
        settings,
        kind=api_tokens.KIND_COMPANION,
        label=device,
        scopes=api_tokens.COMPANION_SCOPES,
        ip=ctx.ip,
    )
    user.last_login_at = utcnow()
    audit.record(
        db,
        action="auth.token_issue",
        actor_user_id=user.id,
        actor_label=user.email,
        target_type="api_token",
        target_id=token.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"kind": token.kind, "label": token.label},
    )
    db.commit()
    principal = load_principal(db, user, None)
    principal.token_scopes = frozenset(token.scopes)
    principal.token_id = token.id
    request.state.principal = principal
    inst_name = auth_api._session_out(db, user, principal).installation_name
    return CompanionSessionOut(
        token=raw,
        token_id=token.id,
        expires_at=token.expires_at,
        user=CompanionUserOut(id=user.id, email=user.email, display_name=user.display_name),
        permissions=principal.effective_permissions(),
        extensions=my_extensions(request, principal, db),
        installation_name=inst_name,
        version=__version__,
    )


# ----------------------------------------------------------------- sign in


@router.post(
    "/companion/login",
    response_model=CompanionSessionOut,
    responses={202: {"model": CompanionChallengeOut, "description": "Second factor required"}},
    summary="Companion sign-in: a bearer token instead of cookies",
)
def companion_login(
    body: CompanionLoginIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> CompanionSessionOut | JSONResponse:
    if not auth_api._limiter(settings).hit(ctx.ip or "unknown"):
        raise auth_api._too_many("Too many sign-in attempts. Wait a minute and try again.")
    user = check_credentials(db, settings, ctx, body.email.strip().lower(), body.password)
    now = utcnow()
    pending, enrolled, mfa_state = mfa_decision(db, user, now)
    if user.must_change_password:
        db.commit()
        raise ProblemError(
            403,
            "Password change required",
            "Choose a new password in the web interface, then sign in here.",
            code="password_change_required",
        )
    if pending and not enrolled:
        audit.record(
            db,
            action="auth.companion_login",
            outcome="denied",
            actor_user_id=user.id,
            actor_label=user.email,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"reason": "mfa_enrolment_required"},
        )
        db.commit()
        raise ProblemError(
            403,
            "Two-factor enrolment required",
            "Set up an authenticator app in the web interface, then sign in here.",
            code="mfa_enrolment_required",
        )
    if pending:
        token, _csrf, session = create_session(
            db, user, settings, ip=ctx.ip, user_agent=ctx.user_agent, mfa_pending=True
        )
        audit.record(
            db,
            action="auth.companion_login",
            actor_user_id=user.id,
            actor_label=user.email,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"mfa": mfa_state, "device": body.device},
        )
        db.commit()
        challenge = mfa_challenge(db, user, session)
        out = CompanionChallengeOut(
            challenge=token,
            enrol=challenge.enrol,
            methods=len(challenge.methods),
            expires_at=session.expires_at,
        )
        return JSONResponse(status_code=202, content=jsonable_encoder(out))
    audit.record(
        db,
        action="auth.companion_login",
        actor_user_id=user.id,
        actor_label=user.email,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"mfa": mfa_state, "device": body.device},
    )
    return _issue(request, db, settings, ctx, user, body.device)


@router.post(
    "/companion/verify",
    response_model=CompanionSessionOut,
    summary="Companion sign-in: complete the second factor",
)
def companion_verify(
    body: CompanionVerifyIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> CompanionSessionOut:
    if not auth_api._limiter(settings).hit(ctx.ip or "unknown"):
        raise auth_api._too_many("Too many attempts. Wait a minute and try again.")
    resolved = resolve_session(db, body.challenge, settings)
    if resolved is None or resolved[0].mfa_verified_at is not None:
        raise ProblemError(
            410,
            "Challenge expired",
            "Start the sign-in again.",
            code="challenge_expired",
        )
    session, user = resolved
    now = utcnow()
    used = attempt_second_factor(db, request, user, session, body.code, ctx, now)
    # The pre-authentication session has done its job; the token replaces it.
    session.revoked_at = now
    audit.record(
        db,
        action="auth.mfa_verify",
        actor_user_id=user.id,
        actor_label=user.email,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={
            "method": "recovery_code" if used == "recovery_code" else "totp",
            "client": "companion",
        },
    )
    return _issue(request, db, settings, ctx, user, body.device)


@router.post("/companion/logout", status_code=204, summary="Revoke this Companion token")
def companion_logout(
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    if principal.token_id is None:
        raise ProblemError(
            400, "Not a token", "This route is for bearer-token clients.", code="not_a_token"
        )
    token = db.get(ApiToken, principal.token_id)
    if token is not None:
        api_tokens.revoke(db, token)
        audit.record(
            db,
            action="auth.token_revoke",
            actor_user_id=principal.user_id,
            actor_label=principal.label,
            target_type="api_token",
            target_id=token.id,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"label": token.label, "by": "logout"},
        )
        db.commit()
    return Response(status_code=204)


# ----------------------------------------------------------------- own tokens


def _require_me(principal: Principal = Depends(current_principal)) -> Principal:
    if not principal.has_scope("me"):
        raise forbidden()
    return principal


@router.get("/tokens", response_model=list[ApiTokenOut], summary="Your connected apps")
def list_tokens(
    principal: Principal = Depends(_require_me), db: Session = Depends(get_db)
) -> list[ApiTokenOut]:
    return [
        token_summary(t, principal.token_id)
        for t in api_tokens.active_tokens(db, principal.user_id)
    ]


@router.delete("/tokens/{token_id}", status_code=204, summary="Revoke one of your tokens")
def revoke_token(
    token_id: uuid.UUID,
    principal: Principal = Depends(_require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    token = db.get(ApiToken, token_id)
    if token is None or token.user_id != principal.user_id or token.revoked_at is not None:
        raise not_found("Token")
    api_tokens.revoke(db, token)
    audit.record(
        db,
        action="auth.token_revoke",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="api_token",
        target_id=token.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"label": token.label},
    )
    db.commit()
    return Response(status_code=204)


@router.post("/tokens/revoke-all", summary="Revoke every token of yours")
def revoke_all_tokens(
    principal: Principal = Depends(_require_me),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, int]:
    count = api_tokens.revoke_user_tokens(db, principal.user_id)
    audit.record(
        db,
        action="auth.token_revoke",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"revoked": count, "all": True},
    )
    db.commit()
    return {"revoked": count}
