# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call history from Asterisk's CDRs (docs/REPORTING.md §3).

``cdr_custom`` writes one CSV line per CDR to ``veyra.csv``; the worker reads
new lines (inode and offset kept in ``system_settings``), stores them as
``call_legs`` and folds each ``linkedid`` into one ``calls`` row: direction
and organization from the channel names, outcome from the legs."""

from __future__ import annotations

import csv
import logging
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from veyra.core.models import (
    CallLeg,
    CallRecord,
    Extension,
    InboundRoute,
    SipTrunk,
    SystemSetting,
)
from veyra.core.models.base import utcnow

log = logging.getLogger("veyra.reporting")

CDR_FILE = Path("/var/log/asterisk/cdr-custom/veyra.csv")
CURSOR_KEY = "cdr.cursor"
RETENTION_KEY = "calls.retention_days"
DEFAULT_RETENTION_DAYS = 400
FORMAT_TAG = "v1"
FIELDS = (
    "uniqueid",
    "linkedid",
    "start",
    "answer",
    "end",
    "duration",
    "billsec",
    "disposition",
    "src",
    "clid",
    "dst",
    "dcontext",
    "channel",
    "dstchannel",
    "lastapp",
    "rec",
)
# A call is complete once no leg has arrived for this long after its end.
SETTLE = timedelta(seconds=60)
TRUNK_PREFIX = "trunk-"
_PJSIP_RE = re.compile(r"^PJSIP/(?P<endpoint>.+)-[0-9a-f]{8}$")
_CLID_RE = re.compile(r'^\s*"?(?P<name>.*?)(?<!\\)"?\s*<(?P<number>[^>]*)>\s*$')


@dataclass(frozen=True)
class Cdr:
    uniqueid: str
    linkedid: str
    start: datetime
    answer: datetime | None
    end: datetime | None
    duration: int
    billsec: int
    disposition: str
    src: str
    clid: str
    dst: str
    dcontext: str
    channel: str
    dstchannel: str
    lastapp: str
    rec: str


def _time(value: str) -> datetime | None:
    """CDR times are the server's local time without a zone."""
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").astimezone()
    except ValueError:
        return None


def _int(value: str) -> int:
    try:
        return max(int(value), 0)
    except ValueError:
        return 0


def parse_line(line: str) -> Cdr | None:
    """One line of ``veyra.csv``; None for anything else (a newer format,
    a partial line, the old Master.csv layout)."""
    try:
        row = next(csv.reader([line]))
    except (csv.Error, StopIteration):
        return None
    if not row or row[0] != FORMAT_TAG or len(row) < len(FIELDS) + 1:
        return None
    v = dict(zip(FIELDS, row[1:], strict=False))
    start = _time(v["start"])
    if start is None or not v["linkedid"]:
        return None
    return Cdr(
        uniqueid=v["uniqueid"][:64],
        linkedid=v["linkedid"][:64],
        start=start,
        answer=_time(v["answer"]),
        end=_time(v["end"]),
        duration=_int(v["duration"]),
        billsec=_int(v["billsec"]),
        disposition=v["disposition"][:16] or "UNKNOWN",
        src=v["src"][:80],
        clid=v["clid"][:200],
        dst=v["dst"][:80],
        dcontext=v["dcontext"][:80],
        channel=v["channel"][:128],
        dstchannel=v["dstchannel"][:128],
        lastapp=v["lastapp"][:80],
        rec=v["rec"][:64],
    )


def endpoint_of(channel: str) -> str | None:
    m = _PJSIP_RE.match(channel)
    return m.group("endpoint") if m else None


def split_clid(clid: str) -> tuple[str | None, str | None]:
    """``"Name" <number>`` as Asterisk writes it (quotes in the name are
    escaped with a backslash)."""
    m = _CLID_RE.match(clid)
    if not m:
        return None, clid or None
    name = m.group("name").replace('\\"', '"').strip() or None
    return name, (m.group("number") or None)


# ------------------------------------------------------------- the file


