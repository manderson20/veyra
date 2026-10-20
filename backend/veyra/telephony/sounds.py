# SPDX-License-Identifier: AGPL-3.0-or-later
"""Built-in sounds (docs/PAGING_RECORDINGS.md §3.1; issue #114).

Bells, chimes and attention tones synthesized here, deterministically, so
Veyra ships audio it owns outright: no recordings, no licence terms. Each is
8 kHz mono 16-bit WAV, the library's format, so it can be added to an
organization's audio library as is. The tones stay below 3.5 kHz (the
telephone band at 8 kHz sampling).

SIP paging is not a life-safety notification system; the alert tones are
for drills and attention, not a replacement for a fire alarm.
"""

from __future__ import annotations

import io
import math
import struct
import wave
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

RATE = 8000
PEAK = 0.7  # of full scale, leaving headroom for phone codecs

Samples = list[float]


def _silence(seconds: float) -> Samples:
    return [0.0] * int(seconds * RATE)


def _tone(freq: float, seconds: float, *, fade: float = 0.01) -> Samples:
    n = int(seconds * RATE)
    f = max(1, int(fade * RATE))
    out = []
    for i in range(n):
        env = min(1.0, i / f, (n - i) / f)
        out.append(env * math.sin(2 * math.pi * freq * i / RATE))
    return out


def _bell(freq: float, seconds: float, *, decay: float = 2.5) -> Samples:
    """A struck bell: inharmonic partials, each fading at its own rate."""
    partials = ((1.0, 1.0), (2.0, 0.5), (2.76, 0.35), (5.4, 0.15), (0.5, 0.25))
    n = int(seconds * RATE)
    out = [0.0] * n
    for ratio, amp in partials:
        p = freq * ratio
        if p >= 3500:
            continue
        rate = decay * (1 + ratio / 3)
        for i in range(n):
            t = i / RATE
            out[i] += amp * math.exp(-rate * t) * math.sin(2 * math.pi * p * t)
    attack = int(0.004 * RATE)
    for i in range(min(attack, n)):
        out[i] *= i / attack
    return out


def _sweep(f0: float, f1: float, seconds: float) -> Samples:
    n = int(seconds * RATE)
    out, phase = [], 0.0
    for i in range(n):
        f = f0 + (f1 - f0) * i / n
        phase += 2 * math.pi * f / RATE
        env = min(1.0, i / 80, (n - i) / 80)
        out.append(env * math.sin(phase))
    return out


def _mix(*parts: tuple[float, Samples]) -> Samples:
    """Overlay parts, each starting at its offset in seconds."""
    end = max(int(at * RATE) + len(s) for at, s in parts)
    out = [0.0] * end
    for at, s in parts:
        start = int(at * RATE)
        for i, v in enumerate(s):
            out[start + i] += v
    return out


def _seq(*parts: Samples) -> Samples:
    out: Samples = []
    for p in parts:
        out += p
    return out


# Note frequencies (equal temperament, A4 = 440 Hz).
def _note(name: str) -> float:
    names = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    semis = names[name[0]] + (1 if "#" in name else 0) + 12 * (int(name[-1]) - 4)
    return 440.0 * 2 ** (semis / 12)


def _school_bell(seconds: float) -> Samples:
    # An electric bell: the clapper strikes about 20 times a second.
    out = [0.0] * int(seconds * RATE)
    strike = _bell(1150, 0.12, decay=14)
    step = int(RATE / 20)
    for start in range(0, len(out) - len(strike), step):
        for i, v in enumerate(strike):
            out[start + i] += v
    return out


def _chimes(notes: str, gap: float, ring: float) -> Samples:
    names = notes.split()
    return _mix(*((i * gap, _bell(_note(n), ring, decay=1.6)) for i, n in enumerate(names)))


def _two_tone(hi: float, lo: float, cycles: int, half: float) -> Samples:
    return _seq(*(_tone(hi if i % 2 == 0 else lo, half) for i in range(cycles * 2)))


