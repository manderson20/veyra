# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provisioning template specification (``template.toml``)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from veyra.core.semver import Version

TEMPLATE_FILENAME = "template.toml"
TEMPLATE_KEY_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+){1,7}$")
VARIABLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

Format = Literal["xml", "json", "ini", "cfg", "text"]
Source = Literal["official", "community", "local"]
Status = Literal["stable", "experimental", "deprecated"]


class VariableDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    type: Literal["string", "integer", "boolean"] = "string"
    description: str = ""
    sensitive: bool = False
    required: bool = False
    default: str | int | bool | None = None
    max_length: int = 255
    pattern: str | None = None


# The approved core variables. Templates may declare additional, non-colliding
# variables; anything else referenced by a template is a validation error.
CORE_VARIABLES: tuple[VariableDef, ...] = (
    VariableDef(
        name="extension_number",
        description="Extension number",
        required=True,
        pattern=r"^[0-9*#+]{1,32}$",
    ),
    VariableDef(
        name="sip_username",
        description="SIP authentication user",
        required=True,
        pattern=r"^[A-Za-z0-9._@+-]{1,80}$",
    ),
    VariableDef(
        name="sip_password", description="SIP authentication secret", sensitive=True, required=True
    ),
    VariableDef(
        name="sip_server",
        description="SIP registrar host or address",
        required=True,
        pattern=r"^[A-Za-z0-9.:\[\]-]{1,255}$",
    ),
    VariableDef(name="sip_port", type="integer", description="SIP registrar port", default=5060),
    VariableDef(name="display_name", description="Name shown on the phone", max_length=80),
    VariableDef(name="caller_id", description="Outbound caller ID name", max_length=80),
    VariableDef(
        name="timezone",
        description="IANA time zone, e.g. America/Chicago",
        default="UTC",
        pattern=r"^[A-Za-z0-9_+\-/]{1,64}$",
    ),
    VariableDef(
        name="ntp_server",
        description="NTP server",
        default="pool.ntp.org",
        pattern=r"^[A-Za-z0-9.:\[\]-]{1,255}$",
    ),
    VariableDef(name="vlan_id", type="integer", description="Voice VLAN ID (blank = none)"),
    VariableDef(
        name="provisioning_url",
        description="Provisioning server base URL",
        pattern=r"^https?://[A-Za-z0-9.:\[\]/_-]{1,500}$",
    ),
)
# Device facts available to filenames and templates (not user-editable values).
DEVICE_VARIABLES = ("mac", "mac_upper", "model", "model_slug")
# Structured facts (spec version 2, docs/DEVICE_PROVISIONING.md §4.1): read-only
# objects Veyra builds from the device, its profile, extensions and zones.
FACT_NAMES = ("device", "organization", "lines", "keys", "paging", "server", "features", "vars")
CORE_NAMES = {v.name for v in CORE_VARIABLES}


class FileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(
        description="Output filename pattern, may use {mac}, {mac_upper}, {model_slug}"
    )
    source: str = Field("", description="Template source file, relative to the template directory")
    format: Format
    # A checksum file instead of a template: the MD5 of another output file
    # in ``md5sum`` form (Algo, docs/PROVISIONING_BREADTH.md §4).
    checksum_of: str | None = Field(
        None, description="Output filename pattern of the file whose MD5 this file holds"
    )

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z0-9{}_.-]{1,128}$", v) or ".." in v:
            raise ValueError(
                "filename pattern may only contain letters, digits, '.', '_', '-' "
                "and {placeholders}"
            )
        for ph in re.findall(r"{([^}]*)}", v):
            if ph not in ("mac", "mac_upper", "model_slug"):
                raise ValueError(f"unknown filename placeholder {{{ph}}}")
        return v

    @field_validator("source")
    @classmethod
    def _source(cls, v: str) -> str:
        if not v:
            return v  # a checksum file has no source (checked below)
        p = PurePosixPath(v)
        if p.is_absolute() or ".." in p.parts or "\\" in v:
            raise ValueError("source must be a relative path inside the template")
        return v

    @model_validator(mode="after")
    def _source_or_checksum(self) -> FileSpec:
        if bool(self.source) == bool(self.checksum_of):
            raise ValueError("a file has either a source or checksum_of")
        return self


class TemplateInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    name: str
    version: str
    manufacturer: str
    models: list[str] = Field(default_factory=list)
    abstract: bool = False
    parent: str | None = None
    # Parent version this template was derived from; lets the UI flag local
    # templates whose official parent has since been updated.
    parent_version: str | None = None
    firmware: str = Field(
        "", description="Firmware compatibility, free text, e.g. 'UC Software 6.4+'"
    )
    status: Status = "experimental"
    description: str = ""

    @field_validator("key", "parent")
    @classmethod
    def _key(cls, v: str | None) -> str | None:
        if v is not None and not TEMPLATE_KEY_RE.match(v):
            raise ValueError("must be lower-case segments separated by '.' or '-'")
        return v

    @field_validator("version")
    @classmethod
    def _version(cls, v: str) -> str:
        Version.parse(v)
        return v


class TemplateManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    spec_version: Literal[1, 2] = 1
    template: TemplateInfo
    files: list[FileSpec] = Field(default_factory=list)
    variables: list[VariableDef] = Field(default_factory=list)
    defaults: dict[str, str | int | bool] = Field(default_factory=dict)
    features: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self) -> TemplateManifest:
        names = set()
        for var in self.variables:
            if (
                not VARIABLE_RE.match(var.name)
                or var.name in CORE_NAMES
                or var.name in DEVICE_VARIABLES
                or var.name in FACT_NAMES
            ):
                raise ValueError(
                    f"variable {var.name!r} is invalid or collides with a core variable"
                )
            names.add(var.name)
        if not self.template.abstract and not self.template.models:
            raise ValueError("non-abstract templates must list the models they support")
        for key in self.defaults:
            if key == "sip_password":
                raise ValueError("templates may not carry a default SIP password")
        return self


class TemplateError(ValueError):
    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


def parse_template_manifest(data: dict[str, Any]) -> TemplateManifest:
    try:
        return TemplateManifest.model_validate(data)
    except ValidationError as e:
        raise TemplateError(
            "Invalid template manifest",
            [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()],
        ) from e


def load_template_manifest(directory: Path) -> TemplateManifest:
    path = directory / TEMPLATE_FILENAME
    try:
        return parse_template_manifest(tomllib.loads(path.read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise TemplateError(f"Cannot read {path}: {e}") from e
