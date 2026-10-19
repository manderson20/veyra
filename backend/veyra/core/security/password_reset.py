# SPDX-License-Identifier: AGPL-3.0-or-later
"""One-time password reset links.

Links are issued by an administrator in the UI
(``POST /users/{id}/password-reset-link``) or by ``veyra users
reset-password`` on the server and handed to the user out of band, or, when
email delivery is set up, requested by the user from the sign-in page
(``POST /auth/password-reset/request``) and emailed. The link carries a
random token whose digest is stored; it is valid for
``settings.password_reset_ttl_hours`` and can be used once. Issuing a
new link invalidates the previous one.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from veyra.core.config import Settings
from veyra.core.models import PasswordResetToken, User
from veyra.core.models.base import utcnow
from veyra.core.security import tokens

# The path in the UI that consumes the token (the token travels in the query
# string, so the UI must never send it to any other origin).
RESET_PATH = "/reset-password/"


def reset_link_path(token: str) -> str:
    return f"{RESET_PATH}?token={token}"


def issue_reset_token(
    db: Session,
    user: User,
    settings: Settings,
    *,
    issued_by: str,
    issued_from_ip: str | None = None,
) -> tuple[str, PasswordResetToken]:
    """Create a reset token for ``user``, replacing any unused one."""
    db.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
        )
    )
    token = tokens.new_token(32)
    now = utcnow()
    row = PasswordResetToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=tokens.digest(token),
        created_at=now,
        expires_at=now + timedelta(hours=settings.password_reset_ttl_hours),
        issued_by=issued_by,
        issued_from_ip=issued_from_ip,
    )
    db.add(row)
    db.flush()
    return token, row


def resolve_reset_token(
    db: Session, token: str, *, now: datetime | None = None
) -> tuple[PasswordResetToken, User] | None:
    """The token row and its user when the token is unused, unexpired and the
    user can sign in locally; otherwise ``None``. Never says which."""
    if not token or len(token) > 200:
        return None
    now = now or utcnow()
    row = db.execute(
        select(PasswordResetToken, User)
        .join(User, User.id == PasswordResetToken.user_id)
        .where(PasswordResetToken.token_hash == tokens.digest(token))
    ).first()
    if row is None:
        return None
    reset, user = row
    if reset.used_at is not None or reset.expires_at <= now or not user.is_active:
        return None
    return reset, user


def purge_reset_tokens(db: Session, settings: Settings) -> int:
    """Delete used and long-expired tokens. Returns the number of rows deleted."""
    cutoff = utcnow() - timedelta(days=settings.session_retention_days)
    result = db.execute(
        delete(PasswordResetToken).where(
            or_(PasswordResetToken.used_at.is_not(None), PasswordResetToken.expires_at < cutoff)
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)
