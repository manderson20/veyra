# SPDX-License-Identifier: AGPL-3.0-or-later
"""From FreePBX (issue #42; docs/BULK_IMPORT.md §5).

Reads a ``mysqldump`` of FreePBX's ``asterisk`` database (``mysqldump
asterisk > asterisk.sql`` on the FreePBX server, plain or gzipped) and
turns its extensions, ring groups and inbound routes into the CSV files of
the bulk import, which the administrator then checks (dry run) and imports
like any other file. Nothing is written here; SIP passwords are never
carried over (Veyra makes new ones), and what has no equivalent yet is
listed as a warning.

Tables read: ``users`` and ``devices`` (extensions), ``sip`` (caller ID),
``ringgroups``, ``incoming``, ``ivr_details`` / ``announcement`` /
``queues_config`` (names of destinations).
"""

from __future__ import annotations

import gzip
import io
import re
import tarfile
from dataclasses import dataclass, field
from typing import Any

from veyra.bulk import service

MAX_DUMP_BYTES = 64 * 1024 * 1024
_CREATE_RE = re.compile(r"CREATE TABLE `([^`]+)` \((.*?)\)[^;()]*;", re.S)
# A column definition: a backquoted name at the start of a line or after a
# comma, followed by its type (index lines start with KEY/PRIMARY instead).
_COLUMN_RE = re.compile(r"(?:^|,)\s*`([^`]+)`\s", re.M)
_INSERT_RE = re.compile(r"INSERT INTO `([^`]+)`(?:\s*\(([^)]*)\))?\s+VALUES\s*", re.I)
TABLES = (
    "users",
    "devices",
    "sip",
    "ringgroups",
    "incoming",
    "ivr_details",
    "announcement",
    "queues_config",
)


class FreepbxError(ValueError):
    pass


@dataclass
class Conversion:
    csv: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ----------------------------------------------------------------- the dump


def read_upload(data: bytes, filename: str | None) -> str:
    """The SQL text of an upload: ``.sql``, ``.sql.gz``, or a tarball that
    holds one (FreePBX 14 backups)."""
    if len(data) > MAX_DUMP_BYTES:
        raise FreepbxError("the file is larger than 64 MB")
    if data[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(data)
        except OSError as e:
            raise FreepbxError(f"the file is not a valid gzip file ({e})") from e
        if len(raw) > 4 * MAX_DUMP_BYTES:
            raise FreepbxError("the unpacked file is too large")
        data = raw
    if data[257:262] == b"ustar":
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            names = [m for m in tar.getmembers() if m.isfile()]
            if any(m.name.startswith("modulejson/") or "/modulejson/" in m.name for m in names):
                raise FreepbxError(
                    "this is a FreePBX 15+ backup, which keeps modules as JSON; upload a "
                    "database dump instead: on the FreePBX server run "
                    "`mysqldump asterisk > asterisk.sql`"
                )
            sql = [m for m in names if m.name.endswith((".sql", ".sql.gz"))]
            if not sql:
                raise FreepbxError("the archive holds no .sql database dump")
            member = tar.extractfile(max(sql, key=lambda m: m.size))
            assert member is not None
            inner = member.read(4 * MAX_DUMP_BYTES + 1)
            return read_upload(inner, sql[0].name)
    text = data.decode("utf-8", errors="replace")
    if "INSERT INTO" not in text:
        raise FreepbxError("no INSERT statements: is this a mysqldump of the asterisk database?")
    return text


def _values(text: str, pos: int) -> tuple[list[list[Any]], int]:
    """The ``(...),(...);`` tuples starting at ``pos``: MySQL quoting with
    backslash escapes, NULL, numbers."""
    rows: list[list[Any]] = []
    n = len(text)
    i = pos
    escapes = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "Z": "\x1a"}
    while i < n:
        while i < n and text[i] in " \t\r\n,":
            i += 1
        if i >= n or text[i] == ";":
            return rows, i + 1
        if text[i] != "(":
            raise FreepbxError(f"unexpected {text[i]!r} in an INSERT")
        i += 1
        row: list[Any] = []
        while True:
            while text[i] in " \t\r\n":
                i += 1
            if text[i] == "'":
                i += 1
                buf: list[str] = []
                while True:
                    c = text[i]
                    if c == "\\":
                        nxt = text[i + 1]
                        buf.append(escapes.get(nxt, nxt))
                        i += 2
                    elif c == "'":
                        if i + 1 < n and text[i + 1] == "'":
                            buf.append("'")
                            i += 2
                        else:
                            i += 1
                            break
                    else:
                        buf.append(c)
                        i += 1
                row.append("".join(buf))
            else:
                j = i
                while text[j] not in ",)":
                    j += 1
                token = text[i:j].strip()
                row.append(None if token.upper() == "NULL" else token)
                i = j
            while text[i] in " \t\r\n":
                i += 1
            if text[i] == ",":
                i += 1
                continue
            if text[i] == ")":
                i += 1
                rows.append(row)
                break
            raise FreepbxError("a row of an INSERT is not closed")
    return rows, i


