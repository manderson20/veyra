# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registered PJSIP contacts with their addresses (docs/CALL_FEATURES.md §2.1).

ARI's ``/endpoints`` says only whether an endpoint is online. The addresses
live in the contact objects, which PJSIP persists in the Asterisk database
(family ``registrar/contact``, one JSON object per contact) and reports with
status and round-trip time in ``pjsip show contacts``. Both are read through
the CLI socket the service account already has (``cli.run``), parsed here
without any shell, and cached by the adapter for a few seconds.

The two outputs are joined on the contact hash: the store keys each contact
by its full 32-hex hash, the listing prints the first ten characters and
truncates long URIs to its column width. Either may be missing: the AstDB
has no status, the CLI listing has no addresses.

Veyra generates every endpoint with ``rewrite_contact=yes``, so PJSIP
replaces the host and port of the stored contact URI with the address the
REGISTER actually arrived from and keeps the phone's own Contact address in
the ``x-ast-orig-host`` URI parameter. Without that parameter (an endpoint
configured otherwise) the URI is the phone's own address and the only hint
of the source is ``via_addr``, which is the Via header as the phone sent it.
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
# The Aor/ContactUri column is cut to its width ("example-1001/sip:exa"); a
# contact that never answered a qualify prints "-nan".
_CONTACT_LINE_RE = re.compile(
    r"^\s*Contact:\s+(?P<aor>[^/\s]+)(?:/(?P<uri>\S*))?\s+(?P<hash>[0-9a-fA-F]+)\s+"
    r"(?P<status>Avail|Unavail|NonQual|Unknown|Created|Removed)\s+(?P<rtt>-?[0-9.]+|-?nan|N/A)?\s*$"
)
_CONTACT_HEADER_RE = re.compile(r"^\s*Contact:\s+<Aor/ContactUri(?P<dots>\.*)>")
_HOSTPORT_RE = re.compile(
    r"^(?:\[(?P<v6>[0-9a-fA-F:.]+)\]|(?P<host>[^:;?>]+))(?::(?P<port>\d{1,5}))?$"
)


def parse_uri(uri: str) -> tuple[str | None, int | None, str | None]:
    """``sip:user@host:port;transport=tls`` -> (host, port, transport)."""
    host, port, params = _split_uri(uri)
    transport = params.get("transport")
    if transport is None and uri.strip().strip("<>").lower().startswith("sips:"):
        transport = "tls"
    return host, port, transport


def _hostport(value: str) -> tuple[str | None, int | None]:
    m = _HOSTPORT_RE.match(value)
    if not m:
        return None, None
    host = m.group("v6") or m.group("host")
    port = None
    if m.group("port"):
        port = int(m.group("port"))
        if not 0 < port < 65536:
            port = None
    return host, port


def _split_uri(uri: str) -> tuple[str | None, int | None, dict[str, str]]:
    """-> (host, port, lower-cased URI parameters)."""
    value = uri.strip().strip("<>")
    rest = value.partition(":")[2] if value.lower().startswith(("sip:", "sips:")) else value
    params = ""
    if ";" in rest:
        rest, params = rest.split(";", 1)
    rest = rest.split("?", 1)[0]
    if "@" in rest:
        rest = rest.rsplit("@", 1)[1]
    host, port = _hostport(rest)
    parsed: dict[str, str] = {}
    for part in params.split(";"):
        k, _, v = part.partition("=")
        if k.strip() and v.strip():
            parsed[k.strip().lower()] = v.strip().lower()
    return host, port, parsed


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
    """``pjsip show contacts`` -> hash prefix -> {aor, uri, status, rtt_ms, truncated}.

    The listing prints the first ten characters of the contact hash and cuts
    ``aor/uri`` to the column width, so a long URI is incomplete
    (``truncated``) and only the store can say where the phone is."""
    out: dict[str, dict[str, Any]] = {}
    width: int | None = None
    for line in output.splitlines():
        h = _CONTACT_HEADER_RE.match(line)
        if h:
            width = len("Aor/ContactUri") + len(h.group("dots"))
            continue
        m = _CONTACT_LINE_RE.match(line)
        if not m:
            continue
        rtt: float | None = None
        raw = m.group("rtt")
        if raw:
            try:
                rtt = round(float(raw), 3)
            except ValueError:
                rtt = None
            if rtt is not None and rtt != rtt:  # nan
                rtt = None
        aor, uri = m.group("aor"), m.group("uri") or ""
        out[m.group("hash").lower()] = {
            "aor": aor,
            "uri": uri,
            "status": m.group("status"),
            "rtt_ms": rtt,
            "truncated": width is not None and len(f"{aor}/{uri}") >= width,
        }
    return out


