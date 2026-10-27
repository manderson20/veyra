# SPDX-License-Identifier: AGPL-3.0-or-later
"""Calendar subscriptions (docs/PAGING_RECORDINGS.md §4.1): fetch an iCal feed,
expand its events (including recurring rules) for a window, cache them."""

from __future__ import annotations

import http.client
import ipaddress
import logging
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from veyra.core.models import Calendar, CalendarEvent
from veyra.core.models.base import utcnow
from veyra.core.security.crypto import DecryptionError, InstallationKey

log = logging.getLogger("veyra.bells")

WINDOW = timedelta(hours=48)
LOOKBACK = timedelta(hours=2)
MAX_BYTES = 5 * 1024 * 1024
MAX_EVENTS = 2000
TIMEOUT = 20


class CalendarError(ValueError):
    pass


@dataclass(frozen=True)
class Occurrence:
    uid: str
    summary: str
    starts_at: datetime
    ends_at: datetime | None
    all_day: bool


def url_purpose(calendar_id: Any) -> str:
    return f"calendar.url:{calendar_id}"


def display_url(url: str) -> str:
    """Scheme and host only: the path of a Google secret address is the secret."""
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/…"


def check_url(url: str) -> str:
    url = url.strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https", "webcal") or not parts.netloc:
        raise CalendarError("enter an http(s) or webcal address")
    if parts.scheme == "webcal":
        url = "https://" + url.split("://", 1)[1]
    return url


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    """Connects only to a public address, checked at connect time: the name
    is resolved once and that address is used (no DNS rebinding), and every
    redirect opens a new connection, so it is checked too."""

    def connect(self) -> None:
        try:
            infos = socket.getaddrinfo(self.host, self.port, proto=socket.IPPROTO_TCP)
        except OSError as e:
            raise CalendarError(f"the calendar's host {self.host} is not known") from e
        addrs = [ipaddress.ip_address(i[4][0]) for i in infos]
        if not addrs or not all(a.is_global for a in addrs):
            raise CalendarError("only calendars on the internet can be used")
        sock = socket.create_connection((str(addrs[0]), self.port), self.timeout)
        self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)


class _PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(_PublicHTTPSConnection, req)


class _NoHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> Any:
        raise CalendarError("the calendar redirected to an address without https")


