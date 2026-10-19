# SPDX-License-Identifier: AGPL-3.0-or-later
"""Update checks: fetch, verify and record available updates. Never installs."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.config import Settings
from veyra.core.models import (
    AvailableUpdate,
    InstalledModule,
    SystemSetting,
    UpdateCheck,
    UpdatePolicy,
)
from veyra.core.semver import Version
from veyra.core.signing import Keyring
from veyra.updates.metadata import MetadataError, UpdateMetadata
from veyra.updates.policy import CHANNEL_VISIBILITY, Channel, Component
from veyra.version import __version__

log = logging.getLogger("veyra.updates")

SEQUENCE_KEY = "updates.metadata_sequence"
MAX_METADATA_BYTES = 2 * 1024 * 1024
_TIMEOUT = 15


def installed_versions(db: Session) -> dict[tuple[str, str], str]:
    versions = {(Component.VEYRA_CORE.value, "veyra"): __version__}
    for m in db.scalars(select(InstalledModule).where(InstalledModule.state != "removed")):
        versions[(Component.MODULES.value, m.module_id)] = m.version
    return versions


def check_for_updates(db: Session, settings: Settings, keyring: Keyring) -> UpdateCheck:
    from veyra.updates import manager

    url = manager.source_url(db, settings)
    if not url:
        check = UpdateCheck(
            source="", outcome="not_configured", message="No update source is configured."
        )
        db.add(check)
        return check
    try:
        seq_row = db.get(SystemSetting, SEQUENCE_KEY)
        meta, _body, _sig = manager.fetch_metadata(
            db, settings, keyring, last_sequence=int(seq_row.value) if seq_row else 0
        )
    except MetadataError as e:
        check = UpdateCheck(source=url, outcome="rejected", message=str(e))
        db.add(check)
        log.warning("Update metadata rejected: %s", e)
        return check
    except (manager.UpdateError, OSError, ValueError) as e:
        check = UpdateCheck(source=url, outcome="failed", message=f"Could not fetch updates: {e}")
        db.add(check)
        return check

    before = {r.id for r in db.scalars(select(AvailableUpdate))}
    found = record_available(db, meta)
    manager.supersede_older(db, settings)
    notify = manager.mail_notifier(db, settings)
    for row in db.scalars(select(AvailableUpdate).where(AvailableUpdate.component == "veyra_core")):
        if row.id not in before:
            notify("available", row)
    if seq_row is None:
        db.add(SystemSetting(key=SEQUENCE_KEY, value=meta.sequence))
    else:
        seq_row.value = meta.sequence
    check = UpdateCheck(source=url, outcome="ok", message=f"{found} update(s) available.")
    db.add(check)
    return check


def record_available(db: Session, meta: UpdateMetadata) -> int:
    policies = {p.component: p for p in db.scalars(select(UpdatePolicy))}
    current = installed_versions(db)
    found = 0
    for rel in meta.releases:
        policy = policies.get(rel.component.value)
        if policy is None or not policy.check_enabled:
            continue
        if rel.channel not in CHANNEL_VISIBILITY[Channel(policy.channel)]:
            continue
        installed = current.get((rel.component.value, rel.target))
        if installed is None or Version.parse(rel.version) <= Version.parse(installed):
            continue
        exists = db.scalar(
            select(AvailableUpdate).where(
                AvailableUpdate.component == rel.component.value,
                AvailableUpdate.target == rel.target,
                AvailableUpdate.version == rel.version,
            )
        )
        if exists is None:
            db.add(
                AvailableUpdate(
                    component=rel.component.value,
                    target=rel.target,
                    version=rel.version,
                    current_version=installed,
                    channel=rel.channel.value,
                    category=rel.category,
                    release_notes=rel.release_notes,
                    state="available",
                    metadata_=rel.model_dump(mode="json"),
                )
            )
        found += 1
    db.flush()
    return found
