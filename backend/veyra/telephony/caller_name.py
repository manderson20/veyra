# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caller name lookup over HTTP (issue #392; FreePBX CID Superfecta,
FreeSWITCH cidlookup). Off by default.

A platform administrator sets one lookup service (an https address with
``{number}`` in it, optionally a header such as an API key, and the JSON
field that holds the name). Inbound routes that ask for it look the caller's
name up before ringing: the dialplan calls the API on 127.0.0.1
(``/internal/caller-name``) with a token, and the API asks the service,
with a short timeout and a cache, and answers with a plain name or nothing.

The caller's number leaves the server only for the service set here, which
is why it is a platform setting and off until someone turns it on.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from veyra.core.models import SystemSetting

KEY = "telephony.caller_name"
HEADER_PURPOSE = "telephony.caller_name.header"
MAX_NAME = 40
MAX_BYTES = 64 * 1024
CACHE_SIZE = 5000
_NAME_RE = re.compile(r"[^A-Za-z0-9 .'&/-]+")


class CallerNameSettings(BaseModel):
    enabled: bool = False
    # https://…{number}…; the number is URL-encoded (digits, maybe a +).
    url: str | None = Field(None, max_length=1000)
    header_name: str | None = Field(None, max_length=100, pattern=r"^[A-Za-z0-9-]+$")
    # Sealed with the installation key; never returned by the API.
    header_value_ciphertext: str | None = None
    # A dotted path into a JSON answer ("name", "data.caller.name"); none:
    # the answer is the name as plain text.
    json_field: str | None = Field(None, max_length=200, pattern=r"^[A-Za-z0-9_.]+$")
    timeout_ms: int = Field(1500, ge=200, le=2500)
    cache_minutes: int = Field(1440, ge=0, le=43200)
    # Shared with the dialplan, so only Asterisk on this server asks.
    token: str | None = None


def load(db: Session) -> CallerNameSettings:
    row = db.get(SystemSetting, KEY)
    if row is None or not isinstance(row.value, dict):
        return CallerNameSettings()
    return CallerNameSettings.model_validate(row.value)


def save(db: Session, settings: CallerNameSettings, updated_by: Any = None) -> None:
    if settings.enabled and not settings.token:
        settings.token = secrets.token_urlsafe(24)
    value = settings.model_dump(mode="json")
    row = db.get(SystemSetting, KEY)
    if row is None:
        db.add(SystemSetting(key=KEY, value=value, updated_by=updated_by))
    else:
        row.value = value
        row.updated_by = updated_by
    db.flush()
    clear_cache()


def check_url(url: str) -> str:
    url = url.strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("the address must start with https://")
    if "{number}" not in url:
        raise ValueError("put {number} where the caller's number goes")
    if parts.username or parts.password:
        raise ValueError("put credentials in the header, not in the address")
    return url


def clean(name: str) -> str:
    """What may be shown as a caller name: no quotes, commas, colons or
    control characters (it goes into the dialplan), at most 40 characters."""
    out = _NAME_RE.sub(" ", name).strip()
    return re.sub(r"\s+", " ", out)[:MAX_NAME].strip()


def _extract(body: bytes, json_field: str | None) -> str:
    text = body.decode("utf-8", "replace")
    if not json_field:
        return text.strip().splitlines()[0] if text.strip() else ""
    try:
        value: Any = json.loads(text)
    except ValueError:
        return ""
    for part in json_field.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return ""
    return value if isinstance(value, str) else ""


_cache: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _cached(number: str, now: float) -> str | None:
    with _lock:
        hit = _cache.get(number)
        if hit is None:
            return None
        if hit[1] < now:
            _cache.pop(number, None)
            return None
        return hit[0]


def _remember(number: str, name: str, until: float) -> None:
    with _lock:
        if len(_cache) >= CACHE_SIZE:
            # The oldest expiry goes first.
            for key, _ in sorted(_cache.items(), key=lambda kv: kv[1][1])[: CACHE_SIZE // 10]:
                _cache.pop(key, None)
        _cache[number] = (name, until)


def fetch(url: str, headers: dict[str, str], timeout: float) -> bytes:
    """GET over https to a public host only (as calendar feeds are fetched)."""
    from veyra.bells.calendars import _NoHTTPHandler, _PublicHTTPSHandler

    req = urllib.request.Request(  # noqa: S310 (https only: check_url)
        url, headers={"User-Agent": "Veyra caller name lookup", **headers}
    )
    opener = urllib.request.build_opener(_PublicHTTPSHandler(), _NoHTTPHandler())
    with opener.open(req, timeout=timeout) as resp:
        data: bytes = resp.read(MAX_BYTES + 1)
    return data[:MAX_BYTES]


def lookup(
    settings: CallerNameSettings,
    number: str,
    header_value: str | None = None,
    *,
    now: float | None = None,
    fetcher: Any = None,
) -> str:
    """The caller's name, or "" (unknown, the service failed or timed out)."""
    digits = re.sub(r"[^0-9+]", "", number or "")
    if not settings.enabled or not settings.url or not re.fullmatch(r"\+?[0-9]{3,20}", digits):
        return ""
    now = time.time() if now is None else now
    cached = _cached(digits, now)
    if cached is not None:
        return cached
    url = settings.url.replace("{number}", urllib.parse.quote(digits, safe=""))
    headers = {}
    if settings.header_name and header_value:
        headers[settings.header_name] = header_value
    try:
        body = (fetcher or fetch)(url, headers, settings.timeout_ms / 1000)
        name = clean(_extract(body, settings.json_field))
    except Exception:
        # Not cached: the next call tries again.
        return ""
    # A name the service does not know is cached too, for less time.
    ttl = settings.cache_minutes * 60 if name else min(settings.cache_minutes * 60, 3600)
    if ttl:
        _remember(digits, name, now + ttl)
    return name
