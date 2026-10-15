# SPDX-License-Identifier: AGPL-3.0-or-later
"""Detection (docs/FIREWALL_TRUST.md §4): parse the event sources into
:class:`Event` objects and score addresses over a sliding window."""

from __future__ import annotations

import ipaddress
import re
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from veyra.firewall.settings import FirewallSettings


@dataclass(frozen=True)
class Event:
    at: datetime
    address: str
    source: str  # asterisk | auth | provisioning | nginx
    kind: str
    detail: str | None = None
    count: int = 1


def normalise_address(value: str | None) -> str | None:
    """A plain IP address (IPv4-mapped IPv6 unwrapped), or None."""
    if not value:
        return None
    try:
        ip = ipaddress.ip_address(value.strip().strip("[]"))
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return str(ip)


# --------------------------------------------------------------- Asterisk

# res_security_log writes one line per event, e.g.
# [Oct 15 01:20:00] SECURITY[123] res_security_log.c: SecurityEvent="InvalidAccountID",...,
#   RemoteAddress="IPV4/UDP/198.51.100.9/5060",...
_FIELD_RE = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')
ASTERISK_KINDS = {
    "InvalidAccountID": "sip_unknown_account",
    "ChallengeResponseFailed": "sip_bad_password",
    "InvalidPassword": "sip_bad_password",
    "FailedACL": "sip_acl",
    "RequestBadFormat": "sip_bad_request",
}


def _remote(value: str) -> str | None:
    # IPV4/UDP/198.51.100.9/5060 or IPV6/UDP/2001:db8::1/5060
    parts = value.split("/")
    if len(parts) < 4:
        return None
    return normalise_address("/".join(parts[2:-1]))


def parse_asterisk(line: str, now: datetime) -> Event | None:
    if "SecurityEvent=" not in line:
        return None
    fields = dict(_FIELD_RE.findall(line))
    kind = ASTERISK_KINDS.get(fields.get("SecurityEvent", ""))
    if kind is None:
        return None
    address = _remote(fields.get("RemoteAddress", ""))
    if address is None:
        return None
    account = fields.get("AccountID") or ""
    if kind == "sip_bad_password" and account == "<unknown>":
        # PJSIP logs this next to InvalidAccountID for the same attempt.
        return None
    service = fields.get("Service") or ""
    detail = " ".join(p for p in (service, account and f"account {account}") if p) or None
    return Event(now, address, "asterisk", kind, detail[:300] if detail else None)


# ------------------------------------------------------------------ NGINX

_NGINX_RE = re.compile(r'limiting requests.*?zone "(?P<zone>[^"]+)", client: (?P<client>[^,\s]+)')


def parse_nginx(line: str, now: datetime) -> Event | None:
    m = _NGINX_RE.search(line)
    if not m:
        return None
    address = normalise_address(m.group("client"))
    if address is None:
        return None
    return Event(now, address, "nginx", "rate_limited", f"zone {m.group('zone')}")


# ---------------------------------------------------------- Veyra records

AUDIT_KINDS = {
    "auth.login": "login_failed",
    "auth.companion_login": "login_failed",
    "auth.mfa_verify": "mfa_failed",
    "auth.password_reset": "reset_invalid",
}


# ---------------------------------------------------------------- scoring


class Scorer:
    """Weighted events per address over ``window_minutes``."""

    def __init__(self) -> None:
        self._events: dict[str, deque[tuple[datetime, int]]] = defaultdict(deque)

    def add(self, event: Event, settings: FirewallSettings) -> int:
        q = self._events[event.address]
        q.append((event.at, settings.weights.get(event.kind, 1) * event.count))
        return self.score(event.address, event.at, settings)

    def score(self, address: str, now: datetime, settings: FirewallSettings) -> int:
        q = self._events.get(address)
        if not q:
            return 0
        horizon = now - timedelta(minutes=settings.window_minutes)
        while q and q[0][0] < horizon:
            q.popleft()
        if not q:
            del self._events[address]
            return 0
        return sum(w for _, w in q)

    def count(self, address: str) -> int:
        return len(self._events.get(address, ()))

    def reset(self, address: str) -> None:
        self._events.pop(address, None)

    def prune(self, now: datetime, settings: FirewallSettings) -> None:
        for address in list(self._events):
            self.score(address, now, settings)


def aggregate(events: list[Event]) -> list[Event]:
    """Collapse identical events (address, source, kind, detail) into one
    with a count, keeping the first time."""
    out: dict[tuple[str, str, str, str | None], Event] = {}
    for ev in events:
        key = (ev.address, ev.source, ev.kind, ev.detail)
        first = out.get(key)
        out[key] = ev if first is None else replace(first, count=first.count + ev.count)
    return list(out.values())


def ban_minutes(offence: int, settings: FirewallSettings) -> int:
    """1st ban ``ban_minutes``, doubling per repeat, capped at ``max_ban_days``."""
    cap = settings.max_ban_days * 1440
    return min(settings.ban_minutes * 2 ** max(offence - 1, 0), cap)
