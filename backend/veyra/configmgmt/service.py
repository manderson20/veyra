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
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.configmgmt.revisions import (
    RevisionState,
    artifacts_to_files,
    content_hash,
    diff,
    files_to_artifacts,
    transition,
)
from veyra.core import audit
from veyra.core.models import ConfigRevision, SystemSetting
from veyra.core.models.base import utcnow
from veyra.core.security.crypto import InstallationKey, InstallationKeyError
from veyra.telephony.adapter import (
    Capability,
    EngineUnavailable,
    GeneratedFile,
    NotSupported,
    TelephonyAdapter,
)
from veyra.telephony.snapshot import build_snapshot

log = logging.getLogger("veyra.configmgmt")

FILE_MODE = 0o640
DEPLOY_NOW = "now"
DEPLOY_WHEN_IDLE = "when_idle"
DEPLOY_MODES = (DEPLOY_NOW, DEPLOY_WHEN_IDLE)
DEFAULT_IDLE_TIMEOUT = timedelta(minutes=30)


# ----------------------------------------------------------------- pending flag

PENDING_KEY = "telephony.pending_change"
# Per organization (docs/MULTI_TENANCY_MSP.md §7): the change an
# organization's administrators saved and the reason its last changes were
# held back.
ORG_PENDING_PREFIX = "telephony.pending_change.org."
HELD_BACK_PREFIX = "telephony.held_back.org."
ORG_APPLY_KEY = "telephony.org_apply"
ORG_APPLIES_KEY = "telephony.org_applies"
ORG_APPLY_MODES = ("apply", "request")
ORG_APPLY_EVERY = timedelta(minutes=5)
ORG_APPLIES_PER_HOUR = 12


def _set(db: Session, key: str, value: dict[str, Any]) -> None:
    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value


def _get(db: Session, key: str) -> dict[str, Any] | None:
    row = db.get(SystemSetting, key)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else None


def mark_changed(
    db: Session, *, by: str, what: str, organization_id: uuid.UUID | None = None
) -> None:
    """Record that something the engine configuration is built from was saved.

    The flag stays until a deployment runs (or an apply finds nothing to
    change), so the "Deploy changes" button is shown after every relevant
    save, whether or not the generated files turn out different. With
    ``organization_id`` the organization's own flag is set too, which its
    administrators see.
    """
    value = {"at": utcnow().isoformat(), "by": by, "what": what}
    _set(db, PENDING_KEY, value)
    if organization_id is not None:
        _set(db, f"{ORG_PENDING_PREFIX}{organization_id}", value)
    db.flush()


def clear_changed(db: Session) -> None:
    for row in db.scalars(
        select(SystemSetting).where(
            (SystemSetting.key == PENDING_KEY) | SystemSetting.key.startswith(ORG_PENDING_PREFIX)
        )
    ):
        db.delete(row)
    db.flush()


def pending_change(db: Session) -> dict[str, Any] | None:
    return _get(db, PENDING_KEY)


def organization_flags(db: Session, prefix: str) -> dict[uuid.UUID, dict[str, Any]]:
    """Per-organization rows under ``prefix`` (pending changes, held back)."""
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for row in db.scalars(select(SystemSetting).where(SystemSetting.key.startswith(prefix))):
        try:
            out[uuid.UUID(row.key[len(prefix) :])] = dict(row.value)
        except (ValueError, TypeError):
            continue
    return out


def org_apply_mode(db: Session) -> str:
    """Whether organization administrators apply their own changes or only
    request it (owner decision 3, docs/MULTI_TENANCY_MSP.md §13)."""
    mode = (_get(db, ORG_APPLY_KEY) or {}).get("mode")
    return mode if mode in ORG_APPLY_MODES else "apply"


def set_org_apply_mode(db: Session, mode: str) -> None:
    if mode not in ORG_APPLY_MODES:
        raise ValueError(f"unknown mode {mode!r}")
    _set(db, ORG_APPLY_KEY, {"mode": mode})
    db.flush()


def org_apply_wait(db: Session, organization_id: uuid.UUID) -> int:
    """Seconds until the organization may apply again: one apply per
    organization every five minutes, twelve an hour across organizations."""
    now = utcnow()
    from datetime import datetime

    recent = [
        (str(a.get("org")), datetime.fromisoformat(str(a["at"])))
        for a in (_get(db, ORG_APPLIES_KEY) or {}).get("applies", [])
        if a.get("at")
    ]
    recent = [(o, at) for o, at in recent if now - at < timedelta(hours=1)]
    waits = [0.0]
    mine = [at for o, at in recent if o == str(organization_id)]
    if mine:
        waits.append((max(mine) + ORG_APPLY_EVERY - now).total_seconds())
    if len(recent) >= ORG_APPLIES_PER_HOUR:
        oldest = sorted(at for _, at in recent)[len(recent) - ORG_APPLIES_PER_HOUR]
        waits.append((oldest + timedelta(hours=1) - now).total_seconds())
    return max(0, int(max(waits)) + (1 if max(waits) > 0 else 0))


