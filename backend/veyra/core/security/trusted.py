# SPDX-License-Identifier: AGPL-3.0-or-later
"""Trusted browsers (issue #137; docs/MFA_DESIGN.md §4): after a second-factor
sign-in the user may let this browser skip the code for the days the policy
allows. The cookie holds a random token; only its digest is stored."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from veyra.core.config import Settings
from veyra.core.models import TrustedBrowser, User
from veyra.core.models.base import utcnow
from veyra.core.security import tokens

COOKIE = "__Host-veyra_trusted"
MAX_PER_USER = 20


def issue(
    db: Session,
    user: User,
    days: int,
    *,
    label: str | None,
    ip: str | None,
) -> tuple[str, TrustedBrowser]:
    token = tokens.new_token(32)
    now = utcnow()
    row = TrustedBrowser(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=tokens.digest(token),
        label=(label or "")[:200] or None,
        created_at=now,
        expires_at=now + timedelta(days=days),
        last_used_at=now,
        last_ip=ip,
    )
    db.add(row)
    db.flush()
    # Keep the newest few; an old browser falls back to the code.
    old = db.scalars(
        select(TrustedBrowser)
        .where(TrustedBrowser.user_id == user.id)
        .order_by(TrustedBrowser.created_at.desc())
        .offset(MAX_PER_USER)
    ).all()
    for r in old:
        db.delete(r)
    return token, row


def set_cookie(response: Response, settings: Settings, token: str, days: int) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


def check(db: Session, user: User, token: str | None, ip: str | None) -> bool:
    """Whether ``token`` is a live trusted browser of ``user`` (and note its use)."""
    if not token or len(token) > 200:
        return False
    row = db.scalar(select(TrustedBrowser).where(TrustedBrowser.token_hash == tokens.digest(token)))
    now = utcnow()
    if row is None or row.user_id != user.id or row.expires_at <= now:
        return False
    row.last_used_at, row.last_ip = now, ip
    return True


def forget_all(db: Session, user_id: uuid.UUID) -> int:
    result = db.execute(delete(TrustedBrowser).where(TrustedBrowser.user_id == user_id))
    return int(getattr(result, "rowcount", 0) or 0)


def purge_expired(db: Session) -> int:
    result = db.execute(delete(TrustedBrowser).where(TrustedBrowser.expires_at <= utcnow()))
    return int(getattr(result, "rowcount", 0) or 0)
