# SPDX-License-Identifier: AGPL-3.0-or-later
"""The configuration checker (docs/CONFIG_VERIFICATION.md §3): a pure
function from rendered phone files to findings. It never touches the
database and never runs when a phone fetches a file.

Each rule has a stable id that is part of a finding's fingerprint. Changing
what a rule does means a new id (``enum.2``), so overrides already given
keep matching the findings they were given for."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

from veyra.provisioning import base_edits
from veyra.provisioning.capabilities import CapabilityCatalog, Entry, Family, Release, parse_version

Severity = Literal["error", "warning", "info"]
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
FINGERPRINT_PREFIX = "cv1:"
MASKED = "••••"
_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?$"
)
DEFAULT_BOOL = ("0", "1")


@dataclass(frozen=True)
class Target:
    """One device model on one firmware version, as the checker sees it."""

    vendor: str
    model: str
    firmware: str | None
    # Where the version came from: device-image, profile-image, reported,
    # oldest (the family's oldest release), none.
    how: str


@dataclass
class Finding:
    severity: Severity
    rule: str
    message: str
    file: str
    parameter: str = ""
    pattern: str = ""
    value: str = ""
    vendor: str = ""
    family: str = ""
    model: str = ""
    firmware: str = ""
    release: str = ""
    catalog_revision: int = 0
    note: str = ""
    source: str = ""
    provenance: str = ""
    # The Veyra fields that filled the setting, or "fixed" (§3.0).
    filled_by: list[str] = field(default_factory=list)
    accepts: str = ""
    # For a summarizing finding: the settings it stands for.
    members: list[str] = field(default_factory=list)
    # The part of the fingerprint that stands for the value.
    value_key: str = ""
    fingerprint: str = ""

    def finish(self) -> Finding:
        raw = "|".join(
            (
                self.vendor,
                self.family,
                self.model,
                self.release,
                self.file,
                self.parameter,
                self.value_key or self.value,
                self.rule,
            )
        )
        self.fingerprint = FINGERPRINT_PREFIX + hashlib.sha256(raw.encode()).hexdigest()
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "severity": self.severity,
            "rule": self.rule,
            "message": self.message,
            "file": self.file,
            "parameter": self.parameter,
            "pattern": self.pattern,
            "value": self.value,
            "vendor": self.vendor,
            "family": self.family,
            "model": self.model,
            "firmware": self.firmware,
            "release": self.release,
            "catalog_revision": self.catalog_revision,
            "note": self.note,
            "source": self.source,
            "provenance": self.provenance,
            "filled_by": self.filled_by,
            "accepts": self.accepts,
            "members": self.members,
        }


@dataclass(frozen=True)
class FileInput:
    """A rendered file to check: its pattern in template.toml (never the
    MAC), its format and its content after Base File Edits."""

    pattern: str
    format: str
    content: str


# ------------------------------------------------------------------ helpers


def is_secret(parameter: str) -> bool:
    return bool(base_edits.SECRET_NAME.search(parameter))


def _value_key(parameter: str, value: str) -> str:
    if is_secret(parameter):
        return "sha256:" + hashlib.sha256(value.encode()).hexdigest()
    return value


def accepts(entry: Entry) -> str:
    """What the setting accepts, in words, for the check window."""
    if entry.type == "enum" and entry.values:
        return ", ".join(f"{v} {entry.labels[v]}" if v in entry.labels else v for v in entry.values)
    if entry.type == "bool":
        return " or ".join(entry.bool_values or DEFAULT_BOOL)
    if entry.type == "int":
        if entry.range_min is not None and entry.range_max is not None:
            return f"a whole number from {entry.range_min} to {entry.range_max}"
        if entry.range_min is not None:
            return f"a whole number from {entry.range_min}"
        if entry.range_max is not None:
            return f"a whole number up to {entry.range_max}"
        return "a whole number"
    words = {"ip": "an IP address", "url": "an address (URL)", "host": "a host name or address"}
    text = words.get(entry.type, "text")
    if entry.max_length:
        text += f", up to {entry.max_length} characters"
    return text


def has_value_rules(entry: Entry) -> bool:
    """Whether the entry can reject a value at all. A seeded entry cannot."""
    if entry.provenance == "seeded-from-template":
        return False
    return entry.type != "string" or bool(entry.max_length or entry.pattern)


def value_problem(entry: Entry, value: str) -> tuple[str, str] | None:
    """``(rule, message)`` when the value breaks the entry's rules."""
    if value == "" and (entry.allow_empty or entry.type == "string"):
        return None
    t = entry.type
    if t == "bool":
        allowed = entry.bool_values or DEFAULT_BOOL
        if value not in allowed:
            return "type.bool", f"{value!r} is not {' or '.join(allowed)}."
        return None
    if t == "int":
        if not re.fullmatch(r"-?[0-9]+", value):
            return "type.int", f"{value!r} is not a whole number."
        n = int(value)
        if (entry.range_min is not None and n < entry.range_min) or (
            entry.range_max is not None and n > entry.range_max
        ):
            return "range.1", f"{value} is outside {entry.range_min} to {entry.range_max}."
        return None
    if t == "enum":
        if value not in (entry.values or ()):
            return "enum.1", f"{value!r} is not a value this firmware knows ({accepts(entry)})."
        return None
    if t == "ip":
        try:
            ipaddress.ip_address(value)
        except ValueError:
            return "type.ip", f"{value!r} is not an IP address."
        return None
    if t == "url":
        u = urlparse(value)
        if u.scheme not in ("http", "https", "ftp", "ftps", "tftp") or not u.netloc:
            return "type.url", f"{value!r} is not an address (URL)."
    if t == "host":
        host = value.rsplit(":", 1)[0] if value.count(":") == 1 else value
        try:
            ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            if not _HOST_RE.match(host):
                return "type.host", f"{value!r} is not a host name or address."
    if entry.max_length is not None and len(value) > entry.max_length:
        return (
            "type.string",
            f"{len(value)} characters; this setting takes at most {entry.max_length}.",
        )
    if entry.pattern is not None and not re.fullmatch(entry.pattern, value):
        return "type.string", f"{value!r} is not in the form this setting takes."
    return None