def parse_dump(text: str, tables: tuple[str, ...] = TABLES) -> dict[str, list[dict[str, Any]]]:
    """``{table: [row, ...]}`` for the tables asked for."""
    columns: dict[str, list[str]] = {}
    for m in _CREATE_RE.finditer(text):
        if m.group(1) in tables:
            columns[m.group(1)] = _COLUMN_RE.findall(m.group(2))
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in tables}
    for m in _INSERT_RE.finditer(text):
        table = m.group(1)
        if table not in tables:
            continue
        names = (
            [c.strip().strip("`") for c in m.group(2).split(",")]
            if m.group(2)
            else columns.get(table)
        )
        if not names:
            raise FreepbxError(f"the dump has rows of {table} but not its CREATE TABLE")
        rows, _ = _values(text, m.end())
        for r in rows:
            out[table].append(dict(zip(names, r, strict=False)))
    return out


# ----------------------------------------------------------------- mapping


_CID_RE = re.compile(r'^\s*"?([^"<]*?)"?\s*<([^>]*)>\s*$')


def _dest(dest: str | None, names: dict[str, dict[str, str]], warn: list[str], what: str) -> str:
    """A FreePBX destination (``context,exten,priority``) as ``type:target``."""
    if not dest:
        return ""
    ctx, _, rest = dest.partition(",")
    exten = rest.partition(",")[0]
    if ctx == "from-did-direct" or (ctx == "ext-local" and not exten.startswith("vm")):
        return f"extension:{exten}"
    if ctx == "ext-local" and exten.startswith("vm"):
        return f"voicemail:{exten[3:]}"
    if ctx == "ext-group":
        return f"ring_group:{exten}"
    if ctx == "ext-queues":
        return f"queue:{exten}"
    if ctx == "app-blackhole":
        return "hangup"
    if ctx.startswith("ivr-"):
        name = names["ivr"].get(ctx[4:])
        if name:
            return f"ivr:{name}"
    if ctx.startswith("app-announcement-"):
        name = names["announcement"].get(ctx[len("app-announcement-") :])
        if name:
            return f"announcement:{name}"
    if ctx == "ext-meetme":
        return f"conference:{exten}"
    warn.append(f"{what}: the destination {dest!r} has no equivalent yet; set it after the import")
    return ""


