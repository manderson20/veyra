# SPDX-License-Identifier: AGPL-3.0-or-later
"""Custom dialplan (docs/CUSTOM_DIALPLAN.md): a platform administrator's own
Asterisk contexts, for what Veyra has no feature for. Stored in
``system_settings`` under ``telephony.custom_dialplan``.

The text is accepted line by line: only ``[custom-*]`` contexts and
``exten``/``same``/``include`` lines, so ``#include``, ``#exec``, globals and
switches never reach the engine. Applications and functions that reach the
server's shell or files are refused. That list narrows what a mistake or a
stolen session can do, but it is not a sandbox: dialplan is code, which is why
only platform administrators can write it."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from veyra.core.models import SystemSetting

CUSTOM_DIALPLAN_KEY = "telephony.custom_dialplan"
MAX_BYTES = 256 * 1024

_CONTEXT_RE = re.compile(r"^\[(custom-[a-z0-9][a-z0-9-]{0,62})\]$")
_INCLUDE_RE = re.compile(r"^include\s*=>\s*(custom-[a-z0-9][a-z0-9-]{0,62})$")
_PRIORITY = r"(?:\d+|n)(?:\([A-Za-z0-9_-]+\))?"
_EXTEN_RE = re.compile(rf"^exten\s*=>\s*[^,\s]+\s*,\s*{_PRIORITY}\s*,\s*(.+)$")
_SAME_RE = re.compile(rf"^same\s*=>\s*{_PRIORITY}\s*,\s*(.+)$")
_APP_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\(.*\))?$")

# Run a command, a script or another application named at run time; write
# files; or reach out of the call (Originate can start any application).
BLOCKED_APPLICATIONS = (
    "AGI",
    "DeadAGI",
    "Dictate",
    "EAGI",
    "Exec",
    "ExecIf",
    "ExecIfTime",
    "ExternalIVR",
    "FastAGI",
    "MixMonitor",
    "Monitor",
    "Originate",
    "Queue",
    "ReceiveFAX",
    "Record",
    "SendFAX",
    "Stasis",
    "System",
    "TryExec",
    "TrySystem",
)
# Run a command, read or write files, secrets and the database, reach the
# network, or evaluate text as dialplan (which would hide all of these).
BLOCKED_FUNCTIONS = (
    "AST_CONFIG",
    "CURL",
    "CURLOPT",
    "DB",
    "DB_DELETE",
    "DB_EXISTS",
    "DB_KEYS",
    "ENV",
    "EVAL",
    "EVAL_EXTEN",
    "FILE",
    "FILE_COUNT_LINE",
    "FILE_FORMAT",
    "GLOB",
    "ODBC",
    "ODBC_FETCH",
    "REALTIME",
    "REALTIME_DESTROY",
    "REALTIME_FIELD",
    "REALTIME_HASH",
    "REALTIME_STORE",
    "SHELL",
    "STAT",
)
_BLOCKED_RE = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join((*BLOCKED_APPLICATIONS, *BLOCKED_FUNCTIONS)) + r")\s*\(",
    re.I,
)
# A name built at run time would get past the list: ${${A}${B}(...)},
# Set(${A}(...)=...).
_COMPUTED_NAME_RE = re.compile(r"\$\{[^}()]*\$\{")
_COMPUTED_SET_RE = re.compile(r"(?<![A-Za-z0-9_])M?Set\s*\([^=]*\$\{", re.I)


def contexts(text: str) -> list[str]:
    """The contexts a valid text defines, in order."""
    out: list[str] = []
    for raw in text.splitlines():
        m = _CONTEXT_RE.match(raw.strip())
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def problems(text: str) -> list[str]:
    """What is wrong with the text, by line; empty when it can be deployed."""
    if len(text.encode()) > MAX_BYTES:
        return [f"the text is larger than {MAX_BYTES // 1024} KB"]
    found: list[str] = []
    in_context = False
    defined = set(contexts(text))
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        where = f"line {number}"
        if ";--" in line or "--;" in line:
            # An open block comment would swallow the generated dialplan after it.
            found.append(f"{where}: block comments are not allowed")
            continue
        if not line or line.startswith(";"):
            continue
        if "\\" in line:
            found.append(f"{where}: backslashes are not allowed")
            continue
        if _CONTEXT_RE.match(line):
            in_context = True
            continue
        if line.startswith("["):
            found.append(
                f"{where}: a context must be named [custom-…] in lowercase, with no template"
            )
            continue
        if not in_context:
            found.append(f"{where}: put this inside a [custom-…] context")
            continue
        include = _INCLUDE_RE.match(line)
        if include:
            if include.group(1) not in defined:
                found.append(f"{where}: {include.group(1)} is not defined here")
            continue
        step = _EXTEN_RE.match(line) or _SAME_RE.match(line)
        if not step:
            found.append(
                f"{where}: only exten =>, same => and include => custom-… lines are allowed"
            )
            continue
        code = step.group(1).split(";", 1)[0].strip()
        if not _APP_RE.match(code):
            found.append(f"{where}: the application name must be written out")
            continue
        blocked = _BLOCKED_RE.search(line)
        if blocked:
            found.append(f"{where}: {blocked.group(1)} is not allowed in custom dialplan")
        elif _COMPUTED_NAME_RE.search(line) or _COMPUTED_SET_RE.search(line):
            found.append(f"{where}: names built from variables are not allowed")
    return found


def load(db: Session) -> dict[str, Any]:
    row = db.get(SystemSetting, CUSTOM_DIALPLAN_KEY)
    return dict(row.value) if row is not None and row.value else {"text": ""}


def save(db: Session, text: str, updated_by: Any) -> None:
    row = db.get(SystemSetting, CUSTOM_DIALPLAN_KEY)
    if row is None:
        row = SystemSetting(key=CUSTOM_DIALPLAN_KEY, value={})
        db.add(row)
    row.value = {"text": text}
    row.updated_by = updated_by
