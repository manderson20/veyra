"""Semantic Versioning 2.0.0 parsing, comparison and version ranges.

Range syntax (comparators separated by commas and/or whitespace, all must match):
    ">=1.2.0 <2.0.0"   "^1.2.0"   "~1.4.2"   "==1.0.0"   "*"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering

_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)
_COMPARATOR = re.compile(r"^(>=|<=|==|!=|>|<|=|\^|~)?\s*(.+)$")


class VersionError(ValueError):
    pass


@total_ordering
@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: str = ""

    @classmethod
    def parse(cls, text: str) -> Version:
        m = _SEMVER.match(text.strip())
        if not m:
            raise VersionError(f"Not a semantic version: {text!r}")
        pre = tuple(m.group(4).split(".")) if m.group(4) else ()
        return cls(int(m.group(1)), int(m.group(2)), int(m.group(3)), pre, m.group(5) or "")

    def __str__(self) -> str:
        s = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            s += "-" + ".".join(self.prerelease)
        if self.build:
            s += "+" + self.build
        return s

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch, self.prerelease) == (
            other.major,
            other.minor,
            other.patch,
            other.prerelease,
        )

    def __hash__(self) -> int:
        return hash((self.major, self.minor, self.patch, self.prerelease))

    def __lt__(self, other: Version) -> bool:
        if (self.major, self.minor, self.patch) != (other.major, other.minor, other.patch):
            return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)
        if self.prerelease == other.prerelease:
            return False
        if not self.prerelease:
            return False
        if not other.prerelease:
            return True
        for a, b in zip(self.prerelease, other.prerelease, strict=False):
            if a == b:
                continue
            if a.isdigit() and b.isdigit():
                return int(a) < int(b)
            if a.isdigit() != b.isdigit():
                return a.isdigit()
            return a < b
        return len(self.prerelease) < len(other.prerelease)


@dataclass(frozen=True)
class VersionRange:
    text: str
    comparators: tuple[tuple[str, Version], ...]

    @classmethod
    def parse(cls, text: str) -> VersionRange:
        text = text.strip()
        if text in ("", "*"):
            return cls("*", ())
        parts = [p for p in re.split(r"[,\s]+", text) if p]
        # Re-join operators separated from versions by whitespace: ">= 1.0.0".
        joined: list[str] = []
        for p in parts:
            if joined and joined[-1] in (">=", "<=", "==", "!=", ">", "<", "=", "^", "~"):
                joined[-1] += p
            else:
                joined.append(p)
        comps: list[tuple[str, Version]] = []
        for p in joined:
            m = _COMPARATOR.match(p)
            if not m:
                raise VersionError(f"Invalid version range: {text!r}")
            op = m.group(1) or "=="
            v = Version.parse(m.group(2))
            if op == "=":
                op = "=="
            if op == "^":
                upper = (
                    Version(v.major + 1, 0, 0)
                    if v.major
                    else Version(0, v.minor + 1, 0)
                    if v.minor
                    else Version(0, 0, v.patch + 1)
                )
                comps += [(">=", v), ("<", upper)]
            elif op == "~":
                comps += [(">=", v), ("<", Version(v.major, v.minor + 1, 0))]
            else:
                comps.append((op, v))
        return cls(text, tuple(comps))

    def contains(self, version: Version | str) -> bool:
        if isinstance(version, str):
            version = Version.parse(version)
        for op, v in self.comparators:
            ok = {
                ">=": version >= v,
                "<=": version <= v,
                ">": version > v,
                "<": version < v,
                "==": version == v,
                "!=": version != v,
            }[op]
            if not ok:
                return False
        return True

    def __str__(self) -> str:
        return self.text
