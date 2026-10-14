# SPDX-License-Identifier: AGPL-3.0-or-later
"""Poly group-page packet encoding (docs/PAGING_RECORDINGS.md §2.2).

Poly VVX phones listen for group pages on one multicast address and port
(default 224.0.1.116:5001) and play only packets whose Poly header names a
group they subscribe to. The header layout is not published; it is to be
taken from a capture of one of the owner's phones paging another (the
*(spike)* of the design). Until that capture lands, ``encode`` passes the
RTP packet through unchanged with the destination set to the Poly address:
harmless (phones ignore it) and the plumbing, ports and timing are exercised
end to end. ``FORMAT`` names what is implemented so the status page can say
so.
"""

from __future__ import annotations

FORMAT = "rtp-passthrough"  # becomes "poly-group-page" once the header is implemented
EMERGENCY_GROUP = 25


def encode(rtp_packet: bytes, group: int, *, priority: str = "normal") -> bytes:
    """The datagram to send to the Poly address for ``rtp_packet`` of ``group``."""
    if not 1 <= group <= EMERGENCY_GROUP:
        raise ValueError("Poly groups are 1-25")
    return rtp_packet
