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
    while True:
        try:
            with session_scope() as db:
                if not bootstrap.setup_required(db):
                    bootstrap.ensure_local_node(db)
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
