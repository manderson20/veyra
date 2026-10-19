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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.api.v1.companion import _origin
from veyra.api.v1.schemas import Email, MessageOut, UserOut, UserSessionOut
from veyra.core import audit, mail
from veyra.core.config import Settings, get_settings
from veyra.core.db import get_db
from veyra.core.deps import (
    SESSION_COOKIE,
    RequestContext,
    current_principal,
    request_context,
)
from veyra.core.errors import ProblemError, conflict, not_found
from veyra.core.models import Installation, PasswordResetToken, User, UserSession
from veyra.core.models.base import utcnow
from veyra.core.security import mfa, password_reset, passwords, trusted
from veyra.core.security.principal import Principal
from veyra.core.security.ratelimit import SlidingWindowLimiter
from veyra.core.security.sessions import (
    PRE_AUTH_TTL,
    active_sessions,
    create_session,
    load_principal,
    revoke_user_sessions,
)
from veyra.integrations import sso
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
    # Only read on an HA standby, whose sign-in cannot open a pre-authentication
    # session (docs/HIGH_AVAILABILITY.md §9): the authenticator code goes with
    # the password.
    code: str | None = Field(None, max_length=32)


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

    # The "Trust this browser for N days" choice (#137); 0: not offered.
    trust_days: int = 0

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


class ResetRequestIn(BaseModel):
    email: Email


class ResetOptionsOut(BaseModel):
    self_service: bool


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
        trust_days=mfa.load_policy(db).trusted_browser_days if methods else 0,
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


def check_credentials(
    db: Session, settings: Settings, ctx: RequestContext, email: str, password: str
) -> User:
    """Password sign-in shared by the web and Companion flows (same errors, audit
    and lockout behaviour); returns the user once the password is accepted."""
    user = db.scalar(select(User).where(User.email == email))
    now = utcnow()
    failure = ProblemError(
        401,
        "Sign-in failed",
        "The email address or password is incorrect.",
        code="invalid_credentials",
    )

    if user is None:
        passwords.verify_dummy(password)
        audit.record(
            db,
            action="auth.login",
            outcome="failure",
            actor_label=email,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"reason": "unknown_user"},
        )
        db.commit()
        raise failure
    if user.locked_until and user.locked_until > now:
        passwords.verify_dummy(password)
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
    if not passwords.verify_password(user.password_hash, password) or not user.is_active:
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

    if sso.password_blocked(db, user):
        audit.record(
            db,
            action="auth.login",
            outcome="denied",
            actor_user_id=user.id,
            actor_label=user.email,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"reason": "sso_required"},
        )
        db.commit()
        raise ProblemError(
            403,
            "Single sign-on required",
            "This account signs in with its organization's sign-in button, not a password.",
            code="sso_required",
        )
    if user.password_hash and passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    return user


def mfa_decision(db: Session, user: User, now: datetime) -> tuple[bool, bool, str]:
    """(second factor pending, enrolled, state label) for a signed-in user."""
    # Second factor (docs/MFA_DESIGN.md §4): enrolled users verify before the
    # session becomes usable; users whom policy requires to enrol get a grace
    # window first, then must enrol inside the pre-authentication session.
    policy = mfa.load_policy(db)
    required = mfa.is_required(db, policy, user)
    mfa.ensure_requirement(user, policy, required, now)
    enrolled = bool(mfa.confirmed_methods(db, user.id))
    pending = enrolled or (required and not mfa.in_grace(user, now))
    mfa_state = "pending" if enrolled else "enrol" if pending else "grace" if required else "none"
    return pending, enrolled, mfa_state


