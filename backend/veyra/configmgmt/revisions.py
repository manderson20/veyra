# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration revision state machine, content hashing and diffs."""

from __future__ import annotations

import difflib
import hashlib
import json
from enum import StrEnum
from typing import Any

from veyra.telephony.adapter import GeneratedFile


class RevisionState(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"


TRANSITIONS: dict[RevisionState, set[RevisionState]] = {
    RevisionState.DRAFT: {RevisionState.VALIDATED, RevisionState.FAILED},
    RevisionState.VALIDATED: {RevisionState.DEPLOYING, RevisionState.SUPERSEDED},
    RevisionState.DEPLOYING: {RevisionState.DEPLOYED, RevisionState.FAILED},
    RevisionState.DEPLOYED: {RevisionState.SUPERSEDED, RevisionState.ROLLED_BACK},
    RevisionState.FAILED: set(),
    RevisionState.SUPERSEDED: {RevisionState.DEPLOYING},  # redeploy = rollback target
    RevisionState.ROLLED_BACK: set(),
}


class InvalidTransition(ValueError):
    pass


def transition(current: str, target: RevisionState) -> RevisionState:
    state = RevisionState(current)
    if target not in TRANSITIONS[state]:
        raise InvalidTransition(f"Cannot move a revision from {state} to {target}")
    return target


def content_hash(files: list[GeneratedFile]) -> str:
    payload = json.dumps(sorted((f.path, f.content) for f in files)).encode()
    return hashlib.sha256(payload).hexdigest()


def artifacts_to_files_safe(artifacts: dict[str, Any] | None) -> list[GeneratedFile]:
    """Files stored in a revision's ``artifacts`` column (tolerates missing data)."""
    out = []
    for f in (artifacts or {}).get("files", []):
        if isinstance(f, dict) and "path" in f and "content" in f:
            out.append(GeneratedFile(str(f["path"]), str(f["content"]), bool(f.get("sensitive"))))
    return out


def diff(old: list[GeneratedFile], new: list[GeneratedFile]) -> dict[str, Any]:
    """Unified diffs per file. Sensitive files report only whether they changed."""
    before = {f.path: f for f in old}
    after = {f.path: f for f in new}
    result: dict[str, Any] = {}
    for path in sorted(set(before) | set(after)):
        a, b = before.get(path), after.get(path)
        if a and b and a.content == b.content:
            continue
        sensitive = (a and a.sensitive) or (b and b.sensitive)
        if sensitive:
            result[path] = {"changed": True, "diff": None, "sensitive": True}
            continue
        lines = difflib.unified_diff(
            (a.content if a else "").splitlines(keepends=True),
            (b.content if b else "").splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        result[path] = {"changed": True, "diff": "".join(lines), "sensitive": False}
    return result