def _temporal3(rounds: int) -> Samples:
    # Three 0.5 s tones 0.5 s apart, then 1.5 s off (ANSI S3.41 evacuation pattern).
    one = _seq(*(_seq(_tone(3000, 0.5), _silence(0.5)) for _ in range(3)), _silence(1.0))
    return _seq(*(one for _ in range(rounds)))


def _pad(freqs: list[float], seconds: float, level: float = 0.25) -> Samples:
    """A soft chord: each note with its octave and sub-octave, swelling in and out."""
    n = int(seconds * RATE)
    attack, release = int(1.2 * RATE), int(1.5 * RATE)
    out = [0.0] * n
    for f in freqs:
        for ratio, amp in ((1.0, 1.0), (2.0, 0.3), (0.5, 0.4)):
            w = 2 * math.pi * f * ratio / RATE
            a = amp * level
            for i in range(n):
                out[i] += a * math.sin(w * i)
    for i in range(n):
        out[i] *= min(1.0, i / attack, (n - i) / release)
    return out


_PROGRESSIONS = {
    # Root-position triads, one per bar.
    "calm": [("C4", "E4", "G4"), ("G3", "B3", "D4"), ("A3", "C4", "E4"), ("F3", "A3", "C4")],
    "warm": [("A3", "C4", "E4"), ("F3", "A3", "C4"), ("C4", "E4", "G4"), ("G3", "B3", "D4")],
}


def _hold_piece(progression: str, bar: float, rounds: int, arpeggio: bool) -> Samples:
    """Original hold music: a chord progression of pads, optionally with a
    gentle bell arpeggio on the chord tones. Deterministic (seeded), and it
    loops cleanly: it starts and ends quiet."""
    import random

    rng = random.Random(7)  # noqa: S311 (a fixed seed for the same melody, not security)
    parts: list[tuple[float, Samples]] = []
    at = 0.0
    for _ in range(rounds):
        for chord in _PROGRESSIONS[progression]:
            freqs = [_note(c) for c in chord]
            parts.append((at, _pad(freqs, bar + 0.8)))
            if arpeggio:
                tones = [f * 2 for f in freqs] + [freqs[0] * 4]
                for k in range(int(bar / 0.5)):
                    tone = tones[k % len(tones)] if k % 4 else rng.choice(tones)
                    parts.append((at + k * 0.5, [0.35 * v for v in _bell(tone, 1.4, decay=3.0)]))
            at += bar
    return _mix(*parts)


def _bell_melody(seconds: float) -> Samples:
    """Soft bells on a pentatonic scale over a low drone."""
    import random

    rng = random.Random(11)  # noqa: S311 (a fixed seed for the same melody, not security)
    scale = [_note(n) for n in ("C5", "D5", "E5", "G5", "A5", "C6")]
    parts: list[tuple[float, Samples]] = [(0.0, _pad([_note("C3"), _note("G3")], seconds, 0.18))]
    t, i = 0.5, 2
    while t < seconds - 2:
        i = max(0, min(len(scale) - 1, i + rng.choice((-2, -1, 1, 2))))
        parts.append((t, [0.4 * v for v in _bell(scale[i], 2.0, decay=2.2)]))
        t += rng.choice((0.75, 0.75, 1.5))
    return _mix(*parts)


@dataclass(frozen=True)
class Sound:
    key: str
    name: str
    kind: str  # the library kind: bell, announcement or music
    description: str
    make: Callable[[], Samples]
    # Known length in seconds, so listing does not synthesize long pieces.
    seconds: float | None = None


