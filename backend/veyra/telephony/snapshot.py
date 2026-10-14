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

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.mail import load_smtp_settings, sender
from veyra.core.models import (
    CallQueue,
    Device,
    Extension,
    InboundRoute,
    Installation,
    IvrEntry,
    IvrMenu,
    Organization,
    OutboundRoute,
    OutboundRouteTrunk,
    PickupGroup,
    PickupGroupMember,
    Prompt,
    QueueMember,
    RingGroup,
    RingGroupMember,
    SipTrunk,
    Site,
    TimeCondition,
    VoicemailBox,
)
from veyra.core.security.crypto import DecryptionError, InstallationKey
from veyra.telephony.settings import load_sip_settings
from veyra.version import __version__

SNAPSHOT_VERSION = 6


def secret_purpose(extension_id: Any) -> str:
    """Associated data that binds a SIP secret ciphertext to its extension."""
    return f"extension.sip_secret:{extension_id}"


def trunk_secret_purpose(trunk_id: Any) -> str:
    """Associated data that binds a trunk password ciphertext to its trunk."""
    return f"trunk.sip_secret:{trunk_id}"


def pin_purpose(box_id: Any) -> str:
    """Associated data that binds a voicemail PIN ciphertext to its box."""
    return f"voicemail.pin:{box_id}"


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


def _pin(box: VoicemailBox, number: str, key: InstallationKey | None) -> str:
    if key is None:
        raise SnapshotError(
            f"the voicemail box of extension {number} has an encrypted PIN but the "
            "installation key is not available (see 'veyra installation-key check')"
        )
    try:
        return key.decrypt(box.pin_ciphertext, pin_purpose(box.id))
    except DecryptionError as e:
        raise SnapshotError(f"the voicemail PIN of extension {number} cannot be read: {e}") from e


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
    org_tz = {o.id: o.timezone for o in orgs}
    ext_by_id = {e.id: e for e in extensions}
    # Site defaults for the emergency caller ID (docs/TRUNKS_ROUTING.md §7) and
    # the number of phones registering each extension (docs/DEVICE_PROVISIONING.md §2).
    site_ecid = {s.id: s.emergency_caller_id_number for s in db.scalars(select(Site))}
    contacts = _contacts(db, ext_by_id)
    ring_groups = [
        g
        for g in db.scalars(select(RingGroup).order_by(RingGroup.number)).all()
        if g.is_enabled and g.organization_id in active
    ]
    queues = [
        q
        for q in db.scalars(select(CallQueue).order_by(CallQueue.number)).all()
        if q.is_enabled and q.organization_id in active
    ]
    targets = Targets(
        number_of={e.id: e.number for e in extensions},
        box_numbers=set(),
        ivr_slug={},
        ring_group_slug={g.id: g.slug for g in ring_groups},
        queue_slug={q.id: q.slug for q in queues},
    )
    voicemail = _voicemail_ivr(
        db, key, active, extensions, org_slug, org_tz, targets, ring_groups, queues
    )
    groups = _groups(db, extensions, org_slug, targets, ring_groups, queues)
    pickup = _pickup_groups(db, active, ext_by_id)
    smtp = load_smtp_settings(db)
    from_address, from_name = sender(smtp, inst.name if inst else "Veyra")
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "veyra_version": __version__,
        "installation": {
            "name": inst.name if inst else "Veyra",
            "instance_id": str(inst.instance_id) if inst else None,
            "multi_tenancy_enabled": bool(inst.multi_tenancy_enabled) if inst else False,
        },
        "sip": load_sip_settings(db).model_dump(mode="json"),
        "smtp": {"enabled": smtp.enabled, "from_address": from_address, "from_name": from_name},
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
                "emergency_caller_id_number": e.emergency_caller_id_number
                or (site_ecid.get(e.site_id) if e.site_id else None),
                "max_contacts": contacts.get(e.id, 1),
                "secret": _secret(e, key),
                "pickup_groups": pickup.get(e.id, []),
            }
            for e in extensions
        ],
        **voicemail,
        **groups,
        **_routing(db, key, active, extensions, targets),
    }


def _contacts(db: Session, ext_by_id: dict[Any, Extension]) -> dict[Any, int]:
    """Extensions carried by more than one device register more than once."""
    counts: dict[Any, int] = {}
    for d in db.scalars(select(Device).where(Device.is_enabled.is_(True))):
        ids = [d.primary_extension_id] if d.primary_extension_id else []
        for line in d.lines or []:
            try:
                ids.append(uuid.UUID(str(line.get("extension_id"))))
            except (ValueError, AttributeError):
                continue
        for ext_id in ids:
            if ext_id in ext_by_id:
                counts[ext_id] = counts.get(ext_id, 0) + 1
    return {k: v for k, v in counts.items() if v > 1}


