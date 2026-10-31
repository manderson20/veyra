# SPDX-License-Identifier: AGPL-3.0-or-later
"""``sudo veyra backup restore`` (docs/PRODUCTION_HARDENING.md §2.5): bring a
server back from a backup directory or an encrypted ``.tar.age`` file."""

from __future__ import annotations

import json
import logging
import os
import pwd
import re
import shlex
import shutil
import stat
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from veyra import __version__
from veyra.backups import policy
from veyra.backups.runner import (
    ASTERISK_ETC,
    SERVICE_GROUP,
    STATUS_DIR,
    STORE,
    VEYRA_CLI,
    VOICEMAIL,
    BackupError,
    Result,
    known_backups,
    record,
    run_backup,
    sha256_file,
)

log_ = logging.getLogger(__name__)

ALL_PARTS = ("db", "etc", "engine", "data", "voicemail", "recordings")
SERVICES = ("veyra-api", "veyra-worker", "veyra-deployer", "veyra-pager", "veyra-firewall")
# The web restore (issue #348). The request is the service account's, on its own
# tmpfs directory (gone when the API stops), and carries the age identity.
REQUEST = Path("/run/veyra-restore/request.json")
REQUEST_MAX = 64 * 1024
# nginx serves this file while the API is stopped; nothing secret goes in it.
PUBLIC_STATUS_DIR = Path("/var/lib/veyra-restore")
IDENTITY_RE = re.compile(r"^AGE-SECRET-KEY-1[0-9A-Z]+$")
STEPS = {
    "Database": "Restoring the database",
    "etc.tar": "Restoring the configuration and secrets",
    "engine.tar": "Restoring the phone system's files",
    "data.tar": "Restoring prompts, music and other data",
    "voicemail.tar": "Restoring voicemail",
    "recordings.tar": "Restoring call recordings",
    "Migrations": "Upgrading the database",
    "Services": "Starting the services",
}


def _version(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("-")[0].split("."))


