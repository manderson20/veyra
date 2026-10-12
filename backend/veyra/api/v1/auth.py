# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local authentication: sign in, sign out, current session, password change,
the caller's sessions, and one-time password reset links."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1.schemas import Email, MessageOut, UserOut, UserSessionOut
from veyra.core import audit
from veyra.core.config import Settings, get_settings
from veyra.core.db import get_db
from veyra.core.deps import (
    SESSION_COOKIE,
    RequestContext,
    current_principal,
    request_context,
)
from veyra.core.errors import ProblemError, conflict, not_found
from veyra.core.models import Installation, User, UserSession
from veyra.core.models.base import utcnow
from veyra.core.security import mfa, password_reset, passwords
from veyra.core.security.principal import Principal
from veyra.core.security.ratelimit import SlidingWindowLimiter
from veyra.core.security.sessions import (
    PRE_AUTH_TTL,
    active_sessions,
    create_session,
    load_principal,
    revoke_user_sessions,
)
from veyra.version import __version__

router = APIRouter(prefix="/auth", tags=["authentication"])

CSRF_COOKIE = "veyra_csrf"
_ip_limiter: SlidingWindowLimiter | None = None
_reset_limiter: SlidingWindowLimiter | None = None


def _limiter(settings: Settings) -> SlidingWindowLimiter:
    global _ip_limiter
    if _ip_limiter is None or _ip_limiter.limit != settings.login_rate_limit_per_minute:
        _ip_limiter = SlidingWindowLimiter(settings.login_rate_limit_per_minute, 60)
    return _ip_limiter


def _reset_limit(settings: Settings) -> SlidingWindowLimiter:
    """Reset-link lookups share the sign-in budget: guessing tokens must be as
    slow as guessing passwords."""
    global _reset_limiter
    if _reset_limiter is None or _reset_limiter.limit != settings.login_rate_limit_per_minute:
        _reset_limiter = SlidingWindowLimiter(settings.login_rate_limit_per_minute, 60)
    return _reset_limiter


def _too_many(detail: str) -> ProblemError:
    return ProblemError(
        429, "Too many requests", detail, code="rate_limited", headers={"Retry-After": "60"}
    )


class LoginIn(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=1024)


class MfaStatusOut(BaseModel):
    """The caller's second-factor situation, for the account page and the nag."""

    enabled: bool
    required: bool
    grace_until: datetime | None = None
    methods: int = 0
    recovery_codes_remaining: int = 0


class MfaMethodOut(BaseModel):
    id: uuid.UUID
    type: str
    label: str
    created_at: datetime | None = None
    last_used_at: datetime | None = None


class MfaChallengeOut(BaseModel):
    """Returned by sign-in (202) while the second factor is pending."""

    mfa_pending: bool = True
    # True when policy requires a factor and none is enrolled: the pre-auth
    # session may enrol one (and only then).
    enrol: bool
    methods: list[MfaMethodOut]
    email: str
    display_name: str
    expires_at: datetime


class SessionOut(BaseModel):
    user: UserOut
    permissions: list[str]
    is_platform_admin: bool
    installation_name: str
    # True when an administrator set a temporary password: only the
    # authentication endpoints work until the user chooses a new one.
    must_change_password: bool = False
    csrf_token: str | None = None
    # Shown next to the logo so administrators know what they are running.
    version: str = __version__
    release: str | None = None
    mfa: MfaStatusOut = MfaStatusOut(enabled=False, required=False)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class ResetTokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class ResetTokenInfo(BaseModel):
    display_name: str
    email: str
    expires_at: str


class PasswordResetIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=1024)


def _set_cookies(
    response: Response, settings: Settings, token: str, csrf: str, max_age: int | None = None
) -> None:
    max_age = max_age if max_age is not None else settings.session_ttl_hours * 3600
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    # Double-submit CSRF token: readable by the UI, echoed in X-CSRF-Token.
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


def mfa_status(db: Session, user: User) -> MfaStatusOut:
    methods = mfa.confirmed_methods(db, user.id)
    return MfaStatusOut(
        enabled=bool(methods),
        required=mfa.is_required(db, mfa.load_policy(db), user),
        grace_until=user.mfa_grace_until if not methods else None,
        methods=len(methods),
        recovery_codes_remaining=mfa.recovery_codes_remaining(db, user.id) if methods else 0,
    )


def _session_out(
    db: Session, user: User, principal: Principal, csrf: str | None = None
) -> SessionOut:
    inst = db.scalar(select(Installation))
    out = UserOut.model_validate(user)
    status = mfa_status(db, user)
    out.mfa_enabled = status.enabled
    return SessionOut(
        user=out,
        permissions=principal.effective_permissions(),
        is_platform_admin=principal.is_platform_admin,
        installation_name=inst.name if inst else "Veyra",
        must_change_password=user.must_change_password,
        csrf_token=csrf,
        release=get_settings().installed_release(),
        mfa=status,
    )


