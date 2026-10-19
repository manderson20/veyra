# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provisioning variables (docs/PROVISIONING_BREADTH.md §2): named values at
installation, organization, site or profile scope. Templates read them as
``vars.<name>``, key lists and zones reference them as ``$name``; a phone
resolves them nearest scope first (profile, site, organization, installation).
A change re-provisions the phones it reaches."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from veyra.core.models import Device, DeviceProfile, Extension, ProvisioningVariable
from veyra.provisioning.spec import CORE_NAMES, FACT_NAMES

SCOPES = ("installation", "organization", "site", "profile")
# Resolution order: the later scope wins.
PRECEDENCE = {"installation": 0, "organization": 1, "site": 2, "profile": 3}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
REF_RE = re.compile(r"^\$([a-z][a-z0-9_]{0,39})$")
MASK = "••••••••"
MAX_VALUE = 1000


class VariableError(ValueError):
    pass


def check_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise VariableError(
            "a variable name starts with a letter and uses lower-case letters, digits and "
            "underscores (up to 40 characters)"
        )
    if name in CORE_NAMES or name in FACT_NAMES or name == "vars":
        raise VariableError(f"{name!r} is a reserved name of the template facts")
    return name


def reference(value: Any) -> str | None:
    """The variable a ``$name`` value refers to, or None for a plain value."""
    m = REF_RE.match(str(value or "").strip())
    return m.group(1) if m else None


class VarsView(dict[str, Any]):
    """The ``vars`` fact of a template: a missing name renders as an empty
    string (a phone must still boot) and is remembered for the preview."""

    def __init__(self, values: dict[str, Any] | None = None) -> None:
        super().__init__(values or {})
        self.missing: set[str] = set()

    def __missing__(self, key: str) -> str:
        self.missing.add(str(key))
        return ""

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_"):
            raise AttributeError(key)
        return self[key]


def resolve_reference(value: Any, variables: VarsView | dict[str, Any] | None) -> str:
    """A key or zone value: ``$name`` becomes the variable's value."""
    name = reference(value)
    if name is None:
        return str(value or "")
    if variables is None:
        return ""
    return str(variables[name] if isinstance(variables, VarsView) else variables.get(name, ""))


# ----------------------------------------------------------------- resolution


def rows_for(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
    profile_id: uuid.UUID | None,
) -> list[ProvisioningVariable]:
    conds = [ProvisioningVariable.scope == "installation"]
    if organization_id is not None:
        conds.append(
            and_(
                ProvisioningVariable.scope == "organization",
                ProvisioningVariable.scope_id == organization_id,
            )
        )
    if site_id is not None:
        conds.append(
            and_(ProvisioningVariable.scope == "site", ProvisioningVariable.scope_id == site_id)
        )
    if profile_id is not None:
        conds.append(
            and_(
                ProvisioningVariable.scope == "profile", ProvisioningVariable.scope_id == profile_id
            )
        )
    return list(db.scalars(select(ProvisioningVariable).where(or_(*conds))))


def resolve_detailed(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
    profile_id: uuid.UUID | None,
) -> list[dict[str, Any]]:
    """Every variable visible from the scopes with the scope it came from,
    nearest scope winning; sorted by name."""
    chosen: dict[str, ProvisioningVariable] = {}
    for row in sorted(
        rows_for(db, organization_id=organization_id, site_id=site_id, profile_id=profile_id),
        key=lambda r: PRECEDENCE[r.scope],
    ):
        chosen[row.name] = row
    return [
        {
            "id": row.id,
            "name": name,
            "value": row.value,
            "scope": row.scope,
            "scope_id": row.scope_id,
            "sensitive": row.sensitive,
            "description": row.description,
        }
        for name, row in sorted(chosen.items())
    ]


def resolve(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
    profile_id: uuid.UUID | None,
) -> dict[str, str]:
    return {
        str(v["name"]): str(v["value"])
        for v in resolve_detailed(
            db, organization_id=organization_id, site_id=site_id, profile_id=profile_id
        )
    }


def scopes_of(device: Device, profile: DeviceProfile) -> dict[str, uuid.UUID | None]:
    """The scopes a phone resolves through: its organization, its site (else
    the profile's) and its profile."""
    return {
        "organization_id": device.organization_id,
        "site_id": device.site_id or profile.site_id,
        "profile_id": profile.id,
    }


# ----------------------------------------------------------------- reach


def devices_in_scope(db: Session, var: ProvisioningVariable) -> list[Device]:
    """The enabled phones a variable can reach (what a change re-provisions)."""
    stmt = select(Device).where(Device.is_enabled.is_(True))
    if var.scope == "organization":
        stmt = stmt.where(Device.organization_id == var.scope_id)
    elif var.scope == "profile":
        stmt = stmt.where(Device.profile_id == var.scope_id)
    elif var.scope == "site":
        profile_ids = select(DeviceProfile.id).where(DeviceProfile.site_id == var.scope_id)
        stmt = stmt.where(
            or_(
                Device.site_id == var.scope_id,
                and_(Device.site_id.is_(None), Device.profile_id.in_(profile_ids)),
            )
        )
    return list(db.scalars(stmt.order_by(Device.mac_address)))


Notify = Callable[[str, str], tuple[bool, str]]


def reprovision(db: Session, devices: Iterable[Device], notify: Notify) -> int:
    """Ask every phone with an extension to re-read its configuration; returns
    how many accepted the request."""
    sent = 0
    for d in devices:
        if d.primary_extension_id is None:
            continue
        ext = db.get(Extension, d.primary_extension_id)
        if ext is None:
            continue
        ok, _ = notify("check_config", ext.endpoint_name)
        if ok:
            sent += 1
    return sent


def references_in_use(db: Session, var: ProvisioningVariable) -> list[str]:
    """Phones whose key list refers to ``$name`` and that would be left with
    no value if this definition went (another scope may still provide it)."""
    ref = f"${var.name}"
    found: list[str] = []
    profiles: dict[uuid.UUID, DeviceProfile] = {}
    for d in devices_in_scope(db, var):
        profile = profiles.get(d.profile_id) if d.profile_id else None
        if profile is None and d.profile_id is not None:
            profile = db.get(DeviceProfile, d.profile_id)
            if profile is not None:
                profiles[profile.id] = profile
        if profile is None:
            continue
        keys = d.keys if d.keys is not None else profile.keys
        if not any(str(k.get("value") or "").strip() == ref for k in (keys or [])):
            continue
        others = [
            r
            for r in rows_for(db, **scopes_of(d, profile))
            if r.name == var.name and r.id != var.id
        ]
        if not others:
            where = "own keys" if d.keys is not None else f"profile {profile.name}"
            found.append(f"phone {d.mac_address} ({where})")
    return found
