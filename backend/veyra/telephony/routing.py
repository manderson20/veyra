# SPDX-License-Identifier: AGPL-3.0-or-later
"""Engine-neutral helpers for trunks and routing: slugs, DIDs, dial patterns
and time conditions. Shared by the API (validation) and the generator
(rendering), so both agree on what is valid. See docs/TRUNKS_ROUTING.md."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DID_ANY = "any"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
AUTH_MODES = ("registration", "ip")
TRANSPORTS = ("udp", "tcp", "tls")
CALLER_ID_HEADERS = ("pai", "rpid", "none")
DTMF_MODES = ("rfc4733", "inband", "info", "auto")
# Where a call can be sent (docs/VOICEMAIL_IVR.md §6): routes use the first
# three; IVR keys and fallbacks may also hang up.
DESTINATION_TYPES = ("extension", "voicemail", "ivr")
IVR_DESTINATION_TYPES = (*DESTINATION_TYPES, "hangup")
IVR_DIGITS = tuple("0123456789*#")
MAX_HOPS = 3
# IVR menus pointing at each other are cut off at this depth.
MAX_IVR_DEPTH = 8

_PIN_RE = re.compile(r"^[0-9]{4,10}$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")

_DID_RE = re.compile(r"^\+?[0-9]{2,20}$")
_PREFIX_RE = re.compile(r"^[0-9*#]{0,15}$")
_PREPEND_RE = re.compile(r"^\+?[0-9]{0,15}$")
_MATCH_RE = re.compile(r"^(?:[0-9*#+NXZ.!]|\[[0-9*#+\-NXZ]+\])+$")
_TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
_HOLIDAY_RE = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
_PATTERN_CHARS = set("NXZ.![")


def slugify(name: str) -> str:
    """Lower-case letters, digits and hyphens; at most 40 characters."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:40].strip("-")
    if not s or not s[0].isalnum():
        raise ValueError("the name must contain at least one letter or digit")
    return s


# ----------------------------------------------------------------- voicemail


def check_pin(value: str) -> str:
    v = value.strip()
    if not _PIN_RE.match(v):
        raise ValueError("4 to 10 digits")
    return v


def check_email(value: str) -> str:
    """One address, plain (no display name): it lands in voicemail.conf and
    in message headers."""
    v = value.strip()
    if len(v) > 254 or not _EMAIL_RE.match(v):
        raise ValueError("enter one email address such as name@example.org")
    return v


# ----------------------------------------------------------------- DIDs


def normalize_did(value: str) -> str:
    v = value.strip().lower()
    if v == DID_ANY:
        return DID_ANY
    v = re.sub(r"[\s().-]", "", v)
    if not _DID_RE.match(v):
        raise ValueError("digits only (a leading + is allowed), 2 to 20 characters, or 'any'")
    return v


def canonical_did(did: str) -> str:
    """Ten digits for a North American number however it was entered."""
    if did == DID_ANY:
        return DID_ANY
    digits = did.lstrip("+")
    if len(digits) == 11 and digits[0] == "1" and did in (digits, "+" + digits):
        return digits[1:]
    return did


def did_aliases(did: str) -> list[str]:
    """Other forms a carrier may send the same number in."""
    canon = canonical_did(did)
    if canon == DID_ANY or len(canon) != 10:
        return []
    forms = [canon, "1" + canon, "+1" + canon]
    return [f for f in forms if f != did]


# ----------------------------------------------------------------- patterns


def check_pattern(prefix: str, match: str, prepend: str) -> tuple[str, str, str]:
    prefix = prefix.strip()
    match = match.strip().upper()
    prepend = prepend.strip()
    if not _PREFIX_RE.match(prefix):
        raise ValueError("prefix: digits, * and # only, at most 15 characters")
    if not match or len(match) > 40 or not _MATCH_RE.match(match):
        raise ValueError(
            "match: digits and the pattern letters X, Z, N, a trailing . or !, "
            "and [ranges] only, at most 40 characters"
        )
    if "." in match[:-1] or "!" in match[:-1]:
        raise ValueError("match: . and ! may only end a pattern")
    if not _PREPEND_RE.match(prepend):
        raise ValueError("prepend: digits (and a leading +) only, at most 15 characters")
    if "+" in match and not match.startswith("+"):
        raise ValueError("match: + may only start a pattern")
    return prefix, match, prepend


