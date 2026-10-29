# SPDX-License-Identifier: AGPL-3.0-or-later
"""The root backup runner (docs/PRODUCTION_HARDENING.md §2): takes the
parts, writes the manifest, verifies by restoring the dump into a scratch
database, encrypts to the administrator's age recipients, copies, prunes
and records the result through ``veyra backup record`` as the service
account. Runs from ``veyra-backup@<instance>.service`` or
``sudo veyra backup run``.

Every command goes through a runner callable so the sequence is testable
without root.
"""

from __future__ import annotations

import contextlib
import grp
import hashlib
import json
import logging
import os
import shlex
import shutil
import socket
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from veyra import __version__
from veyra.backups import destinations, policy

log = logging.getLogger("veyra.backup")

STORE = Path("/var/backups/veyra")
STATUS_DIR = Path("/var/lib/veyra-backup")
SCRATCH_DB = "veyra_restore_test"
VEYRA_CLI = "/usr/local/bin/veyra"
VOICEMAIL = Path("/var/spool/asterisk/voicemail")
ASTERISK_ETC = Path("/etc/asterisk")
# Tables whose row counts the restore test compares with the live database.
COUNTED_TABLES = (
    "users",
    "organizations",
    "sites",
    "extensions",
    "devices",
    "sip_trunks",
    "outbound_routes",
    "audit_log",
)


class BackupError(RuntimeError):
    pass


@dataclass
class Result:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[[Sequence[str]], Result]


