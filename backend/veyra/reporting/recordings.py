# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call recordings after the call (docs/REPORTING.md §4.2-4.3).

Asterisk's MixMonitor writes ``<recordings>/incoming/<ref>--<policy>.wav``.
Once the call is complete the worker converts the file to Ogg Opus under
``<recordings>/<org>/<yyyy>/<mm>/<ref>.ogg``, records it in
``call_recordings`` and deletes the WAV; recordings past their retention are
deleted unless held."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.models import (
    CallRecord,
    CallRecording,
    ConferenceRoom,
    Organization,
    RecordingPolicy,
)
from veyra.core.models.base import utcnow
from veyra.telephony.audio import wav_duration

log = logging.getLogger("veyra.reporting")

INCOMING = "incoming"
# ConfBridge writes <conferences>/<org>--<room slug>-<epoch>.wav while the
# room is recorded (generator.DEFAULT_CONFERENCES_SUBDIR).
CONFERENCES = "conferences"
_CONF_RE = re.compile(
    r"^(?P<org>[0-9a-z-]{1,63})--(?P<slug>[0-9a-z-]{1,40})-(?P<ts>[0-9]{9,11})\.wav$"
)
# The file grows for as long as the room is up; untouched this long, it is done.
CONFERENCE_DONE_AFTER = timedelta(minutes=2)
_NAME_RE = re.compile(r"^(?P<ref>[0-9A-Za-z._-]{1,64})--(?P<policy>[0-9a-f-]{36})\.wav$")
# A WAV with no matching call is converted anyway after this long (the CDR
# was lost, or the call never reached a bridge).
ORPHAN_AFTER = timedelta(hours=24)
# MixMonitor writes a header even when nothing was bridged.
EMPTY_WAV_BYTES = 1024
DEFAULT_RETENTION_DAYS = 90


class ConversionError(Exception):
    pass


