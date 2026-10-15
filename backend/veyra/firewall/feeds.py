# SPDX-License-Identifier: AGPL-3.0-or-later
"""Blocklist feeds (docs/FIREWALL_TRUST.md §5): the CrowdSec local API as a
bouncer, or a plain list of addresses over HTTPS. Entries are kept in
``<data>/firewall/feed-<id>.txt`` so a restart does not wait for a fetch."""

from __future__ import annotations

import ipaddress
import json
import urllib.request
from pathlib import Path

MAX_ENTRIES = 100_000
MAX_BYTES = 8 * 1024 * 1024
TIMEOUT = 20
REFRESH_SECONDS = 600


class FeedError(Exception):
    pass


def _get(url: str, headers: dict[str, str]) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Veyra firewall", **headers})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310
            data: bytes = resp.read(MAX_BYTES + 1)
    except OSError as e:
        raise FeedError(str(e)) from e
    if len(data) > MAX_BYTES:
        raise FeedError("the feed is larger than 8 MB")
    return data


def _network(value: str) -> str | None:
    try:
        net = ipaddress.ip_network(value.strip(), strict=False)
    except ValueError:
        return None
    if net.is_loopback or net.is_link_local or net.prefixlen == 0:
        return None
    return str(net)


def parse_list(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        token = line.split("#", 1)[0].split(";", 1)[0].strip().split()
        if not token:
            continue
        net = _network(token[0])
        if net:
            out.append(net)
        if len(out) > MAX_ENTRIES:
            raise FeedError(f"the feed has more than {MAX_ENTRIES} entries")
    return out


def parse_crowdsec(data: bytes) -> list[str]:
    try:
        doc = json.loads(data)
    except ValueError as e:
        raise FeedError("CrowdSec answered with something other than JSON") from e
    out: list[str] = []
    for d in (doc or {}).get("new") or []:
        if str(d.get("type", "ban")).lower() != "ban":
            continue
        if str(d.get("scope", "")).lower() not in ("ip", "range"):
            continue
        net = _network(str(d.get("value", "")))
        if net:
            out.append(net)
    if len(out) > MAX_ENTRIES:
        raise FeedError(f"the feed has more than {MAX_ENTRIES} entries")
    return out


def fetch(kind: str, url: str, key: str | None) -> list[str]:
    if kind == "crowdsec":
        stream = url.rstrip("/") + "/v1/decisions/stream?startup=true"
        return parse_crowdsec(_get(stream, {"X-Api-Key": key or ""}))
    if not url.startswith("https://"):
        raise FeedError("list feeds must use HTTPS")
    return parse_list(_get(url, {}).decode("utf-8", "replace"))


def store(path: Path, entries: list[str]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(entries) + "\n")
    tmp.replace(path)


def load(path: Path) -> list[str]:
    try:
        return [line for line in path.read_text().splitlines() if line]
    except OSError:
        return []