def subprocess_runner(timeout: float = 3600) -> Runner:
    def run(argv: Sequence[str]) -> Result:
        try:
            p = subprocess.run(  # noqa: S603 - fixed argv built here
                list(argv), capture_output=True, text=True, timeout=timeout, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return Result(127, "", str(e))
        return Result(p.returncode, p.stdout, p.stderr)

    return run


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class Status:
    """``status.json`` for the page, root-owned, readable by the veyra group."""

    def __init__(self, directory: Path, kind: str) -> None:
        self.path = directory / "status.json"
        self.data: dict[str, Any] = {
            "kind": kind,
            "state": "running",
            "step": "Starting",
            "started_at": _now().isoformat(),
            "finished_at": None,
            "error": None,
            "backup": None,
        }
        try:
            self.gid: int | None = grp.getgrnam("veyra").gr_gid
        except KeyError:
            self.gid = None
        self.write()

    def update(self, **kw: Any) -> None:
        self.data.update(kw)
        self.write()

    def write(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f".status.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(self.data, indent=2))
            os.chmod(tmp, 0o640)
            if self.gid is not None and os.geteuid() == 0:
                os.chown(tmp, 0, self.gid)
            os.replace(tmp, self.path)
        except OSError:
            log.warning("Could not write %s", self.path)


@dataclass
class Backup:
    """One backup being taken."""

    kind: str
    settings: dict[str, Any]
    store: Path = STORE
    run: Runner = field(default_factory=subprocess_runner)
    data_dir: Path = Path("/var/lib/veyra")
    config_dir: Path = Path("/etc/veyra")
    asterisk_etc: Path = ASTERISK_ETC
    voicemail: Path = VOICEMAIL
    database: str = "veyra"
    created_by: str = "scheduler"
    now: datetime = field(default_factory=_now)
    name: str = ""
    workdir: Path = field(init=False)
    parts: list[dict[str, Any]] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    verify: dict[str, Any] = field(default_factory=dict)
    copies: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = self.name or policy.stamp(self.now)
        self.workdir = self.store / self.name

    # --- helpers

    def _pg(self, *argv: str) -> Result:
        return self.run(["runuser", "-u", "postgres", "--", *argv])

    def _sql(self, statement: str, database: str | None = None) -> Result:
        return self._pg("psql", "-X", "-qtA", "-d", database or self.database, "-c", statement)

    def _check(self, r: Result, what: str) -> None:
        if not r.ok:
            raise BackupError(f"{what}: {(r.stderr or r.stdout).strip()[:500]}")

    def _part(self, name: str, path: Path) -> None:
        self.parts.append({"name": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})

    # --- parts

    def dump(self) -> None:
        for t in COUNTED_TABLES:
            r = self._sql(f"SELECT count(*) FROM {t}")  # noqa: S608 - fixed names
            if r.ok and r.stdout.strip().isdigit():
                self.counts[t] = int(r.stdout.strip())
        out = self.workdir / "db.dump"
        # Through the shell so the dump (binary) never passes the text runner.
        r = self.run(
            [
                "bash",
                "-c",
                f"runuser -u postgres -- pg_dump -Fc --no-owner {self.database} > {out}",
            ]
        )
        self._check(r, "pg_dump")
        os.chmod(out, 0o600)
        self._part("db.dump", out)

    def tar(self, name: str, root: Path, members: list[str]) -> None:
        present = [m for m in members if (root / m).exists()]
        if not present:
            return
        out = self.workdir / name
        r = self.run(["tar", "--xattrs", "--acls", "-C", str(root), "-cf", str(out), *present])
        self._check(r, name)
        os.chmod(out, 0o600)
        self._part(name, out)

    def take_parts(self) -> None:
        self.workdir.mkdir(parents=True, exist_ok=False)
        os.chmod(self.workdir, 0o700)
        self.dump()
        self.tar("etc.tar", self.config_dir.parent, [self.config_dir.name])
        self.tar("engine.tar", self.asterisk_etc.parent, [self.asterisk_etc.name])
        self.tar(
            "data.tar",
            self.data_dir,
            ["prompts", "moh", "firmware", "provisioning/templates", "modules", "module-store"],
        )
        self.tar("voicemail.tar", self.voicemail.parent, [self.voicemail.name])
        if self.settings.get("recordings"):
            self.tar("recordings.tar", self.data_dir, ["recordings"])

    def write_manifest(self) -> None:
        schema = self._sql("SELECT version_num FROM alembic_version").stdout.strip()
        instance = self._sql("SELECT instance_id FROM installation").stdout.strip()
        role = "standalone"
        node = self.data_dir / "ha" / "node.json"
        if node.exists():
            with contextlib.suppress(ValueError, OSError):
                role = str(json.loads(node.read_text()).get("role") or role)
        self.manifest = {
            "format": 1,
            "name": self.name,
            "kind": self.kind,
            "version": __version__,
            "schema": schema,
            "hostname": socket.gethostname(),
            "instance_id": instance,
            "ha_role": role,
            "started_at": self.now.isoformat(),
            "finished_at": _now().isoformat(),
            "parts": self.parts,
            "counts": self.counts,
        }
        out = self.workdir / "manifest.json"
        out.write_text(json.dumps(self.manifest, indent=2) + "\n")
        os.chmod(out, 0o600)

    # --- verification

    def restore_test(self) -> None:
        """Restore the dump into a scratch database and compare it."""
        checks: dict[str, Any] = {"restore": False, "schema": False, "counts": {}, "parts": {}}
        self._sql(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)', "postgres")
        r = self._sql(f'CREATE DATABASE "{SCRATCH_DB}" TEMPLATE template0', "postgres")
        self._check(r, "creating the scratch database")
        try:
            # The store is root-only, so the dump is fed on stdin (as in dump()).
            r = self.run(
                [
                    "bash",
                    "-c",
                    "runuser -u postgres -- pg_restore --no-owner --no-privileges "
                    f"-d {SCRATCH_DB} < {shlex.quote(str(self.workdir / 'db.dump'))}",
                ]
            )
            if not r.ok:
                raise BackupError(f"restore test: {r.stderr.strip()[:500]}")
            checks["restore"] = True
            schema = self._sql("SELECT version_num FROM alembic_version", SCRATCH_DB).stdout.strip()
            checks["schema"] = schema == self.manifest.get("schema")
            for t, n in self.counts.items():
                r = self._sql(f"SELECT count(*) FROM {t}", SCRATCH_DB)  # noqa: S608
                got = int(r.stdout.strip()) if r.ok and r.stdout.strip().isdigit() else -1
                checks["counts"][t] = {"live": n, "restored": got, "ok": got == n}
        finally:
            self._sql(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)', "postgres")
        for part in self.parts:
            path = self.workdir / part["name"]
            ok = sha256_file(path) == part["sha256"]
            if ok and part["name"].endswith(".tar"):
                ok = self.run(["tar", "-tf", str(path)]).ok
            checks["parts"][part["name"]] = ok
        good = (
            checks["restore"]
            and checks["schema"]
            and all(c["ok"] for c in checks["counts"].values())
            and all(checks["parts"].values())
        )
        checks["ok"] = good
        self.verify = checks
        if not good:
            raise BackupError("the backup did not verify: " + json.dumps(checks)[:400])

    # --- encryption, copies, pruning

    def encrypt(self) -> Path:
        """``age`` to the recipients; the plaintext directory is removed."""
        recipients = list(self.settings.get("recipients") or [])
        if not recipients:
            return self.workdir
        for r in recipients:
            if not policy.valid_recipient(r):
                raise BackupError(f"not an age recipient: {r[:20]}…")
        tarball = self.store / f"{self.name}.tar"
        r = self.run(["tar", "-C", str(self.store), "-cf", str(tarball), self.name])
        self._check(r, "packing the backup")
        out = self.store / f"{self.name}.tar.age"
        argv = ["age", "-o", str(out)]
        for rec in recipients:
            argv += ["-r", rec]
        argv.append(str(tarball))
        r = self.run(argv)
        tarball.unlink(missing_ok=True)
        self._check(r, "age")
        os.chmod(out, 0o600)
        shutil.rmtree(self.workdir, ignore_errors=True)
        return out

    def copy(self, known: list[dict[str, Any]]) -> None:
        """Bring every enabled destination in line (§2.7): copy the verified
        backups it is missing, this one included, and prune it. A failed
        copy does not fail the backup; it is retried at the next run."""
        verified = {
            str(k["name"]): str(k.get("kind") or "scheduled")
            for k in known
            if k.get("state") == "verified"
        }
        verified[self.name] = self.kind
        for dest in self.settings.get("destinations") or []:
            if not dest.get("enabled", True):
                continue
            try:
                rem = destinations.remote(
                    dest,
                    secret=dest.get("secret"),
                    ssh_private_key=self.settings.get("ssh_private_key"),
                )
                result = destinations.sync(
                    rem,
                    store=self.store,
                    verified=verified,
                    keep=destinations.keep_for(dest, self.settings),
                    now=self.now,
                )
            except (destinations.DestinationError, OSError) as e:
                result = {"state": "failed", "at": _now().isoformat(), "error": str(e)[:1000]}
            result["name"] = dest.get("name") or dest["id"]
            self.copies[str(dest["id"])] = result

    def prune(self, known: list[dict[str, Any]]) -> list[str]:
        """Apply the keep policy to the store; ``known`` are the recorded
        backups (name, kind) so kinds are not guessed from names."""
        kinds = {str(k["name"]): str(k.get("kind") or "scheduled") for k in known}
        entries: list[policy.Entry] = []
        for p in self.store.iterdir():
            e = policy.Entry.parse(p.name, kinds.get(p.name.split(".")[0], "scheduled"))
            if e is not None:
                entries.append(policy.Entry(p.name, e.kind, e.at))
        removed: list[str] = []
        for e in policy.to_delete(entries, self.settings.get("keep") or {}, self.now):
            p = self.store / e.name
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
            removed.append(e.name)
        return removed

    def total_bytes(self) -> int:
        return sum(int(p["bytes"]) for p in self.parts)


def record(run: Runner, payload: dict[str, Any]) -> Result:
    """``veyra backup record`` as the service account."""
    return run(
        [
            "runuser",
            "-u",
            "veyra",
            "--",
            VEYRA_CLI,
            "backup",
            "record",
            "--json",
            json.dumps(payload, default=str),
        ]
    )


def load_settings(run: Runner) -> dict[str, Any]:
    """The backup settings through the service account (root has no database)."""
    r = run(
        ["runuser", "-u", "veyra", "--", VEYRA_CLI, "backup", "settings", "--json", "--secrets"]
    )
    if not r.ok:
        raise BackupError(f"reading the backup settings: {(r.stderr or r.stdout).strip()[:300]}")
    try:
        data = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as e:
        raise BackupError("the backup settings are not JSON") from e
    data = data if isinstance(data, dict) else {}
    out = policy.settings_doc(data)
    # The decrypted secrets (``--secrets``) the document itself does not carry.
    if data.get("ssh_private_key"):
        out["ssh_private_key"] = str(data["ssh_private_key"])
    return out


def known_backups(run: Runner) -> list[dict[str, Any]]:
    """The recorded backups (id, name, kind, state) through the service account."""
    r = run(["runuser", "-u", "veyra", "--", VEYRA_CLI, "backup", "list", "--json"])
    if not r.ok:
        return []
    try:
        rows = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return []
    return [x for x in rows if isinstance(x, dict) and x.get("name")]


def run_backup(
    kind: str,
    *,
    created_by: str = "scheduler",
    run: Runner | None = None,
    store: Path = STORE,
    status_dir: Path = STATUS_DIR,
    settings: dict[str, Any] | None = None,
    data_dir: Path = Path("/var/lib/veyra"),
    config_dir: Path = Path("/etc/veyra"),
    asterisk_etc: Path = ASTERISK_ETC,
    voicemail: Path = VOICEMAIL,
) -> dict[str, Any]:
    """The whole sequence; returns the record payload."""
    run = run or subprocess_runner()
    status = Status(status_dir, kind)
    if settings is None:
        settings = load_settings(run)
    else:
        settings = {**settings, **policy.settings_doc(settings)}
    b = Backup(
        kind,
        settings,
        store,
        run,
        data_dir,
        config_dir,
        asterisk_etc,
        voicemail,
        created_by=created_by,
    )
    payload: dict[str, Any] = {
        "name": b.name,
        "kind": kind,
        "started_at": b.now.isoformat(),
        "created_by": created_by,
        "path": str(b.workdir),
        "encrypted": bool(settings.get("recipients")),
        "recipients": [policy_fingerprint(r) for r in settings.get("recipients") or []],
    }
    try:
        store.mkdir(parents=True, exist_ok=True)
        os.chmod(store, 0o700)
        status.update(step="Dumping the database and packing the files")
        b.take_parts()
        b.write_manifest()
        status.update(step="Verifying (restore test)")
        b.restore_test()
        status.update(step="Encrypting" if settings.get("recipients") else "Finishing")
        artifact = b.encrypt()
        known = known_backups(run)
        status.update(step="Pruning")
        removed = b.prune(known)
        if settings.get("destinations"):
            status.update(step="Copying to the destinations")
            b.copy(known)
        payload.update(
            {
                "state": "verified",
                "path": str(artifact),
                "bytes": b.total_bytes(),
                "parts": b.parts,
                "manifest": b.manifest,
                "verify": b.verify,
                "copies": b.copies,
                "removed": removed,
                "finished_at": _now().isoformat(),
            }
        )
        status.update(state="finished", step="Done", finished_at=_now().isoformat(), backup=b.name)
    except Exception as e:
        log.exception("Backup failed")
        payload.update(
            {
                "state": "failed",
                "error": str(e)[:1000],
                "parts": b.parts,
                "verify": b.verify,
                "copies": b.copies,
                "finished_at": _now().isoformat(),
            }
        )
        status.update(state="failed", error=str(e)[:500], finished_at=_now().isoformat())
    r = record(run, payload)
    if not r.ok:
        log.error("Could not record the backup: %s", (r.stderr or r.stdout).strip()[:300])
    return payload


def policy_fingerprint(recipient: str) -> str:
    """A short, non-secret handle of a recipient for the list."""
    return recipient.strip()[:16] + "…"


def delete_backup(
    name: str, *, store: Path = STORE, settings: dict[str, Any] | None = None
) -> bool:
    """Remove a backup's files (root) here and, best effort, from every
    destination; the row is marked by the caller."""
    if not policy.STAMP_RE.fullmatch(name.split(".")[0]):
        raise BackupError("not a backup name")
    found = False
    for p in (store / name, store / f"{name}.tar.age"):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            found = True
        elif p.exists():
            p.unlink()
            found = True
    settings = settings or {}
    for dest in settings.get("destinations") or []:
        try:
            rem = destinations.remote(
                dest,
                secret=dest.get("secret"),
                ssh_private_key=settings.get("ssh_private_key"),
            )
            for candidate in (name, f"{name}.tar.age"):
                if candidate in rem.names():
                    rem.delete(candidate)
        except (destinations.DestinationError, OSError) as e:
            log.warning("Could not delete %s from %s: %s", name, dest.get("name"), e)
    return found
