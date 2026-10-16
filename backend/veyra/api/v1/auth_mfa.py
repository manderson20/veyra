# SPDX-License-Identifier: AGPL-3.0-or-later
"""Multi-factor authentication: the challenge after sign-in, enrolment of an
authenticator app, recovery codes, method management and the policy.

Pre-authentication sessions (password accepted, factor pending) can reach only
the routes listed in ``veyra.core.deps.PRE_AUTH_ALLOWED_PATHS``: challenge,
verify, and TOTP begin/confirm, the last two only while no factor is enrolled.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1 import auth as auth_api
from veyra.api.v1.auth import (
    MfaChallengeOut,
    MfaMethodOut,
    MfaStatusOut,
    SessionOut,
    _session_out,
    _set_cookies,
    _too_many,
    mfa_challenge,
    mfa_status,
)
from veyra.api.v1.schemas import MessageOut
from veyra.core import audit
from veyra.core.config import Settings, get_settings
from veyra.core.db import get_db
from veyra.core.deps import (
    SESSION_COOKIE,
    RequestContext,
    current_principal,
    request_context,
    require,
)
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.models import MfaMethod, User, UserSession
from veyra.core.models.base import utcnow
from veyra.core.security import mfa, passwords, totp
from veyra.core.security.crypto import (
    DecryptionError,
    InstallationKey,
    InstallationKeyError,
    load_installation_key,
)
from veyra.core.security.principal import Principal
from veyra.core.security.sessions import complete_mfa, load_principal

router = APIRouter(prefix="/auth/mfa", tags=["authentication"])


# ----------------------------------------------------------------- schemas


class VerifyIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class TotpBeginIn(BaseModel):
    label: str = Field("Authenticator app", min_length=1, max_length=100)


class TotpBeginOut(BaseModel):
    method_id: uuid.UUID
    secret: str
    uri: str
    qr_svg: str  # data URI
    expires_at: datetime | None = None


class TotpConfirmIn(BaseModel):
    method_id: uuid.UUID
    code: str = Field(min_length=1, max_length=64)
    # Optional device name chosen while scanning the code.
    label: str | None = Field(None, max_length=100)


class TotpConfirmOut(BaseModel):
    method: MfaMethodOut
    # Shown exactly once; empty when codes already existed (second device).
    recovery_codes: list[str]
    session: SessionOut


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]


class MethodsOut(BaseModel):
    status: MfaStatusOut
    methods: list[MfaMethodOut]
    allowed_methods: list[str]


class PolicyOut(BaseModel):
    policy: mfa.MfaPolicy
    roles: list[dict[str, str]]


# ----------------------------------------------------------------- helpers


def _session_and_user(db: Session, principal: Principal) -> tuple[UserSession, User]:
    session = db.get(UserSession, principal.session_id) if principal.session_id else None
    user = db.get(User, principal.user_id)
    if session is None or user is None:
        raise ProblemError(401, "Unauthorized", "Sign in to continue.", code="unauthorized")
    return session, user


def _key(request: Request) -> InstallationKey:
    try:
        return load_installation_key(request.app.state.settings)
    except InstallationKeyError as e:
        raise ProblemError(
            503,
            "Installation key unavailable",
            f"Two-factor secrets cannot be stored or read: {e}",
            code="installation_key_missing",
        ) from e


def _method_out(m: MfaMethod) -> MfaMethodOut:
    return MfaMethodOut(
        id=m.id, type=m.type, label=m.label, created_at=m.created_at, last_used_at=m.last_used_at
    )


def _check_password(db: Session, user: User, password: str, ctx: RequestContext, what: str) -> None:
    """Re-authentication for sensitive changes (removing a factor, new codes)."""
    if not passwords.verify_password(user.password_hash, password):
        audit.record(
            db,
            action=what,
            outcome="failure",
            actor_user_id=user.id,
            actor_label=user.email,
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"reason": "bad_password"},
        )
        db.commit()
        raise ProblemError(
            400, "Not changed", "The password is incorrect.", code="invalid_credentials"
        )


def _record(
    db: Session,
    ctx: RequestContext,
    user: User,
    action: str,
    outcome: str = "success",
    **details: object,
) -> None:
    audit.record(
        db,
        action=action,
        outcome=outcome,
        actor_user_id=user.id,
        actor_label=user.email,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=dict(details),
    )


# ----------------------------------------------------------------- challenge and verify


@router.get(
    "/challenge",
    response_model=MfaChallengeOut,
    summary="What the pre-authentication session must do next",
)
def challenge(
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
) -> MfaChallengeOut:
    session, user = _session_and_user(db, principal)
    out = mfa_challenge(db, user, session)
    out.mfa_pending = session.mfa_verified_at is None
    return out


def attempt_second_factor(
    db: Session,
    request: Request,
    user: User,
    session: UserSession,
    code: str,
    ctx: RequestContext,
    now: datetime,
) -> str:
    """Check an authenticator or recovery code against the pre-authentication
    session (shared by the web and Companion flows). Failures are counted,
    audited and raised; the return value names what matched."""
    methods = mfa.confirmed_methods(db, user.id)
    if not methods:
        raise conflict("No second factor is set up for this account.", "mfa_not_enrolled")
    used: str | None = None
    code = code.strip()
    if len(totp.normalize_code(code)) == totp.DIGITS and totp.normalize_code(code).isdigit():
        key = _key(request)
        for m in methods:
            if m.type != mfa.METHOD_TOTP or not m.secret_ciphertext:
                continue
            try:
                secret = key.decrypt(m.secret_ciphertext, mfa.secret_purpose(user.id))
            except DecryptionError as e:
                raise ProblemError(
                    503,
                    "Second factor unreadable",
                    f"The authenticator secret cannot be decrypted: {e}",
                    code="secret_unreadable",
                ) from e
            matched = totp.verify(
                secret, code, timestamp=time.time(), last_used_step=m.last_used_step
            )
            if matched is not None:
                m.last_used_step = matched
                m.last_used_at = now
                used = f"totp:{m.id}"
                break
    if (
        used is None
        and mfa.looks_like_recovery_code(code)
        and mfa.use_recovery_code(db, user.id, code, now)
    ):
        used = "recovery_code"
    if used is None:
        session.mfa_failures += 1
        locked = session.mfa_failures >= mfa.MAX_VERIFY_FAILURES
        if locked:
            session.revoked_at = now
        _record(
            db,
            ctx,
            user,
            "auth.mfa_verify",
            outcome="failure",
            failures=session.mfa_failures,
            locked=locked,
        )
        db.commit()
        if locked:
            raise ProblemError(
                401,
                "Too many incorrect codes",
                "Sign in again to retry.",
                code="mfa_locked",
            )
        raise ProblemError(
            401, "Code not accepted", "The code is incorrect or has expired.", code="invalid_code"
        )
    return used


@router.post(
    "/verify",
    response_model=SessionOut,
    summary="Complete sign-in with an authenticator code or a recovery code",
)
def verify(
    body: VerifyIn,
    request: Request,
    response: Response,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> SessionOut:
    session, user = _session_and_user(db, principal)
    if session.mfa_verified_at is not None:
        raise conflict("This session has already completed two-factor sign-in.", "already_verified")
    # Codes share the sign-in budget per address (NGINX enforces the same).
    if not auth_api._limiter(settings).hit(ctx.ip or "unknown"):
        raise _too_many("Too many attempts. Wait a minute and try again.")
    now = utcnow()
    used = attempt_second_factor(db, request, user, session, body.code, ctx, now)
    csrf = complete_mfa(session, settings)
    user.last_login_at = now
    remaining = mfa.recovery_codes_remaining(db, user.id)
    _record(
        db,
        ctx,
        user,
        "auth.mfa_verify",
        method="recovery_code" if used == "recovery_code" else "totp",
        recovery_codes_remaining=remaining,
    )
    db.commit()
    session_token = request.cookies.get(SESSION_COOKIE, "")
    _set_cookies(response, settings, session_token, csrf)
    return _session_out(db, user, load_principal(db, user, session.id), csrf)


# ----------------------------------------------------------------- enrolment


def _enrolment_allowed(session: UserSession, methods: list[MfaMethod]) -> None:
    """Inside a pre-authentication session a factor may be enrolled only when
    none exists; otherwise the password alone would be enough to add a device."""
    if session.mfa_verified_at is None and methods:
        raise forbidden("Complete two-factor sign-in before adding another authenticator.")


@router.post(
    "/totp/begin", response_model=TotpBeginOut, summary="Start enrolling an authenticator app"
)
def totp_begin(
    body: TotpBeginIn,
    request: Request,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> TotpBeginOut:
    session, user = _session_and_user(db, principal)
    _enrolment_allowed(session, mfa.confirmed_methods(db, user.id))
    policy = mfa.load_policy(db)
    if mfa.METHOD_TOTP not in policy.allowed_methods:
        raise conflict("Authenticator apps are not allowed by the policy.", "method_not_allowed")
    key = _key(request)
    # One pending enrolment at a time.
    for stale in db.scalars(
        select(MfaMethod).where(MfaMethod.user_id == user.id, MfaMethod.confirmed_at.is_(None))
    ):
        db.delete(stale)
    secret = totp.new_secret()
    method = MfaMethod(
        id=uuid.uuid4(),
        user_id=user.id,
        type=mfa.METHOD_TOTP,
        label=body.label.strip() or "Authenticator app",
        secret_ciphertext=key.encrypt(secret, mfa.secret_purpose(user.id)),
        created_at=utcnow(),
    )
    db.add(method)
    _record(db, ctx, user, "auth.mfa_enrol_begin", method_id=str(method.id))
    db.commit()
    uri = totp.provisioning_uri(secret, user.email)
    return TotpBeginOut(
        method_id=method.id,
        secret=secret,
        uri=uri,
        qr_svg=totp.qr_svg_data_uri(uri),
        expires_at=session.expires_at if session.mfa_verified_at is None else None,
    )


@router.post(
    "/totp/confirm",
    response_model=TotpConfirmOut,
    summary="Confirm the authenticator with its first code; returns the recovery codes once",
)
def totp_confirm(
    body: TotpConfirmIn,
    request: Request,
    response: Response,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> TotpConfirmOut:
    session, user = _session_and_user(db, principal)
    existing = mfa.confirmed_methods(db, user.id)
    _enrolment_allowed(session, existing)
    method = db.get(MfaMethod, body.method_id)
    if method is None or method.user_id != user.id or method.confirmed_at is not None:
        raise not_found("Pending authenticator")
    key = _key(request)
    assert method.secret_ciphertext is not None
    secret = key.decrypt(method.secret_ciphertext, mfa.secret_purpose(user.id))
    matched = totp.verify(secret, body.code, timestamp=time.time())
    if matched is None:
        _record(db, ctx, user, "auth.mfa_enrol_confirm", outcome="failure")
        db.commit()
        raise ProblemError(
            400,
            "Code not accepted",
            "The code did not match. Check the time on your phone and try the next code.",
            code="invalid_code",
        )
    now = utcnow()
    method.confirmed_at = now
    method.last_used_at = now
    method.last_used_step = matched
    if body.label and body.label.strip():
        method.label = body.label.strip()
    codes = mfa.replace_recovery_codes(db, user.id) if not existing else []
    csrf: str | None = None
    completed = session.mfa_verified_at is None
    if completed:
        csrf = complete_mfa(session, settings)
        user.last_login_at = now
    _record(
        db,
        ctx,
        user,
        "auth.mfa_enrol_confirm",
        method_id=str(method.id),
        first_method=not existing,
        completed_sign_in=completed,
    )
    db.commit()
    if csrf is not None:
        _set_cookies(response, settings, request.cookies.get(SESSION_COOKIE, ""), csrf)
    return TotpConfirmOut(
        method=_method_out(method),
        recovery_codes=codes,
        session=_session_out(db, user, load_principal(db, user, session.id), csrf),
    )


# ----------------------------------------------------------------- management


@router.get("/methods", response_model=MethodsOut, summary="Your second factors")
def list_methods(
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
) -> MethodsOut:
    _, user = _session_and_user(db, principal)
    return MethodsOut(
        status=mfa_status(db, user),
        methods=[_method_out(m) for m in mfa.confirmed_methods(db, user.id)],
        allowed_methods=mfa.load_policy(db).allowed_methods,
    )


@router.post(
    "/methods/{method_id}/remove",
    response_model=MessageOut,
    summary="Remove a second factor (password required)",
)
def remove_method(
    method_id: uuid.UUID,
    body: PasswordIn,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    _, user = _session_and_user(db, principal)
    method = db.get(MfaMethod, method_id)
    if method is None or method.user_id != user.id or method.confirmed_at is None:
        raise not_found("Authenticator")
    _check_password(db, user, body.password, ctx, "auth.mfa_method_remove")
    others = [m for m in mfa.confirmed_methods(db, user.id) if m.id != method.id]
    policy = mfa.load_policy(db)
    if not others and mfa.is_required(db, policy, user):
        raise conflict(
            "Your role requires two-factor authentication; add another authenticator before "
            "removing this one.",
            "mfa_required_by_policy",
        )
    db.delete(method)
    if not others:
        mfa.remove_all_factors(db, user.id)  # also drops the recovery codes
    _record(
        db, ctx, user, "auth.mfa_method_remove", method_id=str(method_id), remaining=len(others)
    )
    db.commit()
    return MessageOut(
        message="Authenticator removed."
        if others
        else "Authenticator and recovery codes removed. Two-factor sign-in is off for your account."
    )


@router.post(
    "/recovery-codes/regenerate",
    response_model=RecoveryCodesOut,
    summary="Replace your recovery codes (password required)",
)
def regenerate_recovery_codes(
    body: PasswordIn,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RecoveryCodesOut:
    _, user = _session_and_user(db, principal)
    if not mfa.confirmed_methods(db, user.id):
        raise conflict("Set up an authenticator first.", "mfa_not_enrolled")
    _check_password(db, user, body.password, ctx, "auth.mfa_recovery_codes_regenerate")
    codes = mfa.replace_recovery_codes(db, user.id)
    _record(db, ctx, user, "auth.mfa_recovery_codes_regenerate")
    db.commit()
    return RecoveryCodesOut(recovery_codes=codes)


# ----------------------------------------------------------------- policy


def _roles() -> list[dict[str, str]]:
    from veyra.core.security.permissions import SYSTEM_ROLE_DEFS

    return [{"key": key, "name": name} for key, name, _ in SYSTEM_ROLE_DEFS]


@router.get("/policy", response_model=PolicyOut, summary="Two-factor policy")
def get_policy(
    principal: Principal = Depends(require("system.settings.read")),
    db: Session = Depends(get_db),
) -> PolicyOut:
    return PolicyOut(policy=mfa.load_policy(db), roles=_roles())


@router.put("/policy", response_model=PolicyOut, summary="Change the two-factor policy")
def put_policy(
    body: mfa.MfaPolicy,
    principal: Principal = Depends(require("system.settings.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PolicyOut:
    before = mfa.load_policy(db).model_dump(mode="json")
    mfa.save_policy(db, body, updated_by=principal.user_id)
    affected = mfa.apply_policy(db, body)
    after = body.model_dump(mode="json")
    audit.record(
        db,
        action="security.mfa_policy_update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="settings",
        target_id=mfa.MFA_POLICY_KEY,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={
            "changed": {k: after[k] for k in after if before.get(k) != after[k]},
            "users_affected": affected,
        },
    )
    db.commit()
    return PolicyOut(policy=body, roles=_roles())
