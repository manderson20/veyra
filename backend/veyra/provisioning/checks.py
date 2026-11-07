# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration checks on save (docs/CONFIG_VERIFICATION.md §4, §5): which
mode applies, what to check for a profile or a device, and the gate that
stops a save with open errors unless they are acknowledged. The checks are
prechecks: they run on a profile's values, keys and Base File Edits with
each Veyra field at its typical and extreme values, never on each phone."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.errors import ProblemError, forbidden
from veyra.core.models import (
    ConfigCheckOverride,
    Device,
    DeviceProfile,
    FirmwareImage,
    Installation,
    Organization,
    PagingZone,
)
from veyra.core.models.base import utcnow
from veyra.core.security.principal import Principal
from veyra.provisioning import facts as provisioning_facts
from veyra.provisioning import variables as provisioning_vars
from veyra.provisioning.capabilities import CapabilityCatalog
from veyra.provisioning.precheck import PrecheckResult, precheck
from veyra.provisioning.renderer import TemplateCatalog
from veyra.provisioning.verify import Finding, Target, firmware_targets, is_secret

MODES = ("enforce", "advisory", "off")
OVERRIDE = "provisioning.check.override"
MODE = "provisioning.check.mode"
REASON_MIN, REASON_MAX = 5, 500


class Acknowledgement(BaseModel):
    """An administrator's decision to save despite one finding (§4.2)."""

    fingerprint: str = Field(min_length=4, max_length=80)
    reason: str = Field(min_length=REASON_MIN, max_length=REASON_MAX)
    checker_wrong: bool = False

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        v = v.strip()
        if len(v) < REASON_MIN:
            raise ValueError(f"at least {REASON_MIN} characters")
        return v


# ------------------------------------------------------------------ mode


def effective_mode(
    db: Session, organization_id: uuid.UUID | None, profile: DeviceProfile | None = None
) -> tuple[str, str]:
    """``(mode, level)``: the most specific level that sets a mode wins."""
    if profile is not None and profile.config_check_mode:
        return profile.config_check_mode, "profile"
    if organization_id is not None:
        org = db.get(Organization, organization_id)
        if org is not None and org.config_check_mode:
            return org.config_check_mode, "organization"
    inst = db.scalar(select(Installation))
    return (inst.config_check_mode if inst else "enforce") or "enforce", "installation"


# ------------------------------------------------------------------ what to check


def _versions(db: Session, profile: DeviceProfile, model: str) -> tuple[str | None, list[str]]:
    """The profile's image version for a model, and the versions its phones
    of that model have assigned or report."""
    image = None
    if profile.firmware_image_id:
        img = db.get(FirmwareImage, profile.firmware_image_id)
        if img is not None and (not img.models or model in img.models):
            image = img.version
    phones: list[str] = []
    if profile.id is not None:
        rows = db.execute(
            select(Device.firmware_image_id, Device.firmware_reported).where(
                Device.profile_id == profile.id, Device.model == model
            )
        ).all()
        image_ids = {r[0] for r in rows if r[0]}
        images = (
            {
                i.id: i.version
                for i in db.scalars(select(FirmwareImage).where(FirmwareImage.id.in_(image_ids)))
            }
            if image_ids
            else {}
        )
        for image_id, reported in rows:
            v = images.get(image_id) if image_id else reported
            if v:
                phones.append(v)
    return image, phones


def targets_for(
    db: Session,
    caps: CapabilityCatalog,
    profile: DeviceProfile,
    vendor: str,
    model: str,
) -> list[Target]:
    """Each distinct firmware release to check a model of the profile on
    (§3.5): the profile's image and every version its phones have or
    report, else the family's oldest release."""
    image, phones = _versions(db, profile, model)
    versions = list(dict.fromkeys([v for v in [image, *phones] if v]))
    if not versions:
        return [Target(vendor, model, None, "oldest")]
    found = firmware_targets(vendor, model, reported=versions, catalog=caps)
    return [
        Target(t.vendor, t.model, t.firmware, "profile-image" if t.firmware == image else "phones")
        for t in found
    ]


@dataclass
class ModelResult:
    model: str
    template_key: str
    result: PrecheckResult


def _template_values(resolved: Any, variables: dict[str, str]) -> dict[str, Any]:
    return {k: v for k, v in variables.items() if k in resolved.variables}