def fetch(url: str, *, public_only: bool = False) -> bytes:
    """``public_only``: for addresses users give (not administrators): https
    to public hosts only, redirects included."""
    # The scheme was restricted to http(s) by check_url when the calendar was saved.
    req = urllib.request.Request(url, headers={"User-Agent": "Veyra calendar poller"})  # noqa: S310
    opener = (
        urllib.request.build_opener(_PublicHTTPSHandler(), _NoHTTPHandler())
        if public_only
        else urllib.request.build_opener()
    )
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            data = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise CalendarError(f"the calendar server answered {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CalendarError(f"the calendar could not be fetched: {e}") from e
    if len(data) > MAX_BYTES:
        raise CalendarError("the calendar feed is larger than 5 MB")
    return data


def _to_datetime(value: Any, tz: ZoneInfo) -> tuple[datetime, bool]:
    """A DTSTART/DTEND value as an aware datetime; all-day dates at local midnight."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=tz)
        return value.astimezone(UTC), False
    if isinstance(value, date):
        return datetime.combine(value, time(0, 0), tzinfo=tz).astimezone(UTC), True
    raise CalendarError(f"unexpected date value {value!r}")


def expand(
    data: bytes, *, start: datetime, end: datetime, default_tz: str | None
) -> list[Occurrence]:
    """Occurrences between ``start`` and ``end`` (UTC), recurring rules expanded."""
    from dateutil.rrule import rruleset, rrulestr
    from icalendar import Calendar as ICal

    try:
        cal = ICal.from_ical(data)
    except Exception as e:  # icalendar raises ValueError subclasses and others
        raise CalendarError(f"not a valid iCalendar feed ({type(e).__name__})") from e
    try:
        tz = ZoneInfo(default_tz or str(cal.get("X-WR-TIMEZONE") or "UTC"))
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    out: list[Occurrence] = []
    exceptions: set[tuple[str, datetime]] = set()
    components = [c for c in cal.walk() if c.name == "VEVENT"]
    for comp in components:
        rid = comp.get("RECURRENCE-ID")
        if rid is not None:
            when, _ = _to_datetime(rid.dt, tz)
            exceptions.add((str(comp.get("UID") or ""), when))
    for comp in components:
        uid = str(comp.get("UID") or "")
        summary = str(comp.get("SUMMARY") or "").strip()[:200]
        dtstart = comp.get("DTSTART")
        if dtstart is None:
            continue
        starts, all_day = _to_datetime(dtstart.dt, tz)
        dtend = comp.get("DTEND")
        duration = None
        if dtend is not None:
            ends, _ = _to_datetime(dtend.dt, tz)
            duration = ends - starts
        elif comp.get("DURATION") is not None:
            duration = comp.get("DURATION").dt
        rrule = comp.get("RRULE")
        if rrule is None:
            if comp.get("RECURRENCE-ID") is None and (uid, starts) in exceptions:
                continue
            if start - LOOKBACK <= starts <= end:
                out.append(
                    Occurrence(
                        uid, summary, starts, starts + duration if duration else None, all_day
                    )
                )
            continue
        rules = rruleset()
        local_start = starts.astimezone(tz)
        try:
            rule_text = rrule.to_ical().decode()
            rules.rrule(rrulestr(rule_text, dtstart=local_start))
        except (ValueError, TypeError) as e:
            log.warning("calendar event %s: unusable RRULE (%s)", uid, e)
            continue
        for ex in (
            comp.get("EXDATE", []) if isinstance(comp.get("EXDATE"), list) else [comp.get("EXDATE")]
        ):
            if ex is None:
                continue
            for d in ex.dts:
                when, _ = _to_datetime(d.dt, tz)
                rules.exdate(when.astimezone(tz))
        for when in rules.between((start - LOOKBACK).astimezone(tz), end.astimezone(tz), inc=True):
            when_utc = (
                when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=tz).astimezone(UTC)
            )
            if (uid, when_utc) in exceptions:
                continue
            out.append(
                Occurrence(
                    uid, summary, when_utc, when_utc + duration if duration else None, all_day
                )
            )
            if len(out) > MAX_EVENTS:
                raise CalendarError("the calendar has more than 2000 events in the next two days")
    out.sort(key=lambda o: (o.starts_at, o.uid))
    return out


def poll(
    db: Session, calendar: Calendar, key: InstallationKey | None, *, now: datetime | None = None
) -> int:
    """Fetch, expand and cache one calendar; records the outcome on the row."""
    now = now or utcnow()
    try:
        if key is None:
            raise CalendarError("the installation key is not available")
        try:
            url = key.decrypt(calendar.url_ciphertext, url_purpose(calendar.id))
        except DecryptionError as e:
            raise CalendarError(f"the calendar address cannot be read: {e}") from e
        occurrences = expand(fetch(url), start=now, end=now + WINDOW, default_tz=calendar.timezone)
    except CalendarError as e:
        calendar.last_polled_at = now
        calendar.last_status = "failed"
        calendar.last_error = str(e)[:2000]
        db.commit()
        log.warning("calendar %s: %s", calendar.name, e)
        return 0
    db.execute(delete(CalendarEvent).where(CalendarEvent.calendar_id == calendar.id))
    seen: set[tuple[str, datetime]] = set()
    for o in occurrences:
        if (o.uid, o.starts_at) in seen:
            continue
        seen.add((o.uid, o.starts_at))
        db.add(
            CalendarEvent(
                calendar_id=calendar.id,
                uid=o.uid[:255],
                summary=o.summary,
                starts_at=o.starts_at,
                ends_at=o.ends_at,
                all_day=o.all_day,
            )
        )
    calendar.last_polled_at = now
    calendar.last_status = "ok"
    calendar.last_error = None
    calendar.event_count = len(seen)
    db.commit()
    return len(seen)


def due_calendars(db: Session, now: datetime | None = None) -> list[Calendar]:
    now = now or utcnow()
    out = []
    for c in db.scalars(select(Calendar).where(Calendar.is_enabled.is_(True))):
        if c.last_polled_at is None or now - c.last_polled_at >= timedelta(
            minutes=max(1, c.poll_minutes)
        ):
            out.append(c)
    return out
