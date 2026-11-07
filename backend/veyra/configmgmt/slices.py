# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each organization's part of the snapshot (docs/MULTI_TENANCY_MSP.md §7).

After every valid generation, each organization's part is kept, encrypted.
When a later generation fails, Veyra tries again with one organization's
part taken from its last good copy at a time. If that works, that
organization's data caused the failure: its newer changes are held back
(and its administrators told why) while every other organization's changes
deploy. A failure in shared data (a trunk, a route for every organization)
still stops everyone, as it must.
"""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.models import Organization, OrganizationConfigSlice
from veyra.core.models.base import utcnow
from veyra.core.security.crypto import InstallationKey
from veyra.telephony.snapshot import ORG_LISTS, ORG_NESTED, ORGANIZATIONS_KEY

PURPOSE = "config_slice:{}"


def _owner(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    slug = item.get("organization_slug", item.get("organization"))
    return str(slug) if slug else None


def split(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """slug -> the organization's row and every item it owns."""
    out: dict[str, dict[str, Any]] = {}
    for org in snapshot.get(ORGANIZATIONS_KEY) or []:
        out[str(org["slug"])] = {"organization": copy.deepcopy(org), "lists": {}, "nested": {}}
    for key in ORG_LISTS:
        for item in snapshot.get(key) or []:
            slug = _owner(item)
            if slug in out:
                out[slug]["lists"].setdefault(key, []).append(copy.deepcopy(item))
    for key, members in ORG_NESTED.items():
        nested = snapshot.get(key) or {}
        for member in members:
            for item in nested.get(member) or []:
                slug = _owner(item)
                if slug in out:
                    out[slug]["nested"].setdefault(key, {}).setdefault(member, []).append(
                        copy.deepcopy(item)
                    )
    return out


def with_slice(snapshot: dict[str, Any], slug: str, part: dict[str, Any]) -> dict[str, Any]:
    """The snapshot with ``slug``'s items replaced by ``part``."""
    snap = copy.deepcopy(snapshot)
    snap[ORGANIZATIONS_KEY] = [
        part["organization"] if str(o.get("slug")) == slug else o
        for o in snap.get(ORGANIZATIONS_KEY) or []
    ]
    for key in ORG_LISTS:
        kept = [i for i in snap.get(key) or [] if _owner(i) != slug]
        snap[key] = kept + list(part["lists"].get(key, []))
    for key, members in ORG_NESTED.items():
        nested = dict(snap.get(key) or {})
        for member in members:
            kept = [i for i in nested.get(member) or [] if _owner(i) != slug]
            nested[member] = kept + list(part["nested"].get(key, {}).get(member, []))
        snap[key] = nested
    return snap


def save(
    db: Session,
    key: InstallationKey | None,
    snapshot: dict[str, Any],
    revision_id: uuid.UUID | None,
    skip: set[str] = frozenset(),  # type: ignore[assignment]
) -> None:
    """Keep each organization's part of a snapshot that generated a valid
    configuration (except those held back, whose last good part stays)."""
    if key is None:
        return
    ids = {o.slug: o.id for o in db.scalars(select(Organization))}
    for slug, part in split(snapshot).items():
        if slug in skip or slug not in ids:
            continue
        text = key.encrypt(json.dumps(part, sort_keys=True), PURPOSE.format(ids[slug]))
        row = db.get(OrganizationConfigSlice, ids[slug])
        if row is None:
            db.add(
                OrganizationConfigSlice(
                    organization_id=ids[slug],
                    revision_id=revision_id,
                    ciphertext=text,
                    created_at=utcnow(),
                )
            )
        else:
            row.ciphertext, row.revision_id, row.created_at = text, revision_id, utcnow()
    db.flush()


def load(
    db: Session, key: InstallationKey | None, organization_id: uuid.UUID
) -> dict[str, Any] | None:
    row = db.get(OrganizationConfigSlice, organization_id)
    if row is None or key is None:
        return None
    try:
        part: dict[str, Any] = json.loads(
            key.decrypt(row.ciphertext, PURPOSE.format(organization_id))
        )
    except Exception:
        return None
    return part


@dataclass
class Isolated:
    """A generation that worked once some organizations' newer data was
    held back: the snapshot used, and why each was held back."""

    snapshot: dict[str, Any]
    held_back: dict[str, str] = field(default_factory=dict)  # slug -> first error


def isolate(
    db: Session,
    key: InstallationKey | None,
    snapshot: dict[str, Any],
    errors: list[str],
    attempt: Any,
) -> Isolated | None:
    """Try each organization's last good part in turn; ``attempt(snapshot)``
    returns the problems of a generation (empty when it works). Returns the
    first snapshot that works, or None when no single organization is the
    cause (a shared object, or no last good part)."""
    orgs = {str(o["slug"]): o for o in snapshot.get(ORGANIZATIONS_KEY) or []}
    if len(orgs) < 2:
        return None
    ids = {o.slug: o.id for o in db.scalars(select(Organization))}
    for slug in sorted(orgs):
        if slug not in ids:
            continue
        part = load(db, key, ids[slug])
        if part is None:
            continue
        candidate = with_slice(snapshot, slug, part)
        if not attempt(candidate):
            return Isolated(candidate, {slug: errors[0] if errors else "generation failed"})
    return None