class Targets:
    """What the deployable destinations of this snapshot may point at: the
    numbers of enabled extensions, the numbers that have an enabled box,
    the slugs of enabled menus, ring groups and queues."""

    def __init__(
        self,
        *,
        number_of: dict[Any, str],
        box_numbers: set[str],
        ivr_slug: dict[Any, str],
        ring_group_slug: dict[Any, str],
        queue_slug: dict[Any, str],
    ) -> None:
        self.number_of = number_of
        self.box_numbers = box_numbers
        self.ivr_slug = ivr_slug
        self.ring_group_slug = ring_group_slug
        self.queue_slug = queue_slug

    def dest(self, obj: Any, prefix: str) -> dict[str, Any]:
        """The engine-neutral form of the destination stored in
        ``<prefix>_type`` + target columns of ``obj``: the extension number,
        the number whose voicemail answers, the menu, ring group or queue
        slug, a hang-up, or ``missing`` when the target is gone or not
        deployable (the generator renders congestion and the interface flags
        it)."""
        kind = getattr(obj, f"{prefix}_type")
        if kind == "hangup":
            return {"type": "hangup"}
        if kind == "ivr":
            slug = self.ivr_slug.get(getattr(obj, f"{prefix}_ivr_id"))
            return {"type": "ivr", "ivr": slug} if slug else {"type": "missing"}
        if kind == "ring_group":
            slug = self.ring_group_slug.get(getattr(obj, f"{prefix}_ring_group_id"))
            return {"type": "ring_group", "ring_group": slug} if slug else {"type": "missing"}
        if kind == "queue":
            slug = self.queue_slug.get(getattr(obj, f"{prefix}_queue_id"))
            return {"type": "queue", "queue": slug} if slug else {"type": "missing"}
        number = self.number_of.get(getattr(obj, f"{prefix}_extension_id"))
        if kind == "voicemail":
            if number and number in self.box_numbers:
                return {"type": "voicemail", "number": number}
            return {"type": "missing"}
        return {"type": "extension", "number": number} if number else {"type": "missing"}


def _voicemail_ivr(
    db: Session,
    key: InstallationKey | None,
    active_orgs: set[Any],
    extensions: list[Extension],
    org_slug: dict[Any, str],
    org_tz: dict[Any, str],
    targets: Targets,
    ring_groups: list[RingGroup],
    queues: list[CallQueue],
) -> dict[str, Any]:
    """Voicemail boxes and IVR menus of active organizations
    (docs/VOICEMAIL_IVR.md §3, §5). Fills ``targets`` with the deployable
    boxes and menus."""
    ext_by_id = {e.id: e for e in extensions}
    boxes = [
        b
        for b in db.scalars(select(VoicemailBox).order_by(VoicemailBox.created_at)).all()
        if b.is_enabled and b.extension_id in ext_by_id
    ]
    boxes.sort(key=lambda b: ext_by_id[b.extension_id].number)
    targets.box_numbers.update(ext_by_id[b.extension_id].number for b in boxes)
    menus = [
        m
        for m in db.scalars(select(IvrMenu).order_by(IvrMenu.slug)).all()
        if m.is_enabled and m.organization_id in active_orgs
    ]
    targets.ivr_slug.update({m.id: m.slug for m in menus})
    prompts = {p.id: p for p in db.scalars(select(Prompt)).all()}
    entries: dict[Any, list[IvrEntry]] = {}
    for e in db.scalars(select(IvrEntry).order_by(IvrEntry.digit)).all():
        entries.setdefault(e.menu_id, []).append(e)
    # Direct dialling from a menu reaches extensions, ring groups and queues.
    numbers_by_org: dict[Any, list[str]] = {}
    for ext in extensions:
        numbers_by_org.setdefault(ext.organization_id, []).append(ext.number)
    for g in ring_groups:
        numbers_by_org.setdefault(g.organization_id, []).append(g.number)
    for q in queues:
        numbers_by_org.setdefault(q.organization_id, []).append(q.number)

    def prompt_slug(prompt_id: Any, org_id: Any) -> str | None:
        p = prompts.get(prompt_id) if prompt_id else None
        return p.slug if p is not None and p.organization_id == org_id else None

    return {
        "voicemail_boxes": [
            {
                "number": ext_by_id[b.extension_id].number,
                "name": ext_by_id[b.extension_id].display_name,
                "organization": org_slug.get(b.organization_id, ""),
                "timezone": org_tz.get(b.organization_id) or "UTC",
                "pin": _pin(b, ext_by_id[b.extension_id].number, key),
                "email": b.email,
                "attach_audio": b.attach_audio,
                "delete_after_email": b.delete_after_email,
                "ring_seconds": b.ring_seconds,
            }
            for b in boxes
        ],
        "ivr_menus": [
            {
                "slug": m.slug,
                "name": m.name,
                "organization": org_slug.get(m.organization_id, ""),
                "prompt": prompt_slug(m.prompt_id, m.organization_id),
                "invalid_prompt": prompt_slug(m.invalid_prompt_id, m.organization_id),
                "timeout_seconds": m.timeout_seconds,
                "max_retries": m.max_retries,
                "allow_direct_dial": m.allow_direct_dial,
                "direct_dial": sorted(numbers_by_org.get(m.organization_id, [])),
                "timeout": targets.dest(m, "timeout"),
                "invalid": targets.dest(m, "invalid"),
                "entries": [
                    {"digit": e.digit, **targets.dest(e, "destination")}
                    for e in entries.get(m.id, [])
                ],
            }
            for m in menus
        ],
    }


