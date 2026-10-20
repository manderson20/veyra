# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-process event bus.

Core and modules publish domain events (``organization.created``,
``module.enabled`` ...). Handlers are isolated: a failing handler is logged
and never breaks the publisher or other handlers. Events are delivered
synchronously after the publishing transaction has committed (the caller is
responsible for publishing after commit).

Cross-process delivery (worker, deployer, other HA node) will use PostgreSQL
LISTEN/NOTIFY; see docs/ARCHITECTURE.md §Event system.
"""

from __future__ import annotations

import fnmatch
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("veyra.events")


@dataclass(frozen=True)
class Event:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "core"
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


Handler = Callable[[Event], None]


@dataclass
class _Subscription:
    pattern: str
    handler: Handler
    owner: str


class EventBus:
    def __init__(self) -> None:
        self._subs: list[_Subscription] = []

    def subscribe(self, pattern: str, handler: Handler, *, owner: str = "core") -> None:
        """Subscribe to events matching a glob pattern, e.g. ``organization.*``."""
        self._subs.append(_Subscription(pattern, handler, owner))

    def unsubscribe_owner(self, owner: str) -> None:
        self._subs = [s for s in self._subs if s.owner != owner]

    @contextmanager
    def hold(self) -> Iterator[list[Event]]:
        """Collect this context's events instead of delivering them (a bulk
        import's dry run discards them; a real one delivers them after the
        commit with :meth:`deliver`)."""
        held: list[Event] = []
        token = _held.set(held)
        try:
            yield held
        finally:
            _held.reset(token)

    def deliver(self, events: list[Event]) -> None:
        for event in events:
            self.publish(event)

    def publish(self, event: Event) -> int:
        held = _held.get()
        if held is not None:
            held.append(event)
            return 0
        delivered = 0
        for sub in list(self._subs):
            if not fnmatch.fnmatchcase(event.name, sub.pattern):
                continue
            try:
                sub.handler(event)
                delivered += 1
            except Exception:
                log.exception("Event handler from %s failed for %s", sub.owner, event.name)
        return delivered


_held: ContextVar[list[Event] | None] = ContextVar("veyra_events_held", default=None)
bus = EventBus()