def exten_for(prefix: str, match: str) -> str:
    """The dialplan extension (with ``_`` when it is a pattern)."""
    s = prefix + match
    return "_" + s if _PATTERN_CHARS & set(s) else s


# ----------------------------------------------------------------- time conditions


def check_timezone(name: str) -> str:
    name = name.strip()
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as e:
        raise ValueError("unknown time zone (use an IANA name such as America/Chicago)") from e
    return name


def check_ranges(ranges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, r in enumerate(ranges):
        days = [str(d).lower()[:3] for d in (r.get("days") or [])]
        if not days or any(d not in DAYS for d in days) or len(set(days)) != len(days):
            raise ValueError(f"range {i + 1}: pick one or more distinct weekdays")
        start, end = str(r.get("start") or ""), str(r.get("end") or "")
        if not _TIME_RE.match(start) or not _TIME_RE.match(end):
            raise ValueError(f"range {i + 1}: times are HH:MM (24-hour)")
        if start >= end:
            raise ValueError(f"range {i + 1}: the end must be after the start")
        out.append({"days": sorted(days, key=DAYS.index), "start": start, "end": end})
    return out


# Holidays (docs/ROUTING.md §time conditions; issue #113), one string each:
#   12-25                    every year on that date
#   12-21..01-02             every year, a range of dates (may cross New Year)
#   2026-11-27               once, on that date
#   2026-12-21..2027-01-02   once, a range of dates
#   4-thu-11, last-mon-05    every year, the nth (1-4) or last weekday of a month
_MD = r"(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
_YMD = r"(20[0-9]{2})-" + _MD
_YEARLY_RE = re.compile(rf"^{_MD}$")
_YEARLY_RANGE_RE = re.compile(rf"^{_MD}\.\.{_MD}$")
_DATE_RE = re.compile(rf"^{_YMD}$")
_DATE_RANGE_RE = re.compile(rf"^{_YMD}\.\.{_YMD}$")
_NTH_RE = re.compile(r"^(1|2|3|4|last)-(mon|tue|wed|thu|fri|sat|sun)-(0[1-9]|1[0-2])$")
MONTH_DAYS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
HOLIDAY_HELP = (
    "holidays are MM-DD (every year), MM-DD..MM-DD, YYYY-MM-DD (once), "
    "YYYY-MM-DD..YYYY-MM-DD, or N-ddd-MM / last-ddd-MM (for example 4-thu-11)"
)


def _md_ok(m: str, d: str) -> bool:
    return int(d) <= MONTH_DAYS[int(m) - 1]


def _ymd(y: str, m: str, d: str) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def _check_holiday(h: str) -> str:
    if (g := _YEARLY_RE.match(h)) and _md_ok(*g.groups()):
        return h
    if (g := _YEARLY_RANGE_RE.match(h)) and _md_ok(*g.groups()[:2]) and _md_ok(*g.groups()[2:]):
        first, last = h.split("..")
        return first if first == last else h
    if (g := _DATE_RE.match(h)) and _ymd(*g.groups()):
        return h
    if g := _DATE_RANGE_RE.match(h):
        start, end = _ymd(*g.groups()[:3]), _ymd(*g.groups()[3:])
        if start and end and start <= end:
            return h.split("..")[0] if start == end else h
        if start and end:
            raise ValueError(f"holiday {h}: the range ends before it starts")
    if g := _NTH_RE.match(h):
        if g.group(1) == "last" and g.group(3) == "02":
            raise ValueError(f"holiday {h}: the last weekday of February is not supported")
        return h
    raise ValueError(f"{HOLIDAY_HELP}; {h!r} is not one of them")


def check_holidays(holidays: list[str]) -> list[str]:
    out = []
    for h in holidays:
        h = _check_holiday(str(h).strip().lower())
        if h not in out:
            out.append(h)
    return sorted(out)


def holiday_matches(h: str, day: date) -> bool:
    """Whether the (checked) holiday ``h`` falls on ``day``."""
    md = day.strftime("%m-%d")
    if _YEARLY_RE.match(h):
        return md == h
    if _YEARLY_RANGE_RE.match(h):
        a, b = h.split("..")
        return a <= md <= b if a <= b else (md >= a or md <= b)
    if _DATE_RE.match(h):
        return day.isoformat() == h
    if _DATE_RANGE_RE.match(h):
        a, b = h.split("..")
        return a <= day.isoformat() <= b
    if g := _NTH_RE.match(h):
        n, wd, m = g.groups()
        if day.month != int(m) or DAYS[day.weekday()] != wd:
            return False
        if n == "last":
            return day.day > MONTH_DAYS[day.month - 1] - 7
        return (day.day - 1) // 7 + 1 == int(n)
    return False


def _span(d: int, end: int, last: int) -> str:
    if d == end:
        return str(d)
    return "*" if d == 1 and end == last else f"{d}-{end}"


def _mday_spans(a: tuple[int, int], b: tuple[int, int]) -> list[tuple[str, str]]:
    """(mdays, month) pairs for GotoIfTime covering month/day ``a`` to ``b``
    inclusive, crossing New Year when ``b`` comes before ``a``."""
    out = []
    m, d = a
    wrapped = b < a
    while True:
        last = MONTH_DAYS[m - 1]
        final = m == b[0] and not wrapped
        out.append((_span(d, b[1] if final else last, last), MONTHS[m - 1]))
        if final:
            return out
        m = m % 12 + 1
        if m == 1:
            wrapped = False
        d = 1


def holiday_apps(holidays: list[str], timezone: str, label: str) -> list[str]:
    """Dialplan applications that jump to ``label`` when today is one of the
    (checked) ``holidays`` in ``timezone``."""
    today = f"${{STRFTIME(${{EPOCH}},{timezone},%Y%m%d)}}"
    out = []
    for h in holidays:
        if _YEARLY_RE.match(h):
            month, day = h.split("-")
            out.append(f"GotoIfTime(*,*,{int(day)},{MONTHS[int(month) - 1]},{timezone}?{label})")
        elif _YEARLY_RANGE_RE.match(h):
            (m1, d1), (m2, d2) = ((int(x) for x in part.split("-")) for part in h.split(".."))
            for mdays, month in _mday_spans((m1, d1), (m2, d2)):
                out.append(f"GotoIfTime(*,*,{mdays},{month},{timezone}?{label})")
        elif _DATE_RE.match(h):
            out.append(f"GotoIf($[{today} = {h.replace('-', '')}]?{label})")
        elif _DATE_RANGE_RE.match(h):
            lo, hi = (x.replace("-", "") for x in h.split(".."))
            out.append(f"GotoIf($[{today} >= {lo} & {today} <= {hi}]?{label})")
        elif g := _NTH_RE.match(h):
            n, wd, m = g.groups()
            last = MONTH_DAYS[int(m) - 1]
            first = last - 6 if n == "last" else (int(n) - 1) * 7 + 1
            end = last if n == "last" else first + 6
            out.append(f"GotoIfTime(*,{wd},{first}-{end},{MONTHS[int(m) - 1]},{timezone}?{label})")
    return out


def is_open(
    ranges: list[dict[str, Any]], holidays: list[str], timezone: str, now: datetime | None = None
) -> bool:
    now = (now or datetime.now(ZoneInfo(timezone))).astimezone(ZoneInfo(timezone))
    if any(holiday_matches(h, now.date()) for h in holidays):
        return False
    day = DAYS[now.weekday()]
    hhmm = now.strftime("%H:%M")
    return any(day in r["days"] and r["start"] <= hhmm < r["end"] for r in ranges)


def day_spans(days: list[str]) -> list[str]:
    """Contiguous weekday spans as Asterisk writes them: mon-fri, sat."""
    idx = sorted(DAYS.index(d) for d in days)
    spans: list[list[int]] = []
    for i in idx:
        if spans and spans[-1][-1] == i - 1:
            spans[-1].append(i)
        else:
            spans.append([i])
    return [DAYS[s[0]] if len(s) == 1 else f"{DAYS[s[0]]}-{DAYS[s[-1]]}" for s in spans]


def gotoiftime_args(ranges: list[dict[str, Any]], timezone: str) -> list[str]:
    """Argument strings for GotoIfTime, one per open range and weekday span:
    ``times,days,mdays,months,timezone``. Holidays: :func:`holiday_apps`."""
    opened = []
    for r in ranges:
        for span in day_spans(r["days"]):
            opened.append(f"{r['start']}-{r['end']},{span},*,*,{timezone}")
    return opened
