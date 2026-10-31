# SPDX-License-Identifier: AGPL-3.0-or-later
"""Base File Edit (issue #372): a template's changes to single settings of the
files phones download. They apply after rendering, so an update of the base
file keeps them. Settings are found in the text, not by parsing it: the rest
of the file stays byte for byte as rendered."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from html import unescape
from typing import Any
from xml.sax.saxutils import escape, quoteattr

PARAMETER = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-\[\]]{0,199}$")
# Secrets stay out of the template's JSON and out of this page.
SECRET_NAME = re.compile(r"pass(word|wd)|pwd|secret|credential", re.IGNORECASE)
_COMMENT = re.compile(r"<!--.*?-->|<\?.*?\?>", re.DOTALL)
_ATTRIBUTE = re.compile(r"""([A-Za-z_][\w.\-]*)="([^"]*)\"""")
_ELEMENT = re.compile(r"<(P\d+)>([^<]*)</P\d+>")
_LINE = re.compile(r"^[ \t]*([A-Za-z][A-Za-z0-9_.\-\[\]]*)[ \t]*=[ \t]*(.*?)[ \t]*$", re.MULTILINE)
_LAST_CLOSE = re.compile(r"</[A-Za-z][\w.\-]*>\s*$")


@dataclass(frozen=True)
class Setting:
    parameter: str
    value: str
    # The value's place in the file text.
    start: int
    end: int


def _blank_comments(content: str) -> str:
    """Same length, so positions still fit the real text."""
    return _COMMENT.sub(lambda m: " " * len(m.group(0)), content)


def settings(fmt: str, content: str) -> list[Setting]:
    """Every setting of a rendered file, in file order."""
    if fmt == "xml":
        text = _blank_comments(content)
        found = [
            Setting(m.group(1), unescape(m.group(2)), m.start(2), m.end(2))
            for pattern in (_ATTRIBUTE, _ELEMENT)
            for m in pattern.finditer(text)
        ]
        return sorted(found, key=lambda s: s.start)
    return [Setting(m.group(1), m.group(2), m.start(2), m.end(2)) for m in _LINE.finditer(content)]


def _remove(fmt: str, content: str, parameter: str) -> str:
    name = re.escape(parameter)
    if fmt == "xml":
        content = re.sub(rf"""\s+{name}="[^"]*\"""", "", content)
        return re.sub(rf"[ \t]*<{name}>[^<]*</{name}>\n?", "", content)
    return re.sub(rf"^[ \t]*{name}[ \t]*=.*\n?", "", content, flags=re.MULTILINE)


def _append(fmt: str, content: str, parameter: str, value: str) -> str:
    if fmt != "xml":
        return f"{content.rstrip()}\n{parameter} = {value}\n"
    close = _LAST_CLOSE.search(content)
    if close is None:
        return content  # A file with one self-closed element has nowhere to add to.
    if re.fullmatch(r"P\d+", parameter):
        item = f"<{parameter}>{escape(value)}</{parameter}>"
    else:
        item = f"<veyra {parameter}={quoteattr(value)} />"
    return f"{content[: close.start()]}  {item}\n{content[close.start() :]}"


def _change(fmt: str, content: str, parameter: str, value: str) -> str:
    written = escape(value, {'"': "&quot;"}) if fmt == "xml" else value
    places = [s for s in settings(fmt, content) if s.parameter == parameter]
    if not places:
        return _append(fmt, content, parameter, value)
    for s in reversed(places):
        content = content[: s.start] + written + content[s.end :]
    return content


def apply(fmt: str, content: str, file: str, model: str, edits: Iterable[Mapping[str, Any]]) -> str:
    """``file`` is the file's name in the base file, such as ``{mac}.cfg``."""
    for edit in edits:
        if edit["file"] != file or model not in edit["models"]:
            continue
        if edit.get("remove"):
            content = _remove(fmt, content, edit["parameter"])
        else:
            content = _change(fmt, content, edit["parameter"], str(edit.get("value") or ""))
    return content
