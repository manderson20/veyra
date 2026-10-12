# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ``veyra`` administration command.

Every command works without color or Unicode and returns a non-zero exit
status on failure, so it can be used from scripts and the installer.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from veyra.cli.branding import Style, banner, plain_header
from veyra.version import MODULE_API_VERSION, __version__


def _alembic_config() -> Any:
    from alembic.config import Config

    import veyra

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(veyra.__file__).parent / "migrations"))
    return cfg


# ----------------------------------------------------------------- commands


def cmd_version(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps({"version": __version__, "module_api": MODULE_API_VERSION}))
    else:
        print(f"veyra {__version__} (module API {MODULE_API_VERSION})")
    return 0


def cmd_banner(args: argparse.Namespace) -> int:
    sys.stdout.write(banner(sys.stdout, color=args.color, ascii_only=args.ascii or None))
    return 0


def cmd_db_upgrade(args: argparse.Namespace) -> int:
    from alembic import command

    from veyra.core import bootstrap
    from veyra.core.db import session_scope

    command.upgrade(_alembic_config(), "head")
    with session_scope() as db:
        bootstrap.bootstrap(db)
    print("Database schema is up to date.")
    return 0


def cmd_db_current(args: argparse.Namespace) -> int:
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    from veyra.core.db import get_engine

    script = ScriptDirectory.from_config(_alembic_config())
    with get_engine().connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    head = script.get_current_head()
    print(f"current: {current or 'none'}  head: {head}")
    return 0 if current == head else 3


def cmd_setup_token(args: argparse.Namespace) -> int:
    from veyra.core import bootstrap
    from veyra.core.db import session_scope

    with session_scope() as db:
        if not bootstrap.setup_required(db):
            print("Setup has already been completed; no token is needed.", file=sys.stderr)
            return 1
        token = bootstrap.create_setup_token(db)
    if args.quiet:
        print(token)
    else:
        print("First-run setup token (valid for 24 hours, single use):\n")
        print(f"    {token}\n")
        print(
            "Enter it in the setup wizard in your browser. Creating a new token "
            "invalidates this one."
        )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from sqlalchemy import text

    from veyra.core import bootstrap
    from veyra.core.config import get_settings
    from veyra.core.db import session_scope
    from veyra.system import metrics
    from veyra.telephony import get_adapter

    style = Style(sys.stdout)
    settings = get_settings()
    result: dict[str, Any] = {"version": __version__}
    failed = False
    try:
        with session_scope() as db:
            db.execute(text("SELECT 1"))
            result["database"] = "ok"
            result["setup_required"] = bootstrap.setup_required(db)
    except Exception as e:
        result["database"] = f"failed: {type(e).__name__}"
        failed = True
    engine = get_adapter(settings).health()
    result["telephony"] = {
        "engine": engine.engine,
        "state": engine.state,
        "message": engine.message,
    }
    host = metrics.collect("/")
    result["host"] = {
        "cpu_percent": host.cpu_percent,
        "memory_percent": host.memory_percent,
        "disk_percent": host.disk_percent,
    }
    if args.json:
        print(json.dumps(result, indent=2))
        return 1 if failed else 0
    print(plain_header())
    print(
        style.ok("Database reachable")
        if result["database"] == "ok"
        else style.fail(f"Database: {result['database']}")
    )
    if result.get("setup_required"):
        print(style.warn("First-run setup has not been completed (run: sudo veyra setup-token)"))
    tel = style.ok if engine.state == "running" else style.warn
    print(tel(f"Telephony ({engine.engine}): {engine.state} - {engine.message}"))
    for label, value in (
        ("CPU", host.cpu_percent),
        ("Memory", host.memory_percent),
        ("Disk /", host.disk_percent),
    ):
        print(style.info(f"{label}: {'unavailable' if value is None else f'{value}%'}"))
    return 1 if failed else 0


def _manager() -> Any:
    from veyra.core.config import get_settings
    from veyra.core.events import bus
    from veyra.modules.manager import ModuleManager

    return ModuleManager(get_settings(), bus)