class CdrReader:
    """New complete lines of an append-only file since the cursor stored in
    ``system_settings`` under ``key`` (the CDR file, the queue log)."""

    def __init__(self, path: Path = CDR_FILE, key: str = CURSOR_KEY) -> None:
        self.path = path
        self.key = key

    def read(self, db: Session, max_bytes: int = 8 * 1024 * 1024) -> list[str]:
        try:
            st = self.path.stat()
        except OSError:
            return []
        row = db.get(SystemSetting, self.key)
        cursor: dict[str, Any] = dict(row.value) if row and isinstance(row.value, dict) else {}
        pos = int(cursor.get("offset", 0))
        if cursor.get("inode") != st.st_ino or st.st_size < pos:
            pos = 0  # new or rotated file: read it from the start
        if st.st_size == pos:
            return []
        with self.path.open("rb") as f:
            f.seek(pos)
            data = f.read(max_bytes)
        end = data.rfind(b"\n") + 1
        value = {"inode": st.st_ino, "offset": pos + end}
        if row is None:
            db.add(SystemSetting(key=self.key, value=value))
        else:
            row.value = value
        db.flush()
        return data[:end].decode("utf-8", "replace").splitlines()


# ------------------------------------------------------------ folding


@dataclass
class Directory:
    """Endpoint names → extensions and trunks, loaded once per pass."""

    extensions: dict[str, Extension]
    trunks: dict[str, SipTrunk]
    routes: list[InboundRoute]

    @classmethod
    def load(cls, db: Session) -> Directory:
        return cls(
            {e.endpoint_name: e for e in db.scalars(select(Extension))},
            {TRUNK_PREFIX + t.slug: t for t in db.scalars(select(SipTrunk))},
            list(db.scalars(select(InboundRoute))),
        )

    def route_for(self, number: str) -> InboundRoute | None:
        digits = re.sub(r"\D", "", number or "")
        if not digits:
            return None
        for r in self.routes:
            canon = re.sub(r"\D", "", r.did_canonical or "")
            if canon and (digits == canon or digits.endswith(canon) or canon.endswith(digits)):
                return r
        return None


def fold(call: CallRecord, legs: list[CallLeg], d: Directory, now: datetime) -> None:
    """Derive the call's fields from all its legs (idempotent)."""
    legs = sorted(legs, key=lambda leg: (leg.start, leg.uniqueid))
    first = legs[0]
    callers = [endpoint_of(leg.channel) for leg in legs]
    called = [endpoint_of(leg.dstchannel) for leg in legs]
    first_caller = endpoint_of(first.channel)

    trunk = None
    if first_caller and first_caller in d.trunks:
        direction = "inbound"
        trunk = d.trunks[first_caller]
    else:
        out = next((e for e in called if e and e in d.trunks), None)
        if out:
            direction = "outbound"
            trunk = d.trunks[out]
        else:
            direction = "internal"
    call.direction = direction
    call.trunk_id = trunk.id if trunk else None

    from_ext = d.extensions.get(first_caller or "")
    to_ext = next((d.extensions[e] for e in called if e and e in d.extensions), None)
    call.from_extension_id = from_ext.id if from_ext else None
    call.to_extension_id = to_ext.id if to_ext else None
    name, number = split_clid(first.clid)
    call.from_name = (name or (from_ext.display_name if from_ext else None) or "")[:200] or None
    caller_number = number or first.src
    call.from_number = caller_number[:64] if caller_number else None
    call.to_number = first.dst[:64] if first.dst else None
    route = d.route_for(first.dst) if direction == "inbound" else None
    call.did = first.dst[:64] if direction == "inbound" and first.dst else None

    org = None
    for ext in (from_ext, to_ext):
        if ext is not None:
            org = ext.organization_id
            break
    if org is None and route is not None:
        org = route.organization_id
    if org is None:
        # Any phone on any leg (Local hops of groups and queues).
        for e in [*callers, *called]:
            if e and e in d.extensions:
                org = d.extensions[e].organization_id
                break
    call.organization_id = org

    answered = sorted(
        (
            leg
            for leg in legs
            if leg.disposition == "ANSWERED"
            and leg.answer is not None
            and endpoint_of(leg.dstchannel) is not None
        ),
        key=lambda leg: leg.answer or leg.start,
    )
    answered_ext = None
    for leg in answered:
        ep = endpoint_of(leg.dstchannel)
        if ep and ep in d.extensions:
            answered_ext = d.extensions[ep]
            break
    call.answered_extension_id = answered_ext.id if answered_ext else None

    apps = {leg.lastapp for leg in legs}
    dispositions = {leg.disposition for leg in legs}
    if answered:
        outcome = "answered"
    elif "VoiceMail" in apps:
        outcome = "voicemail"
    elif "Queue" in apps:
        outcome = "abandoned"
    elif "ANSWERED" in dispositions:
        outcome = "answered"  # a menu, a feature code, a page: the system answered
    elif "BUSY" in dispositions:
        outcome = "busy"
    elif "NO ANSWER" in dispositions:
        outcome = "missed"
    else:
        outcome = "failed"
    call.outcome = outcome

    call.started_at = first.start
    answers = [leg.answer for leg in (answered or legs) if leg.answer is not None]
    call.answered_at = min(answers) if answers and outcome != "missed" else None
    ends = [leg.end for leg in legs if leg.end is not None]
    call.ended_at = max(ends) if ends else None
    if call.answered_at and call.ended_at:
        call.ring_seconds = max(int((call.answered_at - call.started_at).total_seconds()), 0)
        call.talk_seconds = max(int((call.ended_at - call.answered_at).total_seconds()), 0)
    else:
        call.ring_seconds = (
            max(int((call.ended_at - call.started_at).total_seconds()), 0) if call.ended_at else 0
        )
        call.talk_seconds = 0
    call.leg_count = len(legs)
    call.recording_ref = next((leg.rec for leg in legs if leg.rec), None)
    call.is_final = call.ended_at is not None and now - call.ended_at >= SETTLE


