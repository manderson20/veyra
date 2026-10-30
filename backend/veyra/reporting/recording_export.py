# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recording export (docs/REPORTING.md §4): a ZIP of recordings with readable
names and a spreadsheet of the calls, streamed without touching the disk, so
decrypted audio is never written anywhere."""

from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
import zipfile
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MANIFEST = "recordings.csv"
MANIFEST_COLUMNS = (
    "file",
    "status",
    "started_at",
    "answered_at",
    "ended_at",
    "direction",
    "outcome",
    "from_number",
    "from_name",
    "to_number",
    "did",
    "answered_by",
    "trunk",
    "queue",
    "ring_group",
    "ring_seconds",
    "talk_seconds",
    "recording_seconds",
    "conference",
    "policy",
    "organization",
    "held",
    "delete_after",
    "recording_ref",
    "recording_id",
    "call_id",
)
TRANSCODE_TIMEOUT_SECONDS = 300


def _part(value: str | None, fallback: str) -> str:
    """One piece of a file name: nothing a caller's ID can use to escape."""
    cleaned = re.sub(r"[^0-9A-Za-z+]+", "-", value or "").strip("-")[:40]
    return cleaned or fallback


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def file_stem(
    started: datetime | None,
    tz: ZoneInfo,
    *,
    direction: str | None,
    from_number: str | None,
    to_number: str | None,
    conference: str | None,
    ref: str,
) -> str:
    """``2026-10-30_1432_inbound_5551234_to_1001``, in the organization's time."""
    when = started.astimezone(tz).strftime("%Y-%m-%d_%H%M") if started else "unknown-time"
    if conference:
        return f"{when}_conference_{_part(conference, 'room')}"
    if direction is None and from_number is None and to_number is None:
        return f"{when}_{_part(ref, 'recording')}"
    return (
        f"{when}_{_part(direction, 'call')}_"
        f"{_part(from_number, 'unknown')}_to_{_part(to_number, 'unknown')}"
    )


def unique_name(stem: str, ext: str, taken: set[str]) -> str:
    name, n = f"{stem}.{ext}", 1
    while name in taken:
        n += 1
        name = f"{stem}_{n}.{ext}"
    taken.add(name)
    return name


def safe_cell(value: Any) -> str:
    """A spreadsheet cell; text a caller controls (their name) cannot become a
    formula. Telephone numbers keep their leading +."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not re.fullmatch(r"\+[0-9]+", text):
        return "'" + text
    return text


def to_mp3(ogg: bytes) -> bytes | None:
    """The audio as MP3, which every player opens; None when it cannot be made.
    Through pipes, and at low priority: calls come first on this server."""
    ffmpeg, nice = shutil.which("ffmpeg"), shutil.which("nice")
    if ffmpeg is None:
        return None
    prefix = [nice, "-n", "15"] if nice else []
    try:
        res = subprocess.run(  # noqa: S603
            [
                *prefix,
                ffmpeg,
                "-nostdin",
                "-loglevel",
                "error",
                "-threads",
                "1",
                "-i",
                "pipe:0",
                "-ac",
                "1",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "32k",
                "-f",
                "mp3",
                "pipe:1",
            ],
            input=ogg,
            capture_output=True,
            timeout=TRANSCODE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 and res.stdout else None


class _Sink(io.RawIOBase):
    """Where ZipFile writes; the generator takes what has collected."""

    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def writable(self) -> bool:
        return True

    def write(self, b: Any) -> int:
        self.chunks.append(bytes(b))
        return len(b)

    def take(self) -> bytes:
        out = b"".join(self.chunks)
        self.chunks.clear()
        return out


def stream_zip(
    items: Iterable[tuple[dict[str, Any], Any]],
    read_audio: Callable[[Any], bytes | None],
    mp3: bool,
) -> Iterator[bytes]:
    """The ZIP, one recording at a time, with the spreadsheet last so that it
    can say which files could not be read. Audio is already compressed: stored."""
    sink = _Sink()
    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
        for row, rec in items:
            data = read_audio(rec)
            name = row["file"]
            if data is None:
                row["file"], row["status"] = "", "missing or unreadable"
            else:
                if mp3:
                    converted = to_mp3(data)
                    if converted is None:
                        # Keep the audio rather than lose it from a records request.
                        name = name.rsplit(".", 1)[0] + ".ogg"
                        row["file"], row["status"] = name, "ogg: could not convert to mp3"
                    else:
                        data = converted
                archive.writestr(name, data)
            rows.append(row)
            yield sink.take()
        text = io.StringIO()
        writer = csv.writer(text)
        writer.writerow(MANIFEST_COLUMNS)
        for row in rows:
            writer.writerow(safe_cell(row.get(c)) for c in MANIFEST_COLUMNS)
        # Excel reads UTF-8 only with the byte order mark.
        archive.writestr(MANIFEST, "﻿" + text.getvalue())
    yield sink.take()
