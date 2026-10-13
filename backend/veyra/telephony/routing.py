# SPDX-License-Identifier: AGPL-3.0-or-later
"""Engine-neutral helpers for trunks and routing: slugs, DIDs, dial patterns
and time conditions. Shared by the API (validation) and the generator
(rendering), so both agree on what is valid. See docs/TRUNKS_ROUTING.md."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DID_ANY = "any"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
AUTH_MODES = ("registration", "ip")
TRANSPORTS = ("udp", "tcp", "tls")
CALLER_ID_HEADERS = ("pai", "rpid", "none")
DTMF_MODES = ("rfc4733", "inband", "info", "auto")
DESTINATION_TYPES = ("extension",)
MAX_HOPS = 3

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


def check_holidays(holidays: list[str]) -> list[str]:
    out = []
    for h in holidays:
        h = str(h).strip()
        if not _HOLIDAY_RE.match(h):
            raise ValueError("holidays are MM-DD dates")
        if h not in out:
            out.append(h)
    return sorted(out)


def is_open(
    ranges: list[dict[str, Any]], holidays: list[str], timezone: str, now: datetime | None = None
) -> bool:
    now = (now or datetime.now(ZoneInfo(timezone))).astimezone(ZoneInfo(timezone))
    if now.strftime("%m-%d") in holidays:
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


def gotoiftime_args(
    ranges: list[dict[str, Any]], holidays: list[str], timezone: str
) -> tuple[list[str], list[str]]:
    """Argument strings for GotoIfTime: (closed-on-holiday checks, open checks).
    Each is ``times,days,mdays,months,timezone``."""
    closed = []
    for h in holidays:
        month, day = h.split("-")
        closed.append(f"*,*,{int(day)},{MONTHS[int(month) - 1]},{timezone}")
    opened = []
    for r in ranges:
        for span in day_spans(r["days"]):
            opened.append(f"{r['start']}-{r['end']},{span},*,*,{timezone}")
    return closed, opened