def check_manifest(manifest: dict[str, Any], running_version: str = __version__) -> list[str]:
    """Why this backup cannot be restored here (empty = fine)."""
    problems: list[str] = []
    if manifest.get("format") != 1:
        problems.append("unknown backup format")
    v = str(manifest.get("version") or "")
    try:
        # Every patch release may add migrations this code does not know.
        if _version(v) > _version(running_version):
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
    work_root: Path | None = None,
    before_stop: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """The procedure of §2.5. Stops the services, restores, migrates, restarts.
    ``before_stop`` runs once the backup has passed its checks; if it raises,
    nothing has changed."""
    unknown = [p for p in parts if p not in ALL_PARTS]
    if unknown:
        raise BackupError(f"unknown parts: {', '.join(unknown)}")
    done: dict[str, Any] = {"parts": []}
    with tempfile.TemporaryDirectory(prefix="veyra-restore-", dir=work_root) as tmp:
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
        if before_stop is not None:
            before_stop()
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
            # The backup directory is root-only, so the dump is fed on stdin.
            # --role: the objects must belong to the service role, not to
            # postgres, or the application cannot read its own tables.
            r = run(
                [
                    "bash",
                    "-c",
                    "runuser -u postgres -- pg_restore --no-owner --no-privileges "
                    f"--role {shlex.quote(database)} -d {shlex.quote(database)} "
                    f"< {shlex.quote(str(directory / 'db.dump'))}",
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
        log("Services")
        run(["systemctl", "daemon-reload"])
        r = run(["systemctl", "start", *SERVICES])
        done["started"] = r.ok
        if "engine" in done["parts"]:
            run(["systemctl", "restart", "asterisk"])
        if source.is_dir() is False:
            shutil.rmtree(directory, ignore_errors=True)
    done["manifest"] = manifest
    return done


# ------------------------------------------------------------------ from the web


class RestoreStatus:
    """Progress for the page: the whole of it for the API, and a part with no
    error text for nginx to serve while the API is stopped."""

    PUBLIC = ("id", "state", "step", "stopped", "safety_backup", "started_at", "finished_at")

    def __init__(self, status_dir: Path, public_dir: Path, restore_id: str) -> None:
        self.status_dir, self.public_dir = status_dir, public_dir
        self.data: dict[str, Any] = {
            "id": restore_id,
            "state": "running",
            "step": "Checking the backup",
            "stopped": False,
            "started_at": datetime.now(UTC).isoformat(),
        }

    def update(self, **kw: Any) -> None:
        self.data.update(kw)
        self._write(self.status_dir / "restore.json", self.data, 0o640, SERVICE_GROUP)
        public = {k: self.data.get(k) for k in self.PUBLIC}
        self._write(self.public_dir / "status.json", public, 0o644, "root")

    @staticmethod
    def _write(path: Path, data: dict[str, Any], mode: int, group: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(json.dumps(data))
        os.chmod(tmp, mode)
        if os.geteuid() == 0:
            shutil.chown(tmp, "root", group)
        tmp.replace(path)


def read_request(path: Path = REQUEST, owner: str | None = "veyra") -> dict[str, Any]:
    """The service account's request, read once and removed. It comes from a
    less trusted account: a regular file of that account's, no link followed."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as e:
        raise BackupError("no restore was requested") from e
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > REQUEST_MAX:
            raise BackupError("the restore request is not valid")
        if owner is not None and st.st_uid != pwd.getpwnam(owner).pw_uid:
            raise BackupError("the restore request is not the service account's")
        with os.fdopen(os.dup(fd), "r") as f:
            data = json.loads(f.read(REQUEST_MAX))
    except (OSError, ValueError) as e:
        raise BackupError("the restore request is not valid") from e
    finally:
        os.close(fd)
        path.unlink(missing_ok=True)
    if not isinstance(data, dict):
        raise BackupError("the restore request is not valid")
    return data


def identity_lines(text: str) -> list[str]:
    """The age secret keys in what was pasted; comments are left behind."""
    lines = [line.strip() for line in text.splitlines()]
    return [line for line in lines if IDENTITY_RE.fullmatch(line)]


def restore_unit(
    backup_id: str,
    *,
    run: Callable[[Sequence[str]], Result],
    request: Path = REQUEST,
    request_owner: str | None = "veyra",
    store: Path = STORE,
    status_dir: Path = STATUS_DIR,
    public_dir: Path = PUBLIC_STATUS_DIR,
    backup: Callable[..., dict[str, Any]] = run_backup,
    **restore_args: Any,
) -> bool:
    """``veyra-backup@restore-<id>``. Only a backup in root's own store can be
    chosen: its name comes through the service account, so nothing but a stamp
    is accepted, and an uploaded file would let the web interface write as root
    anywhere under /etc. A safety backup comes first; the backup's own checks
    come before that, so a refused restore costs nothing."""
    request_data = read_request(request, request_owner)
    status = RestoreStatus(status_dir, public_dir, str(request_data.get("id") or ""))
    status.update()
    safety: dict[str, Any] = {}

    def before_stop() -> None:
        status.update(step="Taking a safety backup of this server")
        safety.update(backup("manual", created_by="before a restore", run=run, local_only=True))
        if safety.get("state") != "verified":
            raise BackupError(f"the safety backup failed: {safety.get('error') or 'unknown'}")
        status.update(safety_backup=safety.get("name"))
        run(["systemctl", "stop", "veyra-backup@run", "veyra-backup@run-manual"])
        status.update(step="Stopping the services", stopped=True)

    def step(message: str) -> None:
        if message in STEPS:
            status.update(step=STEPS[message])

    try:
        if str(request_data.get("backup_id")) != backup_id:
            raise BackupError("the restore request names another backup")
        match = [b for b in known_backups(run) if b.get("id") == backup_id]
        if not match:
            raise BackupError("unknown backup")
        name = str(match[0]["name"])
        if not policy.STAMP_RE.fullmatch(name):
            raise BackupError("not a backup name")
        status.update(backup=name)
        encrypted, folder = store / f"{name}.tar.age", store / name
        source = encrypted if encrypted.is_file() else folder
        if not source.exists():
            raise BackupError("the backup's files are gone from this server")
        with tempfile.TemporaryDirectory(prefix="veyra-identity-") as tmp:
            os.chmod(tmp, 0o700)
            identity: Path | None = None
            keys = identity_lines(str(request_data.get("identity") or ""))
            if keys:
                identity = Path(tmp) / "identity.txt"
                identity.touch(mode=0o600)
                identity.write_text("\n".join(keys) + "\n")
            out = restore(
                source,
                identity=identity,
                run=run,
                log=step,
                work_root=store,
                before_stop=before_stop,
                **restore_args,
            )
        if safety:
            # It was recorded in the database just replaced.
            record(run, safety)
        run(
            [
                "runuser",
                "-u",
                "veyra",
                "--",
                VEYRA_CLI,
                "backup",
                "restore-note",
                "--json",
                json.dumps(
                    {
                        "backup": name,
                        "safety_backup": safety.get("name"),
                        "actor": request_data.get("actor"),
                        "ip": request_data.get("ip"),
                        "parts": out["parts"],
                    }
                ),
            ]
        )
        started = bool(out.get("started"))
        status.update(
            state="finished" if started else "failed",
            step="Done" if started else "The services did not start",
            error=None if started else "The services did not start after the restore.",
            parts=out["parts"],
            finished_at=datetime.now(UTC).isoformat(),
        )
        return started
    except Exception as e:
        log_.exception("Restore failed")
        status.update(state="failed", error=str(e)[:500], finished_at=datetime.now(UTC).isoformat())
        if status.data["stopped"]:
            # Whatever state the data is in, the page should answer again.
            run(["systemctl", "start", *SERVICES])
        return False
