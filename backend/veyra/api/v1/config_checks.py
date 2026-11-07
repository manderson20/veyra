# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration checks (docs/CONFIG_VERIFICATION.md §4, §5, §6): the check
run on save, the read-only check of unsaved changes, the overrides and the
check modes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1 import group_helpers as helpers
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, forbidden, not_found
from veyra.core.models import (
    ConfigCheckOverride,
    Device,
    DeviceProfile,
    FirmwareImage,
    Installation,
    Organization,
)
from veyra.core.models.base import utcnow
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.provisioning import checks
from veyra.provisioning.capabilities import CapabilityCatalog
from veyra.provisioning.checks import Acknowledgement
from veyra.provisioning.precheck import precheck
from veyra.provisioning.renderer import TemplateCatalog
from veyra.provisioning.spec import TemplateError
from veyra.provisioning.verify import Target, firmware_targets

router = APIRouter(prefix="/provisioning", tags=["provisioning"])

READ = "provisioning.read"
WRITE = "provisioning.write"
Mode = Literal["enforce", "advisory", "off"]


def capabilities(request: Request) -> CapabilityCatalog:
    caps = getattr(request.app.state, "capabilities", None)
    return caps if caps is not None else CapabilityCatalog()


def run_profile_check(
    request: Request,
    db: Session,
    principal: Principal,
    ctx: RequestContext,
    profile: DeviceProfile,
    templates: TemplateCatalog,
    served: dict[str, str],
    acknowledge: list[Acknowledgement],
    *,
    gate: bool = True,
) -> dict[str, Any]:
    """Check a profile as it is in the session (after the change is flushed)
    and stop the save when enforced errors are open. Returns the report for
    the response."""
    mode = checks.effective_mode(db, profile.organization_id, profile)
    if mode[0] == "off":
        return {"mode": "off", "level": mode[1], "findings": [], "clean": None}
    try:
        results = checks.check_profile(db, templates, capabilities(request), profile, served)
    except TemplateError:
        # A template that does not render is reported by the template's own checks.
        return {"mode": mode[0], "level": mode[1], "findings": [], "clean": None}
    subject = checks.Subject("profile", str(profile.id), profile.organization_id)
    if gate:
        report = checks.gate(
            db,
            principal,
            subject,
            results,
            mode,
            acknowledge,
            ip=ctx.ip,
            request_id=ctx.request_id,
        )
        checks.store_summaries(db, profile, report)
    else:
        report = checks.Report(mode[0], mode[1], results, checks.live_overrides(db, subject.scopes))
    return report.as_dict()


def run_device_check(
    request: Request,
    db: Session,
    principal: Principal,
    ctx: RequestContext,
    device: Device,
    profile: DeviceProfile | None,
    templates: TemplateCatalog,
    acknowledge: list[Acknowledgement],
) -> dict[str, Any] | None:
    """Check what a phone adds to its profile (§4.1): its own values and
    keys, on its own firmware. The profile's checks cover the rest."""
    from veyra.api.v1.device_profiles import served_models

    if profile is None:
        return None
    mode = checks.effective_mode(db, profile.organization_id, profile)
    if mode[0] == "off":
        device.config_check = {"mode": "off"}
        return {"mode": "off", "level": mode[1], "findings": [], "clean": None}
    key = served_models(templates, profile.template_key, profile.organization_id).get(device.model)
    if key is None:
        return None
    vendor = templates.records[key].manifest.template.manufacturer
    images = {
        i.id: i.version
        for i in db.scalars(
            select(FirmwareImage).where(
                FirmwareImage.id.in_(
                    [x for x in (device.firmware_image_id, profile.firmware_image_id) if x]
                )
            )
        )
    }
    targets = firmware_targets(
        vendor,
        device.model,
        device_image=images.get(device.firmware_image_id) if device.firmware_image_id else None,
        profile_image=images.get(profile.firmware_image_id) if profile.firmware_image_id else None,
        reported=[device.firmware_reported],
        catalog=capabilities(request),
    )
    try:
        results = checks.check_profile(
            db,
            templates,
            capabilities(request),
            profile,
            {device.model: key},
            device_values=dict(device.values or {}),
            device_keys=device.keys,
            models=[device.model],
            targets={device.model: targets},
            site_id=device.site_id,
        )
    except TemplateError:
        return None
    subject = checks.Subject(
        "device", str(device.id), device.organization_id, also=[("profile", str(profile.id))]
    )
    report = checks.gate(
        db, principal, subject, results, mode, acknowledge, ip=ctx.ip, request_id=ctx.request_id
    )
    device.config_check = checks.summarize(report, device.model)
    return report.as_dict()


