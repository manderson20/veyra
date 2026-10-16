# SPDX-License-Identifier: AGPL-3.0-or-later
"""Enrollment of a second node (docs/HIGH_AVAILABILITY.md §5): join tokens
(hashes in ``system_settings`` ``ha.join_tokens``) and the bundle the primary
hands the new node, encrypted with a key derived from the token.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import grp
import json
import os
import pwd
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.orm import Session

from veyra.core.models import SystemSetting
from veyra.core.models.base import utcnow
from veyra.core.security import tokens

TOKENS_KEY = "ha.join_tokens"
TOKEN_PREFIX = "vyj_"  # noqa: S105 - a prefix, not a secret
TOKEN_TTL = timedelta(hours=24)
BUNDLE_VERSION = 1
# Files of the primary the new node needs, relative to the configuration
# directory, with the owner and mode they must get there (docs §5 step 2).
BUNDLE_FILES = (
    "secrets/installation.key",
    "secrets/ari_password",
    "secrets/companion-signing.key",
    "secrets/replication_password",
    "secrets/module-signing.key",
    "tls/ca.key",
    "tls/ca.crt",
    "veyra-ca.crt",
)
BUNDLE_DIRS = ("trust",)


class JoinError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ------------------------------------------------------------------ tokens


def _tokens(db: Session) -> list[dict[str, Any]]:
    row = db.get(SystemSetting, TOKENS_KEY)
    value = row.value if row is not None else None
    return [t for t in value if isinstance(t, dict)] if isinstance(value, list) else []


def _save(db: Session, items: list[dict[str, Any]]) -> None:
    row = db.get(SystemSetting, TOKENS_KEY)
    if row is None:
        db.add(SystemSetting(key=TOKENS_KEY, value=items))
    else:
        row.value = items
    db.flush()


def list_tokens(db: Session) -> list[dict[str, Any]]:
    now = utcnow().isoformat()
    return [
        {k: v for k, v in t.items() if k != "hash"} | {"expired": str(t.get("expires_at")) < now}
        for t in _tokens(db)
    ]


def create_token(db: Session, *, label: str | None, created_by: str) -> tuple[str, dict[str, Any]]:
    raw = TOKEN_PREFIX + tokens.new_token(24)
    now = utcnow()
    item = {
        "id": str(uuid.uuid4()),
        "hash": tokens.digest(raw),
        "label": label,
        "created_by": created_by,
        "created_at": now.isoformat(),
        "expires_at": (now + TOKEN_TTL).isoformat(),
        "used_at": None,
        "used_by": None,
    }
    items = [t for t in _tokens(db) if str(t.get("expires_at")) >= now.isoformat()]
    items.append(item)
    _save(db, items)
    return raw, {k: v for k, v in item.items() if k != "hash"}


def delete_token(db: Session, token_id: str) -> bool:
    items = _tokens(db)
    kept = [t for t in items if t.get("id") != token_id]
    if len(kept) == len(items):
        return False
    _save(db, kept)
    return True


def consume_token(db: Session, raw: str, used_by: str) -> dict[str, Any]:
    """Mark a valid, unused token as used by ``used_by`` or raise JoinError."""
    now = utcnow()
    digest = tokens.digest(raw or "")
    items = _tokens(db)
    for t in items:
        if t.get("hash") == digest:
            if t.get("used_at") or str(t.get("expires_at")) < now.isoformat():
                break
            t["used_at"], t["used_by"] = now.isoformat(), used_by
            _save(db, items)
            return t
    raise JoinError(403, "bad_token", "The join token is not valid, expired or was used.")


# ------------------------------------------------------------------ bundle


def _key(token: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"veyra-ha-join-bundle"
    ).derive(token.encode())


def encrypt_bundle(token: str, bundle: dict[str, Any]) -> str:
    nonce = os.urandom(12)
    plain = json.dumps(bundle, separators=(",", ":"), sort_keys=True).encode()
    sealed = AESGCM(_key(token)).encrypt(nonce, plain, b"veyra-ha-join")
    return f"v{BUNDLE_VERSION}:" + base64.b64encode(nonce + sealed).decode()


def decrypt_bundle(token: str, sealed: str) -> dict[str, Any]:
    version, _, payload = sealed.partition(":")
    if version != f"v{BUNDLE_VERSION}" or not payload:
        raise JoinError(400, "bad_bundle", "The join bundle has an unknown format.")
    try:
        data = base64.b64decode(payload, validate=True)
        plain = AESGCM(_key(token)).decrypt(data[:12], data[12:], b"veyra-ha-join")
        out = json.loads(plain)
    except (binascii.Error, InvalidTag, ValueError) as e:
        raise JoinError(400, "bad_bundle", "The join bundle cannot be decrypted.") from e
    if not isinstance(out, dict):
        raise JoinError(400, "bad_bundle", "The join bundle is not an object.")
    return out


def _file_entry(base: Path, rel: str) -> dict[str, Any] | None:
    p = base / rel
    try:
        st = p.stat()
        content = p.read_bytes()
    except OSError:
        return None
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        owner, group = "root", "root"
    return {
        "path": rel,
        "mode": st.st_mode & 0o7777,
        "owner": owner,
        "group": group,
        "content": base64.b64encode(content).decode(),
    }


def collect_files(config_dir: Path, extra: dict[str, bytes] | None = None) -> list[dict[str, Any]]:
    """The files of BUNDLE_FILES and BUNDLE_DIRS that exist, plus ``extra``
    (path → content) for files made for the new node (its certificate)."""
    out: list[dict[str, Any]] = []
    for rel in BUNDLE_FILES:
        e = _file_entry(config_dir, rel)
        if e is not None:
            out.append(e)
    for d in BUNDLE_DIRS:
        base = config_dir / d
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.is_file():
                    e = _file_entry(config_dir, p.relative_to(config_dir).as_posix())
                    if e is not None:
                        out.append(e)
    for rel, content in (extra or {}).items():
        out.append(
            {
                "path": rel,
                "mode": 0o640,
                "owner": "root",
                "group": "veyra",
                "content": base64.b64encode(content).decode(),
            }
        )
    return out


def write_files(config_dir: Path, files: list[dict[str, Any]], *, chown: bool = True) -> list[str]:
    """Write bundle files under ``config_dir`` with their modes and owners;
    returns the paths written. Never follows a path outside the directory."""
    written: list[str] = []
    for f in files:
        rel = str(f.get("path") or "")
        if not rel or rel.startswith("/") or ".." in rel.split("/"):
            raise JoinError(400, "bad_bundle", f"The bundle names an invalid path: {rel!r}")
        target = config_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(base64.b64decode(str(f.get("content") or "")))
        os.chmod(tmp, int(f.get("mode") or 0o640))
        if chown:
            with contextlib.suppress(KeyError, PermissionError):
                os.chown(
                    tmp,
                    pwd.getpwnam(str(f.get("owner") or "root")).pw_uid,
                    grp.getgrnam(str(f.get("group") or "root")).gr_gid,
                )
        os.replace(tmp, target)
        written.append(rel)
    return written
