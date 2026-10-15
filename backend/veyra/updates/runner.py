# SPDX-License-Identifier: AGPL-3.0-or-later
"""The root upgrade runner (docs/SOFTWARE_UPDATES.md §3.2).

Started as ``veyra-upgrade@<version>.service`` (root) when the service
account asks for it. Nothing the service account wrote is trusted: the
stored metadata is verified again against the official keys, the artifact
is copied into a root-only directory and checked against the signed size
and SHA-256 there, and only then does that release's own
``installer/upgrade.sh --yes`` run. Progress goes to
``<upgrade_dir>/status.json`` (root-owned, readable by the veyra group).

Usage: python -I -m veyra.updates.runner <version>
"""

from __future__ import annotations

import fcntl
import grp
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from veyra.core.config import Settings, get_settings
from veyra.core.semver import Version
from veyra.core.signing import Keyring
from veyra.updates import manager
from veyra.updates.metadata import MetadataError, verify_metadata
from veyra.updates.release import source_version
from veyra.version import __version__

MAX_MEMBERS = 50_000
MAX_UNPACKED = 2 * 1024**3
VEYRA_CLI = "/usr/local/bin/veyra"
STEP_RE = re.compile(r"==>\s*(?:\x1b\[[0-9;]*m)*\s*(.+?)(?:\x1b\[[0-9;]*m)*\s*$")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class RunnerError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class Status:
    """status.json, replaced atomically in the root-owned directory."""

    def __init__(self, directory: Path, version: str, group: str = "veyra") -> None:
        self.path = directory / "status.json"
        self.data: dict[str, Any] = {
            "version": version,
            "from_version": __version__,
            "state": "running",
            "step": "Checking the release",
            "started_at": _now(),
            "finished_at": None,
            "error": None,
            "log_tail": [],
            "log_file": None,
        }
        try:
            self.gid: int | None = grp.getgrnam(group).gr_gid
        except KeyError:
            self.gid = None
        self.write()

    def update(self, **kw: Any) -> None:
        self.data.update(kw)
        self.write()

    def write(self) -> None:
        tmp = self.path.with_name(f".status.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o640)
        with os.fdopen(fd, "w") as f:
            json.dump(self.data, f, indent=2)
        if self.gid is not None and os.geteuid() == 0:
            os.chown(tmp, 0, self.gid)
        os.replace(tmp, self.path)


def _read_regular(path: Path, limit: int) -> bytes:
    """Read a file the service account controls without following links."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        raise RunnerError(f"{path.name} is missing or not a regular file") from e
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise RunnerError(f"{path.name} is not a regular file")
        data = f.read(limit + 1)
    if len(data) > limit:
        raise RunnerError(f"{path.name} is too large")
    return data


def _copy_checked(src: Path, dest: Path, size: int, sha256: str) -> None:
    try:
        fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        raise RunnerError("The downloaded release is missing") from e
    h, total = hashlib.sha256(), 0
    with os.fdopen(fd, "rb") as f, dest.open("xb") as out:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise RunnerError("The downloaded release is not a regular file")
        while chunk := f.read(1 << 20):
            total += len(chunk)
            if total > size:
                break
            h.update(chunk)
            out.write(chunk)
    if total != size or h.hexdigest() != sha256:
        raise RunnerError("The downloaded release does not match the signed size and checksum")


def _extract(artifact: Path, dest: Path, version: str) -> Path:
    top = f"veyra-{version}"
    total = 0
    with tarfile.open(artifact, "r:gz") as tar:
        members = tar.getmembers()
        if len(members) > MAX_MEMBERS:
            raise RunnerError("The release archive has too many entries")
        for m in members:
            parts = Path(m.name).parts
            if not parts or parts[0] != top or ".." in parts or m.name.startswith("/"):
                raise RunnerError(f"Unexpected path in the release archive: {m.name!r}")
            if not (m.isfile() or m.isdir() or m.issym()):
                raise RunnerError(f"Unexpected entry type in the release archive: {m.name!r}")
            total += m.size
        if total > MAX_UNPACKED:
            raise RunnerError("The release archive unpacks to more than 2 GB")
        # "data": no absolute paths, no links leaving the tree, no special
        # files, no set-uid bits.
        tar.extractall(dest, filter="data")
    tree = dest / top
    if source_version(tree) != version:
        raise RunnerError("The archive's version does not match the signed version")
    return tree


def verify_and_unpack(settings: Settings, version: str, work: Path) -> Path:
    src = manager.version_dir(settings, version)
    body = _read_regular(src / manager.METADATA_NAME, manager.MAX_METADATA_BYTES)
    sig = _read_regular(src / (manager.METADATA_NAME + ".sig"), 64 * 1024).decode(
        "utf-8", "replace"
    )
    try:
        meta = verify_metadata(body, sig, Keyring.load(settings.trust_dir))
        rel = manager.core_release(meta, version)
    except (MetadataError, manager.UpdateError) as e:
        raise RunnerError(str(e)) from e
    assert rel.artifact is not None
    if Version.parse(version) <= Version.parse(__version__):
        raise RunnerError(f"{version} is not newer than the installed {__version__}")
    if rel.min_from_version and Version.parse(__version__) < Version.parse(rel.min_from_version):
        raise RunnerError(f"{version} can only be installed from {rel.min_from_version} or later")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, mode=0o700)
    artifact = work / "release.tar.gz"
    _copy_checked(src / manager.ARTIFACT_NAME, artifact, rel.artifact.size, rel.artifact.sha256)
    return _extract(artifact, work, version)


def run_upgrade(tree: Path, status: Status, log_file: Path) -> int:
    tail: deque[str] = deque(maxlen=40)
    env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/root",
        "LANG": "C.UTF-8",
        "NO_COLOR": "1",
        "VEYRA_UPGRADE_INITIATED_BY": "Veyra updates",
    }
    with log_file.open("a") as log:
        proc = subprocess.Popen(  # noqa: S603
            ["/bin/bash", str(tree / "installer" / "upgrade.sh"), "--yes"],
            cwd=tree,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            log.write(line)
            log.flush()
            clean = ANSI_RE.sub("", line.rstrip())
            if clean:
                tail.append(clean)
            m = STEP_RE.search(line.rstrip())
            status.update(
                log_tail=list(tail), **({"step": ANSI_RE.sub("", m.group(1)).strip()} if m else {})
            )
        return proc.wait()


def _record_failure(version: str) -> None:
    if not os.path.exists(VEYRA_CLI):
        return
    subprocess.run(  # noqa: S603
        [
            VEYRA_CLI,
            "updates",
            "record",
            "--component",
            "veyra_core",
            "--target",
            "veyra",
            "--from-version",
            __version__,
            "--to-version",
            version,
            "--outcome",
            "failed",
            "--initiated-by",
            "Veyra updates",
        ],
        capture_output=True,
        timeout=60,
        check=False,
    )


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not manager.VERSION_RE.match(args[0]):
        print("usage: veyra-upgrade-run <version>", file=sys.stderr)
        return 2
    version = args[0]
    settings = settings or get_settings()
    updir = settings.upgrade_dir
    updir.mkdir(parents=True, exist_ok=True)
    lock = (updir / "lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another upgrade is running.", file=sys.stderr)
        return 1
    status = Status(updir, version)
    work = updir / "work" / version
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    log_file = settings.log_dir / f"upgrade-run-{version}-{stamp}.log"
    status.update(log_file=str(log_file))
    rc = 1
    try:
        tree = verify_and_unpack(settings, version, work)
        status.update(step="Running the release's upgrade")
        rc = run_upgrade(tree, status, log_file)
        if rc == 0:
            status.update(state="succeeded", step="Finished", finished_at=_now())
        else:
            status.update(
                state="failed",
                finished_at=_now(),
                error=f"upgrade.sh failed during '{status.data['step']}' (exit {rc}). "
                f"Log: {log_file}",
            )
    except (RunnerError, OSError, ValueError, tarfile.TarError) as e:
        status.update(state="failed", finished_at=_now(), error=str(e))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if status.data["state"] != "succeeded":
        _record_failure(version)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
