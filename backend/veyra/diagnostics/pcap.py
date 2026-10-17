# SPDX-License-Identifier: AGPL-3.0-or-later
"""A minimal pcap reader and SIP summary (docs/CALL_FEATURES.md §2.2), so the
common "why does this phone not register" needs no Wireshark. No
dependencies: the classic pcap format, the link types tcpdump writes for
``-i any`` (Linux cooked v1 and v2), Ethernet and raw IP, IPv4 and IPv6,
UDP and TCP, and SIP messages that start at the beginning of a payload.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

LINKTYPE_ETHERNET = 1
LINKTYPE_RAW = 101
LINKTYPE_LINUX_SLL = 113
LINKTYPE_LINUX_SLL2 = 276
MAX_READ_BYTES = 64 * 1024 * 1024
MAX_MESSAGES = 5000

_REQUEST_RE = re.compile(rb"^([A-Z]{3,16}) (\S+) SIP/2\.0\r?$")
_RESPONSE_RE = re.compile(rb"^SIP/2\.0 (\d{3}) ?(.*?)\r?$")
_COMPACT = {"i": "call-id", "f": "from", "t": "to", "v": "via", "m": "contact", "c": "content-type"}


class PcapError(ValueError):
    pass


@dataclass
class Packet:
    ts: float
    src: str
    sport: int
    dst: str
    dport: int
    transport: str
    payload: bytes


@dataclass
class SipMessage:
    at: str
    src: str
    sport: int
    dst: str
    dport: int
    transport: str
    kind: str  # request | response
    method: str | None
    status: int | None
    reason: str | None
    call_id: str | None
    cseq: str | None
    from_: str | None
    to: str | None
    user_agent: str | None
    request_uri: str | None = None

    def out(self) -> dict[str, Any]:
        d = asdict(self)
        d["from"] = d.pop("from_")
        return d


@dataclass
class Dialog:
    call_id: str
    first_at: str
    last_at: str
    messages: int = 0
    method: str | None = None
    last_status: int | None = None
    last_reason: str | None = None
    from_: str | None = None
    to: str | None = None
    parties: list[str] = field(default_factory=list)

    def out(self) -> dict[str, Any]:
        d = asdict(self)
        d["from"] = d.pop("from_")
        return d


# ------------------------------------------------------------------ pcap


def _header(f: BinaryIO) -> tuple[str, bool, int]:
    """-> (endianness, nanoseconds, link type) of a classic pcap file."""
    head = f.read(24)
    if len(head) < 24:
        raise PcapError("not a pcap file (short header)")
    magic = head[:4]
    if magic == b"\xd4\xc3\xb2\xa1":
        order, nanos = "<", False
    elif magic == b"\xa1\xb2\xc3\xd4":
        order, nanos = ">", False
    elif magic == b"\x4d\x3c\xb2\xa1":
        order, nanos = "<", True
    elif magic == b"\xa1\xb2\x3c\x4d":
        order, nanos = ">", True
    elif magic == b"\x0a\x0d\x0d\x0a":
        raise PcapError("pcapng is not supported; tcpdump writes classic pcap")
    else:
        raise PcapError("not a pcap file")
    linktype = struct.unpack(order + "I", head[20:24])[0]
    return order, nanos, linktype


def records(f: BinaryIO, max_bytes: int = MAX_READ_BYTES) -> Iterator[tuple[float, int, bytes]]:
    """(timestamp, link type, frame) for every record, until ``max_bytes`` were read."""
    order, nanos, linktype = _header(f)
    read = 24
    while read < max_bytes:
        rec = f.read(16)
        if len(rec) < 16:
            return
        sec, frac, incl, _orig = struct.unpack(order + "IIII", rec)
        data = f.read(incl)
        read += 16 + incl
        if len(data) < incl:
            return
        yield sec + frac / (1e9 if nanos else 1e6), linktype, data


def _ip(frame: bytes) -> Packet | None:
    if len(frame) < 20:
        return None
    version = frame[0] >> 4
    if version == 4:
        ihl = (frame[0] & 0x0F) * 4
        if ihl < 20 or len(frame) < ihl:
            return None
        flags_frag = struct.unpack("!H", frame[6:8])[0]
        if flags_frag & 0x1FFF:
            return None  # a later fragment: no transport header
        proto = frame[9]
        total = struct.unpack("!H", frame[2:4])[0]
        src = ".".join(str(b) for b in frame[12:16])
        dst = ".".join(str(b) for b in frame[16:20])
        body = frame[ihl : total if 0 < total <= len(frame) else len(frame)]
    elif version == 6:
        if len(frame) < 40:
            return None
        proto = frame[6]
        length = struct.unpack("!H", frame[4:6])[0]
        import ipaddress

        src = str(ipaddress.IPv6Address(frame[8:24]))
        dst = str(ipaddress.IPv6Address(frame[24:40]))
        body = frame[40 : 40 + length if length else len(frame)]
    else:
        return None
    if proto == 17 and len(body) >= 8:
        sport, dport, ulen = struct.unpack("!HHH", body[:6])
        return Packet(0.0, src, sport, dst, dport, "udp", body[8 : max(8, ulen)])
    if proto == 6 and len(body) >= 20:
        sport, dport = struct.unpack("!HH", body[:4])
        offset = (body[12] >> 4) * 4
        if offset < 20 or len(body) < offset:
            return None
        return Packet(0.0, src, sport, dst, dport, "tcp", body[offset:])
    return None


def _ethertype_payload(ethertype: int, rest: bytes) -> bytes | None:
    while ethertype in (0x8100, 0x88A8) and len(rest) >= 4:  # VLAN tags
        ethertype = struct.unpack("!H", rest[2:4])[0]
        rest = rest[4:]
    return rest if ethertype in (0x0800, 0x86DD) else None


def decode(linktype: int, frame: bytes) -> Packet | None:
    """Link layer -> IP -> UDP/TCP; None for anything else."""
    if linktype == LINKTYPE_ETHERNET:
        if len(frame) < 14:
            return None
        body = _ethertype_payload(struct.unpack("!H", frame[12:14])[0], frame[14:])
    elif linktype == LINKTYPE_LINUX_SLL:
        if len(frame) < 16:
            return None
        body = _ethertype_payload(struct.unpack("!H", frame[14:16])[0], frame[16:])
    elif linktype == LINKTYPE_LINUX_SLL2:
        if len(frame) < 20:
            return None
        body = _ethertype_payload(struct.unpack("!H", frame[0:2])[0], frame[20:])
    elif linktype == LINKTYPE_RAW:
        body = frame
    else:
        return None
    return _ip(body) if body else None


def packets(path: Path, max_bytes: int = MAX_READ_BYTES) -> Iterator[Packet]:
    with path.open("rb") as f:
        for ts, linktype, frame in records(f, max_bytes):
            p = decode(linktype, frame)
            if p is not None:
                p.ts = ts
                yield p


# ------------------------------------------------------------------ SIP


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_sip(p: Packet) -> SipMessage | None:
    """The SIP message at the start of a payload, or None."""
    payload = p.payload.lstrip(b"\r\n")
    if not payload or payload[:1].isspace():
        return None
    head, _, _body = payload.partition(b"\r\n\r\n")
    lines = head.split(b"\n")
    start = lines[0]
    kind = method = reason = uri = None
    status = None
    m = _REQUEST_RE.match(start)
    if m:
        kind, method, uri = "request", m.group(1).decode(), m.group(2).decode(errors="replace")
    else:
        m = _RESPONSE_RE.match(start)
        if not m:
            return None
        kind, status = "response", int(m.group(1))
        reason = m.group(2).decode(errors="replace")[:60] or None
    headers: dict[str, str] = {}
    for raw in lines[1:]:
        line = raw.rstrip(b"\r")
        if not line:
            break
        name, sep, value = line.partition(b":")
        if not sep:
            continue
        key = name.strip().decode(errors="replace").lower()
        key = _COMPACT.get(key, key)
        if key not in headers:  # the first Via, the one From
            headers[key] = value.strip().decode(errors="replace")[:200]
    cseq = headers.get("cseq")
    if kind == "response" and cseq:
        parts = cseq.split()
        method = parts[1] if len(parts) > 1 else None
    return SipMessage(
        at=_iso(p.ts),
        src=p.src,
        sport=p.sport,
        dst=p.dst,
        dport=p.dport,
        transport=p.transport,
        kind=kind,
        method=method,
        status=status,
        reason=reason,
        call_id=headers.get("call-id"),
        cseq=cseq,
        from_=headers.get("from"),
        to=headers.get("to"),
        user_agent=headers.get("user-agent") or headers.get("server"),
        request_uri=uri,
    )


def summary(
    path: Path, *, max_messages: int = MAX_MESSAGES, max_bytes: int = MAX_READ_BYTES
) -> dict[str, Any]:
    """Every SIP message (time, addresses, method or status, Call-ID, From,
    To, User-Agent) and the dialogs they form, grouped by Call-ID."""
    messages: list[SipMessage] = []
    dialogs: dict[str, Dialog] = {}
    seen = 0
    truncated = False
    with path.open("rb") as f:
        for ts, linktype, frame in records(f, max_bytes):
            seen += 1
            p = decode(linktype, frame)
            if p is None:
                continue
            p.ts = ts
            msg = parse_sip(p)
            if msg is None:
                continue
            if len(messages) >= max_messages:
                truncated = True
                break
            messages.append(msg)
            key = msg.call_id or f"(no Call-ID) {msg.src}:{msg.sport}"
            d = dialogs.get(key)
            if d is None:
                d = dialogs[key] = Dialog(
                    call_id=key, first_at=msg.at, last_at=msg.at, from_=msg.from_, to=msg.to
                )
            d.last_at = msg.at
            d.messages += 1
            if d.method is None and msg.kind == "request":
                d.method = msg.method
            if msg.kind == "response":
                d.last_status, d.last_reason = msg.status, msg.reason
            for party in (msg.src, msg.dst):
                if party not in d.parties:
                    d.parties.append(party)
        else:
            truncated = truncated or f.tell() >= max_bytes
    return {
        "packets_read": seen,
        "messages": [m.out() for m in messages],
        "dialogs": [d.out() for d in dialogs.values()],
        "truncated": truncated,
    }