def ingest(db: Session, lines: Iterable[str], now: datetime | None = None) -> int:
    """Store new legs and refold their calls; returns the number of legs."""
    now = now or utcnow()
    cdrs = [c for c in (parse_line(line) for line in lines) if c is not None]
    if not cdrs:
        return 0
    d = Directory.load(db)
    touched: dict[str, CallRecord] = {}
    for c in cdrs:
        call = touched.get(c.linkedid) or db.scalar(
            select(CallRecord).where(CallRecord.linkedid == c.linkedid)
        )
        if call is None:
            call = CallRecord(
                id=uuid.uuid4(),
                linkedid=c.linkedid,
                direction="internal",
                outcome="failed",
                started_at=c.start,
            )
            db.add(call)
            db.flush()
        touched[c.linkedid] = call
        exists = db.scalar(
            select(CallLeg.id).where(
                CallLeg.call_id == call.id,
                CallLeg.uniqueid == c.uniqueid,
                CallLeg.start == c.start,
                CallLeg.dstchannel == c.dstchannel,
            )
        )
        if exists:
            continue
        fields = {k: v for k, v in c.__dict__.items() if k != "linkedid"}
        db.add(CallLeg(id=uuid.uuid4(), call_id=call.id, **fields))
    db.flush()
    for call in touched.values():
        legs = list(db.scalars(select(CallLeg).where(CallLeg.call_id == call.id)))
        fold(call, legs, d, now)
    return len(cdrs)


def settle(db: Session, now: datetime | None = None) -> int:
    """Mark calls complete once their legs stopped arriving."""
    now = now or utcnow()
    calls = db.scalars(
        select(CallRecord).where(CallRecord.is_final.is_(False), CallRecord.ended_at < now - SETTLE)
    ).all()
    for c in calls:
        c.is_final = True
    return len(calls)


def retention_days(db: Session) -> int:
    row = db.get(SystemSetting, RETENTION_KEY)
    try:
        days = int(row.value) if row is not None else DEFAULT_RETENTION_DAYS
    except (TypeError, ValueError):
        days = DEFAULT_RETENTION_DAYS
    return min(max(days, 30), 3650)


def prune(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    cutoff = now - timedelta(days=retention_days(db))
    res = db.execute(delete(CallRecord).where(CallRecord.started_at < cutoff))
    return int(getattr(res, "rowcount", 0) or 0)


def process(db: Session, reader: CdrReader | None = None) -> int:
    """One worker pass: read, ingest, settle."""
    lines = (reader or CdrReader()).read(db)
    n = ingest(db, lines)
    settle(db)
    if n:
        log.info("Call history: %d CDRs read", n)
    return n
