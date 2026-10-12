# SPDX-License-Identifier: AGPL-3.0-or-later
"""SIP and media settings: the installation-wide inputs to configuration
generation. Stored as one JSON document in ``system_settings`` under
``telephony.sip``; validated by :class:`SipSettings`."""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from veyra.core.models import SystemSetting

SIP_SETTINGS_KEY = "telephony.sip"

# Codecs Veyra offers in the UI, in the order Asterisk names them.
CODECS = ("ulaw", "alaw", "g722", "opus", "g729", "gsm", "h264")
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOSTNAME_RE = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})*$")


def _address_or_host(value: str) -> str:
    v = value.strip()
    try:
        ipaddress.ip_address(v)
        return v
    except ValueError:
        pass
    if _HOSTNAME_RE.match(v):
        return v
    raise ValueError("must be an IP address or a host name")


class SipSettings(BaseModel):
    """Everything the SIP transports and media need. Defaults match a
    single-site LAN deployment; NAT fields stay empty until needed."""

    bind_address: str = Field("0.0.0.0", description="Address the SIP transports bind to")  # noqa: S104
    udp_port: int = Field(5060, ge=1, le=65535)
    tcp_enabled: bool = True
    tcp_port: int = Field(5060, ge=1, le=65535)
    tls_enabled: bool = False
    tls_port: int = Field(5061, ge=1, le=65535)
    external_signaling_address: str | None = Field(
        None, description="Public address phones and carriers see when this server is behind NAT"
    )
    external_media_address: str | None = None
    local_nets: list[str] = Field(
        default_factory=list, description="Networks that are local (no NAT), in CIDR notation"
    )
    rtp_start: int = Field(10000, ge=1024, le=65535)
    rtp_end: int = Field(20000, ge=1024, le=65535)
    codecs: list[str] = Field(default_factory=lambda: ["ulaw", "alaw", "g722"])
    default_language: str = Field("en", pattern=r"^[a-z]{2}(_[A-Z]{2})?$")

    @field_validator("bind_address")
    @classmethod
    def _bind(cls, v: str) -> str:
        v = v.strip()
        ipaddress.ip_address(v)  # raises ValueError
        return v

    @field_validator("external_signaling_address", "external_media_address", mode="before")
    @classmethod
    def _external(cls, v: Any) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return _address_or_host(str(v))

    @field_validator("local_nets")
    @classmethod
    def _nets(cls, v: list[str]) -> list[str]:
        out = []
        for net in v:
            net = net.strip()
            if not net:
                continue
            out.append(str(ipaddress.ip_network(net, strict=False)))
        return out

    @field_validator("codecs")
    @classmethod
    def _codecs(cls, v: list[str]) -> list[str]:
        seen: list[str] = []
        for c in v:
            c = c.strip().lower()
            if c not in CODECS:
                raise ValueError(f"unknown codec {c!r}; choose from {', '.join(CODECS)}")
            if c not in seen:
                seen.append(c)
        if not seen:
            raise ValueError("choose at least one codec")
        return seen

    def problems(self) -> list[str]:
        """Cross-field checks that pydantic validators cannot express."""
        out = []
        if self.rtp_end - self.rtp_start < 100:
            out.append("The RTP port range must span at least 100 ports.")
        if self.rtp_end <= self.rtp_start:
            out.append("rtp_end must be greater than rtp_start.")
        ports = {self.udp_port}
        if self.tcp_enabled:
            ports.add(self.tcp_port)
        if self.tls_enabled:
            if self.tls_port == self.tcp_port and self.tcp_enabled:
                out.append("The TLS port must differ from the TCP port.")
            ports.add(self.tls_port)
        for port in sorted(ports):
            if self.rtp_start <= port <= self.rtp_end:
                out.append(f"SIP port {port} lies inside the RTP range.")
        if bool(self.external_signaling_address) != bool(self.external_media_address):
            out.append("Set both external addresses (signaling and media) or neither.")
        if self.external_signaling_address and not self.local_nets:
            out.append("When an external address is set, list the local networks too.")
        return out


def load_sip_settings(db: Session) -> SipSettings:
    row = db.get(SystemSetting, SIP_SETTINGS_KEY)
    if row is None or not isinstance(row.value, dict):
        return SipSettings()
    return SipSettings.model_validate(row.value)


def save_sip_settings(db: Session, settings: SipSettings, updated_by: Any = None) -> None:
    row = db.get(SystemSetting, SIP_SETTINGS_KEY)
    value = settings.model_dump(mode="json")
    if row is None:
        db.add(SystemSetting(key=SIP_SETTINGS_KEY, value=value, updated_by=updated_by))
    else:
        row.value = value
        row.updated_by = updated_by
    db.flush()
