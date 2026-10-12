# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration revisions: generate, validate, queue, deploy, roll back.

The API only *creates* revisions and *requests* deployments (state
``deploying``). The deployer service, a separate process with write access
to the engine's include directory, performs the deployment:

    write files atomically -> targeted reloads -> verify -> deployed
    on any failure: restore the previous files -> reload -> failed

At most one revision is ``deployed`` at a time. Deploying an older
(superseded) revision again is the rollback path.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.configmgmt.revisions import RevisionState, content_hash, diff, transition
from veyra.core import audit
from veyra.core.models import ConfigRevision
from veyra.core.models.base import utcnow
from veyra.telephony.adapter import (
    EngineUnavailable,
    GeneratedFile,
    NotSupported,
    TelephonyAdapter,
)
from veyra.telephony.snapshot import build_snapshot

log = logging.getLogger("veyra.configmgmt")

FILE_MODE = 0o640


# ----------------------------------------------------------------- artifacts


def files_to_artifacts(files: list[GeneratedFile]) -> dict[str, Any]:
    return {
        "files": [{"path": f.path, "content": f.content, "sensitive": f.sensitive} for f in files]
    }


def artifacts_to_files(artifacts: dict[str, Any]) -> list[GeneratedFile]:
    return [
        GeneratedFile(str(f["path"]), str(f["content"]), bool(f.get("sensitive", False)))
        for f in artifacts.get("files", [])
    ]


def current_deployed(db: Session, engine: str) -> ConfigRevision | None:
    return db.scalar(
        select(ConfigRevision)
        .where(ConfigRevision.engine == engine, ConfigRevision.state == RevisionState.DEPLOYED)
        .order_by(ConfigRevision.sequence.desc())
        .limit(1)
    )


def pending(db: Session, engine: str) -> ConfigRevision | None:
    return db.scalar(
        select(ConfigRevision)
        .where(ConfigRevision.engine == engine, ConfigRevision.state == RevisionState.DEPLOYING)
        .order_by(ConfigRevision.sequence)
        .limit(1)
    )


# ----------------------------------------------------------------- create


@dataclass
class Generated:
    revision: ConfigRevision
    files: list[GeneratedFile]
    diff: dict[str, Any]
    unchanged: bool


def create_revision(
    db: Session,
    adapter: TelephonyAdapter,
    *,
    created_by: str,
    summary: str = "",
) -> Generated:
    """Generate configuration from the database and record it as a revision.

    The revision is ``validated`` when the static checks pass and ``failed``
    (with the problems in ``validation_errors``) when they do not, so that a
    bad revision is visible in the history and can never be deployed.
    """
    snapshot = build_snapshot(db)
    deployed = current_deployed(db, adapter.name)
    previous_files = artifacts_to_files(deployed.artifacts) if deployed else []
    errors: list[str] = []
    files: list[GeneratedFile] = []
    try:
        files = adapter.generate_config(snapshot)
        errors = adapter.validate_config(files)
    except NotSupported as e:
        errors = [str(e)]
    except ValueError as e:  # GenerationError and pydantic validation
        errors = [str(e)]
    changes = diff(previous_files, files) if not errors else {}
    unchanged = deployed is not None and not errors and content_hash(files) == deployed.content_hash
    if not summary:
        if errors:
            summary = "Generation failed"
        elif unchanged:
            summary = "No change from the deployed configuration"
        else:
            summary = f"{len(changes)} file(s) changed" if deployed else "Initial configuration"
    rev = ConfigRevision(
        id=uuid.uuid4(),
        engine=adapter.name,
        state=RevisionState.FAILED if errors else RevisionState.VALIDATED,
        summary=summary,
        content_hash=content_hash(files) if not errors else None,
        artifacts=files_to_artifacts(files) if not errors else {"files": []},
        validation_errors=errors,
        parent_id=deployed.id if deployed else None,
        created_by=created_by,
        created_at=utcnow(),
    )
    db.add(rev)
    db.flush()
    return Generated(rev, files, changes, unchanged)


def request_deploy(db: Session, rev: ConfigRevision) -> None:
    """Queue a validated (or superseded, for rollback) revision for the deployer."""
    if pending(db, rev.engine) is not None:
        raise RuntimeError("Another deployment is already in progress.")
    rev.state = transition(rev.state, RevisionState.DEPLOYING)
    db.flush()


# ----------------------------------------------------------------- deploy


class DeployError(RuntimeError):
    pass


