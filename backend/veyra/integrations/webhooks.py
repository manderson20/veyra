# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outgoing webhooks (docs/INTEGRATIONS.md §3).

Publishing writes one delivery row per matching webhook (an outbox) and never
touches the network; the worker sends due deliveries every tick. Requests are
signed with HMAC-SHA256 and go only to addresses outside the server itself.
"""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from veyra.core.models import Organization, Webhook, WebhookDelivery
from veyra.core.models.base import utcnow
from veyra.version import __version__

log = logging.getLogger("veyra.webhooks")

SECRET_PURPOSE = "webhooks:secret"  # noqa: S105 (an encryption purpose)
SECRET_PREFIX = "whsec_"  # noqa: S105 (a public prefix)
TIMEOUT = 10.0
RETRY_DELAYS = (60, 300, 1800, 7200, 21600)
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
DISABLE_AFTER = timedelta(days=3)
ROTATION_OVERLAP = timedelta(hours=24)
KEEP_DELIVERIES = timedelta(days=7)
KEEP_PER_WEBHOOK = 100
EXCERPT_BYTES = 4096
BATCH = 50

# Tests replace these: the transport and the name resolver.
transport: httpx.BaseTransport | None = None
Resolver = Callable[[str, int], list[str]]


def _resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(i[4][0]) for i in infos))


resolver: Resolver = _resolve


@dataclass(frozen=True)
class EventDef:
    name: str
    group: str
    description: str
    # Live events lose their meaning after seconds: one attempt, no retries.
    live: bool = False


EVENTS: tuple[EventDef, ...] = (
    EventDef("call.ringing", "Calls", "An extension starts ringing", live=True),
    EventDef("call.answered", "Calls", "An extension answers a call", live=True),
    EventDef("call.ended", "Calls", "A finished call is in the call history"),
    EventDef("voicemail.message", "Voicemail", "A new voicemail message is left"),
    EventDef("page.sent", "Paging", "A page starts"),
    EventDef("bell.rang", "Paging", "A bell schedule rings"),
    EventDef("alert.raised", "Monitoring", "A monitoring alert is raised"),
    EventDef("alert.resolved", "Monitoring", "A monitoring alert is resolved"),
    EventDef("registration.changed", "Phones", "A phone registers or unregisters"),
    EventDef("deployment.finished", "System", "A configuration deployment ends"),
)
EVENT_NAMES = {e.name for e in EVENTS}
LIVE_EVENTS = {e.name for e in EVENTS if e.live}
TEST_EVENT = "webhook.test"


def known_events(module_events: Iterable[str] = ()) -> set[str]:
    return EVENT_NAMES | set(module_events)


def check_patterns(patterns: list[str], allowed: set[str]) -> list[str]:
    out: list[str] = []
    groups = {n.split(".", 1)[0] for n in allowed}
    for p in patterns:
        p = p.strip()
        if not p:
            continue
        if p.endswith(".*"):
            if p[:-2] not in groups:
                raise ValueError(f"Unknown event group {p!r}")
        elif p not in allowed:
            raise ValueError(f"Unknown event {p!r}")
        if p not in out:
            out.append(p)
    if not out:
        raise ValueError("Choose at least one event")
    return out


def matches(patterns: list[str], event: str) -> bool:
    return event == TEST_EVENT or any(fnmatch.fnmatchcase(event, p) for p in patterns)


def new_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(32)


# --------------------------------------------------------------------------- URLs


class UnsafeDestination(Exception):
    pass


def check_url(url: str, *, allow_http: bool) -> str:
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http"):
        raise ValueError("The address must start with https://")
    if parts.scheme == "http" and not allow_http:
        raise ValueError("Use https://, or allow unencrypted HTTP for a device on your network")
    if not parts.hostname:
        raise ValueError("The address has no host")
    if parts.username or parts.password:
        raise ValueError("Put credentials in the receiver's settings, not in the address")
    if parts.fragment:
        raise ValueError("The address may not contain a #fragment")
    try:
        _ = parts.port
    except ValueError as e:
        raise ValueError("The port is not valid") from e
    if len(url) > 2000:
        raise ValueError("The address is too long")
    # Literal addresses are checked now; names again at every attempt.
    try:
        _check_address(ipaddress.ip_address(parts.hostname))
    except ValueError:
        pass
    except UnsafeDestination as e:
        raise ValueError(str(e)) from e
    return url


def _local_addresses() -> set[str]:
    out: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            out.add(str(info[4][0]))
    except OSError:
        pass
    return out


def _check_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
        or str(addr) in _local_addresses()
    ):
        raise UnsafeDestination(f"{addr} is on this server or not reachable for webhooks")


def pinned_target(url: str) -> tuple[str, str, str]:
    """(URL with the host replaced by a checked address, Host header, SNI name).
    Resolving once and connecting to that address defeats DNS rebinding."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        literal = ipaddress.ip_address(host)
        candidates = [str(literal)]
    except ValueError:
        try:
            candidates = resolver(host, port)
        except OSError as e:
            raise UnsafeDestination(f"Cannot resolve {host}: {e}") from e
    if not candidates:
        raise UnsafeDestination(f"Cannot resolve {host}")
    for c in candidates:
        _check_address(ipaddress.ip_address(c))
    chosen = ipaddress.ip_address(candidates[0])
    netloc_host = f"[{chosen}]" if chosen.version == 6 else str(chosen)
    netloc = f"{netloc_host}:{parts.port}" if parts.port else netloc_host
    host_header = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, "")), host_header, host