def check_profile(
    db: Session,
    templates: TemplateCatalog,
    caps: CapabilityCatalog,
    profile: DeviceProfile,
    served: dict[str, str],
    *,
    device_values: dict[str, Any] | None = None,
    device_keys: list[dict[str, Any]] | None = None,
    models: Iterable[str] | None = None,
    targets: dict[str, list[Target]] | None = None,
    site_id: uuid.UUID | None = None,
) -> list[ModelResult]:
    """Precheck every model a profile serves on each of its firmware
    releases. ``served`` maps a model to its concrete template."""
    variables = provisioning_vars.resolve(
        db,
        organization_id=profile.organization_id,
        site_id=site_id or profile.site_id,
        profile_id=profile.id,
    )
    vars_view = provisioning_vars.VarsView(variables)
    zones = {
        z.slug: z
        for z in db.scalars(
            select(PagingZone).where(PagingZone.organization_id == profile.organization_id)
        )
    }
    paging = provisioning_facts._paging(db, profile)
    out: list[ModelResult] = []
    for model in sorted(models if models is not None else served):
        key = served.get(model)
        if key is None:
            continue
        resolved = templates.resolve(key)
        vendor = resolved.record.manifest.template.manufacturer
        raw = device_keys if device_keys is not None else profile.keys_for(model)
        keys = provisioning_facts._keys(
            db, profile.organization_id, list(raw or []), zones, vars_view
        )
        values = {
            **_template_values(resolved, variables),
            **dict(profile.values or {}),
            **dict(device_values or {}),
        }
        for target in (targets or {}).get(model) or targets_for(db, caps, profile, vendor, model):
            result = precheck(
                caps,
                resolved,
                target,
                values=values,
                keys=keys,
                paging=paging,
                edits=profile.base_edits or [],
                variables=variables,
            )
            out.append(ModelResult(model, key, result))
    return out


# ------------------------------------------------------------------ gate


@dataclass
class Subject:
    """What is being saved: the overrides that cover it are found by scope.
    A device is also covered by its profile's overrides."""

    scope_type: str  # template | profile | device
    scope_id: str
    organization_id: uuid.UUID | None
    also: list[tuple[str, str]] = field(default_factory=list)

    @property
    def scopes(self) -> list[tuple[str, str]]:
        return [(self.scope_type, self.scope_id), *self.also]


def live_overrides(db: Session, scopes: list[tuple[str, str]]) -> dict[str, ConfigCheckOverride]:
    out: dict[str, ConfigCheckOverride] = {}
    for scope_type, scope_id in scopes:
        for row in db.scalars(
            select(ConfigCheckOverride).where(
                ConfigCheckOverride.scope_type == scope_type,
                ConfigCheckOverride.scope_id == scope_id,
                ConfigCheckOverride.revoked_at.is_(None),
            )
        ):
            out.setdefault(row.fingerprint, row)
    return out


def _override_out(row: ConfigCheckOverride) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "by": row.created_by_label,
        "at": row.created_at.isoformat(),
        "reason": row.reason,
        "checker_wrong": row.checker_wrong,
        "scope_type": row.scope_type,
    }


@dataclass
class Report:
    mode: str
    level: str
    results: list[ModelResult]
    overrides: dict[str, ConfigCheckOverride]

    def findings(self) -> list[tuple[ModelResult, Finding]]:
        return [(r, f) for r in self.results for f in r.result.findings]

    def open_errors(self) -> list[Finding]:
        """Errors no override covers, once each."""
        seen: dict[str, Finding] = {}
        for _r, f in self.findings():
            if f.severity == "error" and f.fingerprint not in self.overrides:
                seen.setdefault(f.fingerprint, f)
        return list(seen.values())

    def as_dict(self) -> dict[str, Any]:
        counts = {"error": 0, "warning": 0, "info": 0, "overridden": 0}
        items = []
        for r, f in self.findings():
            d = f.as_dict()
            d["template_key"] = r.template_key
            d["target"] = {"firmware": r.result.target.firmware, "how": r.result.target.how}
            row = self.overrides.get(f.fingerprint)
            d["override"] = _override_out(row) if row is not None else None
            if row is not None and f.severity == "error":
                counts["overridden"] += 1
            else:
                counts[f.severity] += 1
            items.append(d)
        return {
            "mode": self.mode,
            "level": self.level,
            "clean": counts["error"] == 0 and counts["warning"] == 0,
            "counts": counts,
            "checked": sum(r.result.checked for r in self.results),
            "targets": [
                {
                    "model": r.model,
                    "template_key": r.template_key,
                    "firmware": r.result.target.firmware,
                    "how": r.result.target.how,
                    "checked": r.result.checked,
                }
                for r in self.results
            ],
            "findings": items,
        }


def findings_problem(report: Report, errors: list[Finding]) -> ProblemError:
    body = report.as_dict()
    return ProblemError(
        422,
        "Configuration check",
        f"{len(errors)} setting(s) this firmware would refuse. Override them with a reason, "
        "or change the configuration.",
        code="config_findings",
        errors=body["findings"],
    )


