"""Local authentication: sign in, sign out, current session, password change."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1.schemas import Email, MessageOut, UserOut
from veyra.core import audit
from veyra.core.config import Settings, get_settings
from veyra.core.db import get_db
from veyra.core.deps import (
    SESSION_COOKIE,
    RequestContext,
    current_principal,
    request_context,
)
from veyra.core.errors import ProblemError
from veyra.core.models import Installation, User, UserSession
from veyra.core.models.base import utcnow
from veyra.core.security import passwords
from veyra.core.security.principal import Principal
from veyra.core.security.ratelimit import SlidingWindowLimiter
from veyra.core.security.sessions import create_session, revoke_user_sessions

router = APIRouter(prefix="/auth", tags=["authentication"])

CSRF_COOKIE = "veyra_csrf"
_ip_limiter: SlidingWindowLimiter | None = None


def _limiter(settings: Settings) -> SlidingWindowLimiter:
    global _ip_limiter
    if _ip_limiter is None or _ip_limiter.limit != settings.login_rate_limit_per_minute:
        _ip_limiter = SlidingWindowLimiter(settings.login_rate_limit_per_minute, 60)
    return _ip_limiter


class LoginIn(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=1024)


class SessionOut(BaseModel):
    user: UserOut
    permissions: list[str]
    is_platform_admin: bool
    installation_name: str
    csrf_token: str | None = None


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


def _set_cookies(response: Response, settings: Settings, token: str, csrf: str) -> None:
    max_age = settings.session_ttl_hours * 3600
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


def _session_out(
    db: Session, user: User, principal: Principal, csrf: str | None = None
) -> SessionOut:
    inst = db.scalar(select(Installation))
    return SessionOut(
        user=UserOut.model_validate(user),
        permissions=principal.effective_permissions(),
        is_platform_admin=principal.is_platform_admin,
        installation_name=inst.name if inst else "Veyra",
        csrf_token=csrf,
    )


@router.post("/login", response_model=SessionOut, summary="Sign in with email and password")
def login(
    body: LoginIn,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> SessionOut:
    from veyra.core.security.sessions import load_principal

    if not _limiter(settings).hit(ctx.ip or "unknown"):
        raise ProblemError(
            429,
            "Too many requests",
            "Too many sign-in attempts. Wait a minute and try again.",
            code="rate_limited",
            headers={"Retry-After": "60"},
        )
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
    user.last_login_at = now
    token, csrf, session = create_session(db, user, settings, ip=ctx.ip, user_agent=ctx.user_agent)
    audit.record(
        db,
        action="auth.login",
        actor_user_id=user.id,
        actor_label=user.email,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
    )
    db.commit()
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
    try:
        passwords.validate_password(body.new_password, email=user.email)
    except passwords.PasswordPolicyError as e:
        raise ProblemError(422, "Password not changed", str(e), code="password_policy") from e
    user.password_hash = passwords.hash_password(body.new_password)
    revoke_user_sessions(db, user.id, except_id=principal.session_id)
    audit.record(
        db,
        action="auth.password_change",
        actor_user_id=user.id,
        actor_label=user.email,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
    )
    db.commit()
    return MessageOut(message="Password changed. Other sessions have been signed out.")
