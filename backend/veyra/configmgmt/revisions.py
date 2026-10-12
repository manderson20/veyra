# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration revision state machine, content hashing and diffs."""

from __future__ import annotations

import difflib
import hashlib
import json
from enum import StrEnum
from typing import Any

from veyra.core.security.crypto import DecryptionError, InstallationKey, InstallationKeyError
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


def artifact_purpose(revision_id: Any, path: str) -> str:
    """Associated data binding an encrypted artifact to its revision and file."""
    return f"config_revision.file:{revision_id}:{path}"


def files_to_artifacts(
    files: list[GeneratedFile], key: InstallationKey | None, revision_id: Any
) -> dict[str, Any]:
    """The ``artifacts`` document of a revision. Sensitive files (those that
    carry credentials) are stored encrypted with the installation key; the
    others stay readable so the history can be inspected in the database."""
    out: list[dict[str, Any]] = []
    for f in files:
        if f.sensitive:
            if key is None:
                raise InstallationKeyError(
                    f"{f.path} contains credentials but the installation key is not available"
                )
            out.append(
                {
                    "path": f.path,
                    "sensitive": True,
                    "ciphertext": key.encrypt(f.content, artifact_purpose(revision_id, f.path)),
                }
            )
        else:
            out.append({"path": f.path, "content": f.content, "sensitive": False})
    return {"files": out}


def artifacts_to_files(
    artifacts: dict[str, Any] | None, key: InstallationKey | None, revision_id: Any
) -> list[GeneratedFile]:
    """Files stored in a revision's ``artifacts`` column, decrypted. Raises
    :class:`InstallationKeyError` when an encrypted file cannot be read."""
    out: list[GeneratedFile] = []
    for f in (artifacts or {}).get("files", []):
        if not isinstance(f, dict) or "path" not in f:
            continue
        path = str(f["path"])
        sensitive = bool(f.get("sensitive"))
        if "ciphertext" in f:
            if key is None:
                raise InstallationKeyError(
                    f"{path} is encrypted but the installation key is not available"
                )
            try:
                content = key.decrypt(str(f["ciphertext"]), artifact_purpose(revision_id, path))
            except DecryptionError as e:
                raise InstallationKeyError(f"{path} cannot be decrypted: {e}") from e
            out.append(GeneratedFile(path, content, True))
        elif "content" in f:
            out.append(GeneratedFile(path, str(f["content"]), sensitive))
    return out


def artifacts_to_files_safe(
    artifacts: dict[str, Any] | None, key: InstallationKey | None, revision_id: Any
) -> list[GeneratedFile]:
    """Like :func:`artifacts_to_files`, but an unreadable encrypted file is
    returned with empty content instead of raising (for display code)."""
    try:
        return artifacts_to_files(artifacts, key, revision_id)
    except InstallationKeyError:
        out: list[GeneratedFile] = []
        for f in (artifacts or {}).get("files", []):
            if isinstance(f, dict) and "path" in f:
                content = "" if "ciphertext" in f else str(f.get("content", ""))
                out.append(GeneratedFile(str(f["path"]), content, bool(f.get("sensitive"))))
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
