# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which ports each firewall service covers, read from the configuration
Veyra deploys (docs/FIREWALL_TRUST.md §3.1), never assumed."""

from __future__ import annotations

from veyra.firewall.render import PortSpec
from veyra.firewall.settings import FirewallSettings
from veyra.telephony.settings import SipSettings


def service_ports(sip: SipSettings, fw: FirewallSettings) -> dict[str, PortSpec]:
    sip_tcp = []
    if sip.tcp_enabled:
        sip_tcp.append(str(sip.tcp_port))
    if sip.tls_enabled:
        sip_tcp.append(str(sip.tls_port))
    return {
        "sip": PortSpec(udp=(str(sip.udp_port),), tcp=tuple(sorted(set(sip_tcp)))),
        "rtp": PortSpec(udp=(f"{sip.rtp_start}-{sip.rtp_end}",)),
        # Provisioning shares the web ports (HTTPS, and HTTP when enabled).
        "web": PortSpec(tcp=("80", "443")),
        "ssh": PortSpec(tcp=tuple(str(p) for p in fw.ssh_ports)),
    }
