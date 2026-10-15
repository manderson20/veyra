# SPDX-License-Identifier: AGPL-3.0-or-later
"""Release artifacts and update metadata, on the publisher's side
(docs/SOFTWARE_UPDATES.md §1).

A release is ``veyra-<version>.tar.gz``: the committed source tree (``git
archive``) plus the prebuilt web interface and Companion extension, so
servers never need Node.js, and a ``REVISION`` file naming the commit.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from veyra.updates.metadata import UpdateMetadata

PREBUILT = ("frontend/out", "companion/dist")
EXCLUDED_PARTS = {".git", "node_modules", ".venv", "__pycache__", ".next"}
DEFAULT_EXPIRY_DAYS = 30


class ReleaseError(ValueError):
    pass


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout


def source_version(tree: Path) -> str:
    m = re.search(
        r'^__version__ = "([^"]+)"', (tree / "backend/veyra/version.py").read_text(), re.M
    )
    if not m:
        raise ReleaseError("backend/veyra/version.py has no __version__")
    return m.group(1)


def module_api_version(tree: Path) -> str:
    m = re.search(
        r'^MODULE_API_VERSION = "([^"]+)"', (tree / "backend/veyra/version.py").read_text(), re.M
    )
    if not m:
        raise ReleaseError("backend/veyra/version.py has no MODULE_API_VERSION")
    return m.group(1)


def build(repo: Path, out_dir: Path, *, allow_dirty: bool = False) -> Path:
    """Build ``veyra-<version>.tar.gz`` from the commit checked out in ``repo``."""
    if not allow_dirty and _git(repo, "status", "--porcelain", "--untracked-files=no").strip():
        raise ReleaseError("The working tree has uncommitted changes; commit them first.")
    for d in PREBUILT:
        marker = "index.html" if d == "frontend/out" else "manifest.json"
        if not (repo / d / marker).is_file():
            raise ReleaseError(f"{d} is missing: build it first (npm run build).")
    version = source_version(repo)
    revision = _git(repo, "rev-parse", "--short=10", "HEAD").strip()
    top = f"veyra-{version}"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{top}.tar.gz"
    archive = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "archive", "--format=tar", f"--prefix={top}/", "HEAD"],  # noqa: S607
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(dest, "w:gz") as out:
        with tarfile.open(fileobj=io.BytesIO(archive)) as src:
            for member in src.getmembers():
                if member.name.startswith(tuple(f"{top}/{d}/" for d in PREBUILT)):
                    continue  # the prebuilt copies below win
                out.addfile(member, src.extractfile(member) if member.isfile() else None)
        for d in PREBUILT:
            out.add(
                repo / d,
                arcname=f"{top}/{d}",
                filter=lambda ti: None if set(Path(ti.name).parts) & EXCLUDED_PARTS else _clean(ti),
            )
        rev = f"{revision}\n".encode()
        info = tarfile.TarInfo(f"{top}/REVISION")
        info.size, info.mode, info.mtime = len(rev), 0o644, int(datetime.now(UTC).timestamp())
        out.addfile(info, io.BytesIO(rev))
    return dest


def _clean(ti: tarfile.TarInfo) -> tarfile.TarInfo:
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = "root"
    return ti


def inspect(artifact: Path) -> dict[str, Any]:
    """Version, module API and revision of a built release."""
    with tarfile.open(artifact, "r:gz") as tar:
        names = tar.getnames()
        top = names[0].split("/")[0]

        def read(name: str) -> str:
            f = tar.extractfile(f"{top}/{name}")
            if f is None:
                raise ReleaseError(f"{name} missing from {artifact.name}")
            return f.read().decode()

        version_py = read("backend/veyra/version.py")
        revision = read("REVISION").strip() if f"{top}/REVISION" in names else ""
    m = re.search(r'^__version__ = "([^"]+)"', version_py, re.M)
    api = re.search(r'^MODULE_API_VERSION = "([^"]+)"', version_py, re.M)
    if not m or top != f"veyra-{m.group(1)}":
        raise ReleaseError(f"{artifact.name} is not a Veyra release archive")
    return {
        "version": m.group(1),
        "module_api": api.group(1) if api else None,
        "revision": revision,
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load(metadata: Path) -> dict[str, Any]:
    if metadata.exists():
        return dict(json.loads(metadata.read_text()))
    return {"schema_version": 1, "sequence": 0, "releases": []}


def _stamp(doc: dict[str, Any], expiry_days: int) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    doc["sequence"] = int(doc.get("sequence", 0)) + 1
    doc["generated_at"] = now.isoformat()
    doc["expires_at"] = (now + timedelta(days=expiry_days)).isoformat()


def _save(metadata: Path, doc: dict[str, Any]) -> None:
    UpdateMetadata.model_validate(doc)  # never write metadata Veyra would refuse
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text(json.dumps(doc, indent=2) + "\n")
    sig = Path(str(metadata) + ".sig")
    sig.unlink(missing_ok=True)  # stale: sign again


def add(
    metadata: Path,
    artifact: Path,
    *,
    url: str,
    channel: str,
    category: str,
    notes: str = "",
    impact: str = "",
    min_from: str | None = None,
    expiry_days: int = DEFAULT_EXPIRY_DAYS,
) -> dict[str, Any]:
    """Add (or replace) a release in the metadata; size and checksum come
    from the artifact itself so they cannot drift."""
    info = inspect(artifact)
    doc = _load(metadata)
    entry = {
        "component": "veyra_core",
        "target": "veyra",
        "version": info["version"],
        "channel": channel,
        "category": category,
        "release_notes": notes,
        "service_impact": impact,
        "min_from_version": min_from,
        "module_api": info["module_api"],
        "revision": info["revision"],
        "artifact": {"url": url, "sha256": _sha256(artifact), "size": artifact.stat().st_size},
    }
    doc["releases"] = [
        r
        for r in doc.get("releases", [])
        if not (r.get("target") == "veyra" and r.get("version") == info["version"])
    ]
    doc["releases"].insert(0, entry)
    _stamp(doc, expiry_days)
    _save(metadata, doc)
    return entry


def refresh(metadata: Path, expiry_days: int = DEFAULT_EXPIRY_DAYS) -> dict[str, Any]:
    """New sequence and expiry without a release (then sign again)."""
    doc = _load(metadata)
    _stamp(doc, expiry_days)
    _save(metadata, doc)
    return doc
