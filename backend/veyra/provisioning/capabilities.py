# SPDX-License-Identifier: AGPL-3.0-or-later
"""Device capability catalog (docs/CONFIG_VERIFICATION.md §2): vendor packs
of families and firmware releases describing the parameters each device
accepts. Data only: the files are written by hand from the vendor's
documentation and reviewed through pull requests. A release file lists only
its changes against the release it extends; the loader resolves every
release into a flat table so the checker never walks the chain."""

from __future__ import annotations

import dataclasses
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

PACK_FILENAME = "pack.toml"
FAMILY_FILENAME = "family.toml"
SCHEMAS = (1,)

PACK_ID_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+){1,5}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
RELEASE_FILE_RE = re.compile(r"^[0-9][0-9.]{0,39}\.toml$")
VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){0,5}$")
# A parameter name, or a pattern with {n} and {m} for the indexes.
PARAM_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-\[\]{}]{0,199}$")
_PLACEHOLDER = re.compile(r"\{([a-z]+)\}")

Format = Literal["xml", "cfg", "grandstream-p", "algo-conf"]
VersionScheme = Literal["dotted", "yealink"]
Packaging = Literal["family", "model"]
Provenance = Literal["vendor-doc", "observed-on-hardware", "seeded-from-template"]
ParamType = Literal["bool", "int", "string", "enum", "ip", "url", "host"]


class CapabilityError(ValueError):
    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


# ---------------------------------------------------------------- versions


def parse_version(text: str, scheme: VersionScheme = "dotted") -> tuple[int, ...]:
    """A firmware version as numbers. Under the Yealink scheme the first
    number of a four-part version is the model's prefix (``108.86.0.15`` and
    ``66.86.0.15`` are both release 86.0.15), so it is dropped; catalog
    releases are written without it."""
    text = text.strip()
    m = re.match(r"^[0-9]+(?:\.[0-9]+)*", text)
    if not m:
        raise ValueError(f"{text!r} is not a version")
    parts = tuple(int(p) for p in m.group(0).split("."))
    if scheme == "yealink" and len(parts) >= 4:
        parts = parts[1:]
    return parts


