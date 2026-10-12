"""Module manifest (``module.toml``) specification and validation.

The authoritative specification is docs/MODULE_DEVELOPMENT.md. This file is
the executable form of it; ``veyra modules schema`` prints the JSON Schema.
"""

from __future__ import annotations

import re
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from veyra.core.semver import Version, VersionError, VersionRange

MANIFEST_FILENAME = "module.toml"
MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+){1,7}$")
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
ENTRYPOINT_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$"
)


class ManifestError(ValueError):
    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


class RuntimeType(StrEnum):
    IN_PROCESS = "in_process"  # official modules only
    SERVICE = "service"  # isolated process; required for community/third-party code


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModuleInfo(_Strict):
    id: str
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    version: str
    author: str = Field(min_length=1, max_length=200)
    license: str = Field(min_length=1, max_length=100, description="SPDX license expression")
    homepage: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not MODULE_ID_RE.match(v):
            raise ValueError(
                "must be lower-case, dot/dash separated, at least two segments (e.g. 'acme.paging')"
            )
        return v

    @field_validator("version")
    @classmethod
    def _version(cls, v: str) -> str:
        try:
            Version.parse(v)
        except VersionError as e:
            raise ValueError(str(e)) from e
        return v


class Compatibility(_Strict):
    core_api: str = Field(description="Range of the Veyra module API, e.g. '>=1.0.0 <2.0.0'")
    engines: list[str] = Field(default_factory=list, description="Empty = engine independent")

    @field_validator("core_api")
    @classmethod
    def _range(cls, v: str) -> str:
        try:
            VersionRange.parse(v)
        except VersionError as e:
            raise ValueError(str(e)) from e
        return v


class Runtime(_Strict):
    type: RuntimeType = RuntimeType.IN_PROCESS
    entrypoint: str = Field(description="'package.module:object' relative to the module directory")

    @field_validator("entrypoint")
    @classmethod
    def _entry(cls, v: str) -> str:
        if not ENTRYPOINT_RE.match(v):
            raise ValueError("must look like 'backend:module' or 'backend.main:module'")
        return v


class Dependency(_Strict):
    id: str
    version: str = "*"
    optional: bool = False

    @field_validator("version")
    @classmethod
    def _range(cls, v: str) -> str:
        VersionRange.parse(v)
        return v


class PermissionSpec(_Strict):
    key: str
    description: str
    default_roles: list[str] = Field(default_factory=list)


ConfigFieldType = Literal["string", "integer", "boolean", "choice", "secret"]


class ConfigField(_Strict):
    key: str
    label: str
    type: ConfigFieldType
    help: str | None = None
    default: Any = None
    required: bool = False
    min: int | None = None
    max: int | None = None
    max_length: int | None = None
    choices: list[str] | None = None
    scope: Literal["installation", "organization"] = "installation"

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not IDENT_RE.match(v):
            raise ValueError("must be a lower_snake_case identifier")
        return v

    @model_validator(mode="after")
    def _choices(self) -> ConfigField:
        if self.type == "choice" and not self.choices:
            raise ValueError("choice fields require 'choices'")
        if self.type == "secret" and self.default is not None:
            raise ValueError("secret fields may not have a default")
        return self


class Database(_Strict):
    migrations: str | None = Field(None, description="Alembic script directory")
    table_prefix: str