def _groups(
    db: Session,
    extensions: list[Extension],
    org_slug: dict[Any, str],
    targets: Targets,
    ring_groups: list[RingGroup],
    queues: list[CallQueue],
) -> dict[str, Any]:
    """Enabled ring groups and queues of active organizations with their
    enabled members (docs/RING_GROUPS_QUEUES.md §2, §3)."""
    ext_by_id = {e.id: e for e in extensions}
    rg_members: dict[Any, list[RingGroupMember]] = {}
    for m in db.scalars(select(RingGroupMember).order_by(RingGroupMember.position)).all():
        if m.extension_id in ext_by_id:
            rg_members.setdefault(m.group_id, []).append(m)
    q_members: dict[Any, list[QueueMember]] = {}
    for qm in db.scalars(select(QueueMember).order_by(QueueMember.penalty)).all():
        if qm.extension_id in ext_by_id:
            q_members.setdefault(qm.queue_id, []).append(qm)
    prompts = {p.id: p for p in db.scalars(select(Prompt)).all()}

    def prompt_slug(prompt_id: Any, org_id: Any) -> str | None:
        p = prompts.get(prompt_id) if prompt_id else None
        return p.slug if p is not None and p.organization_id == org_id else None

    def member(ext: Extension) -> dict[str, Any]:
        return {"endpoint_name": ext.endpoint_name, "number": ext.number, "name": ext.display_name}

    return {
        "ring_groups": [
            {
                "slug": g.slug,
                "name": g.name,
                "number": g.number,
                "organization": org_slug.get(g.organization_id, ""),
                "strategy": g.strategy,
                "ring_seconds": g.ring_seconds,
                "ring_busy_members": g.ring_busy_members,
                "caller_id_prefix": g.caller_id_prefix,
                "members": [member(ext_by_id[m.extension_id]) for m in rg_members.get(g.id, [])],
                "failover": targets.dest(g, "failover"),
            }
            for g in ring_groups
        ],
        "queues": [
            {
                "slug": q.slug,
                "name": q.name,
                "number": q.number,
                "organization": org_slug.get(q.organization_id, ""),
                "strategy": q.strategy,
                "member_timeout": q.member_timeout,
                "retry_seconds": q.retry_seconds,
                "wrapup_seconds": q.wrapup_seconds,
                "max_wait_seconds": q.max_wait_seconds,
                "max_callers": q.max_callers,
                "join_when_empty": q.join_when_empty,
                "announce_position": q.announce_position,
                "announce_frequency": q.announce_frequency,
                "announcement_prompt": prompt_slug(q.announcement_prompt_id, q.organization_id),
                "periodic_prompt": prompt_slug(q.periodic_prompt_id, q.organization_id),
                "periodic_seconds": q.periodic_seconds,
                "music": q.music,
                "members": [
                    {**member(ext_by_id[m.extension_id]), "penalty": m.penalty}
                    for m in sorted(
                        q_members.get(q.id, []),
                        key=lambda m: (m.penalty, ext_by_id[m.extension_id].number),
                    )
                ],
                "failover": targets.dest(q, "failover"),
            }
            for q in queues
        ],
    }


def _pickup_groups(
    db: Session, active_orgs: set[Any], ext_by_id: dict[Any, Extension]
) -> dict[Any, list[str]]:
    """Pickup group slugs per extension id (docs/RING_GROUPS_QUEUES.md §4)."""
    groups = {
        g.id: g for g in db.scalars(select(PickupGroup)).all() if g.organization_id in active_orgs
    }
    out: dict[Any, list[str]] = {}
    for m in db.scalars(select(PickupGroupMember)).all():
        g = groups.get(m.group_id)
        if g is not None and m.extension_id in ext_by_id:
            out.setdefault(m.extension_id, []).append(g.slug)
    for slugs in out.values():
        slugs.sort()
    return out


def _routing(
    db: Session,
    key: InstallationKey | None,
    active_orgs: set[Any],
    extensions: list[Extension],
    targets: Targets,
) -> dict[str, Any]:
    """Trunks, routes and time conditions (docs/TRUNKS_ROUTING.md §8)."""
    trunks = db.scalars(select(SipTrunk).order_by(SipTrunk.slug)).all()
    enabled_trunks = {t.id: t for t in trunks if t.is_enabled}
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
                "destination": targets.dest(r, "destination"),
                "after_hours": (
                    targets.dest(r, "after_hours") if r.time_condition_id is not None else None
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