def _index_problem(entry: Entry, index: tuple[int, ...], model: str) -> tuple[str, str] | None:
    limits = [entry.index, entry.index2]
    for i, n in enumerate(index):
        lim = limits[i] if i < len(limits) else None
        top = lim.max if lim else None
        if i == 0 and model in entry.index_max_by_model:
            top = entry.index_max_by_model[model]
        low = lim.min if lim else 1
        if n < low or (top is not None and n > top):
            return "index.range", f"index {n} is outside {low} to {top} on {model}."
    return None


def _later(family: Family, release: Release, parameter: str) -> Release | None:
    """The first later release that has the parameter (``param.not-yet``)."""
    for r in family.releases:
        if r.parsed <= release.parsed or (release.models and r.models and model_gap(r, release)):
            continue
        hit = r.lookup(parameter)
        if hit and hit[0].removed_in is None:
            return r
    return None


def model_gap(a: Release, b: Release) -> bool:
    return not set(a.models) & set(b.models)


# ------------------------------------------------------------------ check


@dataclass
class Setting:
    file: str
    parameter: str
    value: str
    filled_by: list[str] = field(default_factory=list)
    # Composite: built from several fields, or a field and fixed text (§3.0).
    composite: bool = False
    # A field-filled value; the fingerprint uses the fields, not the value.
    varies: bool = False


def check_settings(
    catalog: CapabilityCatalog,
    target: Target,
    files: list[FileInput],
    settings: dict[str, list[Setting]],
) -> list[Finding]:
    """Check settings already found in files. ``settings`` maps a file
    pattern to its settings; files the family does not check are reported
    as skipped."""
    out: list[Finding] = []
    hit = catalog.family_for(target.vendor, target.model)
    base: dict[str, Any] = {"vendor": target.vendor.lower(), "model": target.model}
    if hit is None:
        for f in files:
            out.append(
                Finding(
                    "info",
                    "catalog.none",
                    f"No capability pack covers the {target.vendor} {target.model}: "
                    "this file was not checked.",
                    f.pattern,
                    **base,
                    members=[s.parameter for s in settings.get(f.pattern, [])],
                ).finish()
            )
        return out
    pack, family, _support = hit
    base["family"] = family.info.family
    version = target.firmware
    release, why = (None, "older")
    if version:
        release, why = family.release_for(version, target.model)
    else:
        release, why = family.oldest(target.model), "oldest"
    if release is None:
        for f in files:
            out.append(
                Finding(
                    "info",
                    "catalog.none",
                    f"{pack.info.name} has no data for firmware {version or '(unknown)'} on "
                    f"the {target.model}: this file was not checked.",
                    f.pattern,
                    **base,
                    firmware=version or "",
                    members=[s.parameter for s in settings.get(f.pattern, [])],
                ).finish()
            )
        return out
    rel: dict[str, Any] = {
        **base,
        "firmware": version or release.version,
        "release": release.version,
        "catalog_revision": release.revision,
    }
    if why == "newer":
        out.append(
            Finding(
                "info",
                "catalog.newer-firmware",
                f"Firmware {version} is newer than {pack.info.name}'s data; checked "
                f"against release {release.version}.",
                files[0].pattern if files else "",
                **rel,
            ).finish()
        )
    for f in files:
        if f.pattern not in family.info.files:
            out.append(
                Finding(
                    "info",
                    "file.skipped",
                    f"{family.info.name} does not check this file.",
                    f.pattern,
                    **rel,
                ).finish()
            )
            continue
        unverified: list[str] = []
        unknown: list[str] = []
        for s in settings.get(f.pattern, []):
            found = release.lookup(s.parameter)
            if found is None:
                later = _later(family, release, s.parameter)
                if later is not None:
                    out.append(
                        _finding(
                            "error",
                            "param.not-yet",
                            f"Added in firmware {later.version}; release {release.version} "
                            "does not know this setting.",
                            s,
                            None,
                            rel,
                        )
                    )
                else:
                    unknown.append(s.parameter)
                continue
            entry, index = found
            out.extend(_check_one(entry, index, s, target.model, rel))
            if entry.provenance == "seeded-from-template":
                unverified.append(s.parameter)
        if unverified:
            out.append(
                Finding(
                    "info",
                    "entry.unverified",
                    f"{len(unverified)} settings are checked against data taken from Veyra's "
                    "own templates, not yet from the vendor's guide.",
                    f.pattern,
                    **rel,
                    members=sorted(set(unverified)),
                ).finish()
            )
        if unknown:
            out.append(
                Finding(
                    "info",
                    "param.not-in-catalog",
                    f"{len(set(unknown))} settings are not in {pack.info.name}'s data: they were "
                    "not checked.",
                    f.pattern,
                    **rel,
                    members=sorted(set(unknown)),
                ).finish()
            )
    return out