def standby_login(
    request: Request,
    body: LoginIn,
    response: Response,
    db: Session,
    settings: Settings,
    ctx: RequestContext,
) -> SessionOut:
    """Sign-in on an HA standby (docs/HIGH_AVAILABILITY.md §9): password and
    authenticator code checked against the replicated tables, no writes,
    platform administrators only, session in the API process."""
    import time

    from veyra.api.v1.extensions import installation_key
    from veyra.core.security import totp

    failure = ProblemError(
        401,
        "Sign-in failed",
        "The email address or password is incorrect.",
        code="invalid_credentials",
    )
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None:
        passwords.verify_dummy(body.password)
        raise failure
    now = utcnow()
    if (user.locked_until and user.locked_until > now) or not user.is_active:
        passwords.verify_dummy(body.password)
        raise failure
    if not passwords.verify_password(user.password_hash, body.password):
        raise failure
    principal = load_principal(db, user, None)
    if not principal.is_platform_admin:
        raise ProblemError(
            403,
            "Standby node",
            "Only platform administrators can sign in on the standby node.",
            code="ha_standby",
        )
    methods = [m for m in mfa.confirmed_methods(db, user.id) if m.type == mfa.METHOD_TOTP]
    if methods:
        key = installation_key(request)
        code = totp.normalize_code(body.code or "")
        matched = any(
            m.secret_ciphertext
            and totp.verify(
                key.decrypt(m.secret_ciphertext, mfa.secret_purpose(user.id)),
                code,
                timestamp=time.time(),
            )
            is not None
            for m in methods
        )
        if not matched:
            raise ProblemError(
                401 if body.code else 202,
                "Second factor required",
                "Enter the code from your authenticator app with your password.",
                code="mfa_code_required",
            )
    token, csrf = request.app.state.standby_sessions.create(user.id)
    _set_cookies(response, settings, token, csrf, max_age=3600)
    return _session_out(db, user, principal, csrf)


