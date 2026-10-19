# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call events for connected clients (docs/COMPANION.md §4).

The engine listener publishes :class:`CallEvent` objects; each connected
client (a Companion WebSocket) holds a queue filtered to the endpoints of its
own extensions. Everything runs on the API process's event loop, so no
locking is needed. Tickets are one-time, short-lived handles that let a
browser open the WebSocket without being able to set headers.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from veyra.core.models.base import utcnow

EventType = Literal["call.ringing", "call.dialing", "call.answered", "call.ended"]
ListenerState = Literal["disabled", "connecting", "connected", "reconnecting"]
TICKET_TTL = timedelta(seconds=60)
QUEUE_SIZE = 200


@dataclass(frozen=True)
class CallEvent:
    type: EventType
    channel_id: str
    endpoint: str  # engine endpoint name (``<org>-<number>`` for phones)
    direction: Literal["in", "out"]
    remote_number: str | None
    remote_name: str | None
    at: str  # ISO 8601
    answered: bool = False
    cause: str | None = None

    def payload(self, extension_id: uuid.UUID, extension_number: str) -> dict[str, Any]:
        d = asdict(self)
        d.pop("endpoint")
        d["extension_id"] = str(extension_id)
        d["extension_number"] = extension_number
        return d


@dataclass(eq=False)
class Subscriber:
    user_id: uuid.UUID
    endpoints: dict[str, tuple[uuid.UUID, str]]  # endpoint -> (extension id, number)
    # Call events of the user's phones, or an alert for the user itself (a dict
    # sent as is, such as an emergency call, docs/PRODUCTION_HARDENING.md §6).
    queue: asyncio.Queue[CallEvent | dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(QUEUE_SIZE)
    )


@dataclass
class Ticket:
    user_id: uuid.UUID
    token_id: uuid.UUID | None
    session_id: uuid.UUID | None
    expires_at: datetime


class CallEventHub:
    def __init__(self) -> None:
        self.subscribers: set[Subscriber] = set()
        self.tickets: dict[str, Ticket] = {}
        self.state: ListenerState = "disabled"
        self.last_error: str | None = None
        self.events_seen = 0
        # The event loop the streams run on, for alerts sent from other threads.
        self.loop: asyncio.AbstractEventLoop | None = None

    # --- tickets ------------------------------------------------------------

    def issue_ticket(
        self, user_id: uuid.UUID, *, token_id: uuid.UUID | None, session_id: uuid.UUID | None
    ) -> tuple[str, int]:
        self._sweep_tickets()
        ticket = secrets.token_urlsafe(32)
        self.tickets[ticket] = Ticket(user_id, token_id, session_id, utcnow() + TICKET_TTL)
        return ticket, int(TICKET_TTL.total_seconds())

    def redeem_ticket(self, ticket: str) -> Ticket | None:
        self._sweep_tickets()
        return self.tickets.pop(ticket, None)

    def _sweep_tickets(self) -> None:
        now = utcnow()
        for k in [k for k, t in self.tickets.items() if t.expires_at <= now]:
            self.tickets.pop(k, None)

    # --- subscribers ----------------------------------------------------------

    def subscribe(
        self, user_id: uuid.UUID, endpoints: dict[str, tuple[uuid.UUID, str]]
    ) -> Subscriber:
        sub = Subscriber(user_id=user_id, endpoints=dict(endpoints))
        self.subscribers.add(sub)
        with contextlib.suppress(RuntimeError):
            self.loop = asyncio.get_running_loop()
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self.subscribers.discard(sub)

    def publish(self, event: CallEvent) -> int:
        """Deliver to every subscriber that owns the endpoint. A subscriber whose
        queue is full loses the oldest event rather than blocking the listener."""
        self.events_seen += 1
        delivered = 0
        for sub in list(self.subscribers):
            if event.endpoint not in sub.endpoints:
                continue
            if sub.queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    sub.queue.get_nowait()
            sub.queue.put_nowait(event)
            delivered += 1
        return delivered

    def alert(self, user_ids: set[uuid.UUID], payload: dict[str, Any]) -> int:
        """Send ``payload`` to every stream of these users (issue #127)."""
        delivered = 0
        for sub in list(self.subscribers):
            if sub.user_id not in user_ids:
                continue
            if sub.queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    sub.queue.get_nowait()
            sub.queue.put_nowait(payload)
            delivered += 1
        return delivered

    def alert_from_thread(self, user_ids: set[uuid.UUID], payload: dict[str, Any]) -> None:
        """:meth:`alert` from a request or worker thread."""
        if self.loop is not None and user_ids:
            self.loop.call_soon_threadsafe(self.alert, user_ids, payload)

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "clients": len(self.subscribers),
            "events_seen": self.events_seen,
            "last_error": self.last_error,
        }
