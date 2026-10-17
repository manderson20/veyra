# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ``veyra`` administration command.

Every command works without color or Unicode and returns a non-zero exit
status on failure, so it can be used from scripts and the installer.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
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

    if standby_tick(logging.getLogger("veyra.updates"), True):
        print("HA standby: the upgrade is recorded by the primary's history after a switchover")
        return 0
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
                initiated_by=args.initiated_by,
                backup_ref=args.backup_ref,
            )
        )
        audit.record(
            db,
            action="updates.applied",
            actor_type="system",
            actor_label=args.initiated_by,
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
    from veyra.core.security.api_tokens import revoke_user_tokens
    from veyra.core.security.sessions import revoke_user_sessions

    with session_scope() as db:
        user = _find_user(db, args.email)
        revoked = revoke_user_sessions(db, user.id)
        tokens_revoked = revoke_user_tokens(db, user.id)
        audit.record(
            db,
            action="user.sessions_revoke",
            actor_type="system",
            actor_label="cli",
            organization_id=user.home_organization_id,
            target_type="user",
            target_id=user.id,
            details={"sessions_revoked": revoked, "tokens_revoked": tokens_revoked},
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
    from veyra.core.security.api_tokens import purge_tokens
    from veyra.core.security.password_reset import purge_reset_tokens
    from veyra.core.security.sessions import purge_sessions

    # Expired bearer tokens follow the session retention (ADR 0015).
    purge_tokens(db, settings)
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
    from datetime import timedelta

    deployer = Deployer(
        adapter,
        settings.asterisk_config_dir,
        key,
        idle_timeout=timedelta(minutes=settings.deploy_idle_timeout_minutes),
    )
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
        mode = service.DEPLOY_WHEN_IDLE if args.when_idle else service.DEPLOY_NOW
        service.request_deploy(db, rev, mode)
        audit.record(
            db,
            action="telephony.config_deploy_request",
            actor_type="system",
            actor_label="cli",
            target_type="config_revision",
            target_id=rev.id,
            details={"sequence": rev.sequence, "mode": mode},
        )
    print(
        f"revision #{args.sequence} queued for the deployer"
        + (" (waits until no calls are active)" if args.when_idle else "")
    )
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


def cmd_installation_key_rotate(args: argparse.Namespace) -> int:
    """Re-encrypt every ciphertext from the current key to the key in
    ``--new-key`` (docs/PRODUCTION_HARDENING.md §3.1); the root wrapper
    generates the file before and installs it after, so this runs as the
    service account with the database only."""
    import json
    from pathlib import Path

    from veyra.core import audit
    from veyra.core.config import get_settings
    from veyra.core.db import session_scope
    from veyra.core.security import rotation
    from veyra.core.security.crypto import InstallationKey, load_installation_key

    settings = get_settings()
    old = load_installation_key(settings)
    new = InstallationKey.load(Path(args.new_key))
    if new.fingerprint == old.fingerprint:
        raise RuntimeError("the new key is the current key")
    with session_scope() as db:
        before = rotation.check(db, old)
        if not before.ok and not args.force:
            raise RuntimeError(
                "some ciphertexts do not decrypt with the current key: "
                + ", ".join(before.unreadable or [])[:500]
            )
        n = rotation.rotate(db, old, new)
        after = rotation.check(db, new)
        if not after.ok:
            raise RuntimeError("rotation produced unreadable ciphertexts; nothing was committed")
        audit.record(
            db,
            action="security.installation_key_rotate",
            actor_type="system",
            actor_label="console",
            details={"from": old.fingerprint, "to": new.fingerprint, "ciphertexts": n},
        )
    print(json.dumps({"rotated": n, "from": old.fingerprint, "to": new.fingerprint}))
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
    unreadable: list[str] = []
    total = 0
    if getattr(args, "ciphertexts", False):
        from veyra.core.db import session_scope
        from veyra.core.security import rotation

        with session_scope() as db:
            report = rotation.check(db, key)
        total, unreadable = report.total, list(report.unreadable or [])
    if args.json:
        print(
            json.dumps(
                {
                    "path": str(path),
                    "present": True,
                    "fingerprint": key.fingerprint,
                    "ciphertexts": total,
                    "unreadable": unreadable,
                }
            )
        )
    else:
        print(f"installation key: {path} (fingerprint {key.fingerprint})")
        if getattr(args, "ciphertexts", False):
            print(f"ciphertexts: {total}, unreadable: {len(unreadable)}")
            for label in unreadable[:20]:
                print(f"  cannot decrypt: {label}")
    return 1 if unreadable else 0


def process_mail_queue(db: Any, settings: Any, log: Any) -> None:
    """One pass over the outgoing mail queue (docs/VOICEMAIL_IVR.md §2);
    messages given up on are audited as ``mail.failed``."""
    from veyra.core import audit, mail
    from veyra.core.security.crypto import try_load_installation_key

    smtp = mail.load_smtp_settings(db)
    result = mail.process_queue(settings.mailqueue_dir, smtp, try_load_installation_key(settings))
    for name, error in result.failed:
        audit.record(
            db,
            action="mail.failed",
            outcome="failure",
            actor_type="system",
            actor_label="worker",
            target_type="mail",
            target_id=name,
            details={"error": error, "host": smtp.host},
        )
    if result.sent or result.failed:
        log.info("Mail queue: %d sent, %d failed", len(result.sent), len(result.failed))


def poll_calendars_and_ring_bells(db: Any, settings: Any, log: Any) -> None:
    """Bell schedules (docs/PAGING_RECORDINGS.md §4): poll due calendars, ring
    what is due; errors are logged on the calendar row and never stop the worker."""
    from veyra.bells import calendars, scheduler
    from veyra.core.security.crypto import try_load_installation_key
    from veyra.telephony import get_adapter

    key = try_load_installation_key(settings)
    for cal in calendars.due_calendars(db):
        try:
            n = calendars.poll(db, cal, key)
            log.info("Calendar %s: %d event(s) in the next two days", cal.name, n)
        except Exception:
            db.rollback()
            log.exception("Calendar %s: poll failed", cal.name)
    if settings.telephony_engine == "none":
        return
    try:
        for ring in scheduler.ring(db, get_adapter(settings)):
            log.info("Bell %s: %s", ring.summary, ring.outcome)
    except Exception:
        db.rollback()
        log.exception("Bell scheduler pass failed")


def standby_tick(log: Any, logged: bool) -> bool:
    """True when this node's database is in recovery (an HA standby)."""
    from sqlalchemy import func, select

    from veyra.core.db import session_scope

    try:
        with session_scope() as db:
            standby = bool(db.scalar(select(func.pg_is_in_recovery())))
    except Exception:
        return False
    if standby and not logged:
        log.info("This node is an HA standby; the worker is idle until promotion")
    return standby


def central_pass(settings: Any, log: Any) -> None:
    """Check in with the central console when due; as a console, expire
    commands and prune nonces and samples."""
    from veyra.central import console, member
    from veyra.core.db import session_scope
    from veyra.core.security.crypto import try_load_installation_key

    try:
        key = try_load_installation_key(settings)
        if key is None:
            return
        with session_scope() as db:
            if member.due(db):
                from veyra.telephony import get_adapter

                adapter = get_adapter(settings) if settings.telephony_engine != "none" else None
                state = member.check_in(db, settings, key, adapter)
                if state.get("last_error"):
                    log.warning("Central console check-in: %s", state["last_error"])
            if console.enabled(db):
                console.expire_and_prune(db)
    except Exception:
        log.exception("Central management pass failed")


def deliver_webhooks(settings: Any, log: Any) -> None:
    from veyra.core.db import session_scope
    from veyra.core.security.crypto import try_load_installation_key
    from veyra.integrations import sources, webhooks

    try:
        with session_scope() as db:
            sources.voicemail_notifications(db, settings.mailqueue_dir)
        key = try_load_installation_key(settings)
        if key is None:
            return
        with session_scope() as db:
            sent = webhooks.deliver_due(db, lambda enc: key.decrypt(enc, webhooks.SECRET_PURPOSE))
            if sent:
                log.info("Webhooks: %d delivery attempt(s)", sent)
    except Exception:
        log.exception("Webhook pass failed")


def ensure_prompt_dirs(db: Any, settings: Any) -> None:
    """Every active organization gets its prompt folder and ``incoming``
    sub-folder, so ``*95`` recordings from phones have a place to land before
    the first upload (docs/VOICEMAIL_IVR.md §4)."""
    from sqlalchemy import select

    from veyra.core.models import Organization
    from veyra.telephony import audio

    slugs = db.scalars(select(Organization.slug).where(Organization.is_active.is_(True))).all()
    audio.ensure_org_dirs(settings.prompts_dir, slugs)


def cmd_pager(args: argparse.Namespace) -> int:
    """The page sender service (docs/PAGING_RECORDINGS.md §2.2)."""
    import asyncio
    import logging

    from veyra.core.config import get_settings
    from veyra.paging.pager import PAGING_FILE, Pager

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    pager = Pager(get_settings().asterisk_config_dir / PAGING_FILE)
    if args.status:
        asyncio.run(pager.run(once=True))
        print(json.dumps(pager.status(), indent=2))
        return 0
    logging.getLogger("veyra.pager").info("%s pager started", plain_header())
    try:
        asyncio.run(pager.run(once=args.once))
    except KeyboardInterrupt:
        return 0
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    """Background worker: node heartbeat, scheduled update checks, the
    outgoing mail queue, prompt folders; on a short tick, calendars and bells
    and the enabled modules' periodic tasks."""
    import logging
    from datetime import timedelta

    from sqlalchemy import select

    from veyra.core import bootstrap
    from veyra.core.config import get_settings
    from veyra.core.db import session_scope
    from veyra.core.events import bus
    from veyra.core.models import UpdateCheck, UpdatePolicy
    from veyra.core.models.base import utcnow
    from veyra.core.signing import Keyring
    from veyra.modules.manager import ModuleManager
    from veyra.updates.checker import check_for_updates

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("veyra.worker")
    settings = get_settings()
    log.info("%s worker started", plain_header())
    try:
        from veyra.modules import catalog as module_catalog

        with session_scope() as db:
            module_catalog.confirm_restart(db)
    except Exception:
        log.exception("Could not record the finished restart")
    last_purge = 0.0
    last_full = last_module_sync = -1e9
    # Enabled modules' event handlers and periodic tasks (module API 1.1).
    modules = ModuleManager(settings, bus)
    from veyra.integrations import sources as webhook_sources

    webhook_sources.subscribe(bus)
    standby_logged = False
    while True:
        now = time.monotonic()
        # On an HA standby the database is a replica: the worker does
        # nothing but wait (docs/HIGH_AVAILABILITY.md §9); the agent sends
        # the heartbeat. The check is a cheap query each tick.
        if standby_tick(log, standby_logged):
            standby_logged = True
            if args.once:
                return 0
            time.sleep(args.tick)
            continue
        standby_logged = False
        if args.once or now - last_full >= args.interval:
            last_full = now
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
                        # Provisioning, page and bell logs: the retention job
                        # (docs/PRODUCTION_HARDENING.md §4) prunes them daily.
                        from veyra.reporting import cdr

                        pruned_calls = cdr.prune(db)
                        from veyra.reporting import recordings

                        pruned_recs = recordings.prune(db, settings.recordings_dir)
                        from veyra.reporting import queues as queue_log

                        queue_log.prune(db)
                        if pruned_recs:
                            log.info("Deleted %d recordings past their retention", pruned_recs)
                        if pruned_calls:
                            log.info("Pruned %d calls past the history retention", pruned_calls)
                        from veyra.integrations import sso, webhooks

                        sso.prune(db)
                        webhooks.prune(db)
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
                    # Monitoring (docs/REPORTING.md §6.1) before the mail queue,
                    # so a raised alert's email leaves in the same pass.
                    from veyra.reporting import alerts
                    from veyra.telephony import get_adapter

                    alerts.run(
                        db,
                        settings,
                        get_adapter(settings) if settings.telephony_engine != "none" else None,
                    )
                    # Module catalogs once a day; service restarts asked for in
                    # the interface (docs/MODULE_CATALOG.md §3-4).
                    from veyra.modules import catalog as module_catalog

                    module_catalog.refresh_due(db, settings.trust_dir)
                    db.commit()
                    module_catalog.run_restart_request(db)
                    # Veyra releases: finish, download, approve by policy and
                    # start the root upgrade unit (docs/SOFTWARE_UPDATES.md).
                    from veyra.updates import manager as update_manager

                    def calls_in_progress() -> int | None:
                        if settings.telephony_engine == "none":
                            return 0
                        from veyra.configmgmt.service import active_call_count
                        from veyra.telephony import get_adapter

                        return active_call_count(get_adapter(settings))

                    update_manager.refresh_system_packages(db)
                    update_manager.process(
                        db, settings, Keyring.load(settings.trust_dir), calls_in_progress
                    )
                    # Scheduled report emails (docs/REPORT_BUILDER.md §3).
                    from veyra.reporting import schedule as report_schedule

                    report_schedule.process(db, settings.mailqueue_dir)
                    process_mail_queue(db, settings, log)
                    # Retention, once a day (docs/PRODUCTION_HARDENING.md §4).
                    from veyra.core import retention

                    if retention.due(db):
                        removed = retention.run(db)
                        db.commit()
                        gone = {k: v for k, v in removed.items() if v}
                        if gone:
                            log.info("Retention removed %s", gone)
                    # Scheduled backups (docs/PRODUCTION_HARDENING.md §2.2).
                    from veyra.backups import service as backup_service

                    try:
                        if backup_service.tick(db):
                            log.info("Started the scheduled backup")
                    except backup_service.BackupError as e:
                        log.warning("Scheduled backup not started: %s", e.message)
                    if settings.telephony_engine != "none":
                        ensure_prompt_dirs(db, settings)
                        # Dashboard graphs: one reading per iteration (docs/INTERFACE_REWORK.md §2).
                        from veyra.telephony import get_adapter
                        from veyra.telephony.metrics import record_sample

                        record_sample(db, get_adapter(settings))
                        # Phone registrations for webhooks (docs/INTEGRATIONS.md §3.2).
                        from veyra.integrations import sources as webhook_sources

                        webhook_sources.registrations(db, get_adapter(settings))
                        # Samples are pruned by the retention job.
            except Exception:
                log.exception("Worker iteration failed")
        # Bells and module tasks run on a short tick so a bell rings within a
        # few seconds of its time (docs/PAGING_RECORDINGS.md §4.2).
        try:
            with session_scope() as db:
                poll_calendars_and_ring_bells(db, settings, log)
            if settings.telephony_engine != "none":
                # Call history (docs/REPORTING.md §3): new CDRs every tick.
                from veyra.reporting import cdr

                with session_scope() as db:
                    cdr.process(db)
                # Recordings of finished calls (docs/REPORTING.md §4.2).
                from veyra.reporting import recordings

                with session_scope() as db:
                    recordings.process(db, settings.recordings_dir)
                # Queue events for the queue reports (docs/REPORTING.md §5.1).
                from veyra.reporting import queues as queue_log

                with session_scope() as db:
                    queue_log.process(db)
            # Outgoing webhooks (docs/INTEGRATIONS.md §3.5): voicemail
            # notifications in, due deliveries out.
            deliver_webhooks(settings, log)
            # Central management (docs/CENTRAL_MANAGEMENT.md §3).
            central_pass(settings, log)
            with session_scope() as db:
                if args.once or now - last_module_sync >= 60:
                    modules.sync_worker(db)
                    last_module_sync = now
            modules.run_periodic()
        except Exception:
            log.exception("Worker tick failed")
        if args.once:
            return 0
        time.sleep(args.tick)


def cmd_firewall_run(args: argparse.Namespace) -> int:
    """The firewall service (docs/FIREWALL_TRUST.md §3.3)."""
    import logging

    from veyra.core.config import get_settings
    from veyra.core.db import session_scope
    from veyra.core.security.crypto import try_load_installation_key
    from veyra.firewall.service import FirewallService, NftCommand

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("veyra.firewall")
    settings = get_settings()
    service = FirewallService(settings.data_dir, NftCommand(), try_load_installation_key(settings))
    log.info("%s firewall started", plain_header())
    restored = False
    standby_logged = False
    while True:
        # On an HA standby the database is read-only: keep the last ruleset
        # (docs/HIGH_AVAILABILITY.md §9) and wait for the promotion.
        if standby_tick(log, standby_logged):
            standby_logged = True
            if not restored:
                with contextlib.suppress(Exception):
                    restored = service.restore_last()
            if args.once:
                return 0
            time.sleep(args.interval)
            continue
        standby_logged = False
        try:
            with session_scope() as db:
                service.tick(db)
        except Exception:
            log.exception("Firewall pass failed")
            if not restored:
                # Database not reachable yet at boot: keep the last rules.
                try:
                    restored = service.restore_last()
                except Exception:
                    log.exception("Could not apply the last saved ruleset")
                restored = True
        else:
            restored = True
        if args.once:
            return 0
        time.sleep(args.interval)


def cmd_firewall_off(args: argparse.Namespace) -> int:
    """Console recovery: turn the firewall off and remove the table now."""
    from veyra.core.config import get_settings
    from veyra.core.db import session_scope
    from veyra.firewall.service import NftCommand, NftError
    from veyra.firewall.settings import load_settings, save_settings

    try:
        with session_scope() as db:
            fw = load_settings(db)
            fw.enabled = False
            fw.pending_confirm = None
            save_settings(db, fw)
        print("Firewall turned off in the database.")
    except Exception as e:  # the table goes anyway
        print(f"Could not update the database ({e}); removing the table only.", file=sys.stderr)
    # The saved ruleset would be re-applied at boot.
    (get_settings().data_dir / "firewall" / "veyra.nft").unlink(missing_ok=True)
    if args.database_only:
        return 0  # the sudo wrapper removes the table as root
    try:
        NftCommand()._run(["delete", "table", "inet", "veyra"])
        print("Table inet veyra removed.")
    except (NftError, OSError) as e:
        print(f"Table inet veyra not removed: {e}", file=sys.stderr)
    return 0


def cmd_firewall_status(args: argparse.Namespace) -> int:
    from veyra.core.db import session_scope
    from veyra.core.models.base import utcnow
    from veyra.firewall.service import active_bans
    from veyra.firewall.settings import load_settings, load_status

    with session_scope() as db:
        fw = load_settings(db)
        out = {
            "enabled": fw.enabled,
            "policy": fw.policy,
            "service": load_status(db),
            "active_bans": [
                {"address": b.address, "expires_at": b.expires_at.isoformat(), "reason": b.reason}
                for b in active_bans(db, utcnow())
            ],
        }
    print(json.dumps(out, indent=2))
    return 0


def cmd_catalog_add(args: argparse.Namespace) -> int:
    """Add (or replace) a package version in a catalog index (docs/MODULE_CATALOG.md §2.4)."""
    import hashlib
    from datetime import UTC, date, datetime

    from veyra.modules.manifest import load_manifest
    from veyra.modules.packages import extract_package

    pkg = Path(args.package)
    data = pkg.read_bytes()
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        manifest = load_manifest(extract_package(data, Path(tmp)))
    index_path = Path(args.index)
    index = (
        json.loads(index_path.read_text())
        if index_path.exists()
        else {"catalog_version": 1, "name": args.name, "modules": []}
    )
    entry = next((m for m in index["modules"] if m["id"] == manifest.id), None)
    if entry is None:
        entry = {
            "id": manifest.id,
            "name": manifest.module.name,
            "summary": manifest.module.description,
            "publisher": manifest.module.author,
            "homepage": manifest.module.homepage,
            "versions": [],
        }
        index["modules"].append(entry)
    entry["versions"] = [v for v in entry["versions"] if v["version"] != manifest.module.version]
    entry["versions"].insert(
        0,
        {
            "version": manifest.module.version,
            "core_api": manifest.compatibility.core_api,
            "url": args.url,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "released": date.today().isoformat(),
            "notes": args.notes,
        },
    )
    index["modules"].sort(key=lambda m: m["id"])
    index["generated_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    from veyra.modules.catalog import CatalogIndex

    CatalogIndex.model_validate(index)  # never write an index Veyra would refuse
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2) + "\n")
    print(f"{manifest.id} {manifest.module.version} added to {index_path}")
    print("Sign the index again: veyra catalog sign")
    return 0


def cmd_catalog_sign(args: argparse.Namespace) -> int:
    from veyra.core.signing import sign

    index = Path(args.index)
    sig = sign(index.read_bytes(), Path(args.key_file).read_text(), args.key_id)
    Path(str(index) + ".sig").write_text(sig)
    print(f"Signed {index} with {args.key_id}: {index}.sig")
    return 0


def cmd_catalog_verify(args: argparse.Namespace) -> int:
    from veyra.core.config import get_settings
    from veyra.modules import catalog

    keyring = catalog.catalog_keyring(
        Path(args.trust_dir) if args.trust_dir else get_settings().trust_dir
    )
    try:
        if args.index.startswith(("https://", "http://")):
            index, key_id = catalog.fetch_index(args.index, keyring)
        else:
            path = Path(args.index)
            index, key_id = catalog.parse_index(
                path.read_bytes(), Path(str(path) + ".sig").read_text(), keyring
            )
    except (catalog.CatalogError, OSError) as e:
        print(f"NOT VALID: {e}", file=sys.stderr)
        return 1
    print(f"Valid, signed by {key_id}: {len(index.modules)} module(s)")
    for m in index.modules:
        print(f"  {m.id}: " + ", ".join(v.version for v in m.versions))
    return 0


def cmd_release_build(args: argparse.Namespace) -> int:
    from veyra.updates.release import ReleaseError, build

    try:
        dest = build(Path(args.source).resolve(), Path(args.out), allow_dirty=args.allow_dirty)
    except ReleaseError as e:
        print(f"Cannot build: {e}", file=sys.stderr)
        return 1
    print(f"Built {dest} ({dest.stat().st_size // 1024} KB)")
    return 0


def cmd_release_add(args: argparse.Namespace) -> int:
    from veyra.updates.release import ReleaseError, add

    try:
        entry = add(
            Path(args.metadata),
            Path(args.artifact),
            url=args.url,
            channel=args.channel,
            category=args.category,
            notes=args.notes,
            impact=args.impact,
            min_from=args.min_from,
            expiry_days=args.expires_days,
        )
    except (ReleaseError, ValueError, OSError) as e:
        print(f"Cannot add: {e}", file=sys.stderr)
        return 1
    print(f"Added {entry['version']} to {args.metadata}; sign it next (veyra release sign).")
    return 0


def cmd_release_refresh(args: argparse.Namespace) -> int:
    from veyra.updates.release import refresh

    doc = refresh(Path(args.metadata), args.expires_days)
    print(f"Sequence {doc['sequence']}, expires {doc['expires_at']}; sign it next.")
    return 0


def cmd_release_sign(args: argparse.Namespace) -> int:
    from veyra.core.signing import sign

    path = Path(args.metadata)
    Path(str(path) + ".sig").write_text(
        sign(path.read_bytes(), Path(args.key_file).read_text(), args.key_id)
    )
    print(f"Signed {path} with {args.key_id}: {path}.sig")
    return 0


def cmd_updates_run(args: argparse.Namespace) -> int:
    from veyra.updates.runner import main as run

    if os.geteuid() != 0:
        print("veyra updates run must run as root (veyra-upgrade@.service).", file=sys.stderr)
        return 1
    return run([args.version])


# ----------------------------------------------------------------- parser


# ------------------------------------------------------------------ backups


def cmd_backup_unit(args: argparse.Namespace) -> int:
    """``veyra-backup@<instance>``: run, run-manual, verify-<id>, delete-<id>."""
    import json
    import uuid

    from veyra.backups import runner

    instance = str(args.instance)
    if instance in ("run", "run-manual"):
        payload = runner.run_backup(
            "scheduled" if instance == "run" else "manual",
            created_by="scheduler" if instance == "run" else "operator",
        )
        print(json.dumps({k: payload.get(k) for k in ("name", "state", "bytes", "error")}))
        return 0 if payload.get("state") == "verified" else 1
    if instance.startswith("delete-"):
        # Root has no database role: the row is looked up through the
        # service account, as the settings are.
        backup_id = str(uuid.UUID(instance[len("delete-") :]))
        run = runner.subprocess_runner()
        settings = runner.load_settings(run)
        match = [b for b in runner.known_backups(run) if b.get("id") == backup_id]
        if not match:
            raise RuntimeError("unknown backup")
        name, kind = str(match[0]["name"]), str(match[0].get("kind") or "manual")
        runner.delete_backup(name, copy_dir=settings.get("copy_dir") or "")
        r = runner.record(run, {"name": name, "state": "deleted", "kind": kind})
        return 0 if r.ok else 1
    raise RuntimeError(f"unknown backup unit instance {instance!r}")


# ------------------------------------------------------------------ captures


def cmd_capture_unit(args: argparse.Namespace) -> int:
    """``veyra-capture@<id>``: root runs tcpdump for one recorded capture."""
    import json

    from veyra.diagnostics import runner

    payload = runner.run_capture(str(args.instance))
    print(json.dumps({k: payload.get(k) for k in ("id", "state", "bytes", "packets", "error")}))
    return 0 if payload.get("state") in ("finished", "stopped") else 1


def cmd_capture_show(args: argparse.Namespace) -> int:
    """Internal: one capture as JSON, for the root runner."""
    import json
    import uuid

    from veyra.core.db import session_scope
    from veyra.core.models import Capture
    from veyra.diagnostics import captures

    with session_scope() as db:
        row = db.get(Capture, uuid.UUID(args.capture_id))
        if row is None:
            raise RuntimeError("unknown capture")
        print(json.dumps(captures.row_out(row)))
    return 0


def cmd_capture_record(args: argparse.Namespace) -> int:
    import json

    from veyra.core.db import session_scope
    from veyra.diagnostics import captures

    with session_scope() as db:
        row = captures.record(db, json.loads(args.json))
        print(json.dumps({"id": str(row.id), "state": row.state}))
    return 0


def cmd_capture_list(args: argparse.Namespace) -> int:
    import json

    from veyra.core.db import session_scope
    from veyra.diagnostics import captures

    with session_scope() as db:
        rows = [captures.row_out(c) for c in captures.rows(db, 200) if c.state != "deleted"]
    if args.json:
        print(json.dumps(rows))
        return 0
    for r in rows:
        print(
            f"{r['started_at'][:19]}  {r['state']:9} {r['bytes'] // 1024:8} KB "
            f"{r['packets'] if r['packets'] is not None else '-':>7}  {r['id']}  {r['label']}"
        )
    return 0


def cmd_capture_start(args: argparse.Namespace) -> int:
    """From the console: a capture by address, network or all SIP."""
    import json

    from veyra.core.config import get_settings
    from veyra.core.db import session_scope
    from veyra.diagnostics import captures
    from veyra.telephony.settings import load_sip_settings

    with session_scope() as db:
        sip = load_sip_settings(db)
        spec = {
            "hosts": args.host or [],
            "nets": args.net or [],
            "ports": args.port or captures.sip_ports(sip),
            "portranges": [[sip.rtp_start, sip.rtp_end]] if args.rtp else [],
            "rtp": bool(args.rtp),
        }
        try:
            from veyra.diagnostics import filters

            label = args.label or filters.describe(spec)
            row = captures.start(
                db,
                spec=spec,
                label=label,
                directory=get_settings().captures_dir,
                duration_seconds=args.seconds,
                size_limit_mb=args.mb,
                created_by="console",
            )
        except (captures.CaptureError, filters.FilterError) as e:
            print(f"capture not started: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
        print(json.dumps({"id": str(row.id), "expression": row.expression, "path": row.path}))
    return 0


def cmd_capture_stop(args: argparse.Namespace) -> int:
    import uuid

    from veyra.core.db import session_scope
    from veyra.core.models import Capture
    from veyra.diagnostics import captures

    with session_scope() as db:
        row = db.get(Capture, uuid.UUID(args.capture_id))
        if row is None:
            raise RuntimeError("unknown capture")
        try:
            captures.stop(db, row)
        except captures.CaptureError as e:
            print(f"not stopped: {e.message}", file=sys.stderr)
            return 1
    print("stopping")
    return 0


def cmd_capture_delete(args: argparse.Namespace) -> int:
    import uuid

    from veyra.core.db import session_scope
    from veyra.core.models import Capture
    from veyra.diagnostics import captures

    with session_scope() as db:
        row = db.get(Capture, uuid.UUID(args.capture_id))
        if row is None:
            raise RuntimeError("unknown capture")
        try:
            captures.delete(db, row)
        except captures.CaptureError as e:
            print(f"not deleted: {e.message}", file=sys.stderr)
            return 1
    print("deleted")
    return 0


def cmd_backup_run(args: argparse.Namespace) -> int:
    """From the console (root): a manual or pre-upgrade backup, synchronously."""
    import json

    from veyra.backups import runner

    payload = runner.run_backup(args.kind, created_by="console")
    print(json.dumps({k: payload.get(k) for k in ("name", "state", "path", "bytes", "error")}))
    return 0 if payload.get("state") == "verified" else 1


def cmd_backup_record(args: argparse.Namespace) -> int:
    import json

    from veyra.backups import service
    from veyra.core.db import session_scope

    with session_scope() as db:
        row = service.record(db, json.loads(args.json))
        print(json.dumps({"id": str(row.id), "state": row.state}))
    return 0


def cmd_backup_settings(args: argparse.Namespace) -> int:
    import json

    from veyra.backups import service
    from veyra.core.db import session_scope

    with session_scope() as db:
        print(json.dumps(service.settings(db)))
    return 0


def cmd_backup_list(args: argparse.Namespace) -> int:
    import json

    from veyra.backups import service
    from veyra.core.db import session_scope

    with session_scope() as db:
        rows = [service.row_out(b) for b in service.rows(db, 200)]
    if args.json:
        print(
            json.dumps(
                [
                    {"id": r["id"], "name": r["name"], "kind": r["kind"], "state": r["state"]}
                    for r in rows
                ]
            )
        )
        return 0
    for r in rows:
        print(
            f"{str(r['started_at'])[:19]}  {r['kind']:9} {r['state']:9} "
            f"{r['bytes'] // (1024 * 1024):6} MB  {r['path']}"
        )
    return 0


def cmd_backup_restore(args: argparse.Namespace) -> int:
    """Root: restore this server from a backup (docs/PRODUCTION_HARDENING.md §2.5)."""
    from pathlib import Path

    from veyra.backups import restore, runner

    if not args.yes:
        print("This replaces the database, configuration and data of this server.")
        answer = input("Restore now? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            return 1
    parts = [p.strip() for p in (args.parts or ",".join(restore.ALL_PARTS)).split(",") if p.strip()]
    try:
        out = restore.restore(
            Path(args.source),
            parts=parts,
            identity=Path(args.identity) if args.identity else None,
            run=runner.subprocess_runner(timeout=7200),
        )
    except runner.BackupError as e:
        raise RuntimeError(str(e)) from e
    print(
        f"Restored {', '.join(out['parts'])}; "
        f"services {'started' if out.get('started') else 'NOT started'}."
    )
    print("Run: sudo installer/verify.sh")
    return 0


def cmd_ha_agent(args: argparse.Namespace) -> int:
    """The root HA agent (docs/HIGH_AVAILABILITY.md §3)."""
    import logging
    from pathlib import Path

    from veyra.core.config import get_settings
    from veyra.ha import agent as ha_agent
    from veyra.ha.client import SOCKET_PATH

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    log = logging.getLogger("veyra.ha.agent")
    log.info("%s HA agent started", plain_header())
    a = ha_agent.build(settings)
    a.serve(Path(args.socket) if args.socket else SOCKET_PATH, once=args.once)
    return 0


def _ha_client(settings: Any) -> Any:
    from veyra.ha.client import AgentClient

    return AgentClient(settings.ha_socket_path)


def cmd_ha_status(args: argparse.Namespace) -> int:
    import json

    from veyra.core.config import get_settings
    from veyra.ha.client import AgentError

    try:
        st = _ha_client(get_settings()).call("status")
    except AgentError as e:
        raise RuntimeError(e.message) from e
    if args.json:
        print(json.dumps(st, indent=2, default=str))
        return 0
    node = st["node"]
    rep = st.get("replication") or {}
    svc = node.get("service") or {}
    sync = st.get("sync") or {}
    peer = node.get("peer") or {}
    lines = [
        f"node      {node['node_name']}  role {node['role']}  epoch {node['epoch']}  "
        f"state {node['state']}",
        f"database  {rep.get('db_role')}  replication "
        f"{rep.get('state') or rep.get('receiver') or '-'}  lag {rep.get('lag_bytes')} bytes",
        f"service   {svc.get('name') or '-'} {svc.get('address') or ''}  "
        f"held {st.get('holds_address')}",
        f"sync      last success {sync.get('last_success_at') or '-'}  "
        f"backlog {sync.get('backlog')}  {sync.get('last_error') or ''}",
    ]
    if peer:
        lines.insert(
            1,
            f"peer      {peer['node_name']} ({peer['address']})  "
            f"reachable {st.get('peer_reachable')}",
        )
    print("\n".join(lines))
    op = st.get("operation")
    if op:
        print(f"operation {op['kind']} {op['status']} ({op['started_at']})")
        for step in op["steps"]:
            secs = step.get("seconds") or ""
            print(f"  {step['status']:7} {step['name']:18} {secs} {step.get('detail') or ''}")
    return 0


def cmd_ha_verb(args: argparse.Namespace, verb: str) -> int:
    import json

    from veyra.core.config import get_settings
    from veyra.ha.client import AgentError

    warnings = {
        "switchover": "Calls in progress end; phones re-register within their expiry.",
        "failover": "Only when the primary is OFF: two primaries corrupt the data.",
        "resume": (
            "Only when the peer is really down: resuming next to a live primary splits the brain."
        ),
        "standalone": "This node leaves the cluster and runs on its own.",
        "remove-node": "The secondary leaves the cluster; this node becomes standalone.",
    }
    if verb in warnings and not args.yes:
        print(warnings[verb])
        answer = input(f"Run {verb} on this node? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            return 1
    kwargs: dict[str, Any] = {"actor": "cli"}
    if verb == "failover":
        kwargs["confirm_fenced"] = bool(args.confirm_fenced)
    try:
        out = _ha_client(get_settings()).call(verb, **kwargs)
    except AgentError as e:
        raise RuntimeError(e.message) from e
    print(json.dumps(out, indent=2, default=str))
    return 0


def cmd_ha_enable(args: argparse.Namespace) -> int:
    """Standalone becomes the primary (docs/HIGH_AVAILABILITY.md §5), from the console."""
    import json

    from veyra.core.config import get_settings
    from veyra.ha.client import AgentError

    try:
        out = _ha_client(get_settings()).call(
            "enable",
            service={
                "name": args.name,
                "address": args.address,
                "prefix": args.prefix,
                "interface": args.interface,
            },
            synchronous=bool(args.synchronous),
            address=args.node_address or "",
            actor="cli",
        )
    except AgentError as e:
        raise RuntimeError(e.message) from e
    print(json.dumps(out, indent=2, default=str))
    print("Follow the steps with: veyra ha status")
    return 0


def cmd_ha_add_node(args: argparse.Namespace) -> int:
    """A join token and the installer command for the second server."""
    from veyra.core.db import session_scope
    from veyra.ha import join
    from veyra.ha import service as ha_service

    with session_scope() as db:
        inst = ha_service.installation(db)
        if inst.deployment_mode != "ha":
            raise RuntimeError("enable high availability first (veyra ha enable)")
        raw, item = join.create_token(db, label=args.label, created_by="cli")
        me = ha_service.node_by_name(db, ha_service.local_name())
        address = (me.address if me and me.address else None) or ha_service.local_name()
    print(f"Join token (valid until {item['expires_at']}, shown once):")
    print(f"  sudo installer/install.sh --role secondary --join https://{address} --token {raw}")
    return 0


def cmd_ha_join_prepare(args: argparse.Namespace) -> int:
    """Run by install.sh --role secondary: ask the agent to join, then wait."""
    import json

    from veyra.core.config import get_settings
    from veyra.ha.client import AgentError

    client = _ha_client(get_settings())
    try:
        client.call(
            "join-prepare",
            url=args.url,
            token=args.token,
            address=args.address,
            insecure=bool(args.insecure),
        )
        while True:
            st = client.call("status")
            op = st.get("operation") or {}
            if op.get("kind") == "join" and op.get("status") != "running":
                break
            time.sleep(2)
    except AgentError as e:
        raise RuntimeError(e.message) from e
    for step in op.get("steps", []):
        print(f"  {step['status']:7} {step['name']:16} {step.get('detail') or ''}")
    if op.get("status") != "completed":
        raise RuntimeError(f"join failed: {op.get('error')}")
    print(json.dumps({"node": st["node"]["node_name"], "role": st["node"]["role"]}))
    return 0


def cmd_ha_db(args: argparse.Namespace) -> int:
    """Database actions the root agent asks for, run as the service account."""
    import json

    from veyra.core.db import session_scope
    from veyra.ha import service as ha_service

    action = ha_service.ACTIONS.get(args.action)
    if action is None:
        raise RuntimeError(f"unknown action {args.action}")
    payload = json.loads(args.json)
    with session_scope() as db:
        out = action(db, payload)
    print(json.dumps(out, default=str))
    return 0


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

    cat = sub.add_parser(
        "catalog", help="Publish a module catalog (docs/MODULE_CATALOG.md)"
    ).add_subparsers(dest="catalog_cmd", metavar="<action>", required=True)
    s = cat.add_parser("add", help="Add a signed .vmod package to an index.json")
    s.add_argument("package")
    s.add_argument(
        "--url", required=True, help="Where the package will be downloaded (a GitHub release asset)"
    )
    s.add_argument("--index", required=True, help="Path of index.json (created when missing)")
    s.add_argument("--name", default="Veyra modules", help="Catalog name for a new index")
    s.add_argument("--notes", default=None, help="Release notes for this version")
    s.set_defaults(func=cmd_catalog_add)
    s = cat.add_parser("sign", help="Sign index.json with the catalog key (writes index.json.sig)")
    s.add_argument("index")
    s.add_argument("--key-file", required=True)
    s.add_argument("--key-id", required=True)
    s.set_defaults(func=cmd_catalog_sign)
    s = cat.add_parser(
        "verify", help="Check a local or online index against the trusted catalog keys"
    )
    s.add_argument("index", help="Path or URL of index.json")
    s.add_argument(
        "--trust-dir", default=None, help="Trust directory (default: the installation's)"
    )
    s.set_defaults(func=cmd_catalog_verify)

    rel = sub.add_parser(
        "release", help="Build and sign Veyra releases (docs/SOFTWARE_UPDATES.md §1)"
    ).add_subparsers(dest="release_cmd", metavar="<action>", required=True)
    s = rel.add_parser("build", help="Build veyra-<version>.tar.gz from a clean checkout")
    s.add_argument("--source", default=".", help="Repository checkout (default: .)")
    s.add_argument("--out", required=True, help="Output directory")
    s.add_argument("--allow-dirty", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_release_build)
    s = rel.add_parser("add", help="Add a built release to the update metadata")
    s.add_argument("artifact")
    s.add_argument("--url", required=True, help="Where servers will download the artifact")
    s.add_argument("--metadata", required=True, help="Path of the metadata (e.g. stable.json)")
    s.add_argument("--channel", choices=["stable", "beta", "development"], default="stable")
    s.add_argument("--category", choices=["security", "bugfix", "feature"], required=True)
    s.add_argument("--notes", default="", help="Release notes")
    s.add_argument("--impact", default="", help="Expected service impact")
    s.add_argument("--min-from", default=None, help="Oldest version that may upgrade directly")
    s.add_argument("--expires-days", type=int, default=30)
    s.set_defaults(func=cmd_release_add)
    s = rel.add_parser("refresh", help="New sequence and expiry without a release")
    s.add_argument("metadata")
    s.add_argument("--expires-days", type=int, default=30)
    s.set_defaults(func=cmd_release_refresh)
    s = rel.add_parser("sign", help="Sign the metadata with the official key (writes .sig)")
    s.add_argument("metadata")
    s.add_argument("--key-file", required=True)
    s.add_argument("--key-id", required=True)
    s.set_defaults(func=cmd_release_sign)

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
    s.add_argument("--initiated-by", default="upgrade.sh")
    s.set_defaults(func=cmd_updates_record)
    s = upd.add_parser(
        "run",
        help="Install a downloaded, signed release (root; used by veyra-upgrade@.service)",
    )
    s.add_argument("version")
    s.set_defaults(func=cmd_updates_run)

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
    s.add_argument(
        "--when-idle",
        action="store_true",
        help="Wait until the engine has no active calls (up to the idle timeout)",
    )
    s.add_argument("sequence", type=int)
    s.set_defaults(func=cmd_config_deploy)

    ik = sub.add_parser(
        "installation-key", help="The key that encrypts secrets at rest"
    ).add_subparsers(dest="subcommand", metavar="<action>", required=True)
    s = ik.add_parser(
        "rotate", help="Rotate the key and re-encrypt every secret (through sudo veyra)"
    )
    s.add_argument("--new-key", required=True)
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_installation_key_rotate)
    s = ik.add_parser("generate", help="Create the installation key (refuses to replace one)")
    s.add_argument("--path", help="Key file (default: the configured location)")
    s.add_argument("--force", action="store_true", help="Replace an existing key")
    s.set_defaults(func=cmd_installation_key_generate)
    s = ik.add_parser("check", help="Show whether the key is present and its fingerprint")
    s.add_argument("--json", action="store_true")
    s.add_argument(
        "--ciphertexts", action="store_true", help="Also decrypt every stored ciphertext"
    )
    s.set_defaults(func=cmd_installation_key_check)

    s = sub.add_parser("deployer", help="Run the configuration deployer service")
    s.add_argument("--interval", type=int, default=2)
    s.add_argument("--once", action="store_true")
    s.set_defaults(func=cmd_deployer)

    s = sub.add_parser("pager", help="Run the page sender (speakers and Poly phones in step)")
    s.add_argument("--once", action="store_true", help="Load the zone table and exit")
    s.add_argument("--status", action="store_true", help="Print the zone table as JSON and exit")
    s.set_defaults(func=cmd_pager)

    fwp = sub.add_parser("firewall", help="Veyra's firewall").add_subparsers(
        dest="fw_cmd", metavar="<action>", required=True
    )
    s = fwp.add_parser("run", help="Run the firewall service (needs CAP_NET_ADMIN)")
    s.add_argument("--interval", type=int, default=2, help="Seconds between passes")
    s.add_argument("--once", action="store_true")
    s.set_defaults(func=cmd_firewall_run)
    s = fwp.add_parser("off", help="Turn the firewall off and remove its table (console recovery)")
    s.add_argument(
        "--database-only", action="store_true", help=argparse.SUPPRESS
    )  # used by the sudo wrapper, which removes the table as root
    s.set_defaults(func=cmd_firewall_off)
    fwp.add_parser("status", help="Settings, service state and active bans").set_defaults(
        func=cmd_firewall_status
    )

    s = sub.add_parser("worker", help="Run the background worker")
    s.add_argument("--interval", type=int, default=30, help="Seconds between housekeeping passes")
    s.add_argument("--tick", type=int, default=5, help="Seconds between bell and module passes")
    s.add_argument("--once", action="store_true")
    s.set_defaults(func=cmd_worker)
    bk = sub.add_parser("backup", help="Backups (docs/PRODUCTION_HARDENING.md §2)").add_subparsers(
        dest="backup_cmd", metavar="<action>", required=True
    )
    s = bk.add_parser("run", help="Take a backup now (root)")
    s.add_argument("--kind", default="manual", choices=["manual", "upgrade", "scheduled"])
    s.set_defaults(func=cmd_backup_run)
    s = bk.add_parser("list", help="List backups")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_backup_list)
    s = bk.add_parser("restore", help="Restore this server from a backup (root)")
    s.add_argument("source", help="Backup directory or .tar.age file")
    s.add_argument("--identity", help="age identity file for an encrypted backup")
    s.add_argument("--parts", help="Comma-separated: db,etc,engine,data,voicemail,recordings")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_backup_restore)
    s = bk.add_parser("unit", help="Internal: the veyra-backup@ unit")
    s.add_argument("instance")
    s.set_defaults(func=cmd_backup_unit)
    s = bk.add_parser("record", help="Internal: record a runner result")
    s.add_argument("--json", required=True)
    s.set_defaults(func=cmd_backup_record)
    s = bk.add_parser("settings", help="Show the backup settings")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_backup_settings)
    cp = sub.add_parser(
        "capture", help="Packet captures (docs/CALL_FEATURES.md §2.2)"
    ).add_subparsers(dest="capture_cmd", metavar="<action>", required=True)
    s = cp.add_parser("start", help="Start a capture (all SIP, or by address)")
    s.add_argument("--host", action="append", help="Capture this address (repeatable)")
    s.add_argument("--net", action="append", help="Capture this network in CIDR notation")
    s.add_argument("--port", action="append", type=int, help="Port instead of the SIP ports")
    s.add_argument("--rtp", action="store_true", help="Include the RTP port range")
    s.add_argument("--seconds", type=int, default=120, help="Duration (default 120, max 1800)")
    s.add_argument("--mb", type=int, default=50, help="Size limit in MB (default 50, max 500)")
    s.add_argument("--label", help="Shown in the list")
    s.set_defaults(func=cmd_capture_start)
    s = cp.add_parser("stop", help="Stop a running capture")
    s.add_argument("capture_id")
    s.set_defaults(func=cmd_capture_stop)
    s = cp.add_parser("list", help="List captures")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_capture_list)
    s = cp.add_parser("delete", help="Delete a capture and its file")
    s.add_argument("capture_id")
    s.set_defaults(func=cmd_capture_delete)
    s = cp.add_parser("unit", help="Internal: the veyra-capture@ unit")
    s.add_argument("instance")
    s.set_defaults(func=cmd_capture_unit)
    s = cp.add_parser("show", help=argparse.SUPPRESS)
    s.add_argument("capture_id")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_capture_show)
    s = cp.add_parser("record", help=argparse.SUPPRESS)
    s.add_argument("--json", required=True)
    s.set_defaults(func=cmd_capture_record)
    ha = sub.add_parser("ha", help="High availability (docs/HIGH_AVAILABILITY.md)").add_subparsers(
        dest="ha_cmd", metavar="<action>", required=True
    )
    s = ha.add_parser("agent", help="Run the HA agent (root; the veyra-ha-agent unit)")
    s.add_argument("--socket", help=argparse.SUPPRESS)
    s.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_ha_agent)
    s = ha.add_parser("status", help="This node's HA state (from the agent)")
    s.add_argument("--json", action="store_true", help="Print JSON")
    s.set_defaults(func=cmd_ha_status)
    for verb, help_text in (
        ("switchover", "Switch over to this standby (run on the standby)"),
        ("failover", "Fail over to this standby when the primary is down"),
        ("resume", "Resume primary duties on an isolated primary"),
        ("rejoin", "Rejoin as the standby of the peer"),
        ("standalone", "Leave the cluster: this node is on its own again"),
        ("remove-node", "Remove the secondary from the cluster (run on the primary)"),
        ("sync-now", "Run the file sync now (standby)"),
    ):
        s = ha.add_parser(verb, help=help_text)
        if verb == "failover":
            s.add_argument(
                "--confirm-fenced",
                action="store_true",
                help="I confirm the primary is powered off or fenced",
            )
        s.add_argument("--yes", action="store_true", help="Do not ask for confirmation")
        s.set_defaults(func=lambda a, v=verb: cmd_ha_verb(a, v))
    s = ha.add_parser("enable", help="Enable high availability: this node becomes the primary")
    s.add_argument("--name", required=True, help="Service name phones and browsers use")
    s.add_argument("--address", required=True, help="Service address on the shared segment")
    s.add_argument("--prefix", type=int, default=24, help="Prefix length (default 24)")
    s.add_argument("--interface", required=True, help="Interface that carries the service address")
    s.add_argument("--node-address", help="This node's own address (default: from the hostname)")
    s.add_argument("--synchronous", action="store_true", help="Synchronous replication")
    s.set_defaults(func=cmd_ha_enable)
    s = ha.add_parser("add-node", help="Create a join token for the second server")
    s.add_argument("--label", help="A label for the token")
    s.set_defaults(func=cmd_ha_add_node)
    s = ha.add_parser(
        "join-prepare", help="Join a primary as the secondary (used by the installer)"
    )
    s.add_argument("--url", required=True, help="The primary, e.g. https://veyra-dev1")
    s.add_argument("--token", required=True, help="Join token from the primary's HA page")
    s.add_argument("--address", required=True, help="This node's own address")
    s.add_argument("--insecure", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_ha_join_prepare)
    s = ha.add_parser("db", help="Internal: database steps of the HA agent")
    s.add_argument("action")
    s.add_argument("--json", default="{}")
    s.set_defaults(func=cmd_ha_db)
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