def convert(text: str) -> Conversion:
    """The CSV files (by bulk kind) for a FreePBX database dump."""
    t = parse_dump(text)
    conv = Conversion()
    warn = conv.warnings
    names = {
        "ivr": {str(r.get("id")): str(r.get("name") or "") for r in t["ivr_details"]},
        "announcement": {
            str(r.get("announcement_id")): str(r.get("description") or "")
            for r in t["announcement"]
        },
    }
    sip: dict[str, dict[str, str]] = {}
    for r in t["sip"]:
        sip.setdefault(str(r.get("id")), {})[str(r.get("keyword"))] = str(r.get("data") or "")
    devices = {str(d.get("id")): d for d in t["devices"]}

    rows: list[dict[str, str]] = []
    for u in sorted(
        t["users"], key=lambda r: (len(str(r.get("extension"))), str(r.get("extension")))
    ):
        number = str(u.get("extension") or "")
        if not number.isdigit():
            warn.append(f"extension {number!r}: not a number; skipped")
            continue
        cid_name = ""
        m = _CID_RE.match(sip.get(number, {}).get("callerid", ""))
        if m:
            cid_name = m.group(1).strip()
        outbound = ""
        om = _CID_RE.match(str(u.get("outboundcid") or ""))
        if om:
            outbound = re.sub(r"[^0-9+]", "", om.group(2))
        elif u.get("outboundcid"):
            outbound = re.sub(r"[^0-9+]", "", str(u.get("outboundcid")))
        dev = devices.get(number)
        if dev is not None and str(dev.get("tech") or "") not in ("sip", "pjsip"):
            warn.append(f"extension {number}: device type {dev.get('tech')!r} imported as SIP")
        emergency = re.sub(r"[^0-9+]", "", str((dev or {}).get("emergency_cid") or ""))
        rows.append(
            {
                "number": number,
                "display_name": str(u.get("name") or number)[:200],
                "caller_id_name": cid_name[:80],
                "outbound_caller_id_number": outbound[:32],
                "emergency_caller_id_number": emergency[:32],
                "voicemail": "no" if str(u.get("voicemail") or "novm") == "novm" else "yes",
            }
        )
    if rows:
        conv.csv["extensions"] = service.to_csv(service.KINDS["extensions"], rows)
        conv.counts["extensions"] = len(rows)
        warn.append(
            "extensions: SIP passwords are not carried over; each phone gets a new one "
            "(provision the phones, or copy it from the extension's page)"
        )

    groups: list[dict[str, str]] = []
    for g in t["ringgroups"]:
        number = str(g.get("grpnum") or "")
        members, outside = [], []
        for item in re.split(r"[-\s]+", str(g.get("grplist") or "")):
            item = item.strip()
            if not item:
                continue
            if item.endswith("#"):
                outside.append(item.rstrip("#"))
            else:
                members.append(item)
        try:
            ring = max(5, min(120, int(str(g.get("grptime") or 20))))
        except ValueError:
            ring = 20
        strategy = str(g.get("strategy") or "ringall")
        if strategy not in ("ringall", "hunt", "memoryhunt", "ringall-prim", "hunt-prim"):
            warn.append(f"ring group {number}: strategy {strategy!r} imported as ring all")
        groups.append(
            {
                "number": number,
                "name": str(g.get("description") or f"Group {number}")[:100],
                "strategy": "sequential" if "hunt" in strategy else "ringall",
                "ring_seconds": str(ring),
                "members": "; ".join(members),
                "external_members": "; ".join(outside[:10]),
                "caller_id_prefix": str(g.get("grppre") or "")[:40],
                "failover": _dest(str(g.get("postdest") or ""), names, warn, f"ring group {number}")
                or "hangup",
            }
        )
    if groups:
        conv.csv["ring_groups"] = service.to_csv(service.KINDS["ring_groups"], groups)
        conv.counts["ring_groups"] = len(groups)

    routes: list[dict[str, str]] = []
    for r in t["incoming"]:
        did = str(r.get("extension") or "")
        what = f"inbound route {did or '(any DID)'}"
        if not did:
            warn.append(f"{what}: a catch-all route; create it by hand")
            continue
        if r.get("cidnum"):
            warn.append(f"{what}: the caller ID match {r.get('cidnum')!r} is not imported")
        dest = _dest(str(r.get("destination") or ""), names, warn, what)
        if not dest or dest == "hangup":
            continue
        routes.append(
            {
                "did": did,
                "description": str(r.get("description") or "")[:2000],
                "destination": dest,
            }
        )
    if routes:
        conv.csv["inbound_routes"] = service.to_csv(service.KINDS["inbound_routes"], routes)
        conv.counts["inbound_routes"] = len(routes)
    if not conv.csv:
        raise FreepbxError("no extensions, ring groups or inbound routes found in the dump")
    return conv
