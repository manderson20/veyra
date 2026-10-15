# SPDX-License-Identifier: AGPL-3.0-or-later
"""The module API (version ``veyra.version.MODULE_API_VERSION``).

A module's entrypoint object receives a :class:`ModuleContext` in
``register(ctx)``. Everything a module may do with the core goes through
this object; modules must not import other ``veyra.*`` internals except the
documented SDK surface re-exported from ``veyra.sdk``.
"""

from __future__ import annotations

import fnmatch
import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter
from sqlalchemy import MetaData, select
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.db import session_scope
from veyra.core.deps import require
from veyra.core.errors import ProblemError
from veyra.core.events import Event, EventBus
from veyra.core.models import ModuleConfig, User
from veyra.core.security.crypto import (
    DecryptionError,
    InstallationKey,
    InstallationKeyError,
    load_installation_key,
)
from veyra.core.security.principal import Principal

if TYPE_CHECKING:
    from veyra.core.config import Settings
    from veyra.modules.manifest import Manifest

HealthStatus = Literal["ok", "degraded", "failed", "unknown"]


@dataclass(frozen=True)
class HealthResult:
    status: HealthStatus
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PeriodicTask:
    """Background work run by the worker service (module API 1.1)."""

    name: str
    interval_seconds: int
    fn: Callable[[], None]
    last_run: float | None = None


class ModuleAPIError(RuntimeError):
    pass


class ModuleContext:
    def __init__(
        self,
        manifest: Manifest,
        module_dir: Path,
        data_dir: Path,
        bus: EventBus,
        settings: Settings | None = None,
    ) -> None:
        self.manifest = manifest
        self.module_id = manifest.id
        self.module_dir = module_dir
        self.data_dir = data_dir
        self.log = logging.getLogger(f"veyra.module.{manifest.id}")
        self._bus = bus
        self.router: APIRouter | None = None
        self.metadata: MetaData | None = None
        self.health_checks: list[Callable[[], HealthResult]] = []
        self.periodic_tasks: list[PeriodicTask] = []
        self._settings = settings
        self._own_permissions = {p.key for p in manifest.permissions}

    # -- HTTP API --------------------------------------------------------------
    def add_router(self, router: APIRouter) -> None:
        if self.manifest.api is None:
            raise ModuleAPIError("Module declares no [api] section")
        if self.router is not None:
            raise ModuleAPIError("add_router() may only be called once")
        self.router = router

    def require(self, permission: str) -> Callable[..., Principal]:
        """Permission dependency; modules may only check their own permissions."""
        if permission not in self._own_permissions:
            raise ModuleAPIError(f"Permission {permission!r} is not declared by this module")
        return require(permission)

    # -- database --------------------------------------------------------------
    def register_metadata(self, metadata: MetaData) -> None:
        prefix = self.manifest.database.table_prefix if self.manifest.database else None
        if prefix is None:
            raise ModuleAPIError("Module declares no [database] section")
        bad = [t for t in metadata.tables if not t.startswith(prefix)]
        if bad:
            raise ModuleAPIError(f"Tables must be prefixed with {prefix!r}: {bad}")
        self.metadata = metadata

    @contextmanager
    def session(self) -> Iterator[Session]:
        with session_scope() as s:
            yield s

    # -- events ----------------------------------------------------------------
    def subscribe(self, pattern: str, handler: Callable[[Event], None]) -> None:
        if not any(
            fnmatch.fnmatchcase(pattern, d) or pattern == d for d in self.manifest.events.subscribes
        ):
            raise ModuleAPIError(f"Event pattern {pattern!r} is not declared in events.subscribes")
        self._bus.subscribe(pattern, handler, owner=self.module_id)

    def publish(self, name: str, payload: dict[str, Any] | None = None) -> None:
        if not any(fnmatch.fnmatchcase(name, p) for p in self.manifest.events.publishes):
            raise ModuleAPIError(f"Event {name!r} is not declared in events.publishes")
        self._bus.publish(Event(name, payload or {}, source=self.module_id))

    # -- health ----------------------------------------------------------------
    def add_health_check(self, check: Callable[[], HealthResult]) -> None:
        self.health_checks.append(check)

    # -- background work (module API 1.1) -------------------------------------
    def add_periodic_task(self, name: str, interval_seconds: int, fn: Callable[[], None]) -> None:
        """Run ``fn`` about every ``interval_seconds`` (at least 5) in the
        worker service while the module is enabled. Use ``session()`` inside;
        exceptions are logged and never stop the worker."""
        if interval_seconds < 5:
            raise ModuleAPIError("interval_seconds must be at least 5")
        self.periodic_tasks.append(PeriodicTask(name, interval_seconds, fn))

    # -- secrets (module API 1.1) ---------------------------------------------
    def encrypt(self, plaintext: str) -> str:
        """Encrypt a secret (a device password) with the installation key,
        bound to this module: other modules cannot decrypt it."""
        return self._key().encrypt(plaintext, f"module:{self.module_id}")

    def decrypt(self, token: str) -> str:
        return self._key().decrypt(token, f"module:{self.module_id}")

    def _key(self) -> InstallationKey:
        from veyra.core.config import get_settings

        try:
            return load_installation_key(self._settings or get_settings())
        except InstallationKeyError as e:
            raise ProblemError(
                503, "Secrets unavailable", f"The installation key cannot be loaded: {e}"
            ) from e

    # -- configuration ---------------------------------------------------------
    def get_config(self, db: Session, organization_id: uuid.UUID | None = None) -> dict[str, Any]:
        """Effective configuration: manifest defaults overlaid with stored values.
        Secret fields are returned decrypted only to the module itself."""
        values = {f.key: f.default for f in self.manifest.config}
        for org in (None, organization_id) if organization_id else (None,):
            row = db.scalar(
                select(ModuleConfig).where(
                    ModuleConfig.module_id == self.module_id,
                    ModuleConfig.organization_id.is_(None)
                    if org is None
                    else ModuleConfig.organization_id == org,
                )
            )
            if row:
                values.update(row.config)
        # Secrets are stored encrypted for this module (the settings API).
        for f in self.manifest.config:
            if f.type == "secret" and values.get(f.key):
                try:
                    values[f.key] = self.decrypt(str(values[f.key]))
                except DecryptionError:
                    self.log.warning("Setting %s cannot be decrypted", f.key)
                    values[f.key] = None
        return values

    def default_organization(self, db: Session, principal: Principal) -> uuid.UUID | None:
        """The caller's home organization (used when a request names none)."""
        user = db.get(User, principal.user_id)
        return user.home_organization_id if user else None

    def organization_timezone(self, db: Session, organization_id: uuid.UUID) -> str:
        """The organization's IANA time zone (module API 1.1), for times
        administrators type in."""
        from veyra.core.models import Organization

        org = db.get(Organization, organization_id)
        return org.timezone if org and org.timezone else "UTC"

    # -- audit -----------------------------------------------------------------
    def audit(self, db: Session, principal: Principal | None, action: str, **kwargs: Any) -> None:
        audit.record(
            db,
            action=f"{self.module_id}:{action}",
            actor_type="user" if principal else "module",
            actor_user_id=principal.user_id if principal else None,
            actor_label=principal.label if principal else self.module_id,
            **kwargs,
        )
