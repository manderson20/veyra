# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render Veyra's nftables table (docs/FIREWALL_TRUST.md §3.1).

Pure functions: the service gathers rules, bans, feeds and ports and this
module turns them into one ``nft -f`` script that replaces ``inet veyra``
atomically. No other table is ever named."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

TABLE = "veyra"
FAMILY = "inet"


@dataclass(frozen=True)
class PortSpec:
    """The ports of one service: ``udp``/``tcp`` lists of ports or ranges
    such as ``"10000-20000"``."""

    udp: tuple[str, ...] = ()
    tcp: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleSpec:
    action: str  # allow | block
    cidr: str
    services: tuple[str, ...] = ()
    timeout_seconds: int | None = None  # timed manual block


@dataclass(frozen=True)
class BanSpec:
    address: str
    timeout_seconds: int


@dataclass
class Ruleset:
    rules: Sequence[RuleSpec] = ()
    bans: Sequence[BanSpec] = ()
    feed: Iterable[str] = ()
    ports: dict[str, PortSpec] = field(default_factory=dict)
    restricted: Sequence[str] = ()  # services limited to the allow list


def family(cidr: str) -> int:
    return ipaddress.ip_network(cidr, strict=False).version


def _elements(items: list[str]) -> str:
    return f" elements = {{ {', '.join(items)} }};" if items else ""


def _set(name: str, kind: str, flags: str, items: list[str]) -> str:
    return f"  set {name} {{ type {kind}; flags {flags};{_elements(items)} }}"


def _ports_match(spec: PortSpec) -> list[str]:
    out = []
    if spec.udp:
        out.append(f"udp dport {{ {', '.join(spec.udp)} }}")
    if spec.tcp:
        out.append(f"tcp dport {{ {', '.join(spec.tcp)} }}")
    return out


def _collapse(cidrs: Iterable[str]) -> dict[int, list[str]]:
    """Merge overlapping networks: nft refuses overlapping interval elements."""
    nets: dict[int, list[ipaddress.IPv4Network | ipaddress.IPv6Network]] = {4: [], 6: []}
    for c in cidrs:
        n = ipaddress.ip_network(c, strict=False)
        nets[n.version].append(n)
    return {
        v: [str(n) for n in ipaddress.collapse_addresses(ns)]  # type: ignore[type-var]
        for v, ns in nets.items()
    }


def render(rs: Ruleset) -> str:
    allow = _collapse(r.cidr for r in rs.rules if r.action == "allow")
    # Blocks for every service go into the sets; per-service blocks become rules.
    whole_blocks = [r for r in rs.rules if r.action == "block" and not r.services]
    block: dict[int, list[str]] = {4: [], 6: []}
    permanent = _collapse(r.cidr for r in whole_blocks if not r.timeout_seconds)
    for v, nets in permanent.items():
        block[v].extend(nets)
    covered = [ipaddress.ip_network(n) for ns in permanent.values() for n in ns]
    for r in whole_blocks:
        if not r.timeout_seconds:
            continue
        net = ipaddress.ip_network(r.cidr, strict=False)
        if any(net.version == c.version and net.subnet_of(c) for c in covered):  # type: ignore[arg-type]
            continue
        block[net.version].append(f"{net} timeout {r.timeout_seconds}s")
        covered.append(net)
    ban: dict[int, list[str]] = {4: [], 6: []}
    for b in rs.bans:
        ban[family(b.address)].append(f"{b.address} timeout {max(b.timeout_seconds, 1)}s")
    feed = _collapse(rs.feed)

    lines = [
        f"table {FAMILY} {TABLE}",
        f"delete table {FAMILY} {TABLE}",
        f"table {FAMILY} {TABLE} {{",
        _set("allow4", "ipv4_addr", "interval", allow[4]),
        _set("allow6", "ipv6_addr", "interval", allow[6]),
        _set("block4", "ipv4_addr", "interval, timeout", block[4]),
        _set("block6", "ipv6_addr", "interval, timeout", block[6]),
        _set("ban4", "ipv4_addr", "timeout", ban[4]),
        _set("ban6", "ipv6_addr", "timeout", ban[6]),
        _set("feed4", "ipv4_addr", "interval", feed[4]),
        _set("feed6", "ipv6_addr", "interval", feed[6]),
        "",
        "  chain input {",
        "    type filter hook input priority filter - 5; policy accept;",
        "    iif lo return",
        "    ip saddr @allow4 return",
        "    ip6 saddr @allow6 return",
        "    ip saddr @block4 drop",
        "    ip6 saddr @block6 drop",
        "    ip saddr @ban4 drop",
        "    ip6 saddr @ban6 drop",
        "    ip saddr @feed4 drop",
        "    ip6 saddr @feed6 drop",
    ]
    for r in rs.rules:
        if r.action != "block" or not r.services:
            continue
        proto = "ip" if family(r.cidr) == 4 else "ip6"
        net = ipaddress.ip_network(r.cidr, strict=False)
        for service in r.services:
            spec = rs.ports.get(service)
            for match in _ports_match(spec) if spec else []:
                lines.append(f"    {proto} saddr {net} {match} drop")
    for service in rs.restricted:
        spec = rs.ports.get(service)
        for match in _ports_match(spec) if spec else []:
            # Allowed addresses already returned above.
            lines.append(f"    {match} drop")
    lines += ["  }", "}", ""]
    return "\n".join(lines)


def structure(rs: Ruleset) -> str:
    """The script without bans, so a new ban does not count as a change of
    structure (bans are added incrementally)."""
    return render(Ruleset(rs.rules, (), rs.feed, rs.ports, rs.restricted))


def ban_set(address: str) -> str:
    return "ban4" if family(address) == 4 else "ban6"
