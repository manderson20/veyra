# SPDX-License-Identifier: AGPL-3.0-or-later
"""Prompt audio: accept a WAV upload and store it the way Asterisk plays it
without transcoding (8 kHz, 16-bit, mono, PCM). Standard library only:
``wave`` reads and writes the container, the conversion (stereo mix-down,
linear-interpolation resampling) is plain integer arithmetic
(docs/VOICEMAIL_IVR.md §4)."""

from __future__ import annotations

import io
import logging
import os
import sys
import wave
from array import array
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger("veyra.audio")

TARGET_RATE = 8000
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_SECONDS = 300
MAX_INPUT_RATE = 48000
# Where ``*95`` recordings land inside an organization's prompt folder.
INCOMING = "incoming"
ACCEPTED = (
    "a WAV file (PCM, 8 or 16 bit, mono or stereo, up to 48 kHz), "
    f"at most {MAX_UPLOAD_BYTES // (1024 * 1024)} MB and {MAX_SECONDS // 60} minutes"
)


class AudioError(ValueError):
    pass


def _samples(frames: bytes, width: int) -> array:
    """Signed 16-bit samples from PCM frames."""
    if width == 2:
        out = array("h")
        out.frombytes(frames)
        if sys.byteorder == "big":
            out.byteswap()
        return out
    unsigned = array("B")
    unsigned.frombytes(frames)
    return array("h", [(b - 128) << 8 for b in unsigned])


def _mono(samples: array, channels: int) -> array:
    if channels == 1:
        return samples
    return array("h", [(samples[i] + samples[i + 1]) // 2 for i in range(0, len(samples), 2)])


def _resample(samples: array, rate: int) -> array:
    """Linear interpolation to TARGET_RATE."""
    if rate == TARGET_RATE:
        return samples
    n_in = len(samples)
    if n_in < 2:
        return array("h")
    n_out = (n_in * TARGET_RATE) // rate
    out = array("h", bytes(2 * n_out))
    last = n_in - 1
    for i in range(n_out):
        pos = (i * rate) // TARGET_RATE
        frac = (i * rate) % TARGET_RATE  # out of TARGET_RATE
        a = samples[pos]
        b = samples[pos + 1] if pos < last else a
        out[i] = a + ((b - a) * frac) // TARGET_RATE
    return out


def convert_wav(data: bytes) -> tuple[bytes, float]:
    """The upload as 8 kHz 16-bit mono WAV bytes and its duration in seconds.
    Raises :class:`AudioError` with a message that names the accepted format."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise AudioError(f"the file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            channels, width, rate, n_frames = (
                w.getnchannels(),
                w.getsampwidth(),
                w.getframerate(),
                w.getnframes(),
            )
            if w.getcomptype() != "NONE":
                raise AudioError("compressed WAV is not supported")
            if channels not in (1, 2) or width not in (1, 2):
                raise AudioError("only 8 or 16-bit PCM, mono or stereo, is supported")
            if not 8000 <= rate <= MAX_INPUT_RATE:
                raise AudioError(
                    f"the sample rate must be between 8 and {MAX_INPUT_RATE // 1000} kHz"
                )
            if n_frames > rate * MAX_SECONDS:
                raise AudioError(f"the recording is longer than {MAX_SECONDS // 60} minutes")
            frames = w.readframes(n_frames)
    except AudioError:
        raise
    except (wave.Error, EOFError, ValueError) as e:
        raise AudioError(f"not a WAV file ({e})") from e
    samples = _resample(_mono(_samples(frames, width), channels), rate)
    if len(samples) < TARGET_RATE // 10:
        raise AudioError("the recording is shorter than a tenth of a second")
    if sys.byteorder == "big":
        samples = array("h", samples)
        samples.byteswap()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(TARGET_RATE)
        out.writeframes(samples.tobytes())
    return buf.getvalue(), len(samples) / TARGET_RATE


def wav_duration(path: Path) -> float:
    """Seconds of audio in a stored WAV file (0 when it cannot be read)."""
    try:
        with wave.open(str(path), "rb") as w:
            rate = w.getframerate() or TARGET_RATE
            return w.getnframes() / rate
    except (OSError, wave.Error, EOFError):
        return 0.0


def write_atomic(path: Path, data: bytes) -> None:
    """Write so that Asterisk never sees a half-written prompt."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def ensure_org_dirs(base: Path, slugs: Iterable[str]) -> None:
    """Create ``<base>/<slug>`` and ``<base>/<slug>/incoming`` so uploads and
    phone recordings have somewhere to land. The incoming folder is made
    group-writable: Asterisk (group ``asterisk`` on the installation, which
    the folder inherits from the setgid ``prompts`` directory) records into
    it and Veyra adopts or deletes the files. No setgid bit is set here: the
    service units run with ``RestrictSUIDSGID`` and would refuse it, and the
    folder does not need it. Failures are logged, never raised: the worker
    calls this every minute and the API before listing recordings."""
    for slug in slugs:
        incoming = base / slug / INCOMING
        try:
            incoming.mkdir(parents=True, exist_ok=True)
            if (incoming.stat().st_mode & 0o777) != 0o770:
                os.chmod(incoming, 0o770)  # noqa: S103 - shared with Asterisk by design
        except OSError as e:
            log.warning("Prompt directory %s not ready: %s", incoming, e)