def record_org_apply(db: Session, organization_id: uuid.UUID) -> None:
    now = utcnow()
    from datetime import datetime

    applies = [
        a
        for a in (_get(db, ORG_APPLIES_KEY) or {}).get("applies", [])
        if a.get("at") and now - datetime.fromisoformat(str(a["at"])) < timedelta(hours=1)
    ]
    applies.append({"org": str(organization_id), "at": now.isoformat()})
    _set(db, ORG_APPLIES_KEY, {"applies": applies})
    db.flush()


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
    held_back: dict[str, str] = field(default_factory=dict)


@dataclass
class _Generation:
    files: list[GeneratedFile]
    errors: list[str]
    snapshot: dict[str, Any] | None = None
    # Organizations (by slug) whose newer data was held back, with the reason.
    held_back: dict[str, str] = field(default_factory=dict)


def _try(
    adapter: TelephonyAdapter, snapshot: dict[str, Any]
) -> tuple[list[GeneratedFile], list[str]]:
    try:
        files = adapter.generate_config(snapshot)
        return files, adapter.validate_config(files)
    except NotSupported as e:
        return [], [str(e)]
    except ValueError as e:  # GenerationError and pydantic validation
        return [], [str(e)]


def _run(db: Session, adapter: TelephonyAdapter, key: InstallationKey | None) -> _Generation:
    """Generate from the database. When that fails and several organizations
    share the server, try each organization's last good data in turn
    (docs/MULTI_TENANCY_MSP.md §7)."""
    from veyra.configmgmt import slices

    try:
        snapshot = build_snapshot(db, key)
    except ValueError as e:  # SnapshotError
        return _Generation([], [str(e)])
    files, errors = _try(adapter, snapshot)
    if not errors:
        return _Generation(files, [], snapshot)
    found = slices.isolate(db, key, snapshot, errors, lambda snap: _try(adapter, snap)[1])
    if found is None:
        return _Generation(files, errors, snapshot)
    files, _ = _try(adapter, found.snapshot)
    return _Generation(files, [], found.snapshot, found.held_back)


def _generate(
    db: Session, adapter: TelephonyAdapter, key: InstallationKey | None
) -> tuple[list[GeneratedFile], list[str]]:
    """Generated files and the problems found (empty when valid)."""
    g = _run(db, adapter, key)
    return g.files, g.errors


def _note_held_back(db: Session, held: dict[str, str]) -> None:
    """Each organization's held-back reason, shown to its administrators;
    an organization that generates again loses its note."""
    from veyra.core.models import Organization

    ids = {o.slug: o.id for o in db.scalars(select(Organization))}
    current = organization_flags(db, HELD_BACK_PREFIX)
    for slug, error in held.items():
        if slug in ids:
            _set(db, f"{HELD_BACK_PREFIX}{ids[slug]}", {"error": error, "at": utcnow().isoformat()})
    keep = {ids[s] for s in held if s in ids}
    for org_id in current:
        if org_id not in keep:
            row = db.get(SystemSetting, f"{HELD_BACK_PREFIX}{org_id}")
            if row is not None:
                db.delete(row)
    db.flush()


def _previous_files(
    deployed: ConfigRevision | None, key: InstallationKey | None
) -> list[GeneratedFile]:
    if deployed is None:
        return []
    try:
        return artifacts_to_files(deployed.artifacts, key, deployed.id)
    except InstallationKeyError:
        # The diff against an unreadable deployed revision is reported as a
        # full change rather than hiding the problem.
        return []


def create_revision(
    db: Session,
    adapter: TelephonyAdapter,
    *,
    created_by: str,
    key: InstallationKey | None,
    summary: str = "",
) -> Generated:
    """Generate configuration from the database and record it as a revision.

    The revision is ``validated`` when the static checks pass and ``failed``
    (with the problems in ``validation_errors``) when they do not, so that a
    bad revision is visible in the history and can never be deployed.
    Sensitive files are stored encrypted with the installation key.
    """
    deployed = current_deployed(db, adapter.name)
    previous_files = _previous_files(deployed, key)
    generation = _run(db, adapter, key)
    files, errors = generation.files, generation.errors
    rev_id = uuid.uuid4()
    artifacts: dict[str, Any] = {"files": []}
    if not errors:
        try:
            artifacts = files_to_artifacts(files, key, rev_id)
        except InstallationKeyError as e:
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
        if generation.held_back:
            summary += "; held back: " + ", ".join(sorted(generation.held_back))
    rev = ConfigRevision(
        id=rev_id,
        engine=adapter.name,
        state=RevisionState.FAILED if errors else RevisionState.VALIDATED,
        summary=summary,
        content_hash=content_hash(files) if not errors else None,
        artifacts=artifacts,
        validation_errors=errors,
        parent_id=deployed.id if deployed else None,
        created_by=created_by,
        created_at=utcnow(),
    )
    db.add(rev)
    db.flush()
    if not errors and generation.snapshot is not None:
        from veyra.configmgmt import slices

        slices.save(db, key, generation.snapshot, rev_id, skip=set(generation.held_back))
        _note_held_back(db, generation.held_back)
    return Generated(rev, files, changes, unchanged, generation.held_back)