class Api(_Strict):
    prefix: str = Field(description="Mounted at /api/v1/ext/<prefix>")

    @field_validator("prefix")
    @classmethod
    def _prefix(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError("must be a lower-case slug")
        return v


class Events(_Strict):
    subscribes: list[str] = Field(default_factory=list)
    publishes: list[str] = Field(default_factory=list)


class UiColumn(_Strict):
    key: str
    label: str
    format: Literal["text", "datetime", "boolean", "status"] = "text"


class UiFormField(_Strict):
    key: str
    label: str
    type: Literal["text", "textarea", "integer", "boolean", "choice"] = "text"
    required: bool = False
    max_length: int | None = None
    choices: list[str] | None = None
    help: str | None = None


class UiView(_Strict):
    """Declarative views rendered by the core UI. Modules do not ship JavaScript
    into the administrative origin; see docs/MODULE_DEVELOPMENT.md §UI."""

    id: str
    title: str
    type: Literal["resource_table"]
    description: str | None = None
    endpoint: str = Field(description="Path relative to the module API prefix")
    permission: str
    write_permission: str | None = None
    columns: list[UiColumn]
    create_form: list[UiFormField] = Field(default_factory=list)
    delete: bool = False
    empty_title: str = "Nothing here yet"
    empty_body: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError("must be a lower-case slug")
        return v

    @field_validator("endpoint")
    @classmethod
    def _endpoint(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9][a-z0-9/_-]*$", v) or ".." in v:
            raise ValueError("must be a relative path made of lower-case segments")
        return v


class UiNav(_Strict):
    label: str
    view: str
    icon: str = "puzzle"
    permission: str


class Ui(_Strict):
    nav: list[UiNav] = Field(default_factory=list)
    views: list[UiView] = Field(default_factory=list)


class Manifest(_Strict):
    manifest_version: Literal[1] = 1
    module: ModuleInfo
    compatibility: Compatibility
    runtime: Runtime
    dependencies: list[Dependency] = Field(default_factory=list)
    permissions: list[PermissionSpec] = Field(default_factory=list)
    config: list[ConfigField] = Field(default_factory=list)
    database: Database | None = None
    api: Api | None = None
    events: Events = Field(default_factory=Events)
    ui: Ui = Field(default_factory=Ui)
    health_check: bool = False

    @property
    def id(self) -> str:
        return self.module.id

    @property
    def version(self) -> Version:
        return Version.parse(self.module.version)

    @property
    def permission_namespace(self) -> str:
        """Module permissions must start with this prefix."""
        return self.module.id.split(".")[-1].replace("-", "_") + "."

    @model_validator(mode="after")
    def _cross_checks(self) -> Manifest:
        ns = self.permission_namespace
        own = set()
        for p in self.permissions:
            if not p.key.startswith(ns) or not re.match(r"^[a-z0-9_]+\.[a-z0-9_.]+$", p.key):
                raise ValueError(f"permission {p.key!r} must start with {ns!r}")
            own.add(p.key)
        view_ids = {v.id for v in self.ui.views}
        for nav in self.ui.nav:
            if nav.view not in view_ids:
                raise ValueError(f"ui.nav refers to unknown view {nav.view!r}")
        for v in self.ui.views:
            for perm in (v.permission, v.write_permission):
                if perm and perm not in own:
                    raise ValueError(f"view {v.id!r} uses undeclared permission {perm!r}")
            if v.create_form and not v.write_permission:
                raise ValueError(f"view {v.id!r} has a create form but no write_permission")
        if self.ui.views and self.api is None:
            raise ValueError("ui.views require an [api] section")
        if self.database:
            prefix = self.database.table_prefix
            if not re.match(r"^mod_[a-z0-9_]+_$", prefix):
                raise ValueError("database.table_prefix must look like 'mod_<name>_'")
        for pattern in self.events.publishes:
            if not pattern.startswith(ns):
                raise ValueError(f"published event {pattern!r} must start with {ns!r}")
        keys = [c.key for c in self.config]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate config keys")
        return self


def parse_manifest(data: dict[str, Any]) -> Manifest:
    try:
        return Manifest.model_validate(data)
    except ValidationError as e:
        errors = [
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" if err["loc"] else err["msg"]
            for err in e.errors()
        ]
        raise ManifestError("Invalid module manifest", errors) from e


def load_manifest(module_dir: Path) -> Manifest:
    path = module_dir / MANIFEST_FILENAME
    if not path.is_file():
        raise ManifestError(f"{MANIFEST_FILENAME} not found in {module_dir}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"{MANIFEST_FILENAME} is not valid TOML: {e}") from e
    return parse_manifest(data)


def manifest_json_schema() -> dict[str, Any]:
    return Manifest.model_json_schema()
