#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Capture Poly group-page datagrams (docs/PAGING_RECORDINGS.md §2.2 spike).

Joins the Poly paging multicast group on this host and writes the first
packets as a hex dump, so the group-page header can be read off. Run on a
host in the phones' VLAN while one Poly phone pages another:

    python3 -I tools/poly-capture.py --out poly-page.txt [--group 224.0.1.116 --port 5001 --count 20]

The file holds only packet bytes and timing; no names, numbers or addresses
of your installation.
"""

from __future__ import annotations

import argparse
import socket
import struct
import time


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--group", default="224.0.1.116")
    ap.add_argument("--port", type=int, default=5001)
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=120, help="seconds to wait for packets")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", args.port))
    sock.setsockopt(
        socket.IPPROTO_IP,
        socket.IP_ADD_MEMBERSHIP,
        struct.pack("4s4s", socket.inet_aton(args.group), socket.inet_aton("0.0.0.0")),
    )
    sock.settimeout(args.timeout)
    print(f"Joined {args.group}:{args.port}; page from a Poly phone now (waiting {args.timeout}s)")
    started = time.monotonic()
    first: float | None = None
    with open(args.out, "w", encoding="utf-8") as out:
        out.write(f"# Poly group-page capture: {args.group}:{args.port}\n")
        for i in range(args.count):
            try:
                data, _addr = sock.recvfrom(4096)
            except TimeoutError:
                print("No packets received; is this host on the phones' VLAN?")
                break
            now = time.monotonic()
            first = first if first is not None else now
            out.write(f"packet {i + 1} t+{now - first:.3f}s len={len(data)}\n")
            out.write(data.hex(" ", 1) + "\n\n")
            print(f"packet {i + 1}: {len(data)} bytes")
    print(f"Done in {time.monotonic() - started:.1f}s; send {args.out} to the developer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