def run_template_check(
    request: Request,
    db: Session,
    principal: Principal,
    ctx: RequestContext,
    key: str,
    organization_id: uuid.UUID | None,
    templates: TemplateCatalog,
    acknowledge: list[Acknowledgement],
) -> dict[str, Any] | None:
    """Check a saved template on its own (defaults, one key of each type),
    for each model it lists, on the family's oldest release. Profiles on it
    are checked with their own values when they are saved."""
    mode = checks.effective_mode(db, organization_id)
    if mode[0] == "off":
        return {"mode": "off", "level": mode[1], "findings": [], "clean": None}
    rec = templates.records.get(key)
    if rec is None or rec.manifest.template.abstract:
        return None
    try:
        resolved = templates.resolve(key)
        results = [
            checks.ModelResult(
                model,
                key,
                precheck(
                    capabilities(request),
                    resolved,
                    Target(rec.manifest.template.manufacturer, model, None, "oldest"),
                ),
            )
            for model in rec.manifest.template.models
        ]
    except TemplateError:
        return None
    report = checks.gate(
        db,
        principal,
        checks.Subject("template", key, organization_id),
        results,
        mode,
        acknowledge,
        ip=ctx.ip,
        request_id=ctx.request_id,
    )
    return report.as_dict()


MAX_VARIABLE_PROFILES = 50


def run_variable_check(
    request: Request,
    db: Session,
    principal: Principal,
    ctx: RequestContext,
    profiles: list[DeviceProfile],
    templates: TemplateCatalog,
    acknowledge: list[Acknowledgement],
) -> dict[str, Any]:
    """Check every profile a variable reaches (§4.1), up to a limit, and
    stop the save when any has open enforced errors: all of them are listed
    together, each with its profile."""
    from veyra.api.v1.device_profiles import served_models

    reports: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for profile in profiles[:MAX_VARIABLE_PROFILES]:
        served = served_models(templates, profile.template_key, profile.organization_id)
        try:
            report = run_profile_check(
                request, db, principal, ctx, profile, templates, served, acknowledge
            )
        except ProblemError as e:
            if e.code != "config_findings":
                raise
            errors.extend(
                {**f, "profile_id": str(profile.id), "profile_name": profile.name}
                for f in e.errors or []
            )
            continue
        for f in report.get("findings", []):
            f["profile_id"], f["profile_name"] = str(profile.id), profile.name
        reports.append(report)
    if errors:
        raise ProblemError(
            422,
            "Configuration check",
            "Templates this variable reaches would send settings their phones refuse.",
            code="config_findings",
            errors=errors,
        )
    findings = [f for r in reports for f in r.get("findings", [])]
    return {
        "profiles": len(profiles),
        "checked_profiles": min(len(profiles), MAX_VARIABLE_PROFILES),
        "findings": findings,
        "clean": not any(f["severity"] in ("error", "warning") for f in findings),
    }


# ------------------------------------------------------------------ verify


