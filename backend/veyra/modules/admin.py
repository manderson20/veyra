# SPDX-License-Identifier: AGPL-3.0-or-later
"""Module operations shared by the API and the CLI: applying a package,
rolling back, and reading or changing module settings (#149).

Errors are :class:`ProblemError`; the API returns them as they are and the
CLI prints their detail and field errors."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from veyra.core.errors import ProblemError, not_found
from veyra.core.models import InstalledModule, ModuleConfig
from veyra.core.security.crypto import InstallationKey
from veyra.core.semver import Version
from veyra.modules import catalog
from veyra.modules.manager import ModuleError, ModuleManager


def apply_package(
    db: Session,
    engine: Engine,
    mgr: ModuleManager,
    store: catalog.Store,
    package: bytes,
    *,
    unsigned_permitted: bool,
    expect_id: str | None = None,
    enable: bool = False,
) -> tuple[str, str, str]:
    """Verify into the store, check, activate, then install or update.
    Returns (module id, version, what happened)."""
    try:
        manifest, verification = store.add(package, mgr.keyring, unsigned_permitted)
    except catalog.CatalogError as e:
        raise ProblemError(422, "Package refused", str(e), code="package_refused") from e
    if expect_id is not None and manifest.id != expect_id:
        raise ProblemError(
            422,
            "Package refused",
            f"The package is {manifest.id}, not {expect_id}.",
            code="package_refused",
        )
    problems = mgr.trust_problems(manifest, verification) + mgr.compatibility_problems(db, manifest)
    row = db.get(InstalledModule, manifest.id)
    current = row.version if row is not None and row.state != "removed" else None
    if current is not None and Version.parse(manifest.module.version) <= Version.parse(current):
        problems.append(
            f"Version {manifest.module.version} is not newer than the installed {current}."
        )
    if problems:
        raise ProblemError(
            409,
            "Cannot install",
            " ".join(problems),
            code="module_not_installable",
            errors=[{"field": "package", "message": p} for p in problems],
        )
    store.activate(manifest.id, manifest.module.version)
    try:
        if current is None:
            mgr.install(db, engine, manifest.id)
            what = "installed"
            if enable:
                mgr.enable(db, manifest.id)
                what = "installed and enabled"
        else:
            mgr.apply_update(db, engine, manifest.id)
            what = f"updated from {current}"
    except ModuleError as e:
        raise ProblemError(
            e.status,
            "Module operation failed",
            e.detail,
            code="module_error",
            errors=[{"field": "module", "message": p["message"]} for p in e.errors or []],
        ) from e
    return manifest.id, manifest.module.version, what


def rollback(
    db: Session, mgr: ModuleManager, store: catalog.Store, module_id: str
) -> tuple[str, str]:
    """Go back to the previous version kept in the store. Returns (from, to)."""
    row = db.get(InstalledModule, module_id)
    current = store.active_dir(module_id)
    previous = store.previous(module_id)
    if row is None or row.state == "removed" or current is None or previous is None:
        raise ProblemError(
            409,
            "Nothing to roll back to",
            "No previous version of this module is kept.",
            code="no_previous_version",
        )
    added = catalog.migration_files(current) - catalog.migration_files(previous[0])
    if added:
        raise ProblemError(
            409,
            "Cannot roll back",
            "The current version changed the module's database; it cannot go back automatically.",
            code="rollback_blocked",
        )
    old = row.version
    store.activate(module_id, previous[1].module.version)
    row.version = previous[1].module.version
    row.manifest = previous[1].model_dump(mode="json")
    if module_id in mgr.loaded:
        mgr.restart_required.add(module_id)
    return old, row.version


# ---------------------------------------------------------------- settings


def purpose(module_id: str) -> str:
    return f"module:{module_id}"


def config_fields(
    db: Session, module_id: str, organization_id: uuid.UUID | None
) -> list[dict[str, Any]]:
    """Installation-wide fields, or the organization-scoped ones when an
    organization is given."""
    row = db.get(InstalledModule, module_id)
    if row is None or row.state == "removed":
        raise not_found("Installed module")
    return [
        f
        for f in (row.manifest or {}).get("config", [])
        if (f.get("scope") == "organization") == (organization_id is not None)
    ]


def _config_row(
    db: Session, module_id: str, organization_id: uuid.UUID | None
) -> ModuleConfig | None:
    return db.scalar(
        select(ModuleConfig).where(
            ModuleConfig.module_id == module_id,
            ModuleConfig.organization_id == organization_id
            if organization_id
            else ModuleConfig.organization_id.is_(None),
        )
    )


def read_config(db: Session, module_id: str, organization_id: uuid.UUID | None) -> dict[str, Any]:
    """Fields and values; secrets are reported as ``{"has_value": bool}``."""
    fields = config_fields(db, module_id, organization_id)
    row = _config_row(db, module_id, organization_id)
    stored = dict(row.config) if row else {}
    values: dict[str, Any] = {}
    for f in fields:
        if f["type"] == "secret":
            values[f["key"]] = {"has_value": bool(stored.get(f["key"]))}
        else:
            values[f["key"]] = stored.get(f["key"], f.get("default"))
    return {"fields": fields, "values": values}


def _validate(f: dict[str, Any], v: Any) -> Any:
    t, key = f["type"], f["key"]

    def bad(msg: str) -> ProblemError:
        return ProblemError(
            422,
            "Validation failed",
            f"{f['label']}: {msg}",
            code="validation_failed",
            errors=[{"field": key, "message": msg}],
        )

    if v is None or v == "":
        if f.get("required") and t != "secret":
            raise bad("required")
        return None
    if t == "integer":
        try:
            v = int(v)
        except (TypeError, ValueError) as e:
            raise bad("must be a whole number") from e
        if f.get("min") is not None and v < f["min"]:
            raise bad(f"at least {f['min']}")
        if f.get("max") is not None and v > f["max"]:
            raise bad(f"at most {f['max']}")
        return v
    if t == "boolean":
        if not isinstance(v, bool):
            raise bad("must be true or false")
        return v
    v = str(v)
    if f.get("max_length") and len(v) > f["max_length"]:
        raise bad(f"at most {f['max_length']} characters")
    if t == "choice" and v not in (f.get("choices") or []):
        raise bad("not one of the choices")
    return v


def write_config(
    db: Session,
    module_id: str,
    organization_id: uuid.UUID | None,
    values: dict[str, Any],
    load_key: Callable[[], InstallationKey],
) -> None:
    """Validate and store ``values``. A secret set to ``None`` is unchanged
    and ``""`` removes it; ``load_key`` is called only when a secret is set."""
    fields = {f["key"]: f for f in config_fields(db, module_id, organization_id)}
    unknown = set(values) - set(fields)
    if unknown:
        raise ProblemError(
            422,
            "Validation failed",
            f"Unknown setting {sorted(unknown)[0]!r}.",
            code="validation_failed",
        )
    row = _config_row(db, module_id, organization_id)
    stored = dict(row.config) if row else {}
    key = None
    for k, v in values.items():
        f = fields[k]
        if f["type"] == "secret":
            if v is None:
                continue  # unchanged
            if v == "":
                stored.pop(k, None)  # removed
                continue
            key = key or load_key()
            stored[k] = key.encrypt(str(v), purpose(module_id))
        else:
            stored[k] = _validate(f, v)
    for k, f in fields.items():
        if f.get("required") and f["type"] == "secret" and not stored.get(k):
            raise ProblemError(
                422,
                "Validation failed",
                f"{f['label']}: required",
                code="validation_failed",
                errors=[{"field": k, "message": "required"}],
            )
    if row is None:
        db.add(ModuleConfig(module_id=module_id, organization_id=organization_id, config=stored))
    else:
        row.config = stored
