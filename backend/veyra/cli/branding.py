"""Terminal branding: the Veyra wordmark in truecolor, 256-color, 16-color,
monochrome and ASCII-only forms.

Color is used only when writing to a terminal (or when forced) and honours
NO_COLOR (https://no-color.org) and TERM=dumb. Nothing in the CLI depends on
color or Unicode being available. The wordmark text files are shared with
the shell installer (installer/lib/branding.sh).
"""

from __future__ import annotations

import os
import sys
from importlib import resources
from typing import TextIO

from veyra.version import __version__

TAGLINE = "Open Communications Platform"
ELECTRIC_BLUE = (0x00, 0x8C, 0xFF)
TEAL = (0x00, 0xD4, 0xB4)
# Nearest xterm-256 colors to the brand palette.
_ANSI256 = {"blue": 33, "teal": 43}
_ANSI16 = {"blue": 34, "teal": 36}
RESET = "\033[0m"


def _logo(name: str) -> list[str]:
    return resources.files("veyra.cli").joinpath(name).read_text(encoding="utf-8").splitlines()


def color_depth(stream: TextIO, mode: str = "auto") -> int:
    """0 = no color, 16, 256 or 24 (truecolor)."""
    if mode == "never":
        return 0
    if mode == "auto":
        if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
            return 0
        if not (hasattr(stream, "isatty") and stream.isatty()):
            return 0
    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit"):
        return 24
    if "256" in os.environ.get("TERM", ""):
        return 256
    return 16


def supports_unicode(stream: TextIO) -> bool:
    encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
    return encoding in ("utf8", "utf_8") and os.environ.get("TERM") != "linux"


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    r, g, bl = (round(x + (y - x) * t) for x, y in zip(a, b, strict=True))
    return r, g, bl


def _paint(line: str, row: int, rows: int, depth: int) -> str:
    if depth == 0 or not line.strip():
        return line
    if depth == 24:
        out = []
        width = max(len(line) - 1, 1)
        for i, ch in enumerate(line):
            r, g, b = _lerp(ELECTRIC_BLUE, TEAL, i / width)
            out.append(f"\033[38;2;{r};{g};{b}m{ch}" if ch != " " else ch)
        return "".join(out) + RESET
    palette = _ANSI256 if depth == 256 else _ANSI16
    key = "blue" if row < rows / 2 else "teal"
    code = f"38;5;{palette[key]}" if depth == 256 else f"1;{palette[key]}"
    return f"\033[{code}m{line}{RESET}"


def banner(
    stream: TextIO | None = None,
    *,
    color: str = "auto",
    ascii_only: bool | None = None,
    subtitle: str | None = None,
) -> str:
    stream = stream or sys.stdout
    depth = color_depth(stream, color)
    use_ascii = (not supports_unicode(stream)) if ascii_only is None else ascii_only
    lines = _logo("logo-ascii.txt" if use_ascii else "logo-unicode.txt")
    painted = [_paint(line, i, len(lines), depth) for i, line in enumerate(lines)]
    tag = f"{TAGLINE}  ·  v{__version__}" if not use_ascii else f"{TAGLINE}  -  v{__version__}"
    if depth:
        tag = f"\033[2m{tag}{RESET}"
    out = "\n".join(["", *painted, "", tag])
    if subtitle:
        out += "\n" + subtitle
    return out + "\n"


def plain_header() -> str:
    """One-line header for non-interactive output and logs."""
    return f"Veyra {__version__} - {TAGLINE}"


class Style:
    """Status markers that degrade to plain text without color."""

    def __init__(self, stream: TextIO | None = None, color: str = "auto") -> None:
        self.depth = color_depth(stream or sys.stdout, color)

    def _c(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}{RESET}" if self.depth else text

    def ok(self, text: str) -> str:
        return self._c("32", "[ OK ]") + " " + text

    def warn(self, text: str) -> str:
        return self._c("33", "[WARN]") + " " + text

    def fail(self, text: str) -> str:
        return self._c("31", "[FAIL]") + " " + text

    def info(self, text: str) -> str:
        return self._c("36", "[INFO]") + " " + text