class VerifyIn(BaseModel):
    """Check a profile, saved or with unsaved changes, without saving."""

    profile_id: uuid.UUID | None = None
    # A profile not saved yet, or changes to apply to the saved one.
    organization_id: uuid.UUID | None = None
    template_key: str | None = Field(None, max_length=128)
    values: dict[str, Any] | None = None
    keys: list[dict[str, Any]] | None = None
    base_edits: list[dict[str, Any]] | None = None
    firmware_image_id: uuid.UUID | None = None


@router.post("/verify", summary="Check phone configuration without saving it")
def verify(
    body: VerifyIn,
    request: Request,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    from veyra.api.v1 import device_common as common
    from veyra.api.v1.device_profiles import served_models
    from veyra.api.v1.provisioning import catalog_for

    templates = catalog_for(request, db)
    if body.profile_id is not None:
        saved = db.get(DeviceProfile, body.profile_id)
        if saved is None or not principal.has(READ, saved.organization_id):
            raise not_found("Device profile")
        profile = DeviceProfile(
            id=saved.id,
            organization_id=saved.organization_id,
            site_id=saved.site_id,
            name=saved.name,
            template_key=body.template_key or saved.template_key,
            values=body.values if body.values is not None else dict(saved.values or {}),
            keys=body.keys if body.keys is not None else list(saved.keys or []),
            model_keys=dict(saved.model_keys or {}) if body.keys is None else {},
            base_edits=body.base_edits if body.base_edits is not None else saved.base_edits,
            firmware_image_id=body.firmware_image_id
            if "firmware_image_id" in body.model_fields_set
            else saved.firmware_image_id,
            config_check_mode=saved.config_check_mode,
        )
    else:
        if body.organization_id is None or not body.template_key:
            raise common.validation("profile_id", "name a profile, or an organization and template")
        if not principal.has(READ, body.organization_id):
            raise forbidden()
        profile = DeviceProfile(
            id=None,
            organization_id=body.organization_id,
            template_key=body.template_key,
            values=body.values or {},
            keys=body.keys or [],
            model_keys={},
            base_edits=body.base_edits or [],
            firmware_image_id=body.firmware_image_id,
        )
    common.resolve_template(
        templates, profile.template_key, "template_key", profile.organization_id
    )
    served = served_models(templates, profile.template_key, profile.organization_id)
    # The profile here is never added to the session, so nothing is saved.
    return run_profile_check(
        request, db, principal, ctx, profile, templates, served, [], gate=False
    )


# ------------------------------------------------------------------ overrides


class OverrideOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    scope_type: str
    scope_id: str
    fingerprint: str
    rule: str
    vendor: str
    family: str
    model: str
    release: str
    file: str
    parameter: str
    value: str | None
    message: str
    reason: str
    checker_wrong: bool
    created_by_label: str
    created_at: datetime
    revoked_at: datetime | None
    stale_at: datetime | None


def _out(row: ConfigCheckOverride) -> OverrideOut:
    return OverrideOut.model_validate(row, from_attributes=True)


@router.get("/check-overrides", response_model=Page[OverrideOut], summary="List check overrides")
def list_overrides(
    organization_id: uuid.UUID | None = None,
    checker_wrong: bool | None = None,
    include_revoked: bool = False,
    q: str | None = Query(None, max_length=200),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[OverrideOut]:
    stmt = helpers.org_filter(
        select(ConfigCheckOverride), ConfigCheckOverride.organization_id, principal, READ
    ).order_by(ConfigCheckOverride.created_at.desc())
    if organization_id is not None:
        stmt = stmt.where(ConfigCheckOverride.organization_id == organization_id)
    if checker_wrong is not None:
        stmt = stmt.where(ConfigCheckOverride.checker_wrong.is_(checker_wrong))
    if not include_revoked:
        stmt = stmt.where(ConfigCheckOverride.revoked_at.is_(None))
    if q:
        stmt = stmt.where(ConfigCheckOverride.parameter.ilike(f"%{q.strip()}%"))
    rows, total = paginate(db, stmt, params)
    return Page(
        items=[_out(r) for r in rows], total=total, limit=params.limit, offset=params.offset
    )


@router.post(
    "/check-overrides/{override_id}/revoke",
    response_model=OverrideOut,
    summary="Revoke a check override: the finding is open again",
)
def revoke_override(
    override_id: uuid.UUID,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> OverrideOut:
    row = db.get(ConfigCheckOverride, override_id)
    if row is None or not principal.has(READ, row.organization_id):
        raise not_found("Override")
    if not principal.has(checks.OVERRIDE, row.organization_id):
        raise forbidden("You may not revoke configuration check overrides.")
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        row.revoked_by = principal.user_id
        audit.record(
            db,
            action="provisioning.check.revoke",
            actor_user_id=principal.user_id,
            actor_label=principal.label,
            organization_id=row.organization_id,
            target_type=row.scope_type,
            target_id=checks._uuid_or_none(row.scope_id),
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"fingerprint": row.fingerprint, "parameter": row.parameter},
        )
        db.commit()
    return _out(row)


# ------------------------------------------------------------------ modes


class ModeIn(BaseModel):
    scope: Literal["installation", "organization", "profile"]
    scope_id: uuid.UUID | None = None
    # None: follow the next level up (not for the installation).
    mode: Mode | None


class ModeOut(BaseModel):
    installation: str
    organization: str | None = None
    profile: str | None = None
    effective: str
    level: str


@router.get("/check-mode", response_model=ModeOut, summary="The configuration check mode")
def get_mode(
    organization_id: uuid.UUID | None = None,
    profile_id: uuid.UUID | None = None,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> ModeOut:
    inst = db.scalar(select(Installation))
    profile = db.get(DeviceProfile, profile_id) if profile_id else None
    if profile is not None:
        if not principal.has(READ, profile.organization_id):
            raise not_found("Device profile")
        organization_id = profile.organization_id
    org = db.get(Organization, organization_id) if organization_id else None
    if org is not None and not principal.has(READ, org.id):
        raise not_found("Organization")
    mode, level = checks.effective_mode(db, org.id if org else None, profile)
    return ModeOut(
        installation=inst.config_check_mode if inst else "enforce",
        organization=org.config_check_mode if org else None,
        profile=profile.config_check_mode if profile else None,
        effective=mode,
        level=level,
    )


@router.put("/check-mode", response_model=ModeOut, summary="Set the configuration check mode")
def set_mode(
    body: ModeIn,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ModeOut:
    org_id: uuid.UUID | None = None
    profile_id: uuid.UUID | None = None
    if body.scope == "installation":
        if not principal.has("system.settings.write"):
            raise forbidden("Changing the installation's check mode needs system settings.")
        if body.mode is None:
            from veyra.api.v1 import device_common as common

            raise common.validation("mode", "the installation needs a mode")
        inst = db.scalar(select(Installation))
        if inst is None:
            raise not_found("Installation")
        old = inst.config_check_mode
        inst.config_check_mode = body.mode
    elif body.scope == "organization":
        org = db.get(Organization, body.scope_id) if body.scope_id else None
        if org is None or not principal.has(READ, org.id):
            raise not_found("Organization")
        if not principal.has(checks.MODE, org.id):
            raise forbidden()
        old, org.config_check_mode, org_id = org.config_check_mode, body.mode, org.id
    else:
        profile = db.get(DeviceProfile, body.scope_id) if body.scope_id else None
        if profile is None or not principal.has(READ, profile.organization_id):
            raise not_found("Device profile")
        if not principal.has(checks.MODE, profile.organization_id):
            raise forbidden()
        old, profile.config_check_mode = profile.config_check_mode, body.mode
        org_id, profile_id = profile.organization_id, profile.id
    audit.record(
        db,
        action="provisioning.check.mode",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=org_id,
        target_type=body.scope,
        target_id=body.scope_id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"from": old, "to": body.mode},
    )
    db.commit()
    return get_mode(org_id, profile_id, principal, db)