def convert(src: Path, dst: Path) -> None:
    """WAV → Ogg Opus, mono, about 16 kbit/s (≈ 7 MB per hour)."""
    binary = shutil.which("ffmpeg")
    if binary is None:
        raise ConversionError("ffmpeg is not installed")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part.ogg")
    try:
        res = subprocess.run(  # noqa: S603
            [
                binary,
                "-nostdin",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(src),
                "-ac",
                "1",
                "-c:a",
                "libopus",
                "-b:a",
                "16k",
                "-application",
                "voip",
                str(tmp),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise ConversionError(f"ffmpeg could not run: {e}") from e
    if res.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise ConversionError((res.stderr or "ffmpeg failed").strip()[:300])
    tmp.replace(dst)


def _org_slug(db: Session, org_id: uuid.UUID | None) -> str:
    org = db.get(Organization, org_id) if org_id else None
    return org.slug if org else "_unknown"


def process(
    db: Session,
    recordings_dir: Path,
    now: datetime | None = None,
    clock: float | None = None,
) -> int:
    """Convert finished recordings; returns how many were stored."""
    now = now or utcnow()
    clock = clock if clock is not None else time.time()
    incoming = recordings_dir / INCOMING
    try:
        files = sorted(incoming.glob("*.wav"))
    except OSError:
        return 0
    stored = 0
    for wav in files:
        m = _NAME_RE.match(wav.name)
        if not m:
            continue
        ref, policy_id = m.group("ref"), uuid.UUID(m.group("policy"))
        try:
            st = wav.stat()
        except OSError:
            continue
        call = db.scalar(select(CallRecord).where(CallRecord.recording_ref == ref))
        age = clock - st.st_mtime
        if call is not None and not call.is_final:
            continue  # still talking, or the last legs are on their way
        if call is None and age < ORPHAN_AFTER.total_seconds():
            continue
        if db.scalar(select(CallRecording.id).where(CallRecording.ref == ref)):
            wav.unlink(missing_ok=True)  # converted before, the delete failed
            continue
        if st.st_size <= EMPTY_WAV_BYTES:
            log.info("Recording %s has no audio; discarded", ref)
            wav.unlink(missing_ok=True)
            continue
        policy = db.get(RecordingPolicy, policy_id)
        org_id = (call.organization_id if call else None) or (
            policy.organization_id if policy else None
        )
        started = call.started_at if call else now
        rel = Path(_org_slug(db, org_id)) / f"{started:%Y}" / f"{started:%m}" / f"{ref}.ogg"
        dst = recordings_dir / rel
        duration = round(wav_duration(wav))  # 0 when the header is damaged
        try:
            convert(wav, dst)
        except ConversionError as e:
            log.warning("Recording %s not converted: %s", ref, e)
            continue
        retention = policy.retention_days if policy else DEFAULT_RETENTION_DAYS
        db.add(
            CallRecording(
                id=uuid.uuid4(),
                ref=ref,
                organization_id=org_id,
                call_id=call.id if call else None,
                policy_id=policy.id if policy else None,
                path=str(rel),
                format="ogg",
                size_bytes=dst.stat().st_size,
                duration_seconds=duration,
                created_at=now,
                delete_after=now + timedelta(days=retention),
            )
        )
        db.flush()
        wav.unlink(missing_ok=True)
        stored += 1
    if stored:
        log.info("Stored %d call recordings", stored)
    return stored


def process_conferences(
    db: Session,
    recordings_dir: Path,
    now: datetime | None = None,
    clock: float | None = None,
) -> int:
    """Store finished conference recordings with the call recordings (#133)."""
    now = now or utcnow()
    clock = clock if clock is not None else time.time()
    try:
        files = sorted((recordings_dir / CONFERENCES).glob("*.wav"))
    except OSError:
        return 0
    stored = 0
    for wav in files:
        m = _CONF_RE.match(wav.name)
        if not m:
            continue
        try:
            st = wav.stat()
        except OSError:
            continue
        if clock - st.st_mtime < CONFERENCE_DONE_AFTER.total_seconds():
            continue
        ref = f"conf-{m.group('ts')}-{m.group('slug')}"[:64]
        if db.scalar(select(CallRecording.id).where(CallRecording.ref == ref)):
            wav.unlink(missing_ok=True)
            continue
        if st.st_size <= EMPTY_WAV_BYTES:
            wav.unlink(missing_ok=True)
            continue
        room = db.scalar(select(ConferenceRoom).where(ConferenceRoom.slug == m.group("slug")))
        org_id = room.organization_id if room else None
        started = datetime.fromtimestamp(int(m.group("ts")), tz=now.tzinfo)
        rel = Path(_org_slug(db, org_id)) / f"{started:%Y}" / f"{started:%m}" / f"{ref}.ogg"
        dst = recordings_dir / rel
        duration = round(wav_duration(wav))
        try:
            convert(wav, dst)
        except ConversionError as e:
            log.warning("Conference recording %s not converted: %s", ref, e)
            continue
        db.add(
            CallRecording(
                id=uuid.uuid4(),
                ref=ref,
                organization_id=org_id,
                conference_room_id=room.id if room else None,
                path=str(rel),
                format="ogg",
                size_bytes=dst.stat().st_size,
                duration_seconds=duration,
                created_at=now,
                delete_after=now + timedelta(days=DEFAULT_RETENTION_DAYS),
            )
        )
        db.flush()
        wav.unlink(missing_ok=True)
        stored += 1
    if stored:
        log.info("Stored %d conference recordings", stored)
    return stored


def conference_started(ref: str) -> datetime | None:
    """The start time a conference recording's ref carries."""
    m = re.match(r"^conf-([0-9]{9,11})-", ref)
    return datetime.fromtimestamp(int(m.group(1)), tz=UTC) if m else None


def prune(db: Session, recordings_dir: Path, now: datetime | None = None) -> int:
    """Delete recordings past their retention date unless held."""
    now = now or utcnow()
    rows = db.scalars(
        select(CallRecording).where(
            CallRecording.deleted_at.is_(None),
            CallRecording.held.is_(False),
            CallRecording.delete_after < now,
        )
    ).all()
    for r in rows:
        delete_file(recordings_dir, r)
        r.deleted_at = now
        r.deleted_by = "retention"
    return len(rows)


def delete_file(recordings_dir: Path, rec: CallRecording) -> None:
    path = (recordings_dir / rec.path).resolve()
    if recordings_dir.resolve() in path.parents:
        path.unlink(missing_ok=True)


def file_of(recordings_dir: Path, rec: CallRecording) -> Path | None:
    path = (recordings_dir / rec.path).resolve()
    if recordings_dir.resolve() not in path.parents or not path.is_file():
        return None
    return path