# --------------------------------------------------------------------------- signing


def signature(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return mac.hexdigest()


def signature_header(secrets_: list[str], timestamp: int, body: bytes) -> str:
    return ",".join([f"t={timestamp}"] + [f"v1={signature(s, timestamp, body)}" for s in secrets_])


def verify(
    secret: str, header: str, body: bytes, *, tolerance: int = 300, now: float | None = None
) -> bool:
    """Receiver-side check (used by tests and the documentation's example)."""
    fields = [f.split("=", 1) for f in header.split(",") if "=" in f]
    ts = next((v for k, v in fields if k == "t"), None)
    if ts is None or not ts.isdigit():
        return False
    if abs((now or time.time()) - int(ts)) > tolerance:
        return False
    expected = signature(secret, int(ts), body)
    return any(k == "v1" and hmac.compare_digest(v, expected) for k, v in fields)


# --------------------------------------------------------------------------- outbox


def envelope(
    delivery_id: uuid.UUID,
    event: str,
    org: Organization | None,
    data: dict[str, Any],
    occurred_at: datetime,
) -> dict[str, Any]:
    return {
        "id": str(delivery_id),
        "event": event,
        "occurred_at": occurred_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "organization": {"id": str(org.id), "slug": org.slug} if org else None,
        "data": data,
    }


def emit(
    db: Session,
    organization_id: uuid.UUID | None,
    event: str,
    data: dict[str, Any],
    *,
    occurred_at: datetime | None = None,
    only: uuid.UUID | None = None,
) -> int:
    """Queue ``event`` for every enabled webhook of the organization that
    subscribes to it (or only for webhook ``only``). The caller commits."""
    if organization_id is None:
        return 0
    stmt = select(Webhook).where(
        Webhook.organization_id == organization_id, Webhook.enabled.is_(True)
    )
    if only is not None:
        stmt = select(Webhook).where(Webhook.id == only)
    hooks = [h for h in db.scalars(stmt) if only is not None or matches(h.events or [], event)]
    if not hooks:
        return 0
    org = db.get(Organization, organization_id)
    now = utcnow()
    occurred_at = occurred_at or now
    for h in hooks:
        did = uuid.uuid4()
        db.add(
            WebhookDelivery(
                id=did,
                webhook_id=h.id,
                event=event,
                payload=envelope(did, event, org, data, occurred_at),
                status="pending",
                attempts=0,
                max_attempts=1 if event in LIVE_EVENTS else MAX_ATTEMPTS,
                next_attempt_at=now,
                created_at=now,
            )
        )
    db.flush()
    return len(hooks)


def subscribed(db: Session, event: str) -> bool:
    """Cheap pre-check for sources that would otherwise do work for nothing."""
    for patterns in db.scalars(select(Webhook.events).where(Webhook.enabled.is_(True))):
        if matches(patterns or [], event):
            return True
    return False


# --------------------------------------------------------------------------- delivery

Decrypt = Callable[[str], str]


def _secrets_for(hook: Webhook, decrypt: Decrypt, now: datetime) -> list[str]:
    out = [decrypt(hook.secret_enc)]
    if hook.previous_secret_enc and hook.previous_secret_until and hook.previous_secret_until > now:
        out.append(decrypt(hook.previous_secret_enc))
    return out


def send(hook: Webhook, delivery: WebhookDelivery, decrypt: Decrypt) -> None:
    """One attempt; updates the delivery row (not the schedule)."""
    now = utcnow()
    body = json.dumps(delivery.payload, separators=(",", ":"), sort_keys=True).encode()
    ts = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"Veyra-Webhooks/{__version__}",
        "Veyra-Event": delivery.event,
        "Veyra-Delivery": str(delivery.id),
        "Veyra-Signature": signature_header(_secrets_for(hook, decrypt, now), ts, body),
    }
    delivery.attempts += 1
    started = time.monotonic()
    try:
        check_url(hook.url, allow_http=hook.allow_http)
        target, host_header, sni = pinned_target(hook.url)
        headers["Host"] = host_header
        extensions = {"sni_hostname": sni} if target.startswith("https://") else {}
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False, transport=transport) as c:
            req = c.build_request(
                "POST", target, content=body, headers=headers, extensions=extensions
            )
            r = c.send(req, stream=True)
            try:
                excerpt = b""
                for chunk in r.iter_bytes():
                    excerpt += chunk
                    if len(excerpt) >= EXCERPT_BYTES:
                        break
            finally:
                r.close()
            delivery.response_code = r.status_code
            delivery.response_excerpt = excerpt[:EXCERPT_BYTES].decode("utf-8", "replace")
            ok = 200 <= r.status_code < 300
            delivery.error = None if ok else f"HTTP {r.status_code}"
    except (UnsafeDestination, ValueError) as e:
        ok = False
        delivery.response_code = None
        delivery.error = str(e)[:500]
    except httpx.HTTPError as e:
        ok = False
        delivery.response_code = None
        delivery.error = (type(e).__name__ + (f": {e}" if str(e) else ""))[:500]
    delivery.duration_ms = int((time.monotonic() - started) * 1000)
    if ok:
        delivery.status = "delivered"
        delivery.delivered_at = utcnow()


