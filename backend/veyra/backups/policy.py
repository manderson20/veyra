# SPDX-License-Identifier: AGPL-3.0-or-later
"""The keep policy (docs/PRODUCTION_HARDENING.md §2.4) and the backup
settings document, as pure functions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

SETTINGS_KEY = "backup.settings"
STAMP_RE = re.compile(r"veyra-(\d{8})-(\d{6})")
DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "time": "02:30",  # local time of the server, HH:MM
    "keep": {"daily_days": 14, "weekly_weeks": 8, "upgrades": 3},
    "recordings": False,
    "recipients": [],  # age recipients (age1… or ssh-ed25519 …)
    "destinations": [],  # backups/destinations.py
    "ssh_public": "",  # Veyra's SSH key for SFTP destinations
    "ssh_private_ciphertext": None,
}
DESTINATION_KINDS = ("directory", "sftp", "s3")
# The copy directory of 0.23 to 0.27.43 becomes a folder destination.
LEGACY_COPY_DIR_ID = "copy-dir"


def settings_doc(value: dict[str, Any] | None) -> dict[str, Any]:
    v = dict(value or {})
    keep = dict(DEFAULTS["keep"])
    if isinstance(v.get("keep"), dict):
        for k in keep:
            if v["keep"].get(k) is not None:
                keep[k] = max(0, int(v["keep"][k]))
    recipients = [str(r).strip() for r in (v.get("recipients") or []) if str(r).strip()]
    return {
        "enabled": bool(v.get("enabled", DEFAULTS["enabled"])),
        "time": valid_time(str(v.get("time") or DEFAULTS["time"])),
        "keep": keep,
        "recordings": bool(v.get("recordings", False)),
        "recipients": recipients,
        "destinations": _destinations(v),
        "ssh_public": str(v.get("ssh_public") or ""),
        "ssh_private_ciphertext": v.get("ssh_private_ciphertext") or None,
    }


def _destinations(v: dict[str, Any]) -> list[dict[str, Any]]:
    out = [
        dict(d)
        for d in v.get("destinations") or []
        if isinstance(d, dict) and d.get("kind") in DESTINATION_KINDS and d.get("id")
    ]
    copy_dir = str(v.get("copy_dir") or "").strip()
    if copy_dir and not any(d["id"] == LEGACY_COPY_DIR_ID for d in out):
        out.insert(
            0,
            {
                "id": LEGACY_COPY_DIR_ID,
                "kind": "directory",
                "name": "Copy folder",
                "enabled": True,
                "keep": None,
                "path": copy_dir,
            },
        )
    return out


def valid_time(value: str) -> str:
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", value.strip())
    if not m:
        raise ValueError("The time must be HH:MM (24-hour).")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def valid_recipient(value: str) -> bool:
    v = value.strip()
    return bool(re.fullmatch(r"age1[0-9a-z]{58}", v)) or v.startswith(("ssh-ed25519 ", "ssh-rsa "))


@dataclass(frozen=True)
class Entry:
    name: str  # veyra-YYYYMMDD-HHMMSS[.tar.age]
    kind: str  # scheduled | manual | upgrade
    at: datetime

    @classmethod
    def parse(cls, name: str, kind: str) -> Entry | None:
        m = STAMP_RE.search(name)
        if not m:
            return None
        try:
            at = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            return None
        return cls(name, kind, at)


def stamp(now: datetime) -> str:
    return now.astimezone(UTC).strftime("veyra-%Y%m%d-%H%M%S")


def to_delete(entries: list[Entry], keep: dict[str, Any], now: datetime) -> list[Entry]:
    """Which backups the keep policy removes: every scheduled or manual
    backup of the last ``daily_days`` days stays; beyond that, the newest
    of each ISO week stays for ``weekly_weeks`` weeks; the last
    ``upgrades`` pre-upgrade backups stay. Nothing else."""
    daily = timedelta(days=int(keep.get("daily_days", 14)))
    weekly = timedelta(weeks=int(keep.get("weekly_weeks", 8)))
    upgrades = int(keep.get("upgrades", 3))
    kept: set[str] = set()
    regular = sorted((e for e in entries if e.kind != "upgrade"), key=lambda e: e.at, reverse=True)
    weeks_seen: set[tuple[int, int]] = set()
    for e in regular:
        age = now - e.at
        if age <= daily:
            kept.add(e.name)
            continue
        if age <= daily + weekly:
            iso = e.at.isocalendar()
            week = (iso[0], iso[1])
            if week not in weeks_seen:
                weeks_seen.add(week)
                kept.add(e.name)
    for e in sorted((e for e in entries if e.kind == "upgrade"), key=lambda e: e.at, reverse=True)[
        :upgrades
    ]:
        kept.add(e.name)
    return [e for e in entries if e.name not in kept]


def next_due(last: datetime | None, time_of_day: str, now: datetime, tz: Any) -> bool:
    """True when today's scheduled time has passed and no scheduled backup
    ran since then (``now`` and ``last`` are aware; ``tz`` is the server's
    zone for the time of day)."""
    local_now = now.astimezone(tz)
    hh, mm = (int(x) for x in time_of_day.split(":"))
    due_at = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if local_now < due_at:
        return False
    return last is None or last.astimezone(tz) < due_at
