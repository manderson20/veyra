# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scoped bearer tokens for clients without cookies (ADR 0015, docs/COMPANION.md §3).

A token is ``vyc_`` plus 32 random bytes in URL-safe base64; only its SHA-256
digest is stored. It expires ``companion_token_idle_days`` after its last use
and ``companion_token_max_days`` after creation, whichever comes first, and
its permissions are the intersection of the user's grants and its scopes.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from veyra.core.config import Settings
from veyra.core.models import ApiToken, User
from veyra.core.models.base import utcnow
from veyra.core.security import tokens

TOKEN_PREFIX = "vyc_"  # noqa: S105 (a public prefix, not a secret)
# Integration tokens (docs/INTEGRATIONS.md §2): an organization's, not a person's;
# no idle expiry, only the integration's own expiry date.
INTEGRATION_PREFIX = "vyi_"
KIND_COMPANION = "companion"
KIND_INTEGRATION = "integration"
# What a companion token may do, whatever the user's roles allow beyond it.
COMPANION_SCOPES: tuple[str, ...] = ("calls.originate", "calls.read", "directory.read", "me")
_TOUCH_INTERVAL = timedelta(seconds=60)


def new_token(prefix: str = TOKEN_PREFIX) -> str:
    return prefix + secrets.token_urlsafe(32)


def looks_like_token(value: str) -> bool:
    return value.startswith((TOKEN_PREFIX, INTEGRATION_PREFIX)) and 40 <= len(value) <= 80


def issue(
    db: Session,
    user: User,
    settings: Settings,
    *,
    kind: str,
    label: str,
    scopes: tuple[str, ...] | list[str],
    ip: str | None,
) -> tuple[str, ApiToken]:
    """Create a token row and return the clear token (shown once) with the row."""
    raw = new_token()
    now = utcnow()
    row = ApiToken(
        id=uuid.uuid4(),
        user_id=user.id,
        kind=kind,
        label=(label or "Companion").strip()[:120] or "Companion",
        token_hash=tokens.digest(raw),
        scopes=list(scopes),
        created_at=now,
        created_ip=ip,
        expires_at=now + timedelta(days=settings.companion_token_idle_days),
        last_used_at=None,
        last_used_ip=None,
        revoked_at=None,
    )
    db.add(row)
    return raw, row


def resolve(
    db: Session,
    raw: str,
    settings: Settings,
    *,
    ip: str | None = None,
    now: datetime | None = None,
) -> tuple[ApiToken, User] | None:
    """The live token and its user, or None. Extends the idle expiry on use
    (at most once a minute) up to the hard maximum age."""
    now = now or utcnow()
    row = db.execute(
        select(ApiToken, User)
        .join(User, User.id == ApiToken.user_id)
        .where(ApiToken.token_hash == tokens.digest(raw))
    ).first()
    if row is None:
        return None
    token, user = row
    if token.revoked_at is not None or token.expires_at <= now or not user.is_active:
        return None
    if token.kind == KIND_INTEGRATION:
        if token.last_used_at is None or now - token.last_used_at >= _TOUCH_INTERVAL:
            token.last_used_at = now
            token.last_used_ip = ip
            db.commit()
        return token, user
    hard_limit = token.created_at + timedelta(days=settings.companion_token_max_days)
    if hard_limit <= now:
        return None
    if token.last_used_at is None or now - token.last_used_at >= _TOUCH_INTERVAL:
        token.last_used_at = now
        token.last_used_ip = ip
        token.expires_at = min(now + timedelta(days=settings.companion_token_idle_days), hard_limit)
        db.commit()
    return token, user


def active_tokens(db: Session, user_id: uuid.UUID) -> list[ApiToken]:
    now = utcnow()
    return list(
        db.scalars(
            select(ApiToken)
            .where(
                ApiToken.user_id == user_id,
                ApiToken.revoked_at.is_(None),
                ApiToken.expires_at > now,
            )
            .order_by(ApiToken.created_at.desc())
        )
    )


def revoke(db: Session, token: ApiToken) -> None:
    if token.revoked_at is None:
        token.revoked_at = utcnow()


def revoke_user_tokens(
    db: Session, user_id: uuid.UUID, *, except_id: uuid.UUID | None = None
) -> int:
    now = utcnow()
    count = 0
    for t in db.scalars(
        select(ApiToken).where(ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None))
    ):
        if t.id != except_id:
            t.revoked_at = now
            count += 1
    return count


def purge_tokens(db: Session, settings: Settings) -> int:
    cutoff = utcnow() - timedelta(days=settings.session_retention_days)
    result = db.execute(
        delete(ApiToken).where(or_(ApiToken.revoked_at < cutoff, ApiToken.expires_at < cutoff))
    )
    return int(getattr(result, "rowcount", 0) or 0)
