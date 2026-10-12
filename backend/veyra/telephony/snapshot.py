# SPDX-License-Identifier: AGPL-3.0-or-later
"""The engine-neutral snapshot of everything configuration generation reads.

A snapshot is plain data (JSON-serialisable) taken from the database in one
transaction, so a revision is generated from a consistent view and the
generator stays a pure function. Nothing in it is time-dependent: the same
database state produces byte-identical files, which is what lets the
revision history detect "no change".
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.models import Extension, Installation, Organization
from veyra.telephony.settings import load_sip_settings
from veyra.version import __version__

SNAPSHOT_VERSION = 1


def build_snapshot(db: Session) -> dict[str, Any]:
    inst = db.scalar(select(Installation))
    orgs = db.scalars(select(Organization).order_by(Organization.slug)).all()
    extensions = db.scalars(
        select(Extension).where(Extension.is_enabled.is_(True)).order_by(Extension.endpoint_name)
    ).all()
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
        # Extensions are empty until Milestone 4; the generator already
        # handles them so that milestone only has to fill the table and
        # provide the decrypted secret.
        "extensions": [
            {
                "endpoint_name": e.endpoint_name,
                "number": e.number,
                "display_name": e.display_name,
                "organization": org_slug.get(e.organization_id, ""),
                "caller_id_name": e.caller_id_name,
                "caller_id_number": e.caller_id_number,
                "secret": None,  # Milestone 4 decrypts sip_secret_ciphertext here
            }
            for e in extensions
        ],
    }
