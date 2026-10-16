# SPDX-License-Identifier: AGPL-3.0-or-later
"""File sync between the nodes (docs/HIGH_AVAILABILITY.md §4.2): the primary
serves a manifest of its data files and streams one file at a time; the
secondary's agent pulls what changed and removes what left.

The transport is the signed peer channel; this module only knows about
directories, manifests and the plan between two manifests.
"""

from __future__ import annotations

import contextlib
import grp
import hashlib
import os
import pwd
import stat
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHUNK = 1024 * 1024
TEMP_SUFFIX = ".veyra-sync"

# Logical roots (docs/HIGH_AVAILABILITY.md §4.2) relative to the data and
# configuration directories. Recordings are a switch (``ha.sync``).
DATA_ROOTS = (
    "prompts",
    "moh",
    "firmware",
    "provisioning/templates",
    "modules",
    "module-store",
    "updates",
)
RECORDINGS_ROOT = "recordings"
CONFIG_ROOTS = ("secrets", "tls", "trust")
VOICEMAIL_ROOT = "/var/spool/asterisk/voicemail"
# Files the standby must never take from the primary: its own identity.
NEVER_SYNC = ("secrets/node.key",)


@dataclass(frozen=True)
class Entry:
    path: str  # "<root>/<relative>", always with forward slashes
    size: int
    mtime: float
    mode: int
    owner: str
    group: str
    digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size": self.size,
            "mtime": self.mtime,
            "mode": self.mode,
            "owner": self.owner,
            "group": self.group,
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Entry:
        return cls(
            path=str(d["path"]),
            size=int(d["size"]),
            mtime=float(d["mtime"]),
            mode=int(d["mode"]),
            owner=str(d.get("owner") or "root"),
            group=str(d.get("group") or "root"),
            digest=d.get("digest"),
        )

    def same_as(self, other: Entry) -> bool:
        if self.digest and other.digest:
            return self.digest == other.digest
        return self.size == other.size and abs(self.mtime - other.mtime) < 0.001


def roots_for(data_dir: Path, config_dir: Path, *, recordings: bool) -> dict[str, Path]:
    """Logical name → directory on this node."""
    out = {f"data/{r}": data_dir / r for r in DATA_ROOTS}
    if recordings:
        out[f"data/{RECORDINGS_ROOT}"] = data_dir / RECORDINGS_ROOT
    out.update({f"etc/{r}": config_dir / r for r in CONFIG_ROOTS})
    out["voicemail"] = Path(VOICEMAIL_ROOT)
    return out


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _names(st: os.stat_result) -> tuple[str, str]:
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        owner = str(st.st_uid)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = str(st.st_gid)
    return owner, group


def excluded(logical: str) -> bool:
    return any(logical == f"etc/{n}" for n in NEVER_SYNC) or logical.endswith(TEMP_SUFFIX)


_excluded = excluded


def manifest(
    roots: dict[str, Path],
    *,
    digest_cache: dict[str, tuple[float, int, str]] | None = None,
    with_digest: bool = True,
) -> list[Entry]:
    """Every regular file under the roots. Digests are cached by (mtime, size)
    so a manifest every 30 s costs one ``stat`` per file."""
    out: list[Entry] = []
    for name, base in roots.items():
        if not base.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                p = Path(dirpath) / fn
                try:
                    st = p.lstat()
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                logical = f"{name}/{p.relative_to(base).as_posix()}"
                if _excluded(logical):
                    continue
                digest: str | None = None
                if with_digest:
                    cached = digest_cache.get(logical) if digest_cache is not None else None
                    if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
                        digest = cached[2]
                    else:
                        try:
                            digest = sha256_of(p)
                        except OSError:
                            continue
                        if digest_cache is not None:
                            digest_cache[logical] = (st.st_mtime, st.st_size, digest)
                owner, group = _names(st)
                out.append(
                    Entry(
                        logical,
                        st.st_size,
                        st.st_mtime,
                        stat.S_IMODE(st.st_mode),
                        owner,
                        group,
                        digest,
                    )
                )
    out.sort(key=lambda e: e.path)
    return out


