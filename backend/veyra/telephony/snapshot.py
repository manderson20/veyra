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

from veyra.core.models import Extension, Installation, Organization
from veyra.core.security.crypto import DecryptionError, InstallationKey
from veyra.telephony.settings import load_sip_settings
from veyra.version import __version__

SNAPSHOT_VERSION = 2


def secret_purpose(extension_id: Any) -> str:
    """Associated data that binds a SIP secret ciphertext to its extension."""
    return f"extension.sip_secret:{extension_id}"


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
    }
