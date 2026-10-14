# SPDX-License-Identifier: AGPL-3.0-or-later
"""The page sender (``veyra pager``, docs/PAGING_RECORDINGS.md §2.2).

Asterisk pages a zone by dialling ``MulticastRTP/basic/127.0.0.1:<port>``:
plain RTP arrives on the zone's loopback port. For every packet the sender
emits the Poly group-page datagram to the organization's Poly address at
once and the plain packet to the speakers' multicast group after the Poly
phones' buffering delay, so both play together. The zone table comes from
``paging.json`` written by the deployer next to the engine files; the file
is re-read when it changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from veyra.paging import poly

log = logging.getLogger("veyra.pager")

PAGING_FILE = "paging.json"
DEFAULT_DELAY_MS = 200
DEFAULT_TTL = 1
RELOAD_SECONDS = 2.0


@dataclass(frozen=True)
class Zone:
    slug: str
    organization: str
    port: int
    multicast_address: str
    multicast_port: int
    poly_address: str
    poly_port: int
    poly_group: int
    kind: str = "normal"
    delay_ms: int = DEFAULT_DELAY_MS
    ttl: int = DEFAULT_TTL


@dataclass
class Stats:
    packets_in: int = 0
    packets_speakers: int = 0
    packets_poly: int = 0
    errors: int = 0
    by_zone: dict[str, int] = field(default_factory=dict)


def parse_zones(document: dict[str, Any]) -> list[Zone]:
    zones: list[Zone] = []
    defaults = document.get("defaults") or {}
    for z in document.get("zones") or []:
        zones.append(
            Zone(
                slug=str(z["slug"]),
                organization=str(z.get("organization") or ""),
                port=int(z["port"]),
                multicast_address=str(z["multicast_address"]),
                multicast_port=int(z["multicast_port"]),
                poly_address=str(z["poly_address"]),
                poly_port=int(z["poly_port"]),
                poly_group=int(z["poly_group"]),
                kind=str(z.get("kind") or "normal"),
                delay_ms=int(z.get("delay_ms", defaults.get("delay_ms", DEFAULT_DELAY_MS))),
                ttl=int(z.get("ttl", defaults.get("ttl", DEFAULT_TTL))),
            )
        )
    ports = [z.port for z in zones]
    if len(ports) != len(set(ports)):
        raise ValueError("paging.json assigns one port to two zones")
    return zones


def load_zones(path: Path) -> list[Zone]:
    return parse_zones(json.loads(path.read_text(encoding="utf-8")))


def multicast_socket(ttl: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack("b", ttl))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    return sock


class ZoneProtocol(asyncio.DatagramProtocol):
    """One listener per zone: fan a packet out to both formats."""

    def __init__(
        self, zone: Zone, sender: socket.socket, stats: Stats, loop: asyncio.AbstractEventLoop
    ) -> None:
        self.zone = zone
        self.sender = sender
        self.stats = stats
        self.loop = loop

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        z = self.zone
        self.stats.packets_in += 1
        self.stats.by_zone[z.slug] = self.stats.by_zone.get(z.slug, 0) + 1
        try:
            self.sender.sendto(
                poly.encode(data, z.poly_group, priority=z.kind), (z.poly_address, z.poly_port)
            )
            self.stats.packets_poly += 1
        except (OSError, ValueError) as e:
            self.stats.errors += 1
            log.warning("zone %s: Poly send failed: %s", z.slug, e)
        self.loop.call_later(z.delay_ms / 1000.0, self._send_speakers, data)

    def _send_speakers(self, data: bytes) -> None:
        z = self.zone
        try:
            self.sender.sendto(data, (z.multicast_address, z.multicast_port))
            self.stats.packets_speakers += 1
        except OSError as e:
            self.stats.errors += 1
            log.warning("zone %s: speaker send failed: %s", z.slug, e)


class Pager:
    def __init__(self, path: Path, *, bind: str = "127.0.0.1") -> None:
        self.path = path
        self.bind = bind
        self.stats = Stats()
        self.zones: list[Zone] = []
        self.transports: dict[str, asyncio.DatagramTransport] = {}
        self._mtime: float | None = None
        self._sender: socket.socket | None = None

    async def reload(self) -> bool:
        """Re-read the zone table when the file changed; returns True on a change."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            if self.zones or self._mtime is not None:
                log.info("%s missing: no zones", self.path)
            await self._apply([])
            self._mtime = None
            return False
        if mtime == self._mtime:
            return False
        try:
            zones = load_zones(self.path)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
            log.error("%s is not usable: %s", self.path, e)
            self._mtime = mtime
            return False
        self._mtime = mtime
        await self._apply(zones)
        return True

    async def _apply(self, zones: list[Zone]) -> None:
        loop = asyncio.get_running_loop()
        for t in self.transports.values():
            t.close()
        self.transports.clear()
        if self._sender is None:
            self._sender = multicast_socket(max((z.ttl for z in zones), default=DEFAULT_TTL))
        for z in zones:
            try:
                transport, _ = await loop.create_datagram_endpoint(
                    lambda z=z: ZoneProtocol(z, self._sender, self.stats, loop),  # type: ignore[misc]
                    local_addr=(self.bind, z.port),
                )
            except OSError as e:
                self.stats.errors += 1
                log.error("zone %s: cannot listen on %s:%s: %s", z.slug, self.bind, z.port, e)
                continue
            self.transports[z.slug] = transport
        self.zones = zones
        log.info("%d zone(s) listening (Poly format: %s)", len(self.transports), poly.FORMAT)

    async def run(self, *, once: bool = False) -> None:
        await self.reload()
        if once:
            return
        while True:
            await asyncio.sleep(RELOAD_SECONDS)
            await self.reload()

    def status(self) -> dict[str, Any]:
        return {
            "zones": [z.slug for z in self.zones],
            "listening": sorted(self.transports),
            "poly_format": poly.FORMAT,
            **self.stats.__dict__,
        }
