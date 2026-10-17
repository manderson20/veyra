# SPDX-License-Identifier: AGPL-3.0-or-later
"""The capture filter (docs/CALL_FEATURES.md §2.2): structured fields the API
validated, turned into one tcpdump expression. The root runner rebuilds the
expression from the stored fields with the same code, so a capture never
runs anything the validation here did not produce.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

MAX_HOSTS = 16
MAX_PORTS = 16
MAX_RANGES = 4
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


class FilterError(ValueError):
    pass


def _host(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise FilterError("an address is empty")
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        pass
    if _HOSTNAME_RE.match(text) and not text.replace(".", "").isdigit():
        return text.lower()
    raise FilterError(f"{text!r} is not an IP address or host name")


def _net(value: Any) -> str:
    text = str(value or "").strip()
    try:
        return str(ipaddress.ip_network(text, strict=False))
    except ValueError as e:
        raise FilterError(f"{text!r} is not a network in CIDR notation") from e


def _port(value: Any) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as e:
        raise FilterError(f"{value!r} is not a port") from e
    if not 0 < port < 65536:
        raise FilterError(f"port {port} is out of range")
    return port


def normalize(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate and canonicalise a filter: ``hosts``, ``nets``, ``ports``,
    ``portranges`` ([low, high] pairs) and ``rtp``. Raises FilterError."""
    if not isinstance(spec, dict):
        raise FilterError("the filter is not an object")
    unknown = set(spec) - {"hosts", "nets", "ports", "portranges", "rtp"}
    if unknown:
        raise FilterError(f"unknown filter fields: {', '.join(sorted(unknown))}")
    hosts = [_host(h) for h in (spec.get("hosts") or [])]
    nets = [_net(n) for n in (spec.get("nets") or [])]
    ports = sorted({_port(p) for p in (spec.get("ports") or [])})
    ranges: list[list[int]] = []
    for r in spec.get("portranges") or []:
        if not isinstance(r, list | tuple) or len(r) != 2:
            raise FilterError("a port range is a [low, high] pair")
        low, high = _port(r[0]), _port(r[1])
        if low > high:
            raise FilterError(f"port range {low}-{high} is reversed")
        ranges.append([low, high])
    if len(hosts) > MAX_HOSTS or len(nets) > MAX_HOSTS:
        raise FilterError(f"at most {MAX_HOSTS} addresses")
    if len(ports) > MAX_PORTS or len(ranges) > MAX_RANGES:
        raise FilterError("too many ports")
    if not ports and not ranges:
        raise FilterError("a capture needs at least one port or port range")
    return {
        "hosts": sorted(set(hosts)),
        "nets": sorted(set(nets)),
        "ports": ports,
        "portranges": ranges,
        "rtp": bool(spec.get("rtp")),
    }


def expression(spec: dict[str, Any]) -> str:
    """The tcpdump (BPF) expression for a normalised filter."""
    spec = normalize(spec)
    where = [f"host {h}" for h in spec["hosts"]] + [f"net {n}" for n in spec["nets"]]
    what = [f"port {p}" for p in spec["ports"]] + [
        f"portrange {lo}-{hi}" for lo, hi in spec["portranges"]
    ]
    clause = "(" + " or ".join(what) + ")"
    if where:
        clause = "(" + " or ".join(where) + ") and " + clause
    return clause


def describe(spec: dict[str, Any]) -> str:
    """A short human label for the list when the API stored none."""
    spec = normalize(spec)
    where = spec["hosts"] + spec["nets"]
    what = ", ".join(str(p) for p in spec["ports"]) + (" + RTP" if spec["portranges"] else "")
    return (", ".join(where) if where else "all SIP") + f" (ports {what})"