def gate(
    db: Session,
    principal: Principal,
    subject: Subject,
    results: list[ModelResult],
    mode: tuple[str, str],
    acknowledge: list[Acknowledgement],
    *,
    ip: str | None = None,
    request_id: str | None = None,
) -> Report:
    """Stop the save (raise ``config_findings``) when enforced errors are
    open; otherwise record the acknowledged ones as overrides. Call it after
    the change is flushed and before the commit."""
    overrides = live_overrides(db, subject.scopes)
    report = Report(mode[0], mode[1], results, overrides)
    by_fp = {f.fingerprint: f for _r, f in report.findings()}
    wanted = {a.fingerprint: a for a in acknowledge if a.fingerprint in by_fp}
    errors = [f for f in report.open_errors() if f.fingerprint not in wanted]
    if mode[0] == "enforce" and errors:
        raise findings_problem(report, errors)
    if wanted and not principal.has(OVERRIDE, subject.organization_id):
        raise forbidden("You may not override configuration check findings.")
    now = utcnow()
    for fp, ack in wanted.items():
        f = by_fp[fp]
        if f.severity != "error" or fp in overrides:
            continue
        secret = is_secret(f.parameter)
        row = ConfigCheckOverride(
            id=uuid.uuid4(),
            organization_id=subject.organization_id,
            scope_type=subject.scope_type,
            scope_id=subject.scope_id,
            fingerprint=fp,
            severity=f.severity,
            rule=f.rule,
            vendor=f.vendor,
            family=f.family,
            model=f.model,
            release=f.release,
            catalog_revision=f.catalog_revision,
            file=f.file,
            parameter=f.parameter,
            value=None if secret else f.value,
            value_sha256=hashlib.sha256(f.value_key.encode()).hexdigest(),
            message=f.message,
            reason=ack.reason,
            checker_wrong=ack.checker_wrong,
            created_by=principal.user_id,
            created_by_label=principal.label,
            created_at=now,
        )
        db.add(row)
        overrides[fp] = row
        audit.record(
            db,
            action="provisioning.check.override",
            actor_user_id=principal.user_id,
            actor_label=principal.label,
            organization_id=subject.organization_id,
            target_type=subject.scope_type,
            target_id=_uuid_or_none(subject.scope_id),
            ip_address=ip,
            request_id=request_id,
            details={
                "fingerprint": fp,
                "parameter": f.parameter,
                "value": "••••" if secret else f.value,
                "rule": f.rule,
                "model": f.model,
                "release": f.release,
                "reason": ack.reason,
                "checker_wrong": ack.checker_wrong,
            },
        )
    report.overrides = overrides
    return report


def _uuid_or_none(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


# ------------------------------------------------------------------ firmware change


def copy_profile(profile: DeviceProfile, **changes: Any) -> DeviceProfile:
    """A transient copy (never added to the session) with some fields changed."""
    fields = (
        "id",
        "organization_id",
        "site_id",
        "name",
        "template_key",
        "values",
        "keys",
        "model_keys",
        "base_edits",
        "firmware_image_id",
        "config_check_mode",
    )
    data = {f: getattr(profile, f) for f in fields}
    data.update(changes)
    return DeviceProfile(**data)


def _key(f: Finding) -> tuple[str, str, str, str, str]:
    return (f.model, f.file, f.parameter, f.rule, f.value_key or f.value)


def firmware_diff(
    before: list[ModelResult],
    after: list[ModelResult],
    phones: dict[str, int],
) -> dict[str, Any]:
    """What changes for the phones when the firmware does (§4.1): the errors
    and warnings that are new on the new release, and those that go away.
    Fingerprints differ between releases, so findings are matched by model,
    file, setting, rule and value."""

    def index(results: list[ModelResult]) -> dict[tuple[str, str, str, str, str], Finding]:
        out: dict[tuple[str, str, str, str, str], Finding] = {}
        for r in results:
            for f in r.result.findings:
                if f.severity in ("error", "warning"):
                    out.setdefault(_key(f), f)
        return out

    old, new = index(before), index(after)

    def rows(found: dict[Any, Finding], keys: Iterable[Any]) -> list[dict[str, Any]]:
        return [
            {**found[k].as_dict(), "phones": phones.get(found[k].model, 0)} for k in sorted(keys)
        ]

    releases = {
        "from": sorted({r.result.target.firmware or "oldest" for r in before}),
        "to": sorted({r.result.target.firmware or "oldest" for r in after}),
    }
    return {
        **releases,
        "new": rows(new, new.keys() - old.keys()),
        "gone": rows(old, old.keys() - new.keys()),
    }


def phones_by_model(db: Session, profile: DeviceProfile) -> dict[str, int]:
    if profile.id is None:
        return {}
    out: dict[str, int] = {}
    for (model,) in db.execute(select(Device.model).where(Device.profile_id == profile.id)):
        out[model] = out.get(model, 0) + 1
    return out


# ------------------------------------------------------------------ device summary


def summarize(report: Report, model: str | None = None) -> dict[str, Any]:
    """The counts a device keeps (§4.3), for its model when given."""
    counts = {"open_errors": 0, "overridden": 0, "warnings": 0, "notes": 0}
    seen: set[str] = set()
    for r, f in report.findings():
        if (model is not None and r.model != model) or f.fingerprint in seen:
            continue
        seen.add(f.fingerprint)
        if f.severity == "error":
            key = "overridden" if f.fingerprint in report.overrides else "open_errors"
            counts[key] += 1
        elif f.severity == "warning":
            counts["warnings"] += 1
        else:
            counts["notes"] += 1
    return {**counts, "mode": report.mode, "checked_at": utcnow().isoformat()}


def store_summaries(db: Session, profile: DeviceProfile, report: Report) -> None:
    if profile.id is None:
        return
    for device in db.scalars(select(Device).where(Device.profile_id == profile.id)):
        device.config_check = summarize(report, device.model)
