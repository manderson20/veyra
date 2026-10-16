# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registered PJSIP contacts with their addresses (docs/CALL_FEATURES.md §2.1).

ARI's ``/endpoints`` says only whether an endpoint is online. The addresses
live in the contact objects, which PJSIP persists in the Asterisk database
(family ``registrar/contact``, one JSON object per contact) and reports with
status and round-trip time in ``pjsip show contacts``. Both are read through
the CLI socket the service account already has (``cli.run``), parsed here
without any shell, and cached by the adapter for a few seconds.

The two outputs are joined on the contact URI. Either may be missing: the
AstDB has no status, the CLI listing has no addresses.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
from datetime import UTC, datetime
from typing import Any

from veyra.telephony.adapter import Registration

log = logging.getLogger("veyra.telephony.contacts")

CMD_DATABASE = "database show registrar/contact"
CMD_CONTACTS = "pjsip show contacts"

# /registrar/contact/example-1001;@0123456789abcdef : {"uri":"sip:...", ...}
_DB_LINE_RE = re.compile(
    r"^/registrar/contact/(?P<aor>[^;]+);@(?P<hash>[0-9a-fA-F]+)\s*:\s*(?P<json>\{.*\})\s*$"
)
# "  Contact:  example-1001/sip:example-1001@172.16.5.20:5060;ob  0123456789 Avail  12.345"
_CONTACT_LINE_RE = re.compile(
    r"^\s*Contact:\s+(?P<aor>\S+?)/(?P<uri>\S+)\s+(?P<hash>[0-9a-fA-F]+)\s+"
    r"(?P<status>Avail|Unavail|NonQual|Unknown|Created|Removed)\s+(?P<rtt>[0-9.]+|nan|N/A)?\s*$"
)
_HOSTPORT_RE = re.compile(
    r"^(?:\[(?P<v6>[0-9a-fA-F:.]+)\]|(?P<host>[^:;?>]+))(?::(?P<port>\d{1,5}))?$"
)


def parse_uri(uri: str) -> tuple[str | None, int | None, str | None]:
    """``sip:user@host:port;transport=tls`` -> (host, port, transport)."""
    value = uri.strip().strip("<>")
    if value.lower().startswith(("sip:", "sips:")):
        scheme, _, rest = value.partition(":")
    else:
        scheme, rest = "sip", value
    params = ""
    if ";" in rest:
        rest, params = rest.split(";", 1)
    rest = rest.split("?", 1)[0]
    if "@" in rest:
        rest = rest.rsplit("@", 1)[1]
    m = _HOSTPORT_RE.match(rest)
    host = port = None
    if m:
        host = m.group("v6") or m.group("host")
        if m.group("port"):
            port = int(m.group("port"))
            if not 0 < port < 65536:
                port = None
    transport = None
    for part in params.split(";"):
        k, _, v = part.partition("=")
        if k.strip().lower() == "transport" and v:
            transport = v.strip().lower()
    if transport is None and scheme.lower() == "sips":
        transport = "tls"
    return host, port, transport


def _expires(value: Any) -> str | None:
    """AstDB stores the expiry as seconds since the epoch (sometimes with a
    fraction); accept an ISO timestamp too."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        return datetime.fromtimestamp(int(float(text)), UTC).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _port(value: Any) -> int | None:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return port if 0 < port < 65536 else None


def parse_database(output: str) -> dict[str, dict[str, Any]]:
    """``database show registrar/contact`` -> contact URI -> fields (with ``aor``)."""
    out: dict[str, dict[str, Any]] = {}
    for line in output.splitlines():
        m = _DB_LINE_RE.match(line.strip())
        if not m:
            continue
        try:
            fields = json.loads(m.group("json"))
        except ValueError:
            log.debug("unparseable contact row for %s", m.group("aor"))
            continue
        if not isinstance(fields, dict):
            continue
        uri = str(fields.get("uri") or "").strip()
        if not uri:
            continue
        fields["aor"] = urllib.parse.unquote(m.group("aor"))
        fields["hash"] = m.group("hash").lower()
        out[uri] = fields
    return out


def parse_contacts(output: str) -> dict[str, dict[str, Any]]:
    """``pjsip show contacts`` -> contact URI -> {aor, hash, status, rtt_ms}."""
    out: dict[str, dict[str, Any]] = {}
    for line in output.splitlines():
        m = _CONTACT_LINE_RE.match(line)
        if not m:
            continue
        rtt: float | None = None
        raw = m.group("rtt")
        if raw and raw not in ("nan", "N/A"):
            try:
                rtt = round(float(raw), 3)
            except ValueError:
                rtt = None
        out[m.group("uri")] = {
            "aor": m.group("aor"),
            "hash": m.group("hash").lower(),
            "status": m.group("status"),
            "rtt_ms": rtt,
        }
    return out


def merge(
    database: dict[str, dict[str, Any]], listing: dict[str, dict[str, Any]]
) -> list[Registration]:
    """Join both views on the contact URI into Registration rows, one per contact."""
    rows: list[Registration] = []
    for uri in sorted(set(database) | set(listing)):
        db = database.get(uri, {})
        li = listing.get(uri, {})
        endpoint = str(db.get("endpoint") or db.get("aor") or li.get("aor") or "")
        if not endpoint:
            continue
        host, port, transport = parse_uri(uri)
        source_host = str(db.get("via_addr") or "").strip() or None
        rows.append(
            Registration(
                endpoint=endpoint,
                uri=uri,
                contact_host=host,
                contact_port=port,
                source_host=source_host,
                source_port=_port(db.get("via_port")) if source_host else None,
                transport=transport,
                user_agent=(str(db.get("user_agent") or "").strip() or None),
                expires_at=_expires(db.get("expiration_time")),
                status=li.get("status"),
                rtt_ms=li.get("rtt_ms"),
                reg_server=(str(db.get("reg_server") or "").strip() or None),
            )
        )
    return rows