def compare_versions(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    width = max(len(a), len(b))
    pa, pb = a + (0,) * (width - len(a)), b + (0,) * (width - len(b))
    return (pa > pb) - (pa < pb)


@dataclass(frozen=True)
class VersionRange:
    """``>=a, <b``; either bound may be missing."""

    low: tuple[int, ...] | None = None
    high: tuple[int, ...] | None = None
    text: str = ""

    def contains(self, v: tuple[int, ...]) -> bool:
        if self.low is not None and compare_versions(v, self.low) < 0:
            return False
        return not (self.high is not None and compare_versions(v, self.high) >= 0)


def parse_range(text: str) -> VersionRange:
    low = high = None
    for part in (p.strip() for p in text.split(",") if p.strip()):
        m = re.fullmatch(r"(>=|<)\s*([0-9]+(?:\.[0-9]+)*)", part)
        if not m:
            raise ValueError(f"{part!r}: use >=version and <version, separated by a comma")
        v = tuple(int(x) for x in m.group(2).split("."))
        if m.group(1) == ">=":
            low = v
        else:
            high = v
    if low is not None and high is not None and compare_versions(low, high) >= 0:
        raise ValueError(f"{text!r} is empty")
    return VersionRange(low, high, text)


# ---------------------------------------------------------------- schema 1


def _version(v: str) -> str:
    if not VERSION_RE.match(v):
        raise ValueError("a version is numbers separated by dots")
    return v


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # A key of [release.sources] in this release or one it extends.
    ref: str | None = None
    # Or the document named here (pack.toml, family.toml).
    title: str | None = None
    section: str = ""
    page: str = ""

    @model_validator(mode="after")
    def _one(self) -> SourceRef:
        if bool(self.ref) == bool(self.title):
            raise ValueError("a source has either ref or title")
        return self


class SourceDoc(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=300)
    version: str = ""
    url: str = ""


class IndexRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min: int = Field(1, ge=0)
    max: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _order(self) -> IndexRange:
        if self.max is not None and self.max < self.min:
            raise ValueError("max is below min")
        return self


class NumberRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min: int | None = None
    max: int | None = None


# The fields a parameter entry may carry. A ``changed`` table carries any of
# them; a full entry (``param``, ``added``) needs ``type`` and ``provenance``.
class EntryFields(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: ParamType | None = None
    format: str | None = None
    values: list[str] | None = None
    labels: dict[str, str] | None = None
    bool_values: list[str] | None = None
    range: NumberRange | None = None
    max_length: int | None = Field(None, ge=1)
    pattern: str | None = None
    allow_empty: bool | None = None
    default: str | None = None
    index: IndexRange | None = None
    index2: IndexRange | None = None
    index_max_by_model: dict[str, int] | None = None
    not_models: list[str] | None = None
    added_in: str | None = None
    note: str | None = Field(None, max_length=1000)
    source: SourceRef | None = None
    provenance: Provenance | None = None
    # What a seeded entry saw the template write, for the vendor-doc pass.
    seen: list[str] | None = None

    @field_validator("pattern")
    @classmethod
    def _pattern(cls, v: str | None) -> str | None:
        if v is not None:
            re.compile(v)
        return v

    @field_validator("added_in")
    @classmethod
    def _added(cls, v: str | None) -> str | None:
        return None if v is None else _version(v)


class Marker(BaseModel):
    """A ``deprecated`` or ``removed`` table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    replaced_by: str | None = None
    note: str | None = Field(None, max_length=1000)
    source: SourceRef | None = None


class ReleaseInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    extends: str | None = None
    applies_to: str | None = None
    # Under "model" packaging: the models this release is for.
    models: list[str] | None = None
    revision: int = Field(1, ge=1)
    sources: dict[str, SourceDoc] = Field(default_factory=dict)

    @field_validator("version", "extends")
    @classmethod
    def _versions(cls, v: str | None) -> str | None:
        return None if v is None else _version(v)

    @field_validator("applies_to")
    @classmethod
    def _range(cls, v: str | None) -> str | None:
        if v is not None:
            parse_range(v)
        return v


class ReleaseFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_: Literal[1] = Field(alias="schema")
    release: ReleaseInfo
    param: dict[str, EntryFields] = Field(default_factory=dict)
    added: dict[str, EntryFields] = Field(default_factory=dict)
    changed: dict[str, EntryFields] = Field(default_factory=dict)
    deprecated: dict[str, Marker] = Field(default_factory=dict)
    removed: dict[str, Marker] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _shape(self) -> ReleaseFile:
        if self.release.extends is None and (
            self.added or self.changed or self.deprecated or self.removed
        ):
            raise ValueError("a first release lists [param] only; changes need extends")
        if self.release.extends is not None and self.param:
            raise ValueError("a release that extends another lists changes, not [param]")
        return self


class FamilyInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    vendor: str
    family: str
    name: str = Field(min_length=1, max_length=100)
    models: list[str] = Field(min_length=1)
    format: Format
    version_scheme: VersionScheme = "dotted"
    firmware_packaging: Packaging = "family"
    # The filename patterns (as in template.toml) the checker reads.
    files: list[str] = Field(min_length=1)
    templates: list[str] = Field(default_factory=list)

    @field_validator("vendor", "family")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError("lower-case letters, digits and '-'")
        return v


class FamilyFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_: Literal[1] = Field(alias="schema")
    family: FamilyInfo


class Support(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    family: str
    models: list[str] = Field(min_length=1)
    firmware: str = ""
    source: SourceRef
    provenance: Provenance = "vendor-doc"

    @field_validator("firmware")
    @classmethod
    def _range(cls, v: str) -> str:
        if v:
            parse_range(v)
        return v


class PackInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str = Field(min_length=1, max_length=100)
    vendor: str
    version: str
    author: str = ""
    license: str = ""
    description: str = ""

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not PACK_ID_RE.match(v):
            raise ValueError("lower-case segments separated by '.' or '-', at least two")
        return v


class PackFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_: Literal[1] = Field(alias="schema")
    pack: PackInfo
    supports: list[Support] = Field(min_length=1)


# ---------------------------------------------------------------- resolved


@dataclass(frozen=True)
class Entry:
    """A parameter as one release sees it."""

    name: str
    type: str
    provenance: str
    format: str | None = None
    values: tuple[str, ...] | None = None
    labels: dict[str, str] = field(default_factory=dict)
    bool_values: tuple[str, ...] | None = None
    range_min: int | None = None
    range_max: int | None = None
    max_length: int | None = None
    pattern: str | None = None
    allow_empty: bool = False
    default: str | None = None
    index: IndexRange | None = None
    index2: IndexRange | None = None
    index_max_by_model: dict[str, int] = field(default_factory=dict)
    not_models: tuple[str, ...] = ()
    added_in: str | None = None
    deprecated_in: str | None = None
    removed_in: str | None = None
    replaced_by: str | None = None
    note: str = ""
    source: str = ""
    seen: tuple[str, ...] = ()
    regex: re.Pattern[str] | None = None


@dataclass
class Release:
    version: str
    parsed: tuple[int, ...]
    revision: int
    applies: VersionRange
    models: tuple[str, ...]
    path: str
    # Exact names first, then the indexed patterns.
    exact: dict[str, Entry] = field(default_factory=dict)
    patterns: list[Entry] = field(default_factory=list)

    @property
    def entries(self) -> list[Entry]:
        return [*self.exact.values(), *self.patterns]

    def lookup(self, parameter: str) -> tuple[Entry, tuple[int, ...]] | None:
        """The entry for a parameter and the index values it holds."""
        hit = self.exact.get(parameter)
        if hit is not None:
            return hit, ()
        for e in self.patterns:
            assert e.regex is not None
            m = e.regex.fullmatch(parameter)
            if m:
                return e, tuple(int(g) for g in m.groups())
        return None


@dataclass
class Family:
    info: FamilyInfo
    pack_id: str
    releases: list[Release]  # oldest first

    @property
    def key(self) -> str:
        return f"{self.info.vendor}/{self.info.family}"

    def release_for(self, version: str, model: str) -> tuple[Release | None, str]:
        """The release covering a firmware version on a model, and why:
        ``exact``, ``newer`` (past the newest release: checked against it),
        ``older`` (before the oldest: not checked) or ``invalid``."""
        try:
            v = parse_version(version, self.info.version_scheme)
        except ValueError:
            return None, "invalid"
        mine = [r for r in self.releases if not r.models or model in r.models]
        if not mine:
            return None, "older"
        newest = mine[-1]
        for r in reversed(mine):
            if r.applies.contains(v):
                # The newest release's own range is open; a later release
                # line (87 after 86, 2.0 after 1.2) is checked against it
                # but said to be newer than the catalog.
                cut = v[: len(r.parsed)]
                if r is newest and not r.applies.text and compare_versions(cut, r.parsed) > 0:
                    return r, "newer"
                return r, "exact"
        if compare_versions(v, newest.parsed) > 0:
            return newest, "newer"
        return None, "older"

    def oldest(self, model: str) -> Release | None:
        mine = [r for r in self.releases if not r.models or model in r.models]
        return mine[0] if mine else None


@dataclass
class Pack:
    info: PackInfo
    supports: list[Support]
    families: dict[str, Family]
    origin: str  # built-in | module:<id> | local
    path: str

    def covers(self, model: str) -> tuple[Family, Support] | None:
        for s in self.supports:
            if model in s.models:
                return self.families[s.family], s
        return None


def _origin_rank(origin: str) -> int:
    return 0 if origin == "local" else 1 if origin.startswith("module:") else 2


@dataclass
class CapabilityCatalog:
    packs: dict[str, Pack] = field(default_factory=dict)
    load_errors: dict[str, list[str]] = field(default_factory=dict)

    def add(self, pack: Pack) -> None:
        if pack.info.id in self.packs:
            raise CapabilityError(
                f"pack {pack.info.id} is already loaded from {self.packs[pack.info.id].path}"
            )
        self.packs[pack.info.id] = pack

    def family_for(self, vendor: str, model: str) -> tuple[Pack, Family, Support] | None:
        """The pack and family that cover a model; ``vendor`` is the
        template's manufacturer, compared without case."""
        want = vendor.strip().lower()
        # An imported pack wins over a module's, and a module's over a
        # built-in one, for the same models: an administrator who imports a
        # correction wants it used (docs/CONFIG_VERIFICATION.md §2.0).
        for pack in sorted(self.packs.values(), key=lambda p: _origin_rank(p.origin)):
            if pack.info.vendor != want:
                continue
            hit = pack.covers(model)
            if hit:
                return pack, hit[0], hit[1]
        return None

    @classmethod
    def from_paths(cls, paths: list[Path], origin: str = "built-in") -> CapabilityCatalog:
        catalog = cls()
        catalog.extend(paths, origin)
        return catalog

    def extend(self, paths: list[Path], origin: str) -> None:
        for base in paths:
            if not base.is_dir():
                continue
            for d in sorted(p for p in base.iterdir() if (p / PACK_FILENAME).is_file()):
                try:
                    self.add(load_pack(d, origin))
                except CapabilityError as e:
                    self.load_errors[str(d)] = e.errors


# ---------------------------------------------------------------- loading


def _read(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise CapabilityError(f"{path}: {e}") from e


def _schema_errors(path: Path, data: dict[str, Any]) -> list[str]:
    schema = data.get("schema")
    if schema not in SCHEMAS:
        return [f"{path.name}: schema {schema!r} is not one of {list(SCHEMAS)}"]
    return []


def _validate(model: type[BaseModel], path: Path, data: dict[str, Any]) -> Any:
    errors = _schema_errors(path, data)
    if errors:
        raise CapabilityError(f"Invalid {path.name}", errors)
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise CapabilityError(
            f"Invalid {path.name}",
            [
                f"{path.name}: {'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                for err in e.errors()
            ],
        ) from e


def _pattern_regex(name: str) -> re.Pattern[str] | None:
    holders = _PLACEHOLDER.findall(name)
    if not holders:
        return None
    out = ""
    last = 0
    for m in _PLACEHOLDER.finditer(name):
        out += re.escape(name[last : m.start()]) + r"([0-9]+)"
        last = m.end()
    return re.compile(out + re.escape(name[last:]))


def _cite(src: SourceRef | None, docs: dict[str, SourceDoc]) -> str:
    if src is None:
        return ""
    title = src.title or (docs[src.ref].title if src.ref and src.ref in docs else "")
    return ", ".join(p for p in (title, src.section, f"p. {src.page}" if src.page else "") if p)


def _check_entry(
    name: str, f: EntryFields, family: FamilyInfo, docs: dict[str, SourceDoc], where: str
) -> list[str]:
    errors = []
    if not PARAM_RE.match(name):
        errors.append(f"{where}: {name!r} is not a parameter name")
    holders = _PLACEHOLDER.findall(name)
    if any(h not in ("n", "m") for h in holders) or len(holders) != len(set(holders)):
        errors.append(f"{where}: only {{n}} and {{m}}, once each, may appear in {name!r}")
    if f.index is not None and "n" not in holders:
        errors.append(f"{where}: index without {{n}} in the name")
    if f.index2 is not None and "m" not in holders:
        errors.append(f"{where}: index2 without {{m}} in the name")
    if f.index_max_by_model and "n" not in holders:
        errors.append(f"{where}: index_max_by_model without {{n}} in the name")
    t = f.type
    if f.values is not None and t != "enum":
        errors.append(f"{where}: values are only for an enum")
    if t == "enum" and not f.values:
        errors.append(f"{where}: an enum lists its values")
    if f.labels and set(f.labels) - set(f.values or []):
        errors.append(f"{where}: labels for values the enum does not list")
    if f.range is not None and t != "int":
        errors.append(f"{where}: range is only for an int")
    if f.bool_values is not None and (t != "bool" or len(f.bool_values) != 2):
        errors.append(f"{where}: bool_values are two values of a bool")
    if (f.max_length is not None or f.pattern is not None) and t not in ("string", "host", "url"):
        errors.append(f"{where}: max_length and pattern are for text")
    for model in [*(f.index_max_by_model or {}), *(f.not_models or [])]:
        if model not in family.models:
            errors.append(f"{where}: {model!r} is not a model of the family")
    if f.source is not None and f.source.ref and f.source.ref not in docs:
        errors.append(f"{where}: source {f.source.ref!r} is not in any [release.sources]")
    if f.provenance in ("vendor-doc", "observed-on-hardware") and f.source is None:
        errors.append(f"{where}: a {f.provenance} entry cites its source")
    if f.seen is not None and f.provenance != "seeded-from-template":
        errors.append(f"{where}: seen is only for seeded entries")
    return errors


def _entry(name: str, f: EntryFields, docs: dict[str, SourceDoc], added_in: str | None) -> Entry:
    return Entry(
        name=name,
        type=f.type or "string",
        provenance=f.provenance or "seeded-from-template",
        format=f.format,
        values=tuple(f.values) if f.values is not None else None,
        labels=dict(f.labels or {}),
        bool_values=tuple(f.bool_values) if f.bool_values is not None else None,
        range_min=f.range.min if f.range else None,
        range_max=f.range.max if f.range else None,
        max_length=f.max_length,
        pattern=f.pattern,
        allow_empty=bool(f.allow_empty),
        default=f.default,
        index=f.index,
        index2=f.index2,
        index_max_by_model=dict(f.index_max_by_model or {}),
        not_models=tuple(f.not_models or ()),
        added_in=f.added_in or added_in,
        note=f.note or "",
        source=_cite(f.source, docs),
        seen=tuple(f.seen or ()),
        regex=_pattern_regex(name),
    )


def _fields(e: Entry) -> dict[str, Any]:
    """An entry back as the fields ``changed`` may replace."""
    return {
        "type": e.type,
        "format": e.format,
        "values": list(e.values) if e.values is not None else None,
        "labels": e.labels or None,
        "bool_values": list(e.bool_values) if e.bool_values is not None else None,
        "range": {"min": e.range_min, "max": e.range_max}
        if e.range_min is not None or e.range_max is not None
        else None,
        "max_length": e.max_length,
        "pattern": e.pattern,
        "allow_empty": e.allow_empty,
        "default": e.default,
        "index": e.index,
        "index2": e.index2,
        "index_max_by_model": e.index_max_by_model or None,
        "not_models": list(e.not_models) or None,
        "note": e.note or None,
        "provenance": e.provenance,
    }


def _build(
    files: dict[str, ReleaseFile], info: FamilyInfo, directory: Path
) -> tuple[list[Release], list[str]]:
    """Resolve every release of a family, oldest first."""
    errors: list[str] = []
    by_version = {f.release.version: (name, f) for name, f in files.items()}
    if len(by_version) != len(files):
        errors.append(f"{info.family}: two release files declare the same version")
    order = sorted(by_version, key=lambda v: parse_version(v))
    resolved: dict[str, tuple[dict[str, Entry], dict[str, SourceDoc]]] = {}

    def resolve(version: str, depth: int = 0) -> tuple[dict[str, Entry], dict[str, SourceDoc]]:
        if version in resolved:
            return resolved[version]
        name, rf = by_version[version]
        where = name
        rel = rf.release
        if depth > 64:
            raise CapabilityError(f"{where}: extends goes too deep")
        if rel.extends is None:
            docs = dict(rel.sources)
            table: dict[str, Entry] = {}
            for pname, f in rf.param.items():
                errors.extend(_check_entry(pname, f, info, docs, f"{where}: param {pname}"))
                if f.type is None or f.provenance is None:
                    errors.append(f"{where}: param {pname}: type and provenance are required")
                table[pname] = _entry(pname, f, docs, f.added_in)
        else:
            if rel.extends not in by_version:
                raise CapabilityError(f"{where}: extends {rel.extends}, which the family lacks")
            if compare_versions(parse_version(rel.extends), parse_version(version)) >= 0:
                raise CapabilityError(f"{where}: extends a release that is not older")
            parent, parent_docs = resolve(rel.extends, depth + 1)
            docs = {**parent_docs, **rel.sources}
            table = dict(parent)
            for pname, f in rf.added.items():
                errors.extend(_check_entry(pname, f, info, docs, f"{where}: added {pname}"))
                if pname in table and table[pname].removed_in is None:
                    errors.append(f"{where}: added {pname}, which {rel.extends} already has")
                if f.type is None or f.provenance is None:
                    errors.append(f"{where}: added {pname}: type and provenance are required")
                table[pname] = _entry(pname, f, docs, version)
            for pname, f in rf.changed.items():
                old = table.get(pname)
                if old is None:
                    errors.append(f"{where}: changed {pname}, which {rel.extends} does not have")
                    continue
                merged = {k: v for k, v in _fields(old).items() if v is not None}
                merged.update(f.model_dump(exclude_none=True))
                if "source" not in f.model_fields_set:
                    merged.pop("source", None)
                ef = EntryFields.model_validate(merged)
                errors.extend(_check_entry(pname, ef, info, docs, f"{where}: changed {pname}"))
                new = _entry(pname, ef, docs, old.added_in)
                table[pname] = _replace(
                    new,
                    deprecated_in=old.deprecated_in,
                    replaced_by=old.replaced_by,
                    source=new.source or old.source,
                )
            for kind, markers in (("deprecated", rf.deprecated), ("removed", rf.removed)):
                for pname, mk in markers.items():
                    old = table.get(pname)
                    if old is None:
                        errors.append(f"{where}: {kind} {pname}, which {rel.extends} lacks")
                        continue
                    if mk.source is not None and mk.source.ref and mk.source.ref not in docs:
                        errors.append(f"{where}: {kind} {pname}: unknown source {mk.source.ref!r}")
                    changes: dict[str, Any] = {f"{kind}_in": version}
                    if mk.replaced_by:
                        changes["replaced_by"] = mk.replaced_by
                    if mk.note:
                        changes["note"] = mk.note
                    cite = _cite(mk.source, docs)
                    if cite:
                        changes["source"] = cite
                    table[pname] = _replace(old, **changes)
        resolved[version] = (table, docs)
        return resolved[version]

    releases: list[Release] = []
    for i, version in enumerate(order):
        name, rf = by_version[version]
        try:
            table, _ = resolve(version)
        except CapabilityError as e:
            errors.extend(e.errors)
            continue
        rel = rf.release
        if rel.applies_to:
            applies = parse_range(rel.applies_to)
        else:
            nxt = next(
                (
                    v
                    for v in order[i + 1 :]
                    if not rel.models
                    or not by_version[v][1].release.models
                    or set(rel.models) & set(by_version[v][1].release.models or [])
                ),
                None,
            )
            applies = VersionRange(parse_version(version), parse_version(nxt) if nxt else None, "")
        if info.firmware_packaging == "model":
            if not rel.models:
                errors.append(f"{name}: with model packaging a release names its models")
            for m in rel.models or []:
                if m not in info.models:
                    errors.append(f"{name}: {m!r} is not a model of the family")
        elif rel.models:
            errors.append(f'{name}: models on a release need firmware_packaging = "model"')
        release = Release(
            version=version,
            parsed=parse_version(version),
            revision=rel.revision,
            applies=applies,
            models=tuple(rel.models or ()),
            path=str(directory / name),
        )
        for ent in table.values():
            if ent.regex is None:
                release.exact[ent.name] = ent
            else:
                release.patterns.append(ent)
        releases.append(release)
    # Overlapping ranges for the same model would make a version ambiguous.
    for a_i, a in enumerate(releases):
        for b in releases[a_i + 1 :]:
            if a.models and b.models and not set(a.models) & set(b.models):
                continue
            if _overlap(a.applies, b.applies):
                errors.append(f"{info.family}: releases {a.version} and {b.version} overlap")
    return releases, errors


def _overlap(a: VersionRange, b: VersionRange) -> bool:
    def below(x: tuple[int, ...] | None, y: tuple[int, ...] | None) -> bool:
        # x is a high bound, y a low bound: does x come at or before y?
        return x is not None and y is not None and compare_versions(x, y) <= 0

    return not (below(a.high, b.low) or below(b.high, a.low))


def _replace(e: Entry, **changes: Any) -> Entry:
    return dataclasses.replace(e, **changes)


def load_family(directory: Path, pack_id: str, vendor: str) -> tuple[Family, list[str]]:
    info = _validate(FamilyFile, directory / FAMILY_FILENAME, _read(directory / FAMILY_FILENAME))
    errors: list[str] = []
    if info.family.family != directory.name:
        errors.append(f"{directory.name}/family.toml: family {info.family.family!r} must match")
    if info.family.vendor != vendor:
        errors.append(f"{directory.name}/family.toml: vendor differs from the pack's")
    files: dict[str, ReleaseFile] = {}
    for path in sorted(directory.glob("*.toml")):
        if path.name == FAMILY_FILENAME:
            continue
        if not RELEASE_FILE_RE.match(path.name):
            errors.append(f"{directory.name}/{path.name}: a release file is named <version>.toml")
            continue
        try:
            rf = _validate(ReleaseFile, path, _read(path))
        except CapabilityError as e:
            errors.extend(f"{directory.name}/{x}" for x in e.errors)
            continue
        if path.stem != rf.release.version:
            errors.append(f"{directory.name}/{path.name}: version {rf.release.version} differs")
        files[path.name] = rf
    if not files:
        errors.append(f"{directory.name}: no release files")
    releases, more = _build(files, info.family, directory)
    errors.extend(f"{directory.name}/{x}" for x in more)
    return Family(info.family, pack_id, releases), errors


def load_pack(directory: Path, origin: str = "built-in") -> Pack:
    """Load and check a pack directory; raises ``CapabilityError`` with every
    problem found."""
    meta = _validate(PackFile, directory / PACK_FILENAME, _read(directory / PACK_FILENAME))
    errors: list[str] = []
    families: dict[str, Family] = {}
    for sub in sorted(p for p in directory.iterdir() if p.is_dir()):
        if not (sub / FAMILY_FILENAME).is_file():
            continue
        try:
            fam, errs = load_family(sub, meta.pack.id, meta.pack.vendor)
        except CapabilityError as e:
            errors.extend(f"{sub.name}/{x}" for x in e.errors)
            continue
        errors.extend(errs)
        families[fam.info.family] = fam
    covered: dict[str, set[str]] = {}
    for i, s in enumerate(meta.supports):
        where = f"pack.toml: supports[{i}]"
        target = families.get(s.family)
        if target is None:
            errors.append(f"{where}: the pack has no family {s.family!r}")
            continue
        for m in s.models:
            if m not in target.info.models:
                errors.append(f"{where}: {m!r} is not a model of {s.family}")
        covered.setdefault(s.family, set()).update(s.models)
    for name, fam in families.items():
        missing = set(fam.info.models) - covered.get(name, set())
        if missing:
            errors.append(
                f"pack.toml: no supports entry covers {', '.join(sorted(missing))} of {name}"
            )
    seen_models: dict[str, str] = {}
    for name, fam in families.items():
        for m in fam.info.models:
            if m in seen_models:
                errors.append(f"model {m!r} is in both {seen_models[m]} and {name}")
            seen_models[m] = name
    if errors:
        raise CapabilityError(f"Invalid pack {directory.name}", errors)
    return Pack(meta.pack, list(meta.supports), families, origin, str(directory))