def _write_atomic(path: Path, content: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, FILE_MODE)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def read_directory(config_dir: Path, managed: list[str]) -> dict[str, str]:
    """Current content of the managed files on disk (missing files are absent)."""
    out: dict[str, str] = {}
    for name in managed:
        p = config_dir / name
        try:
            out[name] = p.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
    return out


def write_files(config_dir: Path, managed: list[str], files: list[GeneratedFile]) -> list[str]:
    """Write the files and remove managed files that are no longer produced.
    Returns the names whose on-disk content changed."""
    before = read_directory(config_dir, managed)
    wanted = {f.path: f.content for f in files}
    changed: list[str] = []
    for name, content in wanted.items():
        if name not in managed:
            raise DeployError(f"refusing to write unmanaged file {name!r}")
        if before.get(name) != content:
            _write_atomic(config_dir / name, content)
            changed.append(name)
    for name in managed:
        if name not in wanted and name in before:
            (config_dir / name).unlink(missing_ok=True)
            changed.append(name)
    return changed


def restore_files(config_dir: Path, managed: list[str], previous: dict[str, str]) -> None:
    for name in managed:
        p = config_dir / name
        if name in previous:
            _write_atomic(p, previous[name])
        else:
            p.unlink(missing_ok=True)


class Deployer:
    """Applies queued revisions. Run by ``veyra deployer`` (systemd unit
    veyra-deployer) or directly in tests."""

    def __init__(self, adapter: TelephonyAdapter, config_dir: Path) -> None:
        self.adapter = adapter
        self.config_dir = config_dir

    def run_once(self, db: Session) -> ConfigRevision | None:
        rev = pending(db, self.adapter.name)
        if rev is None:
            return None
        self.deploy(db, rev)
        return rev

    def deploy(self, db: Session, rev: ConfigRevision) -> None:
        managed = self.adapter.managed_files()
        files = artifacts_to_files(rev.artifacts)
        previous_on_disk = read_directory(self.config_dir, managed)
        previous_rev = current_deployed(db, rev.engine)
        log_lines: list[str] = []
        try:
            if not self.config_dir.is_dir():
                raise DeployError(f"configuration directory {self.config_dir} does not exist")
            changed = write_files(self.config_dir, managed, files)
            log_lines.append(f"wrote {len(changed)} changed file(s): {', '.join(changed) or '-'}")
            scopes = self.adapter.reload_scopes(changed)
            for scope in scopes:
                self.adapter.reload(scope)
                log_lines.append(f"reloaded {scope}")
            problems = self.adapter.verify_loaded(scopes)
            if problems:
                raise DeployError("; ".join(problems))
        except (DeployError, EngineUnavailable, OSError) as e:
            log.error("Deployment of revision %s failed: %s", rev.sequence, e)
            try:
                restore_files(self.config_dir, managed, previous_on_disk)
                for scope in self.adapter.reload_scopes(managed):
                    self.adapter.reload(scope)
                log_lines.append("restored the previous files and reloaded")
            except (EngineUnavailable, OSError) as restore_error:
                log_lines.append(f"restore failed: {restore_error}")
                log.error("Restore after failed deployment also failed: %s", restore_error)
            rev.state = transition(rev.state, RevisionState.FAILED)
            rev.validation_errors = [str(e), *log_lines]
            db.flush()
            self._audit(db, rev, "failure", {"error": str(e), "log": log_lines})
            db.commit()
            return
        now = utcnow()
        if previous_rev is not None and previous_rev.id != rev.id:
            # Deploying an older revision again is a rollback of the newer one.
            target = (
                RevisionState.ROLLED_BACK
                if previous_rev.sequence > rev.sequence
                else RevisionState.SUPERSEDED
            )
            previous_rev.state = transition(previous_rev.state, target)
        rev.state = transition(rev.state, RevisionState.DEPLOYED)
        rev.deployed_at = now
        rev.validation_errors = log_lines
        db.flush()
        self._audit(db, rev, "success", {"log": log_lines})
        db.commit()
        log.info("Deployed configuration revision %s", rev.sequence)

    @staticmethod
    def _audit(db: Session, rev: ConfigRevision, outcome: str, details: dict[str, Any]) -> None:
        audit.record(
            db,
            action="telephony.config_deploy",
            outcome=outcome,
            actor_type="system",
            actor_label="deployer",
            target_type="config_revision",
            target_id=rev.id,
            details={"sequence": rev.sequence, "engine": rev.engine, **details},
        )
