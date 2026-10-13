# SPDX-License-Identifier: AGPL-3.0-or-later
"""The engine-neutral snapshot of everything configuration generation reads.

A snapshot is plain data (JSON-serialisable) taken from the database in one
transaction, so a revision is generated from a consistent view and the
generator stays a pure function. Nothing in it is time-dependent: the same
database state produces byte-identical files, which is what lets the
revision history detect "no change".

SIP secrets are stored encrypted (``extensions.sip_secret_ciphertext``) and
decrypted here with the installation key, so the snapshot is the only place
where they exist in clear outside the generated ``pjsip.endpoints.conf``.
Callers must not log or persist a snapshot.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.models import (
    Extension,
    InboundRoute,
    Installation,
    Organization,
    OutboundRoute,
    OutboundRouteTrunk,
    SipTrunk,
    TimeCondition,
)
from veyra.core.security.crypto import DecryptionError, InstallationKey
from veyra.telephony.settings import load_sip_settings
from veyra.version import __version__

SNAPSHOT_VERSION = 3


def secret_purpose(extension_id: Any) -> str:
    """Associated data that binds a SIP secret ciphertext to its extension."""
    return f"extension.sip_secret:{extension_id}"


def trunk_secret_purpose(trunk_id: Any) -> str:
    """Associated data that binds a trunk password ciphertext to its trunk."""
    return f"trunk.sip_secret:{trunk_id}"


class SnapshotError(ValueError):
    """The database holds data the snapshot cannot use (for example a SIP
    secret that cannot be decrypted). Reported as a failed revision."""


def _secret(ext: Extension, key: InstallationKey | None) -> str | None:
    if not ext.sip_secret_ciphertext:
        return None
    if key is None:
        raise SnapshotError(
            f"extension {ext.number} has an encrypted SIP secret but the installation key "
            "is not available (see 'veyra installation-key check')"
        )
    try:
        return key.decrypt(ext.sip_secret_ciphertext, secret_purpose(ext.id))
    except DecryptionError as e:
        raise SnapshotError(f"the SIP secret of extension {ext.number} cannot be read: {e}") from e


def _trunk_password(trunk: SipTrunk, key: InstallationKey | None) -> str | None:
    if not trunk.password_ciphertext:
        return None
    if key is None:
        raise SnapshotError(
            f"trunk {trunk.name} has an encrypted password but the installation key "
            "is not available (see 'veyra installation-key check')"
        )
    try:
        return key.decrypt(trunk.password_ciphertext, trunk_secret_purpose(trunk.id))
    except DecryptionError as e:
        raise SnapshotError(f"the password of trunk {trunk.name} cannot be read: {e}") from e


def build_snapshot(db: Session, key: InstallationKey | None) -> dict[str, Any]:
    inst = db.scalar(select(Installation))
    orgs = db.scalars(select(Organization).order_by(Organization.slug)).all()
    active = {o.id for o in orgs if o.is_active}
    extensions = [
        e
        for e in db.scalars(
            select(Extension)
            .where(Extension.is_enabled.is_(True))
            .order_by(Extension.endpoint_name)
        ).all()
        if e.organization_id in active
    ]
    org_slug = {o.id: o.slug for o in orgs}
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "veyra_version": __version__,
        "installation": {
            "name": inst.name if inst else "Veyra",
            "instance_id": str(inst.instance_id) if inst else None,
            "multi_tenancy_enabled": bool(inst.multi_tenancy_enabled) if inst else False,
        },
        "sip": load_sip_settings(db).model_dump(mode="json"),
        "organizations": [
            {"slug": o.slug, "name": o.name, "timezone": o.timezone, "is_active": o.is_active}
            for o in orgs
        ],
        "extensions": [
            {
                "endpoint_name": e.endpoint_name,
                "number": e.number,
                "display_name": e.display_name,
                "organization": org_slug.get(e.organization_id, ""),
                "caller_id_name": e.caller_id_name,
                "caller_id_number": e.caller_id_number,
                "secret": _secret(e, key),
            }
            for e in extensions
        ],
        **_routing(db, key, active, extensions),
    }


def _routing(
    db: Session,
    key: InstallationKey | None,
    active_orgs: set[Any],
    extensions: list[Extension],
) -> dict[str, Any]:
    """Trunks, routes and time conditions (docs/TRUNKS_ROUTING.md §8)."""
    trunks = db.scalars(select(SipTrunk).order_by(SipTrunk.slug)).all()
    enabled_trunks = {t.id: t for t in trunks if t.is_enabled}
    # Only enabled extensions of active organizations are deployable destinations.
    number_of = {e.id: e.number for e in extensions}
    conditions = db.scalars(select(TimeCondition).order_by(TimeCondition.name)).all()
    condition_by_id = {c.id: c for c in conditions}
    inbound = db.scalars(
        select(InboundRoute)
        .where(InboundRoute.is_enabled.is_(True))
        .order_by(InboundRoute.did_canonical)
    ).all()
    outbound = db.scalars(
        select(OutboundRoute)
        .where(OutboundRoute.is_enabled.is_(True))
        .order_by(OutboundRoute.is_emergency.desc(), OutboundRoute.position, OutboundRoute.slug)
    ).all()
    links = db.scalars(select(OutboundRouteTrunk).order_by(OutboundRouteTrunk.position)).all()
    route_trunks: dict[Any, list[str]] = {}
    for link in links:
        trunk = enabled_trunks.get(link.trunk_id)
        if trunk is not None:
            route_trunks.setdefault(link.route_id, []).append(trunk.slug)
    used_conditions: set[Any] = set()
    inbound_out = []
    for r in inbound:
        if r.organization_id not in active_orgs:
            continue
        if r.trunk_id is not None and r.trunk_id not in enabled_trunks:
            continue
        if r.time_condition_id is not None:
            used_conditions.add(r.time_condition_id)
        inbound_out.append(
            {
                "did": r.did,
                "trunk": enabled_trunks[r.trunk_id].slug if r.trunk_id else None,
                "destination": (
                    number_of.get(r.destination_extension_id)
                    if r.destination_extension_id
                    else None
                ),
                "after_hours": (
                    number_of.get(r.after_hours_extension_id)
                    if r.after_hours_extension_id
                    else None
                ),
                "time_condition": str(r.time_condition_id) if r.time_condition_id else None,
                "caller_id_prefix": r.caller_id_prefix,
                "organization": str(r.organization_id),
            }
        )
    return {
        "trunks": [
            {
                "slug": t.slug,
                "name": t.name,
                "auth_mode": t.auth_mode,
                "host": t.host,
                "port": t.port,
                "transport": t.transport,
                "username": t.username,
                "auth_username": t.auth_username or t.username,
                "password": _trunk_password(t, key),
                "from_user": t.from_user,
                "from_domain": t.from_domain,
                "outbound_proxy": t.outbound_proxy,
                "match_addresses": list(t.match_addresses or []),
                "codecs": list(t.codecs) if t.codecs else None,
                "max_channels": t.max_channels,
                "default_caller_id": t.default_caller_id,
                "caller_id_header": t.caller_id_header,
                "dtmf_mode": t.dtmf_mode,
                "qualify_frequency": t.qualify_frequency,
                "register_expiry": t.register_expiry,
            }
            for t in trunks
            if t.is_enabled
        ],
        "inbound_routes": inbound_out,
        "outbound_routes": [
            {
                "slug": r.slug,
                "name": r.name,
                "is_emergency": r.is_emergency,
                "patterns": list(r.patterns or []),
                "trunks": route_trunks.get(r.id, []),
                "caller_id_number": r.caller_id_number,
            }
            for r in outbound
        ],
        "time_conditions": [
            {
                "key": str(c.id),
                "name": c.name,
                "timezone": c.timezone,
                "ranges": list(c.ranges or []),
                "holidays": list(c.holidays or []),
            }
            for c in conditions
            if c.id in used_conditions and c.id in condition_by_id
        ],
    }