def _schedule(hook: Webhook, delivery: WebhookDelivery, now: datetime) -> None:
    hook.last_delivery_at = now
    if delivery.status == "delivered":
        hook.last_status = "delivered"
        hook.failing_since = None
        return
    hook.last_status = "failed"
    hook.failing_since = hook.failing_since or now
    if delivery.attempts >= delivery.max_attempts:
        delivery.status = "failed"
    else:
        delay = RETRY_DELAYS[min(delivery.attempts - 1, len(RETRY_DELAYS) - 1)]
        delivery.next_attempt_at = now + timedelta(seconds=delay)
    if hook.enabled and now - hook.failing_since >= DISABLE_AFTER:
        hook.enabled = False
        hook.disabled_reason = "Turned off after 3 days of failed deliveries"
        log.warning("Webhook %s turned off after 3 days of failures", hook.name)


def deliver_due(
    db: Session, decrypt: Decrypt, *, now: datetime | None = None, limit: int = BATCH
) -> int:
    """Send what is due, oldest first; returns the number of attempts."""
    now = now or utcnow()
    rows = db.execute(
        select(WebhookDelivery, Webhook)
        .join(Webhook, Webhook.id == WebhookDelivery.webhook_id)
        .where(WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= now)
        .order_by(WebhookDelivery.created_at)
        .limit(limit)
        .with_for_update(of=WebhookDelivery, skip_locked=True)
    ).all()
    count = 0
    for delivery, hook in rows:
        if not hook.enabled and delivery.event != TEST_EVENT:
            delivery.status = "failed"
            delivery.error = "The webhook is turned off"
            continue
        try:
            send(hook, delivery, decrypt)
        except Exception as e:  # never let one receiver stop the others
            log.exception("Webhook %s: delivery failed", hook.name)
            delivery.error = f"Internal error: {type(e).__name__}"[:500]
        _schedule(hook, delivery, utcnow())
        count += 1
    db.commit()
    return count


def redeliver(db: Session, delivery: WebhookDelivery) -> WebhookDelivery:
    now = utcnow()
    copy_id = uuid.uuid4()
    payload = dict(delivery.payload)
    payload["id"] = str(copy_id)
    row = WebhookDelivery(
        id=copy_id,
        webhook_id=delivery.webhook_id,
        event=delivery.event,
        payload=payload,
        status="pending",
        attempts=0,
        max_attempts=MAX_ATTEMPTS,
        next_attempt_at=now,
        created_at=now,
    )
    db.add(row)
    db.flush()
    return row


def prune(db: Session, now: datetime | None = None) -> int:
    """Keep 7 days, and at most the last 100 per webhook."""
    now = now or utcnow()
    res = db.execute(
        delete(WebhookDelivery).where(
            WebhookDelivery.created_at < now - KEEP_DELIVERIES,
            WebhookDelivery.status != "pending",
        )
    )
    removed = int(getattr(res, "rowcount", 0) or 0)
    for hook_id in db.scalars(select(Webhook.id)):
        keep = (
            select(WebhookDelivery.id)
            .where(WebhookDelivery.webhook_id == hook_id)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(KEEP_PER_WEBHOOK)
        )
        res = db.execute(
            delete(WebhookDelivery).where(
                WebhookDelivery.webhook_id == hook_id,
                WebhookDelivery.status != "pending",
                WebhookDelivery.id.not_in(keep.scalar_subquery()),
            )
        )
        removed += int(getattr(res, "rowcount", 0) or 0)
    return removed


def emit_all(db: Session, event: str, data: dict[str, Any]) -> int:
    """Installation-wide events (alerts, deployments): every organization whose
    webhooks subscribe gets its own delivery."""
    orgs = {
        h.organization_id
        for h in db.scalars(select(Webhook).where(Webhook.enabled.is_(True)))
        if matches(h.events or [], event)
    }
    return sum(emit(db, org_id, event, data) for org_id in orgs)
