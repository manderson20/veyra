# SPDX-License-Identifier: AGPL-3.0-or-later
"""``sudo veyra backup restore`` (docs/PRODUCTION_HARDENING.md §2.5): bring a
server back from a backup directory or an encrypted ``.tar.age`` file."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from veyra import __version__
from veyra.backups.runner import (
    ASTERISK_ETC,
    VEYRA_CLI,
    VOICEMAIL,
    BackupError,
    Result,
    sha256_file,
)

ALL_PARTS = ("db", "etc", "engine", "data", "voicemail", "recordings")
SERVICES = ("veyra-api", "veyra-worker", "veyra-deployer", "veyra-pager", "veyra-firewall")


def _minor(version: str) -> tuple[int, int]:
    parts = version.split("-")[0].split(".")
    return int(parts[0]), int(parts[1])


def check_manifest(manifest: dict[str, Any], running_version: str = __version__) -> list[str]:
    """Why this backup cannot be restored here (empty = fine)."""
    problems: list[str] = []
    if manifest.get("format") != 1:
        problems.append("unknown backup format")
    v = str(manifest.get("version") or "")
    try:
        if _minor(v) > _minor(running_version):
            problems.append(f"the backup is from Veyra {v}, newer than {running_version}")
    except (ValueError, IndexError):
        problems.append("the backup's version is not readable")
    if manifest.get("ha_role") not in (None, "standalone"):
        problems.append(
            f"the backup was taken on an HA {manifest.get('ha_role')}; restore to a standalone"
        )
    return problems


def unpack(
    source: Path, identity: Path | None, run: Callable[[Sequence[str]], Result], work: Path
) -> Path:
    """The backup directory, decrypting an age file into ``work`` first."""
    if source.is_dir():
        return source
    if source.name.endswith(".tar.age"):
        if identity is None:
            raise BackupError("an encrypted backup needs --identity <age identity file>")
        tarball = work / "backup.tar"
        r = run(["age", "-d", "-i", str(identity), "-o", str(tarball), str(source)])
        if not r.ok:
            raise BackupError(f"age: {r.stderr.strip()[:300]}")
        r = run(["tar", "-C", str(work), "-xf", str(tarball)])
        tarball.unlink(missing_ok=True)
        if not r.ok:
            raise BackupError(f"unpacking: {r.stderr.strip()[:300]}")
        dirs = [p for p in work.iterdir() if p.is_dir()]
        if len(dirs) != 1:
            raise BackupError("the archive does not hold one backup directory")
        return dirs[0]
    raise BackupError("a backup is a directory or a .tar.age file")


def verify_parts(directory: Path, manifest: dict[str, Any]) -> None:
    for part in manifest.get("parts") or []:
        path = directory / str(part["name"])
        if not path.is_file() or sha256_file(path) != part["sha256"]:
            raise BackupError(f"{part['name']} is missing or altered")


def restore(
    source: Path,
    *,
    parts: Sequence[str] = ALL_PARTS,
    identity: Path | None = None,
    run: Callable[[Sequence[str]], Result],
    database: str = "veyra",
    data_dir: Path = Path("/var/lib/veyra"),
    config_dir: Path = Path("/etc/veyra"),
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """The procedure of §2.5. Stops the services, restores, migrates, restarts."""
    unknown = [p for p in parts if p not in ALL_PARTS]
    if unknown:
        raise BackupError(f"unknown parts: {', '.join(unknown)}")
    done: dict[str, Any] = {"parts": []}
    with tempfile.TemporaryDirectory(prefix="veyra-restore-") as tmp:
        work = Path(tmp)
        os.chmod(work, 0o700)
        directory = unpack(source, identity, run, work)
        try:
            manifest = json.loads((directory / "manifest.json").read_text())
        except (OSError, ValueError) as e:
            raise BackupError("manifest.json is missing or not JSON") from e
        problems = check_manifest(manifest)
        if problems:
            raise BackupError("; ".join(problems))
        verify_parts(directory, manifest)
        present = {str(p["name"]) for p in manifest.get("parts") or []}
        log(
            f"Restoring {manifest.get('name')} (Veyra {manifest.get('version')}, "
            f"schema {manifest.get('schema')})"
        )
        run(["systemctl", "stop", *SERVICES])
        if "db" in parts and "db.dump" in present:
            log("Database")
            pg = ["runuser", "-u", "postgres", "--"]
            r = run(
                [*pg, "psql", "-X", "-qc", f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)']
            )
            if not r.ok:
                raise BackupError(f"dropping the database: {r.stderr.strip()[:300]}")
            r = run([*pg, "createdb", "-O", database, "-E", "UTF8", database])
            if not r.ok:
                raise BackupError(f"creating the database: {r.stderr.strip()[:300]}")
            r = run(
                [
                    *pg,
                    "pg_restore",
                    "--no-owner",
                    "--no-privileges",
                    "-d",
                    database,
                    str(directory / "db.dump"),
                ]
            )
            if not r.ok:
                raise BackupError(f"pg_restore: {r.stderr.strip()[:300]}")
            r = run([*pg, "psql", "-X", "-qc", f'ALTER DATABASE "{database}" OWNER TO {database}'])
            run(
                [
                    *pg,
                    "psql",
                    "-X",
                    "-qd",
                    database,
                    "-c",
                    f"REASSIGN OWNED BY postgres TO {database}",
                ]
            )
            done["parts"].append("db")
        for key, name, root in (
            ("etc", "etc.tar", config_dir.parent),
            ("engine", "engine.tar", ASTERISK_ETC.parent),
            ("data", "data.tar", data_dir),
            ("voicemail", "voicemail.tar", VOICEMAIL.parent),
            ("recordings", "recordings.tar", data_dir),
        ):
            if key in parts and name in present:
                log(name)
                r = run(
                    ["tar", "--xattrs", "--acls", "-C", str(root), "-xpf", str(directory / name)]
                )
                if not r.ok:
                    raise BackupError(f"{name}: {r.stderr.strip()[:300]}")
                done["parts"].append(key)
        if "db" in done["parts"]:
            log("Migrations")
            r = run([VEYRA_CLI, "db", "upgrade"])
            if not r.ok:
                raise BackupError(f"migrations: {(r.stderr or r.stdout).strip()[:300]}")
        run(["systemctl", "daemon-reload"])
        r = run(["systemctl", "start", *SERVICES])
        done["started"] = r.ok
        if "engine" in done["parts"]:
            run(["systemctl", "restart", "asterisk"])
        if source.is_dir() is False:
            shutil.rmtree(directory, ignore_errors=True)
    done["manifest"] = manifest
    return done