def _listed(
    listing: dict[str, dict[str, Any]], full_hash: str
) -> tuple[str | None, dict[str, Any]]:
    """The listing row whose hash prefix matches a store hash."""
    for prefix, row in listing.items():
        if full_hash.startswith(prefix) or prefix.startswith(full_hash):
            return prefix, row
    return None, {}


def addresses(
    uri: str, via_addr: Any = None, via_port: Any = None
) -> tuple[str | None, int | None, str | None, int | None, str | None]:
    """-> (contact_host, contact_port, source_host, source_port, transport).

    With ``rewrite_contact`` the URI host and port are the address the
    REGISTER came from and ``x-ast-orig-host`` holds the phone's own Contact
    address. Otherwise the URI is the phone's own address and the Via
    address is the best available source."""
    host, port, params = _split_uri(uri)
    transport = params.get("transport")
    if transport is None and uri.strip().strip("<>").lower().startswith("sips:"):
        transport = "tls"
    orig = params.get("x-ast-orig-host")
    if orig:
        contact_host, contact_port = _hostport(orig)
        return contact_host, contact_port, host, port, transport
    source_host = str(via_addr or "").strip() or None
    source_port = _port(via_port) if source_host else None
    return host, port, source_host, source_port, transport


def merge(
    database: dict[str, dict[str, Any]], listing: dict[str, dict[str, Any]]
) -> list[Registration]:
    """Join the store (by URI) and the listing (by hash prefix) into one
    Registration per contact."""
    rows: list[Registration] = []
    seen: set[str] = set()
    for uri in sorted(database):
        db = database[uri]
        endpoint = str(db.get("endpoint") or db.get("aor") or "")
        if not endpoint:
            continue
        prefix, li = _listed(listing, str(db.get("hash") or ""))
        if prefix:
            seen.add(prefix)
        rows.append(_row(endpoint, uri, db, li))
    # Listed but not (or no longer) in the store: nothing but the listing to go on.
    for prefix in sorted(set(listing) - seen):
        li = listing[prefix]
        endpoint = str(li.get("aor") or "")
        if not endpoint:
            continue
        rows.append(_row(endpoint, str(li.get("uri") or ""), {}, li))
    rows.sort(key=lambda r: (r.endpoint, r.uri))
    return rows


def _row(endpoint: str, uri: str, db: dict[str, Any], li: dict[str, Any]) -> Registration:
    if db or not li.get("truncated"):
        c_host, c_port, s_host, s_port, transport = addresses(
            uri, db.get("via_addr"), db.get("via_port")
        )
    else:
        c_host = c_port = s_host = s_port = transport = None
    return Registration(
        endpoint=endpoint,
        uri=uri,
        contact_host=c_host,
        contact_port=c_port,
        source_host=s_host,
        source_port=s_port,
        transport=transport,
        user_agent=(str(db.get("user_agent") or "").strip() or None),
        expires_at=_expires(db.get("expiration_time")),
        status=li.get("status"),
        rtt_ms=li.get("rtt_ms"),
        reg_server=(str(db.get("reg_server") or "").strip() or None),
    )