@router.post(
    "/login",
    response_model=SessionOut,
    responses={202: {"model": MfaChallengeOut, "description": "Second factor required"}},
    summary="Sign in with email and password",
)
def login(
    body: LoginIn,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> SessionOut | JSONResponse:
    # Per address and per account (docs/PRODUCTION_HARDENING.md §5): a
    # distributed guess at one account is slowed like a burst from one address.
    if not _limiter(settings).hit(ctx.ip or "unknown") or not _limiter(settings).hit(
        f"account:{body.email.lower()}"
    ):
        raise _too_many("Too many sign-in attempts. Wait a minute and try again.")
    if request.app.state.ha_guard.flags().standby:
        return standby_login(request, body, response, db, settings, ctx)
    user = check_credentials(db, settings, ctx, body.email, body.password)
    now = utcnow()
    pending, enrolled, mfa_state = mfa_decision(db, user, now)
    # A browser the user chose to trust skips the code while the policy allows (#137).
    if (
        pending
        and enrolled
        and mfa.load_policy(db).trusted_browser_days > 0
        and trusted.check(db, user, request.cookies.get(trusted.COOKIE), ctx.ip)
    ):
        pending, mfa_state = False, "trusted_browser"
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
    request: Request,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    standby = getattr(request.app.state, "standby_sessions", None)
    if principal.session_id is None and standby is not None:
        standby.revoke(request.cookies.get(SESSION_COOKIE, ""))
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")
        return MessageOut(message="Signed out.")
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


class TrustedBrowserOut(BaseModel):
    id: uuid.UUID
    label: str | None
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    last_ip: str | None
    current: bool


@router.get(
    "/trusted-browsers",
    response_model=list[TrustedBrowserOut],
    summary="Browsers that skip your second factor",
)
def list_trusted_browsers(
    request: Request,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
) -> list[TrustedBrowserOut]:
    from veyra.core.models import TrustedBrowser
    from veyra.core.security import tokens

    mine = request.cookies.get(trusted.COOKIE)
    current = tokens.digest(mine) if mine else None
    rows = db.scalars(
        select(TrustedBrowser)
        .where(TrustedBrowser.user_id == principal.user_id, TrustedBrowser.expires_at > utcnow())
        .order_by(TrustedBrowser.created_at.desc())
    ).all()
    return [
        TrustedBrowserOut(
            id=r.id,
            label=r.label,
            created_at=r.created_at,
            expires_at=r.expires_at,
            last_used_at=r.last_used_at,
            last_ip=r.last_ip,
            current=r.token_hash == current,
        )
        for r in rows
    ]


@router.delete(
    "/trusted-browsers",
    response_model=MessageOut,
    summary="Forget every browser: each asks for the code again",
)
def forget_trusted_browsers(
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    n = trusted.forget_all(db, principal.user_id)
    audit.record(
        db,
        action="auth.trusted_browser_remove",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"removed": n},
    )
    db.commit()
    return MessageOut(message=f"{n} browser{'s' if n != 1 else ''} will ask for the code again.")


@router.delete(
    "/trusted-browsers/{browser_id}",
    response_model=MessageOut,
    summary="Forget one trusted browser",
)
def forget_trusted_browser(
    browser_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    from veyra.core.models import TrustedBrowser

    row = db.get(TrustedBrowser, browser_id)
    if row is None or row.user_id != principal.user_id:
        raise not_found("Trusted browser")
    db.delete(row)
    audit.record(
        db,
        action="auth.trusted_browser_remove",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"removed": 1},
    )
    db.commit()
    return MessageOut(message="That browser will ask for the code again.")


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
        "Request a new one from the sign-in page, or ask an administrator.",
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


# ----------------------------------------------------------------- self-service reset

# A new emailed link for the same account at most this often, so a stranger
# cannot flood a mailbox or keep replacing a link an administrator issued.
SELF_SERVICE_INTERVAL = timedelta(minutes=5)
SELF_SERVICE_ISSUER = "self-service"
_REQUEST_ACCEPTED = (
    "If an account with that address can reset its password here, a link is on its way. "
    "Check your email; the link works once."
)


def _self_service_ready(db: Session) -> mail.SmtpSettings | None:
    smtp = mail.load_smtp_settings(db)
    return smtp if smtp.enabled and not smtp.problems() else None


@router.get(
    "/password-reset/options",
    response_model=ResetOptionsOut,
    summary='Whether the sign-in page offers "Forgot your password?"',
)
def reset_options(db: Session = Depends(get_db)) -> ResetOptionsOut:
    return ResetOptionsOut(self_service=_self_service_ready(db) is not None)


@router.post(
    "/password-reset/request",
    response_model=MessageOut,
    status_code=202,
    summary="Email a one-time reset link to the account with this address",
)
def request_reset(
    body: ResetRequestIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    """The answer is the same whether or not the address has an account, so
    the form cannot be used to find out who has one."""
    if not _reset_limit(settings).hit(ctx.ip or "unknown"):
        raise _too_many("Too many attempts. Wait a minute and try again.")
    smtp = _self_service_ready(db)
    if smtp is None:
        raise ProblemError(
            409,
            "Not available",
            "Password reset by email is not set up here. Ask an administrator for a reset link.",
            code="self_service_reset_unavailable",
        )
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    reason = None
    if user is None:
        reason = "unknown_address"
    elif not user.is_active:
        reason = "disabled"
    elif (user.auth_source != "local" and not user.is_recovery_admin) or sso.password_blocked(
        db, user
    ):
        reason = "external_sign_in"
    elif db.scalar(
        select(PasswordResetToken.id).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.issued_by == SELF_SERVICE_ISSUER,
            PasswordResetToken.created_at > utcnow() - SELF_SERVICE_INTERVAL,
        )
    ):
        reason = "recently_sent"
    if user is None or reason is not None:
        audit.record(
            db,
            action="auth.password_reset_request",
            outcome="failure",
            actor_label="anonymous",
            target_type="user" if user else None,
            target_id=user.id if user else None,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"reason": reason},
        )
        db.commit()
        return MessageOut(message=_REQUEST_ACCEPTED)
    token, row = password_reset.issue_reset_token(
        db, user, settings, issued_by=SELF_SERVICE_ISSUER, issued_from_ip=ctx.ip
    )
    inst = db.scalar(select(Installation))
    from_address, from_name = mail.sender(smtp, inst.name if inst else "Veyra")
    base = f"https://{settings.public_host}" if settings.public_host else _origin(request)
    hours = settings.password_reset_ttl_hours
    msg = mail.compose(
        from_address=from_address,
        from_name=from_name,
        to=user.email,
        subject="Reset your phone system password",
        text=(
            f"Hello {user.display_name},\n\n"
            "Someone (hopefully you) asked to reset the password of this account. "
            "Open the link below to choose a new one:\n\n"
            f"{base}{password_reset.reset_link_path(token)}\n\n"
            f"The link works once and expires in {hours} hour{'s' if hours != 1 else ''}. "
            "Setting a new password signs out your other sessions.\n\n"
            "If you did not ask for this, ignore this message: your password stays as it is. "
            f"The request came from {ctx.ip or 'an unknown address'}.\n"
        ),
    )
    mail.enqueue(settings.mailqueue_dir, msg.as_bytes())
    audit.record(
        db,
        action="auth.password_reset_request",
        actor_label="anonymous",
        organization_id=user.home_organization_id,
        target_type="user",
        target_id=user.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"expires_at": row.expires_at.isoformat()},
    )
    db.commit()
    return MessageOut(message=_REQUEST_ACCEPTED)