def mfa_challenge(db: Session, user: User, session: UserSession) -> MfaChallengeOut:
    methods = mfa.confirmed_methods(db, user.id)
    return MfaChallengeOut(
        enrol=not methods,
        methods=[
            MfaMethodOut(
                id=m.id,
                type=m.type,
                label=m.label,
                created_at=m.created_at,
                last_used_at=m.last_used_at,
            )
            for m in methods
        ],
        email=user.email,
        display_name=user.display_name,
        expires_at=session.expires_at,
    )


def pre_auth_response(
    db: Session, user: User, session: UserSession, settings: Settings, token: str, csrf: str
) -> JSONResponse:
    response = JSONResponse(
        status_code=202, content=jsonable_encoder(mfa_challenge(db, user, session))
    )
    _set_cookies(response, settings, token, csrf, max_age=int(PRE_AUTH_TTL.total_seconds()))
    return response


def _policy_error(e: passwords.PasswordPolicyError, field: str = "new_password") -> ProblemError:
    return ProblemError(
        422,
        "Password not changed",
        str(e),
        code="password_policy",
        errors=[{"field": field, "message": str(e)}],
    )


def session_summary(s: UserSession, current_id: uuid.UUID | None) -> UserSessionOut:
    return UserSessionOut(
        id=s.id,
        created_at=s.created_at,
        last_seen_at=s.last_seen_at,
        expires_at=s.expires_at,
        ip_address=s.ip_address,
        user_agent=s.user_agent,
        is_current=s.id == current_id,
    )


# ----------------------------------------------------------------- sign in / out


@router.post(
    "/login",
    response_model=SessionOut,
    responses={202: {"model": MfaChallengeOut, "description": "Second factor required"}},
    summary="Sign in with email and password",
)
def login(
    body: LoginIn,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> SessionOut | JSONResponse:
    if not _limiter(settings).hit(ctx.ip or "unknown"):
        raise _too_many("Too many sign-in attempts. Wait a minute and try again.")
    user = db.scalar(select(User).where(User.email == body.email))
    now = utcnow()
    failure = ProblemError(
        401,
        "Sign-in failed",
        "The email address or password is incorrect.",
        code="invalid_credentials",
    )

    if user is None:
        passwords.verify_dummy(body.password)
        audit.record(
            db,
            action="auth.login",
            outcome="failure",
            actor_label=body.email,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"reason": "unknown_user"},
        )
        db.commit()
        raise failure
    if user.locked_until and user.locked_until > now:
        passwords.verify_dummy(body.password)
        audit.record(
            db,
            action="auth.login",
            outcome="denied",
            actor_user_id=user.id,
            actor_label=user.email,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"reason": "locked"},
        )
        db.commit()
        raise failure
    if not passwords.verify_password(user.password_hash, body.password) or not user.is_active:
        if user.is_active:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.account_lockout_threshold:
                user.locked_until = now + timedelta(minutes=settings.account_lockout_minutes)
                user.failed_login_count = 0
        audit.record(
            db,
            action="auth.login",
            outcome="failure",
            actor_user_id=user.id,
            actor_label=user.email,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"reason": "inactive" if not user.is_active else "bad_password"},
        )
        db.commit()
        raise failure

    if user.password_hash and passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(body.password)
    user.failed_login_count = 0
    user.locked_until = None
    # Second factor (docs/MFA_DESIGN.md §4): enrolled users verify before the
    # session becomes usable; users whom policy requires to enrol get a grace
    # window first, then must enrol inside the pre-authentication session.
    policy = mfa.load_policy(db)
    required = mfa.is_required(db, policy, user)
    mfa.ensure_requirement(user, policy, required, now)
    enrolled = bool(mfa.confirmed_methods(db, user.id))
    pending = enrolled or (required and not mfa.in_grace(user, now))
    mfa_state = "pending" if enrolled else "enrol" if pending else "grace" if required else "none"
    if not pending:
        user.last_login_at = now
    token, csrf, session = create_session(
        db, user, settings, ip=ctx.ip, user_agent=ctx.user_agent, mfa_pending=pending
    )
    audit.record(
        db,
        action="auth.login",
        actor_user_id=user.id,
        actor_label=user.email,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"must_change_password": user.must_change_password, "mfa": mfa_state},
    )
    db.commit()
    if pending:
        return pre_auth_response(db, user, session, settings, token, csrf)
    _set_cookies(response, settings, token, csrf)
    return _session_out(db, user, load_principal(db, user, session.id), csrf)


