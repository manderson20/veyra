# SPDX-License-Identifier: AGPL-3.0-or-later
"""Prompt audio conversion (pure Python) and the prompt folders."""

import io
import math
import os
import stat
import wave
from array import array

import pytest

from veyra.telephony import audio


def make_wav(seconds=1.0, rate=16000, channels=1, width=2, freq=440.0):
    n = int(seconds * rate)
    frames = array("h") if width == 2 else array("B")
    for i in range(n):
        v = math.sin(2 * math.pi * freq * i / rate)
        for _ in range(channels):
            frames.append(int(v * 12000) if width == 2 else 128 + int(v * 100))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(frames.tobytes())
    return buf.getvalue()


def _info(data):
    with wave.open(io.BytesIO(data), "rb") as w:
        return w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()


@pytest.mark.parametrize(
    ("rate", "channels", "width"),
    [(8000, 1, 2), (16000, 2, 2), (44100, 1, 1), (48000, 2, 1), (11025, 1, 2)],
)
def test_conversion_yields_8khz_16bit_mono_of_the_same_length(rate, channels, width):
    out, duration = audio.convert_wav(make_wav(1.5, rate, channels, width))
    ch, w, r, n = _info(out)
    assert (ch, w, r) == (1, 2, 8000) and abs(n - 12000) <= 1  # integer resampling
    assert duration == pytest.approx(1.5, abs=0.01)
    # already in the target format: unchanged content
    native = make_wav(1.0, 8000, 1, 2)
    again, _ = audio.convert_wav(native)
    assert _info(again) == (1, 2, 8000, 8000)
    assert again[44:] == native[44:]


def test_bad_uploads_are_refused_with_a_reason(monkeypatch):
    with pytest.raises(audio.AudioError, match="not a WAV"):
        audio.convert_wav(b"ID3 not a wav file at all")
    with pytest.raises(audio.AudioError, match="sample rate"):
        audio.convert_wav(make_wav(0.5, 96000))
    with pytest.raises(audio.AudioError, match="larger than"):
        audio.convert_wav(b"\0" * (audio.MAX_UPLOAD_BYTES + 1))
    with pytest.raises(audio.AudioError, match="shorter than"):
        audio.convert_wav(make_wav(0.05, 8000))
    monkeypatch.setattr(audio, "MAX_SECONDS", 1)
    with pytest.raises(audio.AudioError, match="longer than"):
        audio.convert_wav(make_wav(1.5, 8000))


def test_duration_and_atomic_write(tmp_path):
    data, _ = audio.convert_wav(make_wav(2.0))
    path = tmp_path / "welcome.wav"
    audio.write_atomic(path, data)
    assert path.read_bytes() == data and not list(tmp_path.glob(".*tmp"))
    assert audio.wav_duration(path) == pytest.approx(2.0, abs=0.01)
    assert audio.wav_duration(tmp_path / "missing.wav") == 0.0


def test_ensure_org_dirs_creates_group_writable_incoming_folders(tmp_path):
    base = tmp_path / "prompts"
    audio.ensure_org_dirs(base, ["brookfield", "beta"])
    for slug in ("brookfield", "beta"):
        inc = base / slug / audio.INCOMING
        assert inc.is_dir()
        assert stat.S_IMODE(os.stat(inc).st_mode) == 0o770  # group asterisk comes from the parent
    audio.ensure_org_dirs(base, ["brookfield"])  # idempotent
    # a file in the way is logged, not raised
    (base / "broken").write_text("x")
    audio.ensure_org_dirs(base, ["broken"])
