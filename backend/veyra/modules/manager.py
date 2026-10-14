# SPDX-License-Identifier: AGPL-3.0-or-later
"""Module Manager: discovery, compatibility checks, trust policy and lifecycle.

Lifecycle states (``installed_modules.state``)::

    (available) --install--> installed --enable--> enabled
                                 ^                   |
                                 +----- disable -----+  (state: disabled)
    disabled/installed --uninstall--> removed   (data retained; row kept)
    removed --install--> installed              (data reused)
    uninstall(purge=True) drops the module's tables; requires explicit confirmation

Trust policy for loading code into the core process:

* ``official`` signature verified        → may run in-process
* ``community`` / ``third_party`` signed → must use the isolated ``service``
  runtime (not yet available; such modules are refused for now)
* unsigned                               → refused, unless
  ``allow_unsigned_modules`` is set in a non-production environment
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi import Depends, FastAPI
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from veyra.core import bootstrap
from veyra.core.config import Settings
from veyra.core.errors import ProblemError
from veyra.core.events import Event, EventBus
from veyra.core.models import InstalledModule, ModuleConfig
from veyra.core.security.permissions import PermissionDef, registry
from veyra.core.semver import Version, VersionRange
from veyra.core.signing import Keyring, TrustLevel
from veyra.modules import migrations
from veyra.modules.context import HealthResult, ModuleContext
from veyra.modules.manifest import (
    MANIFEST_FILENAME,
    Manifest,
    ManifestError,
    RuntimeType,
    load_manifest,
)
from veyra.modules.packages import Verification, verify_directory
from veyra.version import MODULE_API_VERSION

log = logging.getLogger("veyra.modules")

API_PREFIX = "/api/v1/ext"


class ModuleError(ProblemError):
    def __init__(self, detail: str, *, status: int = 409, errors: list[str] | None = None) -> None:
        super().__init__(
            status,
            "Module operation failed",
            detail,
            code="module_error",
            errors=[{"message": e} for e in errors] if errors else None,
        )


@dataclass
class Candidate:
    """A module found on disk (installed or merely available)."""

    path: Path
    manifest: Manifest | None
    verification: Verification
    manifest_errors: list[str] = field(default_factory=list)

    @property
    def module_id(self) -> str:
        return self.manifest.id if self.manifest else self.path.name


@dataclass
class LoadedModule:
    manifest: Manifest
    path: Path
    ctx: ModuleContext
    entry: Any
    python_package: str


class ModuleManager:
    def __init__(self, settings: Settings, bus: EventBus, keyring: Keyring | None = None) -> None:
        self.settings = settings
        self.bus = bus
        self.keyring = keyring if keyring is not None else Keyring.load(settings.trust_dir)
        self.loaded: dict[str, LoadedModule] = {}
        self.enabled: set[str] = set()
        self.app: FastAPI | None = None
        self.restart_required: set[str] = set()
        self._mounted: set[str] = set()

    # ------------------------------------------------------------- discovery
    def discover(self) -> dict[str, Candidate]:
        found: dict[str, Candidate] = {}
        for base in self.settings.module_paths:
            if not base.is_dir():
                continue
            for d in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")):
                if not (d / MANIFEST_FILENAME).is_file():
                    continue
                verification = verify_directory(d, self.keyring)
                try:
                    manifest: Manifest | None = load_manifest(d)
                    errors: list[str] = []
                except ManifestError as e:
                    manifest, errors = None, e.errors
                cand = Candidate(d, manifest, verification, errors)
                if cand.module_id in found:
                    log.warning("Duplicate module %s at %s ignored", cand.module_id, d)
                    continue
                found[cand.module_id] = cand
        return found

    def candidate(self, module_id: str) -> Candidate:
        cand = self.discover().get(module_id)
        if cand is None:
            raise ModuleError(
                f"Module {module_id!r} was not found in the module paths.", status=404
            )
        if cand.manifest is None:
            raise ModuleError(
                f"Module {module_id!r} has an invalid manifest.",
                errors=cand.manifest_errors,
                status=422,
            )
        return cand

    # ------------------------------------------------------------- checks
    def trust_problems(self, manifest: Manifest, verification: Verification) -> list[str]:
        if not verification.verified:
            if self.settings.unsigned_modules_permitted:
                log.warning("Loading UNSIGNED module %s (development mode)", manifest.id)
                return []
            return [f"Package verification failed: {verification.error}"]
        if (
            verification.trust_level != TrustLevel.OFFICIAL
            and manifest.runtime.type == RuntimeType.IN_PROCESS
        ):
            return [
                "Only official modules may run inside the core process; "
                "community and third-party modules must use the 'service' runtime."
            ]
        if manifest.runtime.type == RuntimeType.SERVICE:
            return ["The isolated 'service' module runtime is not available in this release."]
        return []

    def compatibility_problems(
        self, db: Session, manifest: Manifest, *, require_enabled_deps: bool = False
    ) -> list[str]:
        problems: list[str] = []
        if not VersionRange.parse(manifest.compatibility.core_api).contains(MODULE_API_VERSION):
            problems.append(
                f"Requires module API {manifest.compatibility.core_api}; "
                f"this Veyra provides {MODULE_API_VERSION}."
            )
        engines = manifest.compatibility.engines
        if engines and self.settings.telephony_engine not in engines:
            problems.append(
                f"Supports engines {engines}; this installation uses "
                f"{self.settings.telephony_engine!r}."
            )
        installed = {m.module_id: m for m in db.scalars(select(InstalledModule))}
        for dep in manifest.dependencies:
            row = installed.get(dep.id)
            if row is None or row.state == "removed":
                if not dep.optional:
                    problems.append(f"Requires module {dep.id} {dep.version}.")
                continue
            if not VersionRange.parse(dep.version).contains(row.version):
                problems.append(f"Requires {dep.id} {dep.version}; installed is {row.version}.")
            if require_enabled_deps and not dep.optional and row.state != "enabled":
                problems.append(f"Module {dep.id} must be enabled first.")
        return problems

    # ------------------------------------------------------------- lifecycle
    def install(self, db: Session, engine: Engine, module_id: str) -> InstalledModule:
        cand = self.candidate(module_id)
        manifest = cand.manifest
        assert manifest is not None
        row = db.get(InstalledModule, module_id)
        if row is not None and row.state != "removed":
            raise ModuleError(f"Module {module_id} is already installed.")
        problems = self.trust_problems(manifest, cand.verification) + self.compatibility_problems(
            db, manifest
        )
        if problems:
            raise ModuleError("Module cannot be installed.", errors=problems)

        migrations.upgrade(engine, manifest, cand.path)
        self._register_permissions(manifest)
        bootstrap.sync_permissions(db)
        if row is None:
            row = InstalledModule(module_id=module_id)
            db.add(row)
        row.version = manifest.module.version
        row.state = "installed"
        row.trust_level = cand.verification.trust_level.value
        row.signature_verified = cand.verification.verified
        row.source_path = str(cand.path)
        row.manifest = manifest.model_dump(mode="json")
        row.last_error = None
        loaded = self._load(manifest, cand.path)
        self._call_hook(loaded, "on_install")
        db.flush()
        return row

    def enable(self, db: Session, module_id: str) -> InstalledModule:
        row = self._row(db, module_id)
        if row.state == "enabled" and module_id in self.enabled:
            return row
        if row.state not in ("installed", "disabled", "failed", "enabled"):
            raise ModuleError(f"Module {module_id} cannot be enabled from state {row.state!r}.")
        cand = self.candidate(module_id)
        manifest = cand.manifest
        assert manifest is not None
        if manifest.module.version != row.version:
            raise ModuleError(
                "The module files on disk do not match the installed version; "
                "apply the module update first."
            )
        problems = self.trust_problems(manifest, cand.verification) + self.compatibility_problems(
            db, manifest, require_enabled_deps=True
        )
        if problems:
            raise ModuleError("Module cannot be enabled.", errors=problems)
        try:
            loaded = self._load(manifest, cand.path)
            self._activate(loaded)
            self._call_hook(loaded, "on_enable")
        except ModuleError:
            raise
        except Exception as e:
            log.exception("Enabling module %s failed", module_id)
            self._deactivate(module_id)
            row.state, row.last_error = "failed", f"{type(e).__name__}: {e}"
            db.flush()
            raise ModuleError(f"Module {module_id} failed to start: {e}") from e
        row.state, row.last_error = "enabled", None
        self._register_permissions(manifest)
        bootstrap.sync_permissions(db)
        db.flush()
        self.bus.publish(Event("module.enabled", {"module_id": module_id}))
        return row

    def disable(self, db: Session, module_id: str) -> InstalledModule:
        row = self._row(db, module_id)
        dependents = [
            m.module_id
            for m in db.scalars(select(InstalledModule).where(InstalledModule.state == "enabled"))
            if m.module_id != module_id
            and any(
                d.get("id") == module_id and not d.get("optional")
                for d in m.manifest.get("dependencies", [])
            )
        ]
        if dependents:
            raise ModuleError(f"Disable these modules first: {', '.join(dependents)}.")
        loaded = self.loaded.get(module_id)
        if loaded:
            self._call_hook(loaded, "on_disable", swallow=True)
        self._deactivate(module_id)
        row.state = "disabled"
        db.flush()
        self.bus.publish(Event("module.disabled", {"module_id": module_id}))
        return row

    def uninstall(
        self, db: Session, engine: Engine, module_id: str, *, purge: bool
    ) -> InstalledModule | None:
        row = self._row(db, module_id)
        if row.state == "enabled":
            raise ModuleError("Disable the module before uninstalling it.")
        manifest = Manifest.model_validate(row.manifest)
        loaded = self.loaded.get(module_id)
        if loaded:
            self._call_hook(loaded, "on_uninstall", purge, swallow=True)
        self._unload(module_id)
        registry.unregister_module(module_id)
        if purge:
            path = Path(row.source_path)
            if path.is_dir():
                migrations.downgrade_to_base(engine, manifest, path)
            db.execute(delete(ModuleConfig).where(ModuleConfig.module_id == module_id))
            db.delete(row)
            db.flush()
            return None
        row.state = "removed"
        db.flush()
        return row

    def apply_update(self, db: Session, engine: Engine, module_id: str) -> InstalledModule:
        """Apply a newer version already present on disk (placed there by the
        update service after package verification)."""
        row = self._row(db, module_id)
        cand = self.candidate(module_id)
        manifest = cand.manifest
        assert manifest is not None
        if Version.parse(manifest.module.version) <= Version.parse(row.version):
            raise ModuleError(f"No newer version of {module_id} is available on disk.")
        problems = self.trust_problems(manifest, cand.verification) + self.compatibility_problems(
            db, manifest
        )
        if problems:
            raise ModuleError("Module update cannot be applied.", errors=problems)
        previous = row.version
        migrations.upgrade(engine, manifest, cand.path)
        row.version = manifest.module.version
        row.manifest = manifest.model_dump(mode="json")
        row.trust_level = cand.verification.trust_level.value
        row.signature_verified = cand.verification.verified
        db.flush()
        if module_id in self.loaded:
            # New code cannot be hot-swapped safely inside a running process.
            self.restart_required.add(module_id)
        log.info("Module %s updated %s -> %s", module_id, previous, row.version)
        return row

    # ------------------------------------------------------------- runtime
    def startup(self, app: FastAPI, db: Session) -> None:
        """Load every enabled module. A failing module never prevents startup."""
        self.app = app
        for row in db.scalars(select(InstalledModule).where(InstalledModule.state == "enabled")):
            try:
                cand = self.candidate(row.module_id)
                manifest = cand.manifest
                assert manifest is not None
                problems = self.trust_problems(manifest, cand.verification)
                if manifest.module.version != row.version:
                    problems.append("Files on disk do not match the installed version.")
                if problems:
                    raise ModuleError("; ".join(problems))
                loaded = self._load(manifest, cand.path)
                self._activate(loaded)
                self._register_permissions(manifest)
            except Exception as e:
                log.error("Module %s failed to load: %s", row.module_id, e)
                row.state, row.last_error = "failed", str(getattr(e, "detail", None) or e)
        bootstrap.sync_permissions(db)

    # ---------------------------------------------------------------- worker
    def sync_worker(self, db: Session) -> None:
        """Worker side (module API 1.1): keep the loaded modules in step with
        the enabled ones, without routes and without changing module rows
        (the API service records failures). Event subscriptions and periodic
        tasks of enabled modules run in the worker process."""
        rows = {
            r.module_id: r.version
            for r in db.scalars(select(InstalledModule).where(InstalledModule.state == "enabled"))
        }
        for module_id in list(self.loaded):
            loaded = self.loaded[module_id]
            if rows.get(module_id) != loaded.manifest.module.version:
                self._unload(module_id)
        for module_id, version in rows.items():
            if module_id in self.loaded:
                continue
            try:
                cand = self.candidate(module_id)
                manifest = cand.manifest
                assert manifest is not None
                problems = self.trust_problems(manifest, cand.verification)
                if manifest.module.version != version:
                    problems.append("Files on disk do not match the installed version.")
                if problems:
                    raise ModuleError("; ".join(problems))
                self._activate(self._load(manifest, cand.path))
                log.info("Worker loaded module %s %s", module_id, version)
            except Exception as e:
                log.error(
                    "Module %s not loaded in the worker: %s",
                    module_id,
                    getattr(e, "detail", None) or e,
                )

    def run_periodic(self, now: float | None = None) -> int:
        """Run the periodic tasks that are due; returns how many ran."""
        now = time.monotonic() if now is None else now
        ran = 0
        for module_id in sorted(self.enabled):
            loaded = self.loaded.get(module_id)
            if loaded is None:
                continue
            for task in loaded.ctx.periodic_tasks:
                if task.last_run is not None and now - task.last_run < task.interval_seconds:
                    continue
                task.last_run = now
                ran += 1
                try:
                    task.fn()
                except Exception:
                    log.exception("Module %s: periodic task %s failed", module_id, task.name)
        return ran

    def is_enabled(self, module_id: str) -> bool:
        return module_id in self.enabled

    def health(self, module_id: str) -> HealthResult:
        loaded = self.loaded.get(module_id)
        if loaded is None or module_id not in self.enabled:
            return HealthResult("unknown", "Module is not running.")
        if not loaded.ctx.health_checks:
            return HealthResult("ok", "Module is running (no health checks declared).")
        worst: HealthResult = HealthResult("ok")
        order = {"ok": 0, "unknown": 1, "degraded": 2, "failed": 3}
        for check in loaded.ctx.health_checks:
            try:
                result = check()
            except Exception as e:  # a health check must never break the caller
                result = HealthResult("failed", f"Health check raised {type(e).__name__}: {e}")
            if order[result.status] > order[worst.status]:
                worst = result
        return worst

    def ui_extensions(self) -> list[dict[str, Any]]:
        out = []
        for module_id in sorted(self.enabled):
            m = self.loaded[module_id].manifest
            if not m.ui.nav and not m.ui.views:
                continue
            out.append(
                {
                    "module_id": module_id,
                    "module_name": m.module.name,
                    "api_base": f"{API_PREFIX}/{m.api.prefix}" if m.api else None,
                    "nav": [n.model_dump() for n in m.ui.nav],
                    "views": [v.model_dump() for v in m.ui.views],
                }
            )
        return out

    # ------------------------------------------------------------- internals
    def _row(self, db: Session, module_id: str) -> InstalledModule:
        row = db.get(InstalledModule, module_id)
        if row is None:
            raise ModuleError(f"Module {module_id} is not installed.", status=404)
        return row

    def _register_permissions(self, manifest: Manifest) -> None:
        for p in manifest.permissions:
            registry.register(
                PermissionDef(
                    p.key,
                    p.description,
                    module_id=manifest.id,
                    default_roles=tuple(p.default_roles),
                )
            )

    def _python_package_name(self, manifest: Manifest) -> str:
        return "veyra_ext_" + re.sub(r"[^a-z0-9]+", "_", manifest.id)

    def _load(self, manifest: Manifest, path: Path) -> LoadedModule:
        if manifest.id in self.loaded:
            return self.loaded[manifest.id]
        pkg_name = self._python_package_name(manifest)
        rel_module, _, attr = manifest.runtime.entrypoint.partition(":")
        top, *rest = rel_module.split(".")
        pkg_dir = path / top
        init = pkg_dir / "__init__.py"
        if not init.is_file():
            raise ModuleError(f"Entrypoint package {top!r} not found in {path}")
        spec = importlib.util.spec_from_file_location(
            pkg_name, init, submodule_search_locations=[str(pkg_dir)]
        )
        if spec is None or spec.loader is None:
            raise ModuleError(f"Cannot import module package for {manifest.id}")
        package: ModuleType = importlib.util.module_from_spec(spec)
        sys.modules[pkg_name] = package
        try:
            spec.loader.exec_module(package)
            target = importlib.import_module(".".join([pkg_name, *rest])) if rest else package
            entry = getattr(target, attr)
        except Exception:
            self._purge_python(pkg_name)
            raise
        data_dir = self.settings.data_dir / "modules" / manifest.id
        ctx = ModuleContext(manifest, path, data_dir, self.bus, self.settings)
        entry.register(ctx)
        loaded = LoadedModule(manifest, path, ctx, entry, pkg_name)
        self.loaded[manifest.id] = loaded
        return loaded

    def _activate(self, loaded: LoadedModule) -> None:
        module_id = loaded.manifest.id
        router = loaded.ctx.router
        if (
            router is not None
            and self.app is not None
            and module_id in self._mounted
            and not getattr(router, "_veyra_mounted", False)
        ):
            # Routes from an earlier load of this module are still mounted in
            # this process; new code takes effect after a service restart.
            self.restart_required.add(module_id)
        elif router is not None and self.app is not None and module_id not in self._mounted:
            assert loaded.manifest.api is not None
            self.app.include_router(
                router,
                prefix=f"{API_PREFIX}/{loaded.manifest.api.prefix}",
                tags=[f"module: {loaded.manifest.module.name}"],
                dependencies=[Depends(self._guard(module_id))],
            )
            router._veyra_mounted = True  # type: ignore[attr-defined]
            self._mounted.add(module_id)
            self.app.openapi_schema = None
        self.enabled.add(module_id)

    def _guard(self, module_id: str) -> Callable[[], None]:
        def module_enabled() -> None:
            if module_id not in self.enabled:
                raise ProblemError(
                    404, "Not found", "This module is not enabled.", code="module_disabled"
                )

        return module_enabled

    def _deactivate(self, module_id: str) -> None:
        self.enabled.discard(module_id)
        self.bus.unsubscribe_owner(module_id)

    def _unload(self, module_id: str) -> None:
        self._deactivate(module_id)
        loaded = self.loaded.pop(module_id, None)
        if loaded:
            self._purge_python(loaded.python_package)

    @staticmethod
    def _purge_python(pkg_name: str) -> None:
        for name in [n for n in sys.modules if n == pkg_name or n.startswith(pkg_name + ".")]:
            del sys.modules[name]

    def _call_hook(
        self, loaded: LoadedModule, name: str, *args: Any, swallow: bool = False
    ) -> None:
        hook = getattr(loaded.entry, name, None)
        if hook is None:
            return
        try:
            hook(loaded.ctx, *args)
        except Exception:
            log.exception("Module %s hook %s failed", loaded.manifest.id, name)
            if not swallow:
                raise