@router.post("/logout", response_model=MessageOut, summary="Sign out of the current session")
def logout(
    response: Response,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    if principal.session_id:
        s = db.get(UserSession, principal.session_id)
        if s:
            s.revoked_at = utcnow()
    audit.record(
        db,
        action="auth.logout",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
    )
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    # Ask the browser to drop any other cookie it holds for this origin too.
    response.headers["Clear-Site-Data"] = '"cookies"'
    return MessageOut(message="Signed out.")


@router.get(
    "/session", response_model=SessionOut, summary="Current user, permissions and installation"
)
def session_info(
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
) -> SessionOut:
    user = db.get(User, principal.user_id)
    assert user is not None
    return _session_out(db, user, principal)


# ----------------------------------------------------------------- password change


@router.post("/password", response_model=MessageOut, summary="Change your own password")
def change_password(
    body: PasswordChangeIn,
    request: Request,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    user = db.get(User, principal.user_id)
    assert user is not None
    if not passwords.verify_password(user.password_hash, body.current_password):
        audit.record(
            db,
            action="auth.password_change",
            outcome="failure",
            actor_user_id=user.id,
            actor_label=user.email,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
        )
        db.commit()
        raise ProblemError(
            400,
            "Password not changed",
            "The current password is incorrect.",
            code="invalid_credentials",
        )
    if body.new_password == body.current_password:
        raise _policy_error(
            passwords.PasswordPolicyError("The new password must differ from the current one.")
        )
    try:
        passwords.validate_password(
            body.new_password, email=user.email, display_name=user.display_name
        )
    except passwords.PasswordPolicyError as e:
        raise _policy_error(e) from e
    _apply_new_password(user, body.new_password)
    revoked = revoke_user_sessions(db, user.id, except_id=principal.session_id)
    audit.record(
        db,
        action="auth.password_change",
        actor_user_id=user.id,
        actor_label=user.email,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"sessions_revoked": revoked},
    )
    db.commit()
    return MessageOut(message="Password changed. Other sessions have been signed out.")


def _apply_new_password(user: User, new_password: str) -> None:
    user.password_hash = passwords.hash_password(new_password)
    user.password_changed_at = utcnow()
    user.must_change_password = False
    user.failed_login_count = 0
    user.locked_until = None


# ----------------------------------------------------------------- own sessions


@router.get("/sessions", response_model=list[UserSessionOut], summary="Your active sessions")
def list_own_sessions(
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[UserSessionOut]:
    return [
        session_summary(s, principal.session_id)
        for s in active_sessions(db, principal.user_id, settings)
    ]


@router.delete(
    "/sessions/{session_id}", response_model=MessageOut, summary="Sign out one of your sessions"
)
def revoke_own_session(
    session_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    if session_id == principal.session_id:
        raise conflict("Use sign out to end the current session.", code="current_session")
    s = db.get(UserSession, session_id)
    if s is None or s.user_id != principal.user_id or s.revoked_at is not None:
        raise not_found("Session")
    s.revoked_at = utcnow()
    audit.record(
        db,
        action="auth.session_revoke",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="session",
        target_id=s.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"session_ip": s.ip_address},
    )
    db.commit()
    return MessageOut(message="Session signed out.")


@router.post(
    "/sessions/revoke-others",
    response_model=MessageOut,
    summary="Sign out everywhere except this session",
)
def revoke_other_sessions(
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    revoked = revoke_user_sessions(db, principal.user_id, except_id=principal.session_id)
    audit.record(
        db,
        action="auth.sessions_revoke_others",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"sessions_revoked": revoked},
    )
    db.commit()
    if revoked == 0:
        return MessageOut(message="No other sessions were signed in.")
    return MessageOut(
        message=f"Signed out of {revoked} other session{'s' if revoked != 1 else ''}."
    )


# ----------------------------------------------------------------- password reset links


def _reset_not_found() -> ProblemError:
    return ProblemError(
        404,
        "Reset link not valid",
        "This password reset link is invalid, has expired or has already been used. "
        "Ask an administrator for a new one.",
        code="reset_token_invalid",
    )


@router.post(
    "/password-reset/check",
    response_model=ResetTokenInfo,
    summary="Check a password reset link before showing the form",
)
def check_reset_token(
    body: ResetTokenIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> ResetTokenInfo:
    if not _reset_limit(settings).hit(ctx.ip or "unknown"):
        raise _too_many("Too many attempts. Wait a minute and try again.")
    resolved = password_reset.resolve_reset_token(db, body.token)
    if resolved is None:
        raise _reset_not_found()
    reset, user = resolved
    return ResetTokenInfo(
        display_name=user.display_name, email=user.email, expires_at=reset.expires_at.isoformat()
    )


@router.post(
    "/password-reset",
    response_model=MessageOut,
    summary="Set a new password with a one-time reset link",
)
def reset_password(
    body: PasswordResetIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    if not _reset_limit(settings).hit(ctx.ip or "unknown"):
        raise _too_many("Too many attempts. Wait a minute and try again.")
    resolved = password_reset.resolve_reset_token(db, body.token)
    if resolved is None:
        audit.record(
            db,
            action="auth.password_reset",
            outcome="failure",
            actor_label="anonymous",
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"reason": "invalid_token"},
        )
        db.commit()
        raise _reset_not_found()
    reset, user = resolved
    try:
        passwords.validate_password(
            body.new_password, email=user.email, display_name=user.display_name
        )
    except passwords.PasswordPolicyError as e:
        raise _policy_error(e) from e
    _apply_new_password(user, body.new_password)
    reset.used_at = utcnow()
    revoked = revoke_user_sessions(db, user.id)
    audit.record(
        db,
        action="auth.password_reset",
        actor_user_id=user.id,
        actor_label=user.email,
        target_type="user",
        target_id=user.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"issued_by": reset.issued_by, "sessions_revoked": revoked},
    )
    db.commit()
    return MessageOut(message="Password set. Sign in with your new password.")
