# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone trust bootstrap (docs/FIREWALL_TRUST.md §6.3): over plain HTTP the
provisioning server hands out only public data, the Veyra CA certificate and
the HTTPS address, so the phone switches to HTTPS and gets its secrets there.

Poly only for now; other brands get 404 over HTTP (their templates add the
same bootstrap later)."""

from __future__ import annotations

import ipaddress
import logging
from pathlib import Path
from xml.sax.saxutils import quoteattr

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.models import Device, Organization
from veyra.core.security.crypto import DecryptionError, InstallationKey
from veyra.firewall.settings import load_settings
from veyra.telephony.settings import load_sip_settings

log = logging.getLogger("veyra.provisioning")

# Public copy of the CA certificate the installer writes (the key stays root-only).
CA_FILE = "veyra-ca.crt"
BOOTSTRAP_PREFIX = "veyra-bootstrap-"

# Poly device.prov.serverType: 0 FTP, 1 TFTP, 2 HTTP, 3 HTTPS, 4 FTPS.
POLY_HTTPS = "3"


def ca_certificate(config_dir: Path) -> str | None:
    try:
        pem = (config_dir / CA_FILE).read_text()
    except OSError:
        return None
    return pem if "BEGIN CERTIFICATE" in pem else None


def bootstrap_networks(db: Session) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """The firewall setting, or the SIP settings' local networks when empty."""
    nets = load_settings(db).bootstrap_networks or load_sip_settings(db).local_nets
    return [ipaddress.ip_network(n, strict=False) for n in nets]


def client_allowed(
    address: str | None, networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network]
) -> bool:
    if not address:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip.version == n.version and ip in n for n in networks)


def is_poly(user_agent: str | None, device: Device | None) -> bool:
    if device is not None:
        return device.manufacturer.lower() in ("poly", "polycom")
    ua = (user_agent or "").lower()
    return "polycom" in ua or "poly" in ua


def _attr(value: str) -> str:
    # Newlines in attribute values are normalised to spaces by XML parsers;
    # the PEM must keep them.
    return quoteattr(value, {"\n": "&#10;", "\r": ""})


def poly_master(mac: str) -> str:
    return (
        '<?xml version="1.0" standalone="yes"?>\n'
        f'<APPLICATION APP_FILE_PATH="" CONFIG_FILES="{BOOTSTRAP_PREFIX}{mac}.cfg" '
        'MISC_FILES="" LOG_FILE_DIRECTORY="" />\n'
    )


def poly_config(
    ca_pem: str, server_name: str, user: str | None = None, password: str | None = None
) -> str:
    attrs = [
        ("device.set", "1"),
        ("device.sec.TLS.customCaCert1.set", "1"),
        ("device.sec.TLS.customCaCert1", ca_pem.strip() + "\n"),
        ("device.prov.serverType.set", "1"),
        ("device.prov.serverType", POLY_HTTPS),
        ("device.prov.serverName.set", "1"),
        ("device.prov.serverName", server_name),
    ]
    if user and password:
        attrs += [
            ("device.prov.user.set", "1"),
            ("device.prov.user", user),
            ("device.prov.password.set", "1"),
            ("device.prov.password", password),
        ]
    body = "\n  ".join(f"{k}={_attr(v)}" for k, v in attrs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        "<!-- Veyra bootstrap: trust the Veyra CA, then provision over HTTPS -->\n"
        f"<polycomConfig>\n <device\n  {body}\n />\n</polycomConfig>\n"
    )


def enrollment_credential(
    db: Session, key: InstallationKey | None, device: Device | None
) -> tuple[str, str] | None:
    """The organization enrollment credential, only when the organization
    chose to carry it in the bootstrap (§6.4)."""
    if device is None or key is None:
        return None
    org = db.get(Organization, device.organization_id)
    if (
        org is None
        or not org.bootstrap_includes_credential
        or not org.provisioning_user
        or not org.provisioning_secret_ciphertext
    ):
        return None
    try:
        password = key.decrypt(
            org.provisioning_secret_ciphertext, f"organization.provisioning_secret:{org.id}"
        )
    except DecryptionError:
        log.warning("bootstrap: enrollment credential of %s cannot be decrypted", org.slug)
        return None
    return org.provisioning_user, password


def find_device(db: Session, mac: str | None) -> Device | None:
    if not mac:
        return None
    return db.scalar(select(Device).where(Device.mac_address == mac))