def changes_pending(
    db: Session, adapter: TelephonyAdapter, key: InstallationKey | None
) -> bool | None:
    """Whether the database now differs from the deployed configuration.

    ``None`` when the engine cannot generate configuration. Generation
    problems count as pending: the deployed files do not reflect the data.
    """
    if Capability.CONFIG_GENERATION not in adapter.capabilities():
        return None
    if pending_change(db) is not None:
        return True
    files, errors = _generate(db, adapter, key)
    if errors:
        return True
    deployed = current_deployed(db, adapter.name)
    if deployed is None:
        return True
    return content_hash(files) != deployed.content_hash


def request_deploy(db: Session, rev: ConfigRevision, mode: str = DEPLOY_NOW) -> None:
    """Queue a validated (or superseded, for rollback) revision for the deployer.

    ``when_idle`` asks the deployer to wait until the engine reports no
    active calls (up to its idle timeout) before writing and reloading."""
    if mode not in DEPLOY_MODES:
        raise ValueError(f"unknown deploy mode {mode!r}")
    if pending(db, rev.engine) is not None:
        raise RuntimeError("Another deployment is already in progress.")
    rev.state = transition(rev.state, RevisionState.DEPLOYING)
    rev.deploy_mode = mode
    rev.deploy_requested_at = utcnow()
    db.flush()


def active_call_count(adapter: TelephonyAdapter) -> int | None:
    """How many calls the engine reports, or None when it cannot say."""
    if Capability.ACTIVE_CALLS not in adapter.capabilities():
        return None
    try:
        return len(adapter.active_calls())
    except (EngineUnavailable, NotSupported):
        return None


def pending_wait(db: Session, adapter: TelephonyAdapter) -> dict[str, Any] | None:
    """What a queued when-idle deployment is waiting for (for the engine status)."""
    rev = pending(db, adapter.name)
    if rev is None:
        return None
    out: dict[str, Any] = {
        "sequence": rev.sequence,
        "mode": rev.deploy_mode or DEPLOY_NOW,
        "requested_at": (rev.deploy_requested_at or rev.created_at).isoformat(),
    }
    if rev.deploy_mode == DEPLOY_WHEN_IDLE:
        out["active_calls"] = active_call_count(adapter)
    return out


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

    def __init__(
        self,
        adapter: TelephonyAdapter,
        config_dir: Path,
        key: InstallationKey | None = None,
        idle_timeout: timedelta = DEFAULT_IDLE_TIMEOUT,
    ) -> None:
        self.adapter = adapter
        self.config_dir = config_dir
        self.key = key
        self.idle_timeout = idle_timeout
        # (active calls, requested at) while a when-idle revision is held back.
        self.waiting: tuple[int, Any] | None = None

    def run_once(self, db: Session) -> ConfigRevision | None:
        rev = pending(db, self.adapter.name)
        if rev is None:
            self.waiting = None
            return None
        note: str | None = None
        if rev.deploy_mode == DEPLOY_WHEN_IDLE:
            calls = active_call_count(self.adapter) or 0
            requested = rev.deploy_requested_at or rev.created_at
            waited = utcnow() - requested
            if calls and waited < self.idle_timeout:
                if self.waiting is None or self.waiting[0] != calls:
                    log.info(
                        "Revision %s waits for %d active call(s) to end (%s left)",
                        rev.sequence,
                        calls,
                        self.idle_timeout - waited,
                    )
                self.waiting = (calls, requested)
                return None
            if calls:
                note = (
                    f"idle timeout of {self.idle_timeout} reached after waiting since "
                    f"{requested:%H:%M:%S}; deployed with {calls} active call(s)"
                )
            else:
                note = f"deployed when idle after waiting {waited.total_seconds():.0f} s"
        self.waiting = None
        self.deploy(db, rev, note=note)
        return rev

    def deploy(self, db: Session, rev: ConfigRevision, *, note: str | None = None) -> None:
        managed = self.adapter.managed_files()
        previous_on_disk = read_directory(self.config_dir, managed)
        previous_rev = current_deployed(db, rev.engine)
        log_lines: list[str] = [note] if note else []
        try:
            if not self.config_dir.is_dir():
                raise DeployError(f"configuration directory {self.config_dir} does not exist")
            try:
                files = artifacts_to_files(rev.artifacts, self.key, rev.id)
            except InstallationKeyError as e:
                raise DeployError(str(e)) from e
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
        clear_changed(db)
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
        from veyra.integrations import webhooks

        webhooks.emit_all(
            db,
            "deployment.finished",
            {
                "revision": rev.sequence,
                "engine": rev.engine,
                "result": outcome,
                "error": details.get("error"),
            },
        )
