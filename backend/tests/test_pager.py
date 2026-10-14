# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 9c: the page sender fans one RTP stream out to the speakers'
multicast group (delayed) and the Poly address (docs/PAGING_RECORDINGS.md §2.2)."""

import asyncio
import json
import socket

import pytest

from veyra.paging import poly
from veyra.paging.pager import Pager, Stats, Zone, ZoneProtocol, parse_zones


def _doc(**over):
    zone = {
        "slug": "building-a",
        "organization": "example",
        "port": 40000,
        "multicast_address": "239.1.2.10",
        "multicast_port": 5004,
        "poly_address": "224.0.1.116",
        "poly_port": 5001,
        "poly_group": 3,
        "kind": "normal",
    }
    zone.update(over)
    return {"defaults": {"delay_ms": 50, "ttl": 1}, "zones": [zone]}


def test_parse_zones_applies_defaults_and_rejects_duplicate_ports():
    zones = parse_zones(_doc())
    assert zones[0] == Zone(
        "building-a", "example", 40000, "239.1.2.10", 5004, "224.0.1.116", 5001, 3, "normal", 50, 1
    )
    doc = _doc()
    doc["zones"].append({**doc["zones"][0], "slug": "b"})
    with pytest.raises(ValueError, match="one port"):
        parse_zones(doc)


def test_poly_encoder_validates_the_group():
    assert poly.encode(b"\x80\x00", 3) == b"\x80\x00"  # passthrough until the capture lands
    with pytest.raises(ValueError):
        poly.encode(b"", 26)


class _FakeSocket:
    def __init__(self):
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, data, addr):
        self.sent.append((data, addr))


def test_zone_protocol_sends_poly_now_and_speakers_after_the_delay():
    async def run():
        loop = asyncio.get_running_loop()
        zone = parse_zones(_doc(poly_address="127.0.0.1", multicast_address="127.0.0.1"))[0]
        sock = _FakeSocket()
        proto = ZoneProtocol(zone, sock, Stats(), loop)  # type: ignore[arg-type]
        proto.datagram_received(b"\x80\x00rtp1", ("127.0.0.1", 1))
        assert sock.sent == [(b"\x80\x00rtp1", ("127.0.0.1", 5001))]
        await asyncio.sleep(0.12)
        assert sock.sent[1] == (b"\x80\x00rtp1", ("127.0.0.1", 5004))
        assert (
            proto.stats.packets_in == 1
            and proto.stats.packets_poly == 1
            and proto.stats.packets_speakers == 1
        )

    asyncio.run(run())


def test_pager_listens_per_zone_and_reloads_on_change(tmp_path):
    async def run():
        path = tmp_path / "paging.json"
        pager = Pager(path, bind="127.0.0.1")
        await pager.run(once=True)
        assert pager.status()["zones"] == []
        path.write_text(json.dumps(_doc(port=40123)))
        assert await pager.reload() is True
        assert pager.status()["listening"] == ["building-a"]
        # A real datagram on the zone port is counted.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(b"\x80\x00abc", ("127.0.0.1", 40123))
        await asyncio.sleep(0.15)
        assert pager.status()["packets_in"] == 1 and pager.status()["by_zone"] == {"building-a": 1}
        # Unchanged file: no reload; removed file: no zones.
        assert await pager.reload() is False
        path.unlink()
        await pager.reload()
        assert pager.status()["listening"] == []
        for t in pager.transports.values():
            t.close()

    asyncio.run(run())