def cmd_modules_list(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from veyra.core.db import session_scope
    from veyra.core.models import InstalledModule

    mgr = _manager()
    found = mgr.discover()
    with session_scope() as db:
        rows = {r.module_id: r for r in db.scalars(select(InstalledModule))}
    ids = sorted(set(found) | set(rows))
    if not ids:
        print("No modules found.")
        return 0
    print(f"{'MODULE':40} {'STATE':10} {'INSTALLED':12} {'ON DISK':12} TRUST")
    for i in ids:
        row, cand = rows.get(i), found.get(i)
        disk = cand.manifest.module.version if cand and cand.manifest else "-"
        trust = row.trust_level if row else (cand.verification.trust_level.value if cand else "-")
        print(
            f"{i:40} {(row.state if row else 'available'):10} "
            f"{(row.version if row else '-'):12} {disk:12} {trust}"
        )
    return 0


def _module_action(args: argparse.Namespace, action: str) -> int:
    from veyra.core import audit
    from veyra.core.db import get_engine, session_scope
    from veyra.modules.manager import ModuleError

    mgr = _manager()
    try:
        with session_scope() as db:
            if action == "install":
                mgr.install(db, get_engine(), args.module_id)
            elif action == "enable":
                mgr.enable(db, args.module_id)
            elif action == "disable":
                mgr.disable(db, args.module_id)
            audit.record(
                db,
                action=f"module.{action}",
                actor_type="system",
                actor_label="cli",
                target_type="module",
                target_id=args.module_id,
            )
    except ModuleError as e:
        print(f"error: {e.detail}", file=sys.stderr)
        for err in e.errors or []:
            print(f"  - {err['message']}", file=sys.stderr)
        return 1
    print(f"Module {args.module_id}: {action} complete. Restart veyra-api to apply.")
    return 0


def cmd_modules_schema(args: argparse.Namespace) -> int:
    from veyra.modules.manifest import manifest_json_schema

    print(json.dumps(manifest_json_schema(), indent=2))
    return 0


def cmd_modules_validate(args: argparse.Namespace) -> int:
    from veyra.modules.manifest import ManifestError, load_manifest

    try:
        m = load_manifest(Path(args.path))
    except ManifestError as e:
        print("Manifest is invalid:", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"OK: {m.id} {m.module.version}")
    return 0


def cmd_keygen(args: argparse.Namespace) -> int:
    from veyra.core.signing import KEY_ID_RE, generate_keypair

    if not KEY_ID_RE.match(args.key_id):
        print("error: key id must be lower-case letters, digits and dashes", file=sys.stderr)
        return 2
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    priv, pub = generate_keypair()
    priv_path = out / f"{args.key_id}.key"
    if priv_path.exists():
        print(f"error: {priv_path} already exists", file=sys.stderr)
        return 1
    priv_path.touch(mode=0o600)
    priv_path.write_text(priv + "\n")
    (out / f"{args.key_id}.pub").write_text(pub + "\n")
    print(f"Wrote {priv_path} (keep secret) and {out / (args.key_id + '.pub')}")
    return 0


def cmd_modules_sign(args: argparse.Namespace) -> int:
    from veyra.modules.packages import build_package, sign_directory

    key = Path(args.key_file).read_text().strip()
    sign_directory(Path(args.path), key, args.key_id)
    print(f"Signed {args.path} with key {args.key_id}")
    if args.package:
        print(f"Package: {build_package(Path(args.path), Path(args.package))}")
    return 0


def cmd_templates_validate(args: argparse.Namespace) -> int:
    from veyra.core.config import get_settings
    from veyra.provisioning.renderer import TemplateCatalog, read_template_dir, validate
    from veyra.provisioning.spec import TemplateError

    catalog = TemplateCatalog.from_paths(
        [*get_settings().template_paths, Path(args.base)]
        if args.base
        else get_settings().template_paths
    )
    try:
        rec = read_template_dir(Path(args.path), "local")
        catalog.records[rec.key] = rec
        problems = validate(catalog.resolve(rec.key))
    except TemplateError as e:
        problems = e.errors
    if problems:
        print("Template is invalid:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"OK: {rec.key} {rec.manifest.template.version}")
    return 0


def cmd_updates_check(args: argparse.Namespace) -> int:
    from veyra.core.config import get_settings
    from veyra.core.db import session_scope
    from veyra.core.signing import Keyring
    from veyra.updates.checker import check_for_updates

    settings = get_settings()
    with session_scope() as db:
        check = check_for_updates(db, settings, Keyring.load(settings.trust_dir))
        outcome, message = check.outcome, check.message
    print(f"{outcome}: {message}")
    return 0 if outcome in ("ok", "not_configured") else 1


def cmd_updates_record(args: argparse.Namespace) -> int:
    """Record an update performed outside the API (used by installer/upgrade.sh)."""
    import uuid

    from veyra.core import audit
    from veyra.core.db import session_scope
    from veyra.core.models import UpdateHistory
    from veyra.core.models.base import utcnow

    with session_scope() as db:
        db.add(
            UpdateHistory(
                id=uuid.uuid4(),
                component=args.component,
                target=args.target,
                from_version=args.from_version,
                to_version=args.to_version,
                started_at=utcnow(),
                finished_at=utcnow(),
                outcome=args.outcome,
                initiated_by="upgrade.sh",
                backup_ref=args.backup_ref,
            )
        )
        audit.record(
            db,
            action="updates.applied",
            actor_type="system",
            actor_label="upgrade.sh",
            target_type=args.component,
            target_id=args.target,
            outcome="success" if args.outcome == "success" else "failure",
            details={"from": args.from_version, "to": args.to_version},
        )
    return 0


def _find_user(db: Any, email: str) -> Any:
    from sqlalchemy import select

    from veyra.core.models import User

    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise RuntimeError(f"no user with the email address {email!r}")
    return user


def cmd_users_reset_password(args: argparse.Namespace) -> int:
    """Issue a one-time reset link from the server console.

    This is the recovery path when no administrator can sign in: whoever can
    run this command already controls the server, as with ``setup-token``.
    """
    from veyra.core import audit
    from veyra.core.config import get_settings
    from veyra.core.db import session_scope
    from veyra.core.security import password_reset

    settings = get_settings()
    with session_scope() as db:
        user = _find_user(db, args.email)
        if not user.is_active:
            raise RuntimeError(f"{user.email} is disabled; enable the account first")
        token, row = password_reset.issue_reset_token(db, user, settings, issued_by="cli")
        audit.record(
            db,
            action="user.password_reset_link",
            actor_type="system",
            actor_label="cli",
            organization_id=user.home_organization_id,
            target_type="user",
            target_id=user.id,
            details={"expires_at": row.expires_at.isoformat(), "unlock": args.unlock},
        )
        if args.unlock:
            user.locked_until = None
            user.failed_login_count = 0
        expires = row.expires_at
        email = user.email
    path = password_reset.reset_link_path(token)
    if args.quiet:
        print(path)
        return 0
    base = (args.base_url or "https://<server>").rstrip("/")
    valid = f"valid until {expires:%Y-%m-%d %H:%M %Z}, single use"
    print(f"Password reset link for {email} ({valid}):\n")
    print(f"    {base}{path}\n")
    print(
        "Give it to the user over a channel you trust. Issuing another link, or "
        "using this one, invalidates it."
    )
    return 0


def cmd_users_mfa_reset(args: argparse.Namespace) -> int:
    """Remove a user's second factors from the server console (the escape hatch
    for the recovery administrator, who is not exempt from the MFA policy)."""
    from veyra.core import audit
    from veyra.core.db import session_scope
    from veyra.core.models.base import utcnow
    from veyra.core.security import mfa
    from veyra.core.security.sessions import revoke_user_sessions

    with session_scope() as db:
        user = _find_user(db, args.email)
        removed = mfa.remove_all_factors(db, user.id)
        policy = mfa.load_policy(db)
        user.mfa_required_at = None
        user.mfa_grace_until = None
        mfa.ensure_requirement(user, policy, mfa.is_required(db, policy, user), utcnow())
        revoked = revoke_user_sessions(db, user.id)
        audit.record(
            db,
            action="user.mfa_reset",
            actor_type="system",
            actor_label="cli",
            organization_id=user.home_organization_id,
            target_type="user",
            target_id=user.id,
            details={"methods_removed": removed, "sessions_revoked": revoked},
        )
        email = user.email
    print(f"{email}: removed {removed} second-factor method(s), signed out {revoked} session(s)")
    if removed:
        print("The user sets up a new authenticator at the next sign-in.")
    return 0


def cmd_users_unlock(args: argparse.Namespace) -> int:
    from veyra.core import audit
    from veyra.core.db import session_scope
    from veyra.core.models.base import utcnow

    with session_scope() as db:
        user = _find_user(db, args.email)
        was_locked = bool(user.locked_until and user.locked_until > utcnow())
        user.locked_until = None
        user.failed_login_count = 0
        audit.record(
            db,
            action="user.unlock",
            actor_type="system",
            actor_label="cli",
            organization_id=user.home_organization_id,
            target_type="user",
            target_id=user.id,
            details={"was_locked": was_locked},
        )
        email = user.email
    print(f"{email}: {'unlocked' if was_locked else 'was not locked'}")
    return 0


def cmd_sessions_revoke(args: argparse.Namespace) -> int:
    from veyra.core import audit
    from veyra.core.db import session_scope
    from veyra.core.security.sessions import revoke_user_sessions

    with session_scope() as db:
        user = _find_user(db, args.email)
        revoked = revoke_user_sessions(db, user.id)
        audit.record(
            db,
            action="user.sessions_revoke",
            actor_type="system",
            actor_label="cli",
            organization_id=user.home_organization_id,
            target_type="user",
            target_id=user.id,
            details={"sessions_revoked": revoked},
        )
        email = user.email
    print(f"{email}: {revoked} session(s) signed out")
    return 0


def cmd_sessions_purge(args: argparse.Namespace) -> int:
    from veyra.core.config import get_settings
    from veyra.core.db import session_scope

    with session_scope() as db:
        sessions, resets = purge_expired(db, get_settings())
    print(f"deleted {sessions} expired session(s) and {resets} used or expired reset token(s)")
    return 0


def purge_expired(db: Any, settings: Any) -> tuple[int, int]:
    """Delete sessions and reset tokens past their retention. Used by the
    worker (hourly) and ``veyra sessions purge``."""
    from veyra.core.security.password_reset import purge_reset_tokens
    from veyra.core.security.sessions import purge_sessions

    return purge_sessions(db, settings), purge_reset_tokens(db, settings)


def cmd_deployer(args: argparse.Namespace) -> int:
    """Deployer service: applies queued configuration revisions to the engine.

    The only Veyra process with write access to the engine's include
    directory. See docs/TELEPHONY_ENGINE.md.
    """
    import logging

    from veyra.configmgmt.service import Deployer
    from veyra.core.config import get_settings
    from veyra.core.db import session_scope
    from veyra.core.security.crypto import InstallationKeyError, load_installation_key
    from veyra.telephony import get_adapter

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("veyra.deployer")
    settings = get_settings()
    adapter = get_adapter(settings)
    try:
        key = load_installation_key(settings)
    except InstallationKeyError as e:
        # Revisions without credentials still deploy; the rest fail with
        # this reason recorded on the revision.
        log.warning("%s; revisions with credentials cannot be deployed", e)
        key = None
    deployer = Deployer(adapter, settings.asterisk_config_dir, key)
    log.info(
        "%s deployer started (engine %s, %s)",
        plain_header(),
        adapter.name,
        settings.asterisk_config_dir,
    )
    while True:
        try:
            with session_scope() as db:
                rev = deployer.run_once(db)
                if rev is not None:
                    log.info("revision %s -> %s", rev.sequence, rev.state)
        except Exception:
            log.exception("Deployer iteration failed")
        if args.once:
            return 0
        time.sleep(args.interval)


def cmd_config_status(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from veyra.configmgmt import service
    from veyra.core.config import get_settings
    from veyra.core.db import session_scope
    from veyra.core.models import ConfigRevision
    from veyra.telephony import get_adapter

    adapter = get_adapter(get_settings())
    with session_scope() as db:
        deployed = service.current_deployed(db, adapter.name)
        queued = service.pending(db, adapter.name)
        recent = db.scalars(
            select(ConfigRevision)
            .where(ConfigRevision.engine == adapter.name)
            .order_by(ConfigRevision.sequence.desc())
            .limit(args.limit)
        ).all()
        health = adapter.health()
        rows: list[dict[str, Any]] = [
            {
                "sequence": r.sequence,
                "state": r.state,
                "summary": r.summary,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat(),
            }
            for r in recent
        ]
        deployed_seq = deployed.sequence if deployed else None
        pending_seq = queued.sequence if queued else None
    if args.json:
        print(
            json.dumps(
                {
                    "engine": health.engine,
                    "state": health.state,
                    "deployed": deployed_seq,
                    "pending": pending_seq,
                    "revisions": rows,
                }
            )
        )
        return 0
    print(f"engine: {health.engine} ({health.state}) {health.message}")
    print(f"deployed revision: {deployed_seq if deployed_seq is not None else 'none'}")
    print(f"pending revision:  {pending_seq if pending_seq is not None else 'none'}")
    for r in rows:
        when = r["created_at"][:16].replace("T", " ")
        print(f"  #{r['sequence']:<4} {r['state']:<11} {when} {r['created_by']:<24} {r['summary']}")
    return 0


def cmd_config_generate(args: argparse.Namespace) -> int:
    from veyra.configmgmt import service
    from veyra.core import audit
    from veyra.core.config import get_settings
    from veyra.core.db import session_scope
    from veyra.core.security.crypto import try_load_installation_key
    from veyra.telephony import get_adapter

    settings = get_settings()
    adapter = get_adapter(settings)
    key = try_load_installation_key(settings)
    with session_scope() as db:
        generated = service.create_revision(db, adapter, created_by="cli", key=key)
        rev = generated.revision
        audit.record(
            db,
            action="telephony.config_generate",
            outcome="failure" if rev.validation_errors else "success",
            actor_type="system",
            actor_label="cli",
            target_type="config_revision",
            target_id=rev.id,
            details={"sequence": rev.sequence, "errors": rev.validation_errors},
        )
        if args.deploy and rev.state == "validated":
            service.request_deploy(db, rev)
        seq, state = rev.sequence, rev.state
        errors, unchanged, changed = (
            list(rev.validation_errors),
            generated.unchanged,
            sorted(generated.diff),
        )
    print(f"revision #{seq}: {state}")
    for e in errors:
        print(f"  problem: {e}")
    if unchanged:
        print("  no change from the deployed configuration")
    elif changed:
        print("  changed files: " + ", ".join(changed))
    if state == "deploying":
        print("  queued for the deployer (watch: journalctl -u veyra-deployer)")
    return 0 if state in ("validated", "deploying") else 1


def cmd_config_deploy(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from veyra.configmgmt import service
    from veyra.core import audit
    from veyra.core.db import session_scope
    from veyra.core.models import ConfigRevision

    with session_scope() as db:
        rev = db.scalar(select(ConfigRevision).where(ConfigRevision.sequence == args.sequence))
        if rev is None:
            raise RuntimeError(f"no revision #{args.sequence}")
        if rev.state not in ("validated", "superseded"):
            raise RuntimeError(
                f"revision #{args.sequence} is {rev.state}; "
                "only validated or superseded revisions can be deployed"
            )
        service.request_deploy(db, rev)
        audit.record(
            db,
            action="telephony.config_deploy_request",
            actor_type="system",
            actor_label="cli",
            target_type="config_revision",
            target_id=rev.id,
            details={"sequence": rev.sequence},
        )
    print(f"revision #{args.sequence} queued for the deployer")
    return 0


def cmd_installation_key_generate(args: argparse.Namespace) -> int:
    """Create the installation key by hand (the installer normally does it)."""
    import grp
    import shutil

    from veyra.core.config import get_settings
    from veyra.core.security.crypto import InstallationKey, InstallationKeyError

    path = Path(args.path) if args.path else get_settings().installation_key_path
    if path.exists() and not args.force:
        print(
            f"{path} already exists. Replacing it makes every SIP secret and encrypted "
            "revision unreadable; use --force only if you mean that.",
            file=sys.stderr,
        )
        return 1
    key = InstallationKey.generate()
    try:
        key.write(path, overwrite=args.force)
    except (InstallationKeyError, OSError) as e:
        print(f"cannot write {path}: {e}", file=sys.stderr)
        return 1
    try:
        grp.getgrnam("veyra")
        shutil.chown(path, "root", "veyra")
    except (KeyError, PermissionError, LookupError):
        pass  # development: keep the current owner
    print(f"installation key written to {path} (fingerprint {key.fingerprint})")
    print("Back it up with /etc/veyra; without it SIP secrets cannot be recovered.")
    return 0


def cmd_installation_key_check(args: argparse.Namespace) -> int:
    from veyra.core.config import get_settings
    from veyra.core.security.crypto import InstallationKeyError, load_installation_key

    settings = get_settings()
    path = settings.installation_key_path
    try:
        key = load_installation_key(settings)
    except InstallationKeyError as e:
        if args.json:
            print(json.dumps({"path": str(path), "present": False, "error": str(e)}))
        else:
            print(f"installation key: missing ({e})")
        return 1
    if args.json:
        print(json.dumps({"path": str(path), "present": True, "fingerprint": key.fingerprint}))
    else:
        print(f"installation key: {path} (fingerprint {key.fingerprint})")
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    """Background worker: node heartbeat and scheduled update checks."""
    import logging
    from datetime import timedelta

    from sqlalchemy import select

    from veyra.core import bootstrap
    from veyra.core.config import get_settings
    from veyra.core.db import session_scope
    from veyra.core.models import UpdateCheck, UpdatePolicy
    from veyra.core.models.base import utcnow
    from veyra.core.signing import Keyring
    from veyra.updates.checker import check_for_updates

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("veyra.worker")
    settings = get_settings()
    log.info("%s worker started", plain_header())
    last_purge = 0.0
    while True:
        try:
            with session_scope() as db:
                if not bootstrap.setup_required(db):
                    bootstrap.ensure_local_node(db)
                if time.monotonic() - last_purge >= 3600 or args.once:
                    purged_sessions, purged_tokens = purge_expired(db, settings)
                    last_purge = time.monotonic()
                    if purged_sessions or purged_tokens:
                        log.info(
                            "Purged %d expired sessions and %d reset tokens",
                            purged_sessions,
                            purged_tokens,
                        )
                policy = db.get(UpdatePolicy, "veyra_core")
                last = db.scalar(
                    select(UpdateCheck).order_by(UpdateCheck.checked_at.desc()).limit(1)
                )
                due = (
                    policy is not None
                    and policy.check_enabled
                    and policy.mode != "manual"
                    and (
                        last is None
                        or utcnow() - last.checked_at
                        >= timedelta(hours=policy.check_interval_hours)
                    )
                )
                if due and settings.update_metadata_url:
                    check = check_for_updates(db, settings, Keyring.load(settings.trust_dir))
                    log.info("Update check: %s %s", check.outcome, check.message)
        except Exception:
            log.exception("Worker iteration failed")
        if args.once:
            return 0
        time.sleep(args.interval)


# ----------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="veyra", description="Veyra administration command")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    s = sub.add_parser("version", help="Show version")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_version)

    s = sub.add_parser("banner", help="Print the Veyra wordmark")
    s.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    s.add_argument("--ascii", action="store_true", help="ASCII-only output")
    s.set_defaults(func=cmd_banner)

    s = sub.add_parser("status", help="Summarize system status")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    db = sub.add_parser("db", help="Database schema").add_subparsers(
        dest="db_cmd", metavar="<action>"
    )
    db.add_parser("upgrade", help="Apply migrations and bootstrap data").set_defaults(
        func=cmd_db_upgrade
    )
    db.add_parser("current", help="Show schema revision").set_defaults(func=cmd_db_current)

    s = sub.add_parser("setup-token", help="Issue a one-time first-run setup token")
    s.add_argument("--quiet", action="store_true", help="Print only the token")
    s.set_defaults(func=cmd_setup_token)

    mod = sub.add_parser("modules", help="Module management").add_subparsers(
        dest="mod_cmd", metavar="<action>"
    )
    mod.add_parser("list", help="List modules").set_defaults(func=cmd_modules_list)
    for action in ("install", "enable", "disable"):
        s = mod.add_parser(action, help=f"{action.capitalize()} a module")
        s.add_argument("module_id")
        s.set_defaults(func=lambda a, act=action: _module_action(a, act))
    mod.add_parser("schema", help="Print the manifest JSON Schema").set_defaults(
        func=cmd_modules_schema
    )
    s = mod.add_parser("validate", help="Validate a module directory's manifest")
    s.add_argument("path")
    s.set_defaults(func=cmd_modules_validate)
    s = mod.add_parser("keygen", help="Generate an Ed25519 signing key pair")
    s.add_argument("key_id")
    s.add_argument("--output-dir", default=".")
    s.set_defaults(func=cmd_keygen)
    s = mod.add_parser("sign", help="Sign a module directory (and optionally build a package)")
    s.add_argument("path")
    s.add_argument("--key-file", required=True)
    s.add_argument("--key-id", required=True)
    s.add_argument("--package", metavar="OUTPUT_DIR", help="Also build a .vmod package")
    s.set_defaults(func=cmd_modules_sign)

    tpl = sub.add_parser("templates", help="Provisioning templates").add_subparsers(
        dest="tpl_cmd", metavar="<action>"
    )
    s = tpl.add_parser("validate", help="Validate a template directory")
    s.add_argument("path")
    s.add_argument("--base", help="Additional template root containing official/ (for parents)")
    s.set_defaults(func=cmd_templates_validate)

    upd = sub.add_parser("updates", help="Update management").add_subparsers(
        dest="upd_cmd", metavar="<action>"
    )
    upd.add_parser("check", help="Check for updates now (never installs)").set_defaults(
        func=cmd_updates_check
    )
    s = upd.add_parser("record", help="Record an update applied by upgrade.sh")
    s.add_argument(
        "--component", required=True, choices=["veyra_core", "modules", "provisioning_templates"]
    )
    s.add_argument("--target", required=True)
    s.add_argument("--from-version")
    s.add_argument("--to-version", required=True)
    s.add_argument("--outcome", choices=["success", "failed"], required=True)
    s.add_argument("--backup-ref")
    s.set_defaults(func=cmd_updates_record)

    usr = sub.add_parser("users", help="User account recovery").add_subparsers(
        dest="usr_cmd", metavar="<action>"
    )
    s = usr.add_parser("reset-password", help="Issue a one-time password reset link for a user")
    s.add_argument("email")
    s.add_argument("--unlock", action="store_true", help="Also clear an account lockout")
    s.add_argument("--base-url", help="Public URL of this server, used to print the full link")
    s.add_argument("--quiet", action="store_true", help="Print only the link path")
    s.set_defaults(func=cmd_users_reset_password)
    s = usr.add_parser("mfa-reset", help="Remove a user's second factors (they enrol again)")
    s.add_argument("email")
    s.set_defaults(func=cmd_users_mfa_reset)
    s = usr.add_parser("unlock", help="Clear an account lockout")
    s.add_argument("email")
    s.set_defaults(func=cmd_users_unlock)

    ses = sub.add_parser("sessions", help="Sign-in sessions").add_subparsers(
        dest="ses_cmd", metavar="<action>"
    )
    s = ses.add_parser("revoke", help="Sign a user out of every session")
    s.add_argument("email")
    s.set_defaults(func=cmd_sessions_revoke)
    ses.add_parser("purge", help="Delete sessions and reset tokens past retention").set_defaults(
        func=cmd_sessions_purge
    )

    cfg = sub.add_parser("config", help="Telephony configuration revisions").add_subparsers(
        dest="cfg_cmd", metavar="<action>"
    )
    s = cfg.add_parser("status", help="Engine state and recent revisions")
    s.add_argument("--json", action="store_true")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(func=cmd_config_status)
    s = cfg.add_parser("generate", help="Generate and validate a revision from the database")
    s.add_argument("--deploy", action="store_true", help="Queue it for deployment when valid")
    s.set_defaults(func=cmd_config_generate)
    s = cfg.add_parser("deploy", help="Queue a revision for deployment (rollback: an older one)")
    s.add_argument("sequence", type=int)
    s.set_defaults(func=cmd_config_deploy)

    ik = sub.add_parser(
        "installation-key", help="The key that encrypts secrets at rest"
    ).add_subparsers(dest="subcommand", metavar="<action>", required=True)
    s = ik.add_parser("generate", help="Create the installation key (refuses to replace one)")
    s.add_argument("--path", help="Key file (default: the configured location)")
    s.add_argument("--force", action="store_true", help="Replace an existing key")
    s.set_defaults(func=cmd_installation_key_generate)
    s = ik.add_parser("check", help="Show whether the key is present and its fingerprint")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_installation_key_check)

    s = sub.add_parser("deployer", help="Run the configuration deployer service")
    s.add_argument("--interval", type=int, default=2)
    s.add_argument("--once", action="store_true")
    s.set_defaults(func=cmd_deployer)

    s = sub.add_parser("worker", help="Run the background worker")
    s.add_argument("--interval", type=int, default=60)
    s.add_argument("--once", action="store_true")
    s.set_defaults(func=cmd_worker)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        if sys.stdout.isatty():
            sys.stdout.write(banner(sys.stdout))
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
