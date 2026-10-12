"""Server-side sessions and principal loading."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from veyra.core.config import Settings
from veyra.core.models import Role, RoleAssignment, RolePermission, User, UserSession
from veyra.core.models.base import utcnow
from veyra.core.security import tokens
from veyra.core.security.principal import Grant, Principal

# Refresh last_seen_at at most this often to avoid a write on every request.
_TOUCH_INTERVAL = timedelta(seconds=60)


def create_session(
    db: Session, user: User, settings: Settings, *, ip: str | None, user_agent: str | None
) -> tuple[str, str, UserSession]:
    token = tokens.new_token()
    csrf = tokens.new_token()
    now = utcnow()
    session = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=tokens.digest(token),
        csrf_token_hash=tokens.digest(csrf),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
        ip_address=ip,
        user_agent=(user_agent or "")[:500] or None,
    )
    db.add(session)
    return token, csrf, session


def rotate_csrf(session: UserSession) -> str:
    csrf = tokens.new_token()
    session.csrf_token_hash = tokens.digest(csrf)
    return csrf


def resolve_session(
    db: Session, token: str, settings: Settings, *, now: datetime | None = None
) -> tuple[UserSession, User] | None:
    now = now or utcnow()
    row = db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.token_hash == tokens.digest(token))
    ).first()
    if row is None:
        return None
    session, user = row
    if session.revoked_at is not None or session.expires_at <= now:
        return None
    if session.last_seen_at + timedelta(minutes=settings.session_idle_minutes) <= now:
        session.revoked_at = now
        db.commit()
        return None
    if not user.is_active:
        return None
    if now - session.last_seen_at >= _TOUCH_INTERVAL:
        session.last_seen_at = now
        db.commit()
    return session, user


def active_sessions(db: Session, user_id: uuid.UUID, settings: Settings) -> list[UserSession]:
    """A user's sessions that can still be used, newest first.

    A session that has passed its idle timeout is reported as active until a
    request lazily revokes it, so the idle rule is applied here as well.
    """
    now = utcnow()
    idle_cutoff = now - timedelta(minutes=settings.session_idle_minutes)
    rows = db.scalars(
        select(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
            UserSession.last_seen_at > idle_cutoff,
        )
        .order_by(UserSession.last_seen_at.desc())
    )
    return list(rows)


def revoke_user_sessions(
    db: Session, user_id: uuid.UUID, *, except_id: uuid.UUID | None = None
) -> int:
    """Revoke every live session of a user (optionally keeping one). Returns the count."""
    now = utcnow()
    count = 0
    for s in db.scalars(
        select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    ):
        if s.id != except_id:
            s.revoked_at = now
            count += 1
    return count


def purge_sessions(db: Session, settings: Settings) -> int:
    """Delete sessions that expired or were revoked longer ago than the retention
    period. Returns the number of rows deleted."""
    cutoff = utcnow() - timedelta(days=settings.session_retention_days)
    result = db.execute(
        delete(UserSession).where(
            or_(UserSession.revoked_at < cutoff, UserSession.expires_at < cutoff)
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


def load_principal(db: Session, user: User, session_id: uuid.UUID | None = None) -> Principal:
    rows = db.execute(
        select(RoleAssignment, Role.id)
        .join(Role, Role.id == RoleAssignment.role_id)
        .where(RoleAssignment.user_id == user.id)
    ).all()
    role_ids = {role_id for _, role_id in rows}
    perms_by_role: dict[uuid.UUID, set[str]] = {rid: set() for rid in role_ids}
    if role_ids:
        for rp in db.scalars(select(RolePermission).where(RolePermission.role_id.in_(role_ids))):
            perms_by_role[rp.role_id].add(rp.permission_key)
    grants = [
        Grant(
            scope_type=a.scope_type,
            organization_id=a.organization_id,
            site_id=a.site_id,
            permissions=frozenset(perms_by_role.get(role_id, set())),
        )
        for a, role_id in rows
    ]
    return Principal(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        grants=grants,
        session_id=session_id,
    )