def _finding(
    severity: Severity,
    rule: str,
    message: str,
    s: Setting,
    entry: Entry | None,
    rel: dict[str, Any],
) -> Finding:
    secret = is_secret(s.parameter)
    value_key = "fields:" + ",".join(s.filled_by) if s.varies else _value_key(s.parameter, s.value)
    return Finding(
        severity,
        rule,
        message,
        s.file,
        parameter=s.parameter,
        pattern=entry.name if entry else "",
        value=MASKED if secret else s.value,
        note=entry.note if entry else "",
        source=entry.source if entry else "",
        provenance=entry.provenance if entry else "",
        filled_by=list(s.filled_by),
        accepts=accepts(entry) if entry else "",
        value_key=value_key,
        **rel,
    ).finish()


def _check_one(
    entry: Entry, index: tuple[int, ...], s: Setting, model: str, rel: dict[str, Any]
) -> list[Finding]:
    out = []
    if model in entry.not_models:
        out.append(
            _finding(
                "error", "param.unknown-model", f"The {model} ignores this setting.", s, entry, rel
            )
        )
    if entry.removed_in is not None:
        out.append(
            _finding(
                "error",
                "param.removed",
                f"Removed in firmware {entry.removed_in}.",
                s,
                entry,
                rel,
            )
        )
        return out
    if entry.deprecated_in is not None:
        replaced = f" Use {entry.replaced_by} instead." if entry.replaced_by else ""
        out.append(
            _finding(
                "warning",
                "param.deprecated",
                f"Deprecated since firmware {entry.deprecated_in}.{replaced}",
                s,
                entry,
                rel,
            )
        )
    problem = _index_problem(entry, index, model)
    if problem:
        out.append(_finding("error", problem[0], problem[1], s, entry, rel))
    problem = value_problem(entry, s.value)
    if problem:
        out.append(_finding("error", problem[0], problem[1], s, entry, rel))
    if s.composite and has_value_rules(entry):
        out.append(
            _finding(
                "warning",
                "binding.composite",
                "Built from several Veyra fields and fixed text; checked with their shortest "
                "and longest values. Review it.",
                s,
                entry,
                rel,
            )
        )
    return out


def file_settings(f: FileInput) -> list[Setting]:
    """The settings of a rendered file, each a fixed value."""
    fmt = "xml" if f.format == "xml" else "cfg"
    return [Setting(f.pattern, s.parameter, s.value) for s in base_edits.settings(fmt, f.content)]


def check_files(
    catalog: CapabilityCatalog, target: Target, files: list[FileInput]
) -> list[Finding]:
    """Check rendered files as they are: every value is taken as fixed."""
    return sort_findings(
        check_settings(catalog, target, files, {f.pattern: file_settings(f) for f in files})
    )


def sort_findings(findings: Iterable[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f.severity], f.file, f.parameter, f.rule))


# ------------------------------------------------------------------ targets


def firmware_targets(
    vendor: str,
    model: str,
    *,
    device_image: str | None = None,
    profile_image: str | None = None,
    reported: Iterable[str | None] = (),
    catalog: CapabilityCatalog | None = None,
) -> list[Target]:
    """The versions to check one model against (§3.5): the assigned image
    (device first, then profile), else every distinct reported version, else
    the oldest release of the family. Versions of the same catalog release
    are checked once."""
    if device_image:
        candidates = [(device_image, "device-image")]
    elif profile_image:
        candidates = [(profile_image, "profile-image")]
    else:
        candidates = [(v, "reported") for v in dict.fromkeys(r for r in reported if r)]
    if not candidates:
        return [Target(vendor, model, None, "oldest")]
    hit = catalog.family_for(vendor, model) if catalog else None
    out: list[Target] = []
    seen: set[str] = set()
    for version, how in candidates:
        key = version
        if hit is not None:
            release, _why = hit[1].release_for(version, model)
            if release is not None:
                key = f"release:{release.version}"
            else:
                try:
                    key = ".".join(map(str, parse_version(version, hit[1].info.version_scheme)))
                except ValueError:
                    key = version
        if key in seen:
            continue
        seen.add(key)
        out.append(Target(vendor, model, version, how))
    return out
