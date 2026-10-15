# SPDX-License-Identifier: AGPL-3.0-or-later
"""Single sign-on through OpenID Connect (docs/INTEGRATIONS.md §1).

``start`` records a sign-in attempt and returns the provider's authorization
URL; ``finish`` checks the callback, verifies the ID token and returns the
Veyra account. Sessions and Companion tokens are created by the API layer.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from veyra.core.config import Settings
from veyra.core.models import (
    IdentityProvider,
    Role,
    RoleAssignment,
    SsoRequest,
    SystemSetting,
    User,
    UserIdentity,
)
from veyra.core.models.base import utcnow
from veyra.core.security import oidc, tokens

SECRET_PURPOSE = "sso:client-secret"  # noqa: S105 (an encryption purpose)
POLICY_KEY = "auth.sso"
REQUEST_TTL = timedelta(minutes=10)
CODE_TTL = timedelta(seconds=60)
METADATA_TTL = timedelta(hours=24)
KINDS = ("google", "microsoft", "oidc")
CLIENTS = ("web", "companion")


class SsoPolicy(BaseModel):
    # Accounts linked to a provider may not use a password (recovery admin exempt).
    require_sso: bool = False


class SsoFailure(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass
class Started:
    url: str
    browser_token: str | None


def load_policy(db: Session) -> SsoPolicy:
    row = db.get(SystemSetting, POLICY_KEY)
    if row is None or not isinstance(row.value, dict):
        return SsoPolicy()
    return SsoPolicy.model_validate(row.value)


def save_policy(db: Session, policy: SsoPolicy, updated_by: uuid.UUID | None) -> None:
    row = db.get(SystemSetting, POLICY_KEY)
    value = policy.model_dump(mode="json")
    if row is None:
        db.add(SystemSetting(key=POLICY_KEY, value=value, updated_by=updated_by))
    else:
        row.value = value
        row.updated_by = updated_by
    db.flush()


def has_identity(db: Session, user_id: uuid.UUID) -> bool:
    return (
        db.scalar(select(UserIdentity.id).where(UserIdentity.user_id == user_id).limit(1))
        is not None
    )


def password_blocked(db: Session, user: User) -> bool:
    """True when policy says this account signs in through its provider only."""
    if user.is_recovery_admin:
        return False
    return load_policy(db).require_sso and has_identity(db, user.id)


def callback_url(base: str) -> str:
    """One address for every provider: the state names the attempt and its provider."""
    return f"{base}/api/v1/auth/sso/callback"


def companion_extension_ids(settings: Settings, packaged_id: str | None) -> set[str]:
    ids = {i.strip() for i in settings.companion_dev_extension_ids.split(",") if i.strip()}
    if packaged_id:
        ids.add(packaged_id)
    return ids


def companion_redirect_ok(redirect_uri: str, allowed_ids: set[str]) -> bool:
    parts = urlsplit(redirect_uri)
    if parts.scheme != "https" or parts.query or parts.fragment or parts.port is not None:
        return False
    host = (parts.hostname or "").lower()
    if not host.endswith(".chromiumapp.org"):
        return False
    return host.removesuffix(".chromiumapp.org") in allowed_ids


def safe_next(value: str | None) -> str:
    """Only a local path: no scheme, no host, no protocol-relative ``//``."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return "/"
    return value[:500]


# --------------------------------------------------------------------------- metadata


