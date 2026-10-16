# SPDX-License-Identifier: AGPL-3.0-or-later
"""The standby's API (docs/HIGH_AVAILABILITY.md §9): writes answer
``503 ha_standby`` (or ``503 ha_switchover`` on a frozen primary), and
sign-in keeps its session in the API process because the session table
cannot be written on a replica.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.core.models import Installation
from veyra.core.security import tokens

CACHE_SECONDS = 5.0
SESSION_SECONDS = 3600
# Writes still allowed on a standby or a frozen primary.
WRITE_ALLOWED_PREFIXES = ("/api/v1/ha/", "/api/v1/auth/login", "/api/v1/auth/logout")


@dataclass
class Flags:
    standby: bool = False
    frozen: bool = False
    checked_at: float = 0.0


class Guard:
    """``pg_is_in_recovery()`` and ``installation.ha_frozen``, cached for a
    few seconds so every request does not pay for a query."""

    def __init__(self, session_factory: Any, cache_seconds: float = CACHE_SECONDS) -> None:
        self._factory = session_factory
        self._cache = cache_seconds
        self._flags = Flags()
        self._lock = threading.Lock()

    def flags(self, now: float | None = None) -> Flags:
        now = time.monotonic() if now is None else now
        with self._lock:
            if now - self._flags.checked_at < self._cache:
                return self._flags
            try:
                with self._factory() as db:
                    self._flags = Flags(*query_flags(db), checked_at=now)
            except Exception:
                self._flags = Flags(checked_at=now)
            return self._flags

    def refresh(self) -> None:
        with self._lock:
            self._flags.checked_at = 0.0


def query_flags(db: Session) -> tuple[bool, bool]:
    standby = bool(db.scalar(select(func.pg_is_in_recovery())))
    frozen = bool(db.scalar(select(Installation.ha_frozen)))
    return standby, frozen


def write_blocked(path: str, flags: Flags) -> str | None:
    """The problem code when a write to ``path`` must be refused, else None."""
    if not (flags.standby or flags.frozen):
        return None
    if any(path.startswith(p) for p in WRITE_ALLOWED_PREFIXES):
        return None
    return "ha_standby" if flags.standby else "ha_switchover"


@dataclass
class StandbySession:
    user_id: uuid.UUID
    csrf_hash: str
    expires_at: float


class StandbySessions:
    """In-memory sessions of the standby's interface (platform administrators
    only, one hour, gone with the process)."""

    def __init__(self, ttl: int = SESSION_SECONDS) -> None:
        self._ttl = ttl
        self._items: dict[str, StandbySession] = {}
        self._lock = threading.Lock()

    def create(self, user_id: uuid.UUID, now: float | None = None) -> tuple[str, str]:
        now = time.time() if now is None else now
        token, csrf = tokens.new_token(), tokens.new_token()
        with self._lock:
            self._purge(now)
            self._items[tokens.digest(token)] = StandbySession(
                user_id, tokens.digest(csrf), now + self._ttl
            )
        return token, csrf

    def resolve(self, token: str, now: float | None = None) -> StandbySession | None:
        now = time.time() if now is None else now
        with self._lock:
            s = self._items.get(tokens.digest(token))
            if s is None or s.expires_at <= now:
                return None
            return s

    def revoke(self, token: str) -> None:
        with self._lock:
            self._items.pop(tokens.digest(token), None)

    def csrf_ok(self, s: StandbySession, csrf: str) -> bool:
        return bool(csrf) and tokens.matches(csrf, s.csrf_hash)

    def _purge(self, now: float) -> None:
        for k in [k for k, v in self._items.items() if v.expires_at <= now]:
            del self._items[k]

    def __len__(self) -> int:
        return len(self._items)