SOUNDS: tuple[Sound, ...] = (
    Sound(
        "school-bell",
        "School bell",
        "bell",
        "A classic electric class bell, 3 seconds.",
        lambda: _school_bell(3.0),
    ),
    Sound(
        "school-bell-long",
        "School bell (long)",
        "bell",
        "The electric bell for 6 seconds: the start and end of the day.",
        lambda: _school_bell(6.0),
    ),
    Sound(
        "westminster",
        "Westminster chime",
        "bell",
        "The four-note quarter chime, twice.",
        lambda: _chimes("G#4 F#4 E4 B3 E4 G#4 F#4 B3", 0.6, 2.5),
    ),
    Sound(
        "chime-two",
        "Two-tone chime",
        "bell",
        "Ding-dong, as before an announcement.",
        lambda: _chimes("E5 C5", 0.55, 2.0),
    ),
    Sound(
        "chime-three-up",
        "Three-tone chime, rising",
        "announcement",
        "Attention, an announcement follows.",
        lambda: _chimes("C5 E5 G5", 0.35, 1.8),
    ),
    Sound(
        "chime-three-down",
        "Three-tone chime, falling",
        "announcement",
        "The end of an announcement.",
        lambda: _chimes("G5 E5 C5", 0.35, 1.8),
    ),
    Sound(
        "chime-soft",
        "Soft single chime",
        "announcement",
        "One gentle chime before a short page.",
        lambda: _bell(_note("A5"), 2.0, decay=1.8),
    ),
    Sound(
        "alert-hi-lo",
        "Hi-lo alert",
        "announcement",
        "Two alternating tones for 5 seconds, for drills and urgent attention.",
        lambda: _two_tone(960, 770, 5, 0.5),
    ),
    Sound(
        "alert-whoop",
        "Whoop alert",
        "announcement",
        "A rising sweep, five times, for lockdown drills.",
        lambda: _seq(*(_seq(_sweep(500, 1200, 0.85), _silence(0.15)) for _ in range(5))),
    ),
    Sound(
        "temporal-3",
        "Temporal-3 tone",
        "announcement",
        "Three-pulse evacuation pattern for drills (not a fire alarm).",
        lambda: _temporal3(3),
    ),
    Sound(
        "door-held",
        "Door held open",
        "announcement",
        "Three quick beeps, repeated: a door is propped open.",
        lambda: _seq(
            *(
                _seq(*(_seq(_tone(1400, 0.12), _silence(0.08)) for _ in range(3)), _silence(0.6))
                for _ in range(3)
            )
        ),
    ),
    Sound(
        "beep",
        "Single beep",
        "announcement",
        "A short beep, for example before a recorded message.",
        lambda: _tone(1000, 0.3),
    ),
    # Hold music (#138): original pieces made here, free to play to callers.
    Sound(
        "hold-calm",
        "Calm chords",
        "music",
        "Soft chords with a gentle bell arpeggio, about a minute; loops.",
        lambda: _hold_piece("calm", 4.0, 4, True),
        seconds=64.9,
    ),
    Sound(
        "hold-warm",
        "Warm pads",
        "music",
        "Slow, warm chords without a melody, about a minute; loops.",
        lambda: _hold_piece("warm", 5.0, 3, False),
        seconds=60.8,
    ),
    Sound(
        "hold-bells",
        "Soft bells",
        "music",
        "A quiet bell melody over a low drone, about 45 seconds; loops.",
        lambda: _bell_melody(45.0),
        seconds=45.0,
    ),
)
BY_KEY = {s.key: s for s in SOUNDS}

LICENSE = "Veyra built-in (synthesized)"
CREDIT = "Generated by Veyra (veyra/telephony/sounds.py)"


@lru_cache(maxsize=len(SOUNDS))
def wav(key: str) -> bytes:
    """The sound as 8 kHz mono 16-bit WAV bytes (KeyError when unknown)."""
    samples = BY_KEY[key].make()
    top = max((abs(v) for v in samples), default=0.0) or 1.0
    scale = PEAK * 32767 / top
    frames = struct.pack(f"<{len(samples)}h", *(int(v * scale) for v in samples))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames)
    return buf.getvalue()


def duration(key: str) -> float:
    known = BY_KEY[key].seconds
    if known is not None:
        return known
    data = wav(key)
    return (len(data) - 44) / (2 * RATE)