def metadata(
    db: Session, provider: IdentityProvider, *, force: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The discovery document and key set, cached for a day."""
    fresh = (
        provider.discovery
        and provider.jwks
        and provider.metadata_fetched_at
        and utcnow() - provider.metadata_fetched_at < METADATA_TTL
    )
    if fresh and not force:
        return provider.discovery or {}, provider.jwks or {}
    doc = oidc.discover(provider.issuer)
    jwks = oidc.fetch_jwks(doc)
    provider.discovery = doc
    provider.jwks = jwks
    provider.metadata_fetched_at = utcnow()
    db.flush()
    return doc, jwks


def _jwks_with(db: Session, provider: IdentityProvider, token: str) -> dict[str, Any]:
    """The key set, refetched once when the token names a key we do not know
    (the provider rotated its keys)."""
    _, jwks = metadata(db, provider)
    kid = oidc.token_kid(token)
    if kid and not any(isinstance(k, dict) and k.get("kid") == kid for k in jwks.get("keys", [])):
        _, jwks = metadata(db, provider, force=True)
    return jwks


# --------------------------------------------------------------------------- flow


def start(
    db: Session,
    provider: IdentityProvider,
    *,
    base_url: str,
    client: str,
    next_path: str | None,
    redirect_uri: str | None,
    client_challenge: str | None,
    login_hint: str | None,
    silent: bool,
    ip: str | None,
) -> Started:
    doc, _ = metadata(db, provider)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    verifier = oidc.new_verifier()
    browser = secrets.token_urlsafe(32) if client == "web" else None
    now = utcnow()
    db.add(
        SsoRequest(
            id=uuid.uuid4(),
            provider_id=provider.id,
            state_hash=tokens.digest(state),
            browser_hash=tokens.digest(browser) if browser else None,
            nonce=nonce,
            code_verifier=verifier,
            client=client,
            next_path=safe_next(next_path) if client == "web" else None,
            redirect_uri=redirect_uri if client == "companion" else None,
            client_challenge=client_challenge if client == "companion" else None,
            created_at=now,
            expires_at=now + REQUEST_TTL,
            ip_address=ip,
        )
    )
    extra: dict[str, str] = {}
    domains = [d.strip().lower() for d in provider.allowed_domains if d.strip()]
    if provider.kind == "google" and len(domains) == 1:
        extra["hd"] = domains[0]
    if login_hint and "@" in login_hint and len(login_hint) <= 320:
        extra["login_hint"] = login_hint
    if silent:
        extra["prompt"] = "none"
    elif provider.kind == "google" and client == "web":
        extra["prompt"] = "select_account"
    url = oidc.authorization_url(
        doc,
        client_id=provider.client_id,
        redirect_uri=callback_url(base_url),
        state=state,
        nonce=nonce,
        verifier=verifier,
        extra=extra,
    )
    db.flush()
    return Started(url=url, browser_token=browser)


def pending_request(db: Session, state: str) -> SsoRequest | None:
    return db.scalar(select(SsoRequest).where(SsoRequest.state_hash == tokens.digest(state)))


def finish(
    db: Session,
    provider: IdentityProvider,
    req: SsoRequest,
    *,
    code: str,
    base_url: str,
    browser_token: str | None,
    client_secret: str,
) -> tuple[User, oidc.IdClaims]:
    now = utcnow()
    if req.used_at is not None or req.expires_at < now:
        raise SsoFailure("expired_request", "This sign-in link has expired. Start again.")
    req.used_at = now
    if req.client == "web" and (
        not browser_token
        or not req.browser_hash
        or not tokens.matches(browser_token, req.browser_hash)
    ):
        raise SsoFailure(
            "browser_mismatch", "This sign-in was started in another browser. Start again."
        )
    try:
        doc, _ = metadata(db, provider)
        id_token = oidc.exchange_code(
            doc,
            client_id=provider.client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=callback_url(base_url),
            verifier=req.code_verifier,
        )
        jwks = _jwks_with(db, provider, id_token)
        claims = oidc.verify_id_token(
            id_token, jwks, issuer=provider.issuer, client_id=provider.client_id, nonce=req.nonce
        )
    except oidc.OidcError as e:
        raise SsoFailure(e.reason, str(e)) from e
    if not oidc.domain_allowed(claims, provider.allowed_domains, kind=provider.kind):
        raise SsoFailure(
            "domain_not_allowed", f"{claims.email} is not allowed to sign in to Veyra."
        )
    user = resolve_user(db, provider, claims)
    return user, claims


def resolve_user(db: Session, provider: IdentityProvider, claims: oidc.IdClaims) -> User:
    now = utcnow()
    link = db.scalar(
        select(UserIdentity).where(
            UserIdentity.provider_id == provider.id, UserIdentity.subject == claims.subject
        )
    )
    if link is not None:
        user = db.get(User, link.user_id)
        if user is None:  # pragma: no cover (cascade deletes the link)
            raise SsoFailure("no_account", "No Veyra account for this address.")
    else:
        user = db.scalar(select(User).where(User.email == claims.email))
        if user is None:
            if not provider.create_accounts:
                raise SsoFailure(
                    "no_account",
                    f"There is no Veyra account for {claims.email}. Ask an administrator.",
                )
            user = _create_account(db, provider, claims)
        if user.auth_source == "integration":
            raise SsoFailure("no_account", "No Veyra account for this address.")
        if user.is_recovery_admin:
            raise SsoFailure(
                "recovery_admin",
                "The recovery administrator always signs in with a password.",
            )
        link = UserIdentity(
            id=uuid.uuid4(),
            user_id=user.id,
            provider_id=provider.id,
            subject=claims.subject,
            email=claims.email,
            created_at=now,
        )
        db.add(link)
    if user.is_recovery_admin:
        raise SsoFailure(
            "recovery_admin", "The recovery administrator always signs in with a password."
        )
    if not user.is_active:
        raise SsoFailure("inactive", "This Veyra account is disabled.")
    link.last_used_at = now
    user.last_login_at = now
    db.flush()
    return user


def _create_account(db: Session, provider: IdentityProvider, claims: oidc.IdClaims) -> User:
    user = User(
        id=uuid.uuid4(),
        email=claims.email,
        display_name=claims.name[:200],
        password_hash=None,
        auth_source=provider.kind,
        home_organization_id=provider.organization_id,
    )
    db.add(user)
    db.flush()
    role = db.scalar(
        select(Role).where(Role.key == provider.default_role_key, Role.organization_id.is_(None))
    )
    if role is not None and role.key != "platform_admin":
        db.add(
            RoleAssignment(
                id=uuid.uuid4(),
                user_id=user.id,
                role_id=role.id,
                scope_type="organization",
                organization_id=provider.organization_id,
                site_id=None,
            )
        )
    return user


def issue_companion_code(db: Session, req: SsoRequest, user: User) -> str:
    code = secrets.token_urlsafe(32)
    req.result_code_hash = tokens.digest(code)
    req.result_user_id = user.id
    req.result_expires_at = utcnow() + CODE_TTL
    db.flush()
    return code


def redeem_companion_code(db: Session, code: str, verifier: str) -> User | None:
    req = db.scalar(select(SsoRequest).where(SsoRequest.result_code_hash == tokens.digest(code)))
    now = utcnow()
    if (
        req is None
        or req.client != "companion"
        or req.result_user_id is None
        or req.result_expires_at is None
        or req.result_expires_at < now
        or not req.client_challenge
    ):
        return None
    # One use, whatever happens next.
    req.result_code_hash = None
    db.flush()
    if not secrets.compare_digest(oidc.challenge_of(verifier), req.client_challenge):
        return None
    user = db.get(User, req.result_user_id)
    if user is None or not user.is_active:
        return None
    return user


def prune(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    result = db.execute(delete(SsoRequest).where(SsoRequest.expires_at < now - timedelta(hours=1)))
    return int(getattr(result, "rowcount", 0) or 0)