def resolve(roots: dict[str, Path], logical: str) -> Path | None:
    """The local path of a manifest entry, or None when it escapes its root."""
    for name, base in roots.items():
        prefix = name + "/"
        if logical.startswith(prefix):
            rel = logical[len(prefix) :]
            if not rel or rel.startswith("/") or ".." in rel.split("/"):
                return None
            return base / rel
    return None


@dataclass
class Plan:
    fetch: list[Entry]
    delete: list[str]

    @property
    def backlog(self) -> int:
        return len(self.fetch) + len(self.delete)


def plan(
    local: Iterable[Entry], remote: Iterable[Entry], covered: Iterable[str] | None = None
) -> Plan:
    """What to fetch and what to delete. Deletions only happen inside roots
    the primary says it listed completely (``covered``; None = all): a root
    the primary could not read must never empty the standby's copy."""
    mine = {e.path: e for e in local}
    theirs = {e.path: e for e in remote}
    fetch = [e for p, e in theirs.items() if p not in mine or not mine[p].same_as(e)]
    roots = None if covered is None else [c.rstrip("/") + "/" for c in covered]
    delete = [
        p
        for p in mine
        if p not in theirs and (roots is None or any(p.startswith(r) for r in roots))
    ]
    return Plan(fetch, delete)


def split_roots(roots: dict[str, Path]) -> tuple[dict[str, Path], dict[str, Path]]:
    """(roots the service account can read, roots only root can read)."""
    readable = {k: v for k, v in roots.items() if not k.startswith("etc/")}
    privileged = {k: v for k, v in roots.items() if k.startswith("etc/")}
    return readable, privileged


Fetcher = Callable[[str], Iterator[bytes]]


def _chown(path: Path, owner: str, group: str) -> None:
    try:
        uid = pwd.getpwnam(owner).pw_uid
        gid = grp.getgrnam(group).gr_gid
    except KeyError:
        return
    # Not root (tests): the file keeps the caller's identity.
    with contextlib.suppress(PermissionError):
        os.chown(path, uid, gid)


def write_entry(roots: dict[str, Path], entry: Entry, chunks: Iterable[bytes]) -> Path:
    """Write a fetched file next to its target and rename it into place with
    the manifest's mode, owner, group and mtime; verifies the digest."""
    target = resolve(roots, entry.path)
    if target is None:
        raise ValueError(f"refusing path outside the sync roots: {entry.path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + TEMP_SUFFIX)
    h = hashlib.sha256()
    size = 0
    with tmp.open("wb") as f:
        for chunk in chunks:
            h.update(chunk)
            size += len(chunk)
            f.write(chunk)
    if entry.digest and h.hexdigest() != entry.digest:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"digest mismatch for {entry.path}")
    if size != entry.size:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"size mismatch for {entry.path}")
    os.chmod(tmp, entry.mode)
    _chown(tmp, entry.owner, entry.group)
    os.utime(tmp, (entry.mtime, entry.mtime))
    os.replace(tmp, target)
    return target


def delete_entry(roots: dict[str, Path], logical: str) -> None:
    target = resolve(roots, logical)
    if target is not None:
        target.unlink(missing_ok=True)


def apply(roots: dict[str, Path], p: Plan, fetch: Fetcher) -> tuple[int, list[str]]:
    """Run a plan; returns (files transferred, errors)."""
    errors: list[str] = []
    done = 0
    for entry in p.fetch:
        try:
            write_entry(roots, entry, fetch(entry.path))
            done += 1
        except (OSError, ValueError) as e:
            errors.append(f"{entry.path}: {e}")
    for logical in p.delete:
        try:
            delete_entry(roots, logical)
        except OSError as e:
            errors.append(f"{logical}: {e}")
    return done, errors


def read_chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as f:
        yield from iter(lambda: f.read(CHUNK), b"")
