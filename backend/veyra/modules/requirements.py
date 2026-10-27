# SPDX-License-Identifier: AGPL-3.0-or-later
"""Python libraries a module needs (manifest ``[runtime] requires``, #149).

Modules run in the core's virtual environment and cannot bring their own
libraries; a module declares what it imports so that install is refused
with a clear message when this Veyra lacks it, instead of failing on
import. Requirements are ``name`` or ``name<op>version[,<op>version…]``
with ``>= > <= < == !=`` comparing the numeric release (``2.1.4``)."""

from __future__ import annotations

import operator
import re
from collections.abc import Callable
from importlib import metadata

REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*"
    # One way to match the space around a comma: no exponential backtracking.
    r"(?P<specs>(?:(?:>=|<=|==|!=|>|<)\s*\d+(?:\.\d+)*\s*(?:,\s*)?)*)$"
)
_SPEC_RE = re.compile(r"(>=|<=|==|!=|>|<)\s*(\d+(?:\.\d+)*)")
_OPS: dict[str, Callable[[tuple[int, ...], tuple[int, ...]], bool]] = {
    ">=": operator.ge,
    ">": operator.gt,
    "<=": operator.le,
    "<": operator.lt,
    "==": operator.eq,
    "!=": operator.ne,
}


def valid(requirement: str) -> bool:
    return REQUIREMENT_RE.match(requirement.strip()) is not None


def _release(text: str) -> tuple[int, ...]:
    m = re.match(r"\d+(?:\.\d+)*", text)
    parts = [int(p) for p in m.group(0).split(".")] if m else [0]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def problem(requirement: str) -> str | None:
    """Why ``requirement`` is not met by this environment, or None."""
    m = REQUIREMENT_RE.match(requirement.strip())
    if m is None:
        return f"Python requirement {requirement!r} is not understood."
    name = m.group("name")
    try:
        installed = metadata.version(name)
    except metadata.PackageNotFoundError:
        return f"Needs the Python library {name}, which this Veyra does not include."
    have = _release(installed)
    for op, version in _SPEC_RE.findall(m.group("specs")):
        if not _OPS[op](have, _release(version)):
            return f"Needs Python library {requirement.strip()}; this Veyra has {name} {installed}."
    return None
