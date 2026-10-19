# SPDX-License-Identifier: AGPL-3.0-or-later
"""Template catalog, inheritance resolution and sandboxed rendering.

Security properties:
* Templates are rendered by Jinja2's SandboxedEnvironment with StrictUndefined;
  they cannot call arbitrary Python, read files or reach the network.
* Templates can only load sources from their own inheritance chain.
* Every value is validated against its variable definition before rendering.
* XML output is auto-escaped, so values cannot inject markup.
* Output filenames are validated (no separators, no traversal).
* Sensitive variables are masked in previews and never exported.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jinja2 import BaseLoader, StrictUndefined, TemplateNotFound, TemplateSyntaxError, meta
from jinja2.exceptions import SecurityError, UndefinedError
from jinja2.sandbox import ImmutableSandboxedEnvironment

from veyra.provisioning.spec import (
    CORE_VARIABLES,
    DEVICE_VARIABLES,
    FACT_NAMES,
    TEMPLATE_FILENAME,
    FileSpec,
    TemplateError,
    TemplateManifest,
    VariableDef,
    load_template_manifest,
)

MASK = "********"
# What templates see for the structured facts when a preview renders without a
# device (docs/DEVICE_PROVISIONING.md §4.1).
EMPTY_FACTS: dict[str, Any] = {
    "device": {},
    "organization": {},
    "lines": [],
    "keys": [],
    "paging": {"enabled": False, "groups": []},
    "server": {},
    "features": {},
    "vars": {},
}
MAX_SOURCE_BYTES = 256 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024
OUTPUT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAC_RE = re.compile(r"^[0-9a-f]{12}$")
_TEXT_SUFFIXES = {".j2", ".cfg", ".xml", ".json", ".ini", ".txt", ".conf", ".tmpl"}


@dataclass
class TemplateRecord:
    manifest: TemplateManifest
    source: str  # official | community | local
    sources: dict[str, str] = field(default_factory=dict)  # relative path -> template text

    @property
    def key(self) -> str:
        return self.manifest.template.key


@dataclass
class ResolvedTemplate:
    record: TemplateRecord
    chain: list[TemplateRecord]  # self first, root last
    files: list[FileSpec]
    variables: dict[str, VariableDef]
    defaults: dict[str, Any]

    @property
    def features(self) -> set[str]:
        """Features declared anywhere in the inheritance chain."""
        return {f for r in self.chain for f in r.manifest.features}


@dataclass
class RenderedFile:
    filename: str
    format: str
    content: str


def read_template_dir(directory: Path, source: str) -> TemplateRecord:
    manifest = load_template_manifest(directory)
    sources: dict[str, str] = {}
    root = directory.resolve()
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or path.name == TEMPLATE_FILENAME
            or path.suffix not in _TEXT_SUFFIXES
        ):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise TemplateError(f"Template {manifest.template.key}: links are not allowed")
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise TemplateError(f"Template {manifest.template.key}: {path.name} is too large")
        sources[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return TemplateRecord(manifest, source, sources)


class TemplateCatalog:
    def __init__(self) -> None:
        self.records: dict[str, TemplateRecord] = {}
        self.load_errors: dict[str, list[str]] = {}

    @classmethod
    def from_paths(cls, paths: list[Path]) -> TemplateCatalog:
        """Load ``<path>/official/*`` and ``<path>/community/*`` template directories."""
        catalog = cls()
        for base in paths:
            for source in ("official", "community"):
                d = base / source
                if not d.is_dir():
                    continue
                for tdir in sorted(p for p in d.iterdir() if (p / TEMPLATE_FILENAME).is_file()):
                    try:
                        catalog.add(read_template_dir(tdir, source))
                    except TemplateError as e:
                        catalog.load_errors[str(tdir)] = e.errors
        return catalog

    def add(self, record: TemplateRecord) -> None:
        existing = self.records.get(record.key)
        # Official templates cannot be shadowed by a community template with the same key.
        if existing and existing.source == "official" and record.source != "official":
            raise TemplateError(f"Template key {record.key!r} is reserved by an official template")
        self.records[record.key] = record

    def resolve(self, key: str) -> ResolvedTemplate:
        record = self.records.get(key)
        if record is None:
            raise TemplateError(f"Template {key!r} not found")
        chain: list[TemplateRecord] = [record]
        seen = {key}
        while chain[-1].manifest.template.parent:
            parent_key = chain[-1].manifest.template.parent
            assert parent_key is not None
            if parent_key in seen:
                raise TemplateError(f"Template inheritance loop at {parent_key!r}")
            parent = self.records.get(parent_key)
            if parent is None:
                raise TemplateError(f"Parent template {parent_key!r} not found")
            chain.append(parent)
            seen.add(parent_key)
            if len(chain) > 8:
                raise TemplateError("Template inheritance is too deep (max 8)")
        files: dict[str, FileSpec] = {}
        variables: dict[str, VariableDef] = {v.name: v for v in CORE_VARIABLES}
        defaults: dict[str, Any] = {
            v.name: v.default for v in CORE_VARIABLES if v.default is not None
        }
        for rec in reversed(chain):  # root first, child overrides
            for f in rec.manifest.files:
                files[f.name] = f
            for v in rec.manifest.variables:
                variables[v.name] = v
                if v.default is not None:
                    defaults[v.name] = v.default
            defaults.update(rec.manifest.defaults)
        return ResolvedTemplate(record, chain, list(files.values()), variables, defaults)


class _ChainLoader(BaseLoader):
    """Resolves ``name`` within the inheritance chain; ``<key>/<path>`` addresses
    a specific ancestor (used for ``{% extends %}`` of a parent's file)."""

    def __init__(self, chain: list[TemplateRecord]) -> None:
        self.chain = chain
        self.by_key = {r.key: r for r in chain}

    def get_source(self, environment: Any, template: str) -> tuple[str, str | None, Any]:
        p = PurePosixPath(template)
        if p.is_absolute() or ".." in p.parts:
            raise TemplateNotFound(template)
        first, _, rest = template.partition("/")
        if first in self.by_key and rest:
            rec = self.by_key[first]
            if rest in rec.sources:
                return rec.sources[rest], None, lambda: True
            raise TemplateNotFound(template)
        for rec in self.chain:
            if template in rec.sources:
                return rec.sources[template], None, lambda: True
        raise TemplateNotFound(template)


def _utc_offset_seconds(tz: str, when: datetime | None = None) -> int:
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return 0
    offset = (when or datetime.now(zone)).astimezone(zone).utcoffset()
    return int(offset.total_seconds()) if offset else 0


def _bool01(value: Any) -> str:
    return "1" if value else "0"


def _environment(chain: list[TemplateRecord], autoescape: bool) -> ImmutableSandboxedEnvironment:
    env = ImmutableSandboxedEnvironment(
        loader=_ChainLoader(chain),
        undefined=StrictUndefined,
        autoescape=autoescape,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    # No globals (range, cycler, lipsum, ...): templates only see their variables.
    # This also removes the easiest route to CPU-exhaustion loops.
    env.globals.clear()
    env.filters["utc_offset_seconds"] = _utc_offset_seconds
    env.filters["bool01"] = _bool01
    return env


def normalize_mac(mac: str) -> str:
    value = re.sub(r"[^0-9a-fA-F]", "", mac).lower()
    if not MAC_RE.match(value):
        raise TemplateError("MAC address must contain 12 hexadecimal digits")
    return value


def output_filename(pattern: str, mac: str, model: str) -> str:
    name = (
        pattern.replace("{mac}", mac)
        .replace("{mac_upper}", mac.upper())
        .replace("{model_slug}", model_slug(model))
    )
    if not OUTPUT_NAME_RE.match(name) or ".." in name:
        raise TemplateError(f"Generated filename {name!r} is not allowed")
    return name


def coerce_one(var: VariableDef, raw: Any) -> Any:
    """One value checked against its definition; ``ValueError`` with a short
    reason ("longer than 80 characters") when it does not fit."""
    if var.type == "integer":
        return int(raw)
    if var.type == "boolean":
        return raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes", "on")
    value = str(raw)
    if len(value) > var.max_length:
        raise ValueError(f"longer than {var.max_length} characters")
    if any(ord(c) < 32 for c in value):
        raise ValueError("contains control characters")
    if var.pattern and not re.match(var.pattern, value):
        raise ValueError("has an invalid format")
    return value


def coerce_values(resolved: ResolvedTemplate, values: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    unknown = set(values) - set(resolved.variables)
    if unknown:
        errors.append(f"Unknown variables: {', '.join(sorted(unknown))}")
    out: dict[str, Any] = {}
    for name, var in resolved.variables.items():
        raw = values.get(name, resolved.defaults.get(name))
        if raw is None or raw == "":
            if var.required:
                errors.append(f"{name} is required")
            out[name] = None
            continue
        try:
            value = coerce_one(var, raw)
        except (ValueError, TypeError) as e:
            errors.append(f"{name} {e}")
            continue
        out[name] = value
    if errors:
        raise TemplateError("Template values are invalid", errors)
    return out


def validate(resolved: ResolvedTemplate) -> list[str]:
    """Static validation: syntax, sandbox-safe sources, declared variables only."""
    problems: list[str] = []
    if resolved.record.manifest.template.abstract:
        return problems  # rendered only through a concrete child template
    allowed = set(resolved.variables) | set(DEVICE_VARIABLES) | set(FACT_NAMES)
    for f in resolved.files:
        if f.checksum_of:
            continue  # no source to check
        env = _environment(resolved.chain, autoescape=f.format == "xml")
        try:
            source, _, _ = env.loader.get_source(env, f.source)  # type: ignore[union-attr]
            ast = env.parse(source)
        except TemplateNotFound:
            problems.append(f"{f.name}: source {f.source!r} not found")
            continue
        except TemplateSyntaxError as e:
            problems.append(f"{f.name}: syntax error on line {e.lineno}: {e.message}")
            continue
        undeclared = meta.find_undeclared_variables(ast) - allowed
        if undeclared:
            problems.append(f"{f.name}: uses undeclared variables {sorted(undeclared)}")
    if not resolved.files:
        problems.append("Template produces no files")
    return problems


def model_slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")


def render(
    resolved: ResolvedTemplate,
    values: Mapping[str, Any],
    *,
    mac: str,
    model: str,
    mask_secrets: bool = False,
    facts: Mapping[str, Any] | None = None,
) -> list[RenderedFile]:
    """Render every file of a concrete template. ``facts`` are the structured
    objects of spec version 2 (already masked by the caller when needed); they
    are added to the context as they are, never validated as variables."""
    if resolved.record.manifest.template.abstract:
        raise TemplateError("Abstract templates cannot be rendered; use a model template")
    if model not in resolved.record.manifest.template.models:
        raise TemplateError(f"Template {resolved.record.key} does not support model {model!r}")
    mac = normalize_mac(mac)
    context = coerce_values(resolved, values)
    if mask_secrets:
        for name, var in resolved.variables.items():
            if var.sensitive and context.get(name) is not None:
                context[name] = MASK
    context.update(mac=mac, mac_upper=mac.upper(), model=model, model_slug=model_slug(model))
    if facts is None:
        # Previews without a device: sample facts derived from the values.
        from veyra.provisioning.facts import sample_facts  # local import: facts uses this module

        facts = sample_facts({k: v for k, v in context.items() if v is not None}, mac, model)
    for name in FACT_NAMES:
        context[name] = facts.get(name, EMPTY_FACTS[name])
    rendered: list[RenderedFile] = []
    for f in resolved.files:
        if f.checksum_of:
            continue  # computed below, from the rendered file it covers
        env = _environment(resolved.chain, autoescape=f.format == "xml")
        try:
            content = env.get_template(f.source).render(context)
        except (
            UndefinedError,
            SecurityError,
            TemplateSyntaxError,
            TemplateNotFound,
            OverflowError,
            TypeError,
            ValueError,
        ) as e:
            raise TemplateError(f"{f.name}: rendering failed: {e}") from e
        if len(content.encode()) > MAX_OUTPUT_BYTES:
            raise TemplateError(f"{f.name}: output is too large")
        rendered.append(RenderedFile(output_filename(f.name, mac, model), f.format, content))
    by_name = {r.filename: r for r in rendered}
    for f in resolved.files:
        if not f.checksum_of:
            continue
        target_name = output_filename(f.checksum_of, mac, model)
        target = by_name.get(target_name)
        if target is None:
            raise TemplateError(f"{f.name}: checksum of {target_name!r}, which is not rendered")
        digest = hashlib.md5(target.content.encode(), usedforsecurity=False).hexdigest()
        rendered.append(
            RenderedFile(
                output_filename(f.name, mac, model), f.format, f"{digest}  {target_name}\n"
            )
        )
    return rendered


def export_template(record: TemplateRecord) -> dict[str, Any]:
    """Portable export (JSON-serializable). Never includes secrets: sensitive
    variables lose their defaults and sip_password can never have one."""
    manifest = record.manifest.model_dump(mode="json")
    for var in manifest.get("variables", []):
        if var.get("sensitive"):
            var["default"] = None
    sensitive = {v["name"] for v in manifest.get("variables", []) if v.get("sensitive")} | {
        v.name for v in CORE_VARIABLES if v.sensitive
    }
    manifest["defaults"] = {
        k: v for k, v in manifest.get("defaults", {}).items() if k not in sensitive
    }
    return {
        "format": "veyra-provisioning-template",
        "format_version": 1,
        "manifest": manifest,
        "sources": dict(record.sources),
    }
