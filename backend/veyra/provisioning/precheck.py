# SPDX-License-Identifier: AGPL-3.0-or-later
"""The precheck (docs/CONFIG_VERIFICATION.md §3.0): check a template, with a
profile's values, keys and Base File Edits, against the vendor's catalog,
without a real phone. The template is rendered with sample facts three
times, with each Veyra field at its typical, shortest and longest value
(``domains.FACT_DOMAINS``). The typical values are distinctive, so the
precheck can tell which field filled which setting.

A setting that breaks a rule with the typical values is an error. One that
breaks it only at a field's shortest or longest value is a warning: some
phones may be refused. No database is used; the caller supplies the keys
and paging it wants checked, or the precheck uses one key of each type."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from veyra.provisioning import base_edits
from veyra.provisioning.capabilities import CapabilityCatalog
from veyra.provisioning.domains import FACT_DOMAINS
from veyra.provisioning.facts import sample_facts
from veyra.provisioning.renderer import RenderedFile, ResolvedTemplate, coerce_values, render
from veyra.provisioning.spec import TemplateError
from veyra.provisioning.variables import VarsView
from veyra.provisioning.verify import (
    FileInput,
    Finding,
    Setting,
    Target,
    check_settings,
    sort_findings,
)

SAMPLE_MAC = "0004f2a7391c"
VARIANTS = ("typical", "shortest", "longest")
# Typical values shorter than this are too common to say which field they came from.
_MIN_MARK = 4
SAMPLE_TIMEZONE = "America/Chicago"  # has daylight saving, so those settings are written


def _v(path: str, variant: str) -> str:
    d = FACT_DOMAINS[path]
    return d.samples().get(variant, d.typical)


def default_keys(variant: str = "typical") -> list[dict[str, Any]]:
    """One key of each type the official templates know."""
    label = _v("key.label", variant)
    value = _v("key.value", variant)
    return [
        {"index": 1, "type": "line", "value": "1", "label": label or "Line 1"},
        {"index": 2, "type": "blf", "value": value, "label": label, "blf_index": 1},
        {"index": 3, "type": "speed_dial", "value": value, "label": label, "speed_dial_index": 1},
        {"index": 4, "type": "record", "value": "*1", "label": label, "speed_dial_index": 2},
        {"index": 5, "type": "transfer", "value": "", "label": label},
        {
            "index": 6,
            "type": "page",
            "value": "qzone-hall",
            "label": label,
            "group": 1,
            "multicast_address": _v("zone.multicast_address", variant),
            "multicast_port": 5001,
        },
    ]


def default_paging(variant: str = "typical") -> dict[str, Any]:
    return {
        "enabled": True,
        "address": "239.7.3.90",
        "port": 5001,
        "codec": "G.711Mu",
        "default_group": 1,
        "priority_group": 24,
        "emergency_group": 25,
        "groups": [
            {
                "number": 1,
                "label": _v("zone.label", variant),
                "slug": "qzone-hall",
                "multicast_address": _v("zone.multicast_address", variant),
                "multicast_port": 5001,
                "subscribed": True,
                "transmit": True,
                "kind": "normal",
            }
        ],
    }


def variant_facts(
    values: Mapping[str, Any],
    model: str,
    variant: str,
    keys: list[dict[str, Any]] | None,
    paging: dict[str, Any] | None,
    variables: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    facts = sample_facts({"timezone": SAMPLE_TIMEZONE, **values}, SAMPLE_MAC, model)
    lines = []
    for index in (1, 2):
        lines.append(
            {
                **facts["lines"][0],
                "index": index,
                "extension_number": _v("line.extension_number", variant),
                "sip_username": _v("line.sip_username", variant),
                "sip_password": _v("line.sip_password", variant),
                "display_name": _v("line.display_name", variant),
                "label": _v("line.label", variant),
                "caller_id_name": _v("line.caller_id_name", variant),
                "caller_id_number": _v("line.caller_id_number", variant),
                "voicemail": True,
                "hotline": _v("line.hotline", variant) if index == 1 else None,
                "hotline_delay": 0,
            }
        )
    facts["lines"] = lines
    facts["keys"] = keys if keys is not None else default_keys(variant)
    facts["paging"] = paging if paging is not None else default_paging(variant)
    facts["features"] = {"voicemail": True, "blf": True, "paging": True}
    facts["device"] = {
        **facts["device"],
        "label": _v("device.label", variant),
        "credential_user": _v("device.credential_user", variant),
        "credential_password": _v("device.credential_password", variant),
    }
    facts["organization"] = {"name": _v("organization.name", variant), "slug": "qorg"}
    server = dict(facts["server"])
    server.update(
        sip_host=_v("server.sip_host", variant),
        ntp_server=_v("server.ntp_server", variant),
        provisioning_url=_v("server.provisioning_url", variant),
        directory_url=_v("server.directory_url", variant),
        firmware_url="https://pbx.qhost.example/firmware/sample/",
        firmware_version="0.0.0",
    )
    facts["server"] = server
    facts["vars"] = VarsView(dict(variables or {}))
    return facts


def _marks() -> list[tuple[str, str]]:
    """``(typical value, field)``, longest first."""
    marks = [(d.typical, path) for path, d in FACT_DOMAINS.items() if len(d.typical) >= _MIN_MARK]
    return sorted(marks, key=lambda m: -len(m[0]))


def binding(value: str) -> tuple[list[str], bool]:
    """The fields whose typical values appear in a rendered value, and
    whether the value is composite (several fields, or a field and text)."""
    rest = value
    fields: list[str] = []
    for mark, path in _marks():
        if mark in rest:
            fields.append(path)
            rest = rest.replace(mark, "\x00")
    leftover = rest.replace("\x00", "").strip()
    composite = len(fields) > 1 or (bool(fields) and bool(leftover))
    return sorted(set(fields)), composite


@dataclass
class PrecheckResult:
    target: Target
    findings: list[Finding] = field(default_factory=list)
    # Settings in the files the family checks.
    checked: int = 0
    files: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not any(f.severity in ("error", "warning") for f in self.findings)

    def counts(self) -> dict[str, int]:
        out = {"error": 0, "warning": 0, "info": 0}
        for f in self.findings:
            out[f.severity] += 1
        return out


def _settings(
    files: list[RenderedFile], typical: dict[tuple[str, str], Setting] | None
) -> dict[str, list[Setting]]:
    out: dict[str, list[Setting]] = {}
    for f in files:
        fmt = "xml" if f.format == "xml" else "cfg"
        for s in base_edits.settings(fmt, f.content):
            key = (f.source_name, s.parameter)
            if typical is None:
                fields, composite = binding(s.value)
                setting = Setting(
                    f.source_name, s.parameter, s.value, fields, composite, bool(fields)
                )
            else:
                t = typical.get(key)
                setting = Setting(
                    f.source_name,
                    s.parameter,
                    s.value,
                    list(t.filled_by) if t else [],
                    t.composite if t else False,
                    t.varies if t else False,
                )
            out.setdefault(f.source_name, []).append(setting)
    return out


def precheck(
    catalog: CapabilityCatalog,
    resolved: ResolvedTemplate,
    target: Target,
    *,
    values: Mapping[str, Any] | None = None,
    keys: list[dict[str, Any]] | None = None,
    paging: dict[str, Any] | None = None,
    edits: Iterable[Mapping[str, Any]] = (),
    variables: Mapping[str, Any] | None = None,
) -> PrecheckResult:
    """Check one template for one model and firmware. Raises
    ``TemplateError`` when the template does not render at all."""
    edits = list(edits)
    result = PrecheckResult(target)
    by_fp: dict[str, Finding] = {}
    typical_settings: dict[tuple[str, str], Setting] = {}
    for variant in VARIANTS:
        # The core variables come from line 1 and the server, as for a phone.
        core = {
            "extension_number": _v("line.extension_number", variant),
            "sip_username": _v("line.sip_username", variant),
            "sip_password": _v("line.sip_password", variant),
            "sip_server": _v("server.sip_host", variant),
            "display_name": _v("line.display_name", variant),
        }
        given = {k: v for k, v in dict(values or {}).items() if v not in (None, "")}
        try:
            coerced = coerce_values(resolved, {**core, **given})
            context = {k: v for k, v in coerced.items() if v is not None}
            facts = variant_facts(context, target.model, variant, keys, paging, variables)
            files = render(
                resolved,
                context,
                mac=SAMPLE_MAC,
                model=target.model,
                facts=facts,
                edits=edits,
            )
        except TemplateError as e:
            if variant == "typical":
                raise
            # A field at its extreme that a phone could really have (§3.0).
            f = Finding(
                "warning",
                "render.extreme",
                f"With the {variant} values Veyra allows, this template does not render: "
                + "; ".join(e.errors),
                "",
                vendor=target.vendor.lower(),
                model=target.model,
                firmware=target.firmware or "",
                value_key=variant,
            ).finish()
            by_fp.setdefault(f.fingerprint, f)
            continue
        files = [f for f in files if f.source_name]
        settings = _settings(files, None if variant == "typical" else typical_settings)
        if variant == "typical":
            typical_settings = {(s.file, s.parameter): s for ss in settings.values() for s in ss}
            result.files = [f.source_name for f in files]
        inputs = [FileInput(f.source_name, f.format, f.content) for f in files]
        for finding in check_settings(catalog, target, inputs, settings):
            if variant == "typical":
                by_fp.setdefault(finding.fingerprint, finding)
                continue
            if finding.fingerprint in by_fp or finding.members or not finding.parameter:
                continue  # Already found with typical values, or a summary.
            if finding.severity == "error":
                finding.severity = "warning"
                fields = ", ".join(finding.filled_by) or "a field"
                finding.message = (
                    f"With the {variant} value of {fields} ({finding.value}): {finding.message} "
                    "Some phones may refuse it."
                )
            by_fp[finding.fingerprint] = finding
    hit = catalog.family_for(target.vendor, target.model)
    checked_files = set(hit[1].info.files) if hit else set()
    result.checked = sum(1 for (file, _p) in typical_settings if file in checked_files)
    result.findings = sort_findings(by_fp.values())
    return result
