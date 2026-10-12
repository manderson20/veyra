# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small in-process sliding-window rate limiter.

Limits are per API worker process. That is adequate for brute-force
protection on a single node (the per-account lockout in the database is the
authoritative control); a shared limiter is planned with HA (Milestone 16).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, now: float | None = None) -> bool:
        """Record an attempt. Returns False when the key is over its limit."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            if len(self._hits) > 10_000:  # bound memory under address spraying
                self._evict(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _evict(self, now: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]
        for k in stale:
            del self._hits[k]
