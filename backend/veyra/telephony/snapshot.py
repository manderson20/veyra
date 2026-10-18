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
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.mail import load_smtp_settings, sender
from veyra.core.models import (
    Announcement,
    CallFlow,
    CallQueue,
    ClassOfService,
    ConferenceRoom,
    Device,
    Extension,
    ExtensionState,
    FollowMe,
    InboundRoute,
    Installation,
    IvrEntry,
    IvrMenu,
    MohClass,
    MohClassTrack,
    Organization,
    OutboundRoute,
    OutboundRouteTrunk,
    Page,
    PageMember,
    PageZone,
    PagingZone,
    PagingZoneMember,
    ParkingLot,
    PickupGroup,
    PickupGroupMember,
    Prompt,
    QueueMember,
    RecordingPolicy,
    RingGroup,
    RingGroupMember,
    SipTrunk,
    Site,
    TimeCondition,
    VoicemailBox,
    VoicemailBoxMember,
)
from veyra.core.security.crypto import DecryptionError, InstallationKey
from veyra.telephony import features, moh
from veyra.telephony.numbering import load_numbering_plan
from veyra.telephony.settings import load_sip_settings
from veyra.version import __version__

SNAPSHOT_VERSION = 11  # 11: engine namespaces (docs/MULTI_TENANCY.md)


def secret_purpose(extension_id: Any) -> str:
    """Associated data that binds a SIP secret ciphertext to its extension."""
    return f"extension.sip_secret:{extension_id}"


def trunk_secret_purpose(trunk_id: Any) -> str:
    """Associated data that binds a trunk password ciphertext to its trunk."""
    return f"trunk.sip_secret:{trunk_id}"


def call_flow_pin_purpose(flow_id: Any) -> str:
    """Encryption purpose of a call flow's toggle PIN."""
    return f"call_flow.pin:{flow_id}"


def time_condition_pin_purpose(tc_id: Any) -> str:
    """Encryption purpose of a time condition's override PIN."""
    return f"time_condition.pin:{tc_id}"


def conference_pin_purpose(room_id: Any, which: str) -> str:
    """Encryption purpose of a conference room's user or admin PIN."""
    return f"conference.pin:{room_id}:{which}"


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


def _conference_pin(room: ConferenceRoom, which: str, key: InstallationKey | None) -> str | None:
    ciphertext = getattr(room, f"{which}_pin_ciphertext")
    if not ciphertext:
        return None
    if key is None:
        raise SnapshotError(
            f"the conference room {room.name} has an encrypted PIN but the installation "
            "key is not available (see 'veyra installation-key check')"
        )
    try:
        return key.decrypt(ciphertext, conference_pin_purpose(room.id, which))
    except DecryptionError as e:
        raise SnapshotError(
            f"the {which} PIN of conference room {room.name} cannot be read: {e}"
        ) from e


def _switch_pin(row: Any, purpose: str, what: str, key: InstallationKey | None) -> str | None:
    if not row.pin_ciphertext:
        return None
    if key is None:
        raise SnapshotError(
            f"{what} has an encrypted PIN but the installation key is not available "
            "(see 'veyra installation-key check')"
        )
    try:
        return key.decrypt(row.pin_ciphertext, purpose)
    except DecryptionError as e:
        raise SnapshotError(f"the PIN of {what} cannot be read: {e}") from e


def _callflow(
    db: Session,
    key: InstallationKey | None,
    org_slug: dict[Any, str],
    targets: Targets,
    announcements: list[Announcement],
    rooms: list[ConferenceRoom],
    moh_slug: Callable[[Any, Any], str | None],
    flows: list[CallFlow] | None = None,
    lots: list[ParkingLot] | None = None,
) -> dict[str, Any]:
    """Announcements and conference rooms of active organizations
    (docs/CALL_FEATURES.md §4.1, §4.3). ``targets`` already knows their slugs."""
    prompts = {p.id: p for p in db.scalars(select(Prompt)).all()}

    def prompt_slug(prompt_id: Any, org_id: Any) -> str | None:
        p = prompts.get(prompt_id) if prompt_id else None
        return p.slug if p is not None and p.organization_id == org_id else None

    return {
        "announcements": [
            {
                "slug": a.slug,
                "name": a.name,
                "organization": org_slug.get(a.organization_id, ""),
                "prompt": prompt_slug(a.prompt_id, a.organization_id),
                "allow_skip": a.allow_skip,
                "repeat_key": a.repeat_key,
                "destination": targets.dest(a, "destination"),
            }
            for a in announcements
        ],
        "call_flows": [
            {
                "slug": f.slug,
                "name": f.name,
                "organization": org_slug.get(f.organization_id, ""),
                "code_index": f.code_index,
                "pin": _switch_pin(f, call_flow_pin_purpose(f.id), f"call flow {f.name}", key),
                "override": bool(f.override),
                "normal": targets.dest(f, "normal"),
                "override_destination": targets.dest(f, "override"),
            }
            for f in flows or []
        ],
        "parking_lots": [
            {
                "slug": lot.slug,
                "name": lot.name,
                "organization": org_slug.get(lot.organization_id, ""),
                "park_exten": lot.park_exten,
                "slot_first": lot.slot_first,
                "slot_last": lot.slot_last,
                "timeout_seconds": lot.timeout_seconds,
                "return_ring_seconds": lot.return_ring_seconds,
                "courtesy_tone": lot.courtesy_tone,
                "timeout": targets.dest(lot, "timeout"),
            }
            for lot in lots or []
        ],
        "conference_rooms": [
            {
                "slug": r.slug,
                "name": r.name,
                "number": r.number,
                "organization": org_slug.get(r.organization_id, ""),
                "user_pin": _conference_pin(r, "user", key),
                "admin_pin": _conference_pin(r, "admin", key),
                "max_participants": r.max_participants,
                "record": r.record,
                "announce_join_leave": r.announce_join_leave,
                "music_on_hold_alone": r.music_on_hold_alone,
                "wait_for_admin": r.wait_for_admin,
                "hold_music": moh_slug(r.moh_class_id, r.organization_id),
            }
            for r in rooms
        ],
    }


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
    org_intercom = {o.id: o.intercom_default for o in orgs}
    # Classes of service (docs/CALL_FEATURES.md §3.8), by id for the extensions
    # and as a list for the generator's guards.
    classes = list(db.scalars(select(ClassOfService).order_by(ClassOfService.slug)))
    class_slug = {c.id: c.slug for c in classes}
    route_slug = {r.id: r.slug for r in db.scalars(select(OutboundRoute))}
    ext_by_id = {e.id: e for e in extensions}
    ring_seconds = {
        s.extension_id: s.ring_seconds
        for s in db.scalars(
            select(ExtensionState).where(ExtensionState.extension_id.in_(list(ext_by_id)))
        )
    }
    # Find me / follow me (docs/CALL_FEATURES.md §3.4): extension members are
    # resolved to endpoints here; a disabled or missing one gets no endpoint.
    by_org_number = {(e.organization_id, e.number): e for e in extensions}
    follow_me: dict[Any, dict[str, Any]] = {}
    for fm in db.scalars(select(FollowMe).where(FollowMe.extension_id.in_(list(ext_by_id)))):
        owner = ext_by_id[fm.extension_id]
        members = []
        for m in fm.members or []:
            kind = str(m.get("type") or "extension")
            number = str(m.get("target") or "")
            member: dict[str, Any] = {
                "type": kind,
                "target": number,
                "ring_seconds": int(m.get("ring_seconds") or 20),
            }
            if kind == "extension":
                target = by_org_number.get((owner.organization_id, number))
                member["endpoint"] = target.endpoint_name if target else None
            members.append(member)
        follow_me[fm.extension_id] = {
            "strategy": fm.strategy,
            "initial_ring_seconds": fm.initial_ring_seconds,
            "confirm_calls": fm.confirm_calls,
            "caller_id_mode": fm.caller_id_mode,
            "members": members,
            "no_answer_destination": fm.no_answer_destination,
        }
    # Site defaults for the emergency caller ID (docs/TRUNKS_ROUTING.md §7) and
    # the number of phones registering each extension (docs/DEVICE_PROVISIONING.md §2).
    sites = list(db.scalars(select(Site)))
    site_ecid = {s.id: s.emergency_caller_id_number for s in sites}
    # Emergency calling (docs/PRODUCTION_HARDENING.md §6): what the generator
    # needs per site for the PSAP callback and site-bound routes.
    sites_out = [
        {
            "id": str(s.id),
            "slug": s.slug,
            "name": s.name,
            "organization": org_slug.get(s.organization_id, ""),
            "emergency_caller_id_number": s.emergency_caller_id_number,
            "callback_minutes": int(s.emergency_callback_minutes or 30),
            "responder": (
                ext_by_id[s.emergency_responder_extension_id].number
                if s.emergency_responder_extension_id in ext_by_id
                else None
            ),
        }
        for s in sites
        if s.organization_id in active
    ]
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
    # Milestone 19 destinations (docs/CALL_FEATURES.md §4): enabled rooms and
    # announcements of active organizations are deployable targets.
    announcements = [
        a
        for a in db.scalars(select(Announcement).order_by(Announcement.slug)).all()
        if a.is_enabled and a.organization_id in active
    ]
    rooms = [
        r
        for r in db.scalars(select(ConferenceRoom).order_by(ConferenceRoom.number)).all()
        if r.is_enabled and r.organization_id in active
    ]
    flows = [
        f
        for f in db.scalars(select(CallFlow).order_by(CallFlow.code_index)).all()
        if f.is_enabled and f.organization_id in active
    ]
    targets = Targets(
        number_of={e.id: e.number for e in extensions},
        box_numbers=set(),
        ivr_slug={},
        ring_group_slug={g.id: g.slug for g in ring_groups},
        queue_slug={q.id: q.slug for q in queues},
        announcement_slug={a.id: a.slug for a in announcements},
        conference_slug={r.id: r.slug for r in rooms},
        call_flow_slug={f.id: f.slug for f in flows},
    )
    voicemail = _voicemail_ivr(
        db, key, active, extensions, org_slug, org_tz, targets, ring_groups, queues, rooms
    )
    shared_by_ext: dict[Any, list[str]] = voicemail.pop("_shared_by_extension")
    hold_music, moh_slug = _hold_music(db, active, org_slug)
    groups = _groups(db, extensions, org_slug, targets, ring_groups, queues, moh_slug)
    lots = [
        lot
        for lot in db.scalars(select(ParkingLot).order_by(ParkingLot.park_exten)).all()
        if lot.is_enabled and lot.organization_id in active
    ]
    callflow = _callflow(db, key, org_slug, targets, announcements, rooms, moh_slug, flows, lots)
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
        # Configurable feature codes (docs/CALL_FEATURES.md §3.1).
        "feature_codes": features.active(db),
        "numbering": {"extension_length": load_numbering_plan(db).extension_length},
        "classes_of_service": [
            {
                "slug": c.slug,
                "name": c.name,
                "organization": org_slug.get(c.organization_id, ""),
                "allowed_routes": sorted(
                    route_slug[uuid.UUID(x)]
                    for x in (c.allowed_outbound_route_ids or [])
                    if uuid.UUID(x) in route_slug
                ),
                "allowed_feature_codes": c.allowed_feature_code_keys,
                "allow_external_forwards": c.allow_external_forwards,
                "allow_external_follow_me": c.allow_external_follow_me,
                "allow_intercom": c.allow_intercom,
                "max_outbound_calls": c.max_outbound_calls,
            }
            for c in classes
            if c.organization_id in active
        ],
        "smtp": {"enabled": smtp.enabled, "from_address": from_address, "from_name": from_name},
        "organizations": [
            {
                "slug": o.slug,
                "name": o.name,
                "timezone": o.timezone,
                "is_active": o.is_active,
                "namespace": o.engine_namespace,
                "hold_music": moh_slug(o.moh_class_id, o.id),
            }
            for o in orgs
        ],
        "hold_music": hold_music,
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
                "outbound_caller_id_number": e.outbound_caller_id_number,
                "outbound_caller_id_name": e.outbound_caller_id_name,
                # Ring time (docs/CALL_FEATURES.md §3.3); None: the box's or the default.
                "ring_seconds": ring_seconds.get(e.id),
                "follow_me": follow_me.get(e.id),
                # Intercom (docs/CALL_FEATURES.md §3.6); default = the organization's.
                "intercom": (
                    e.intercom
                    if e.intercom in ("allow", "deny")
                    else org_intercom.get(e.organization_id, "allow")
                ),
                "class_of_service": (
                    class_slug.get(e.class_of_service_id) if e.class_of_service_id else None
                ),
                # Phones that may register (docs/EXTENSIONS.md §1): the larger of
                # the administrator's limit and the provisioned-phone count.
                "max_contacts": max(contacts.get(e.id, 1), e.max_registrations or 1),
                "secret": _secret(e, key),
                "pickup_groups": pickup.get(e.id, []),
                "shared_mailboxes": shared_by_ext.get(e.id, []),
                "site": str(e.site_id) if e.site_id else None,
            }
            for e in extensions
        ],
        "sites": sites_out,
        **voicemail,
        **groups,
        **callflow,
        **_routing(db, key, active, extensions, targets, org_slug),
        "paging": _paging(db, active, org_slug, ext_by_id),
        "recording": _recording(db, active, org_slug, ext_by_id, ring_groups, queues),
    }


def _recording(
    db: Session,
    active: set[Any],
    org_slug: dict[Any, str],
    ext_by_id: dict[Any, Extension],
    ring_groups: list[RingGroup],
    queues: list[CallQueue],
) -> list[dict[str, Any]]:
    """Enabled recording policies of active organizations (docs/REPORTING.md
    §4), with their targets as the generator names them."""
    prompts = {p.id: p for p in db.scalars(select(Prompt)).all()}
    routes = {r.id: r for r in db.scalars(select(InboundRoute)).all()}
    group_slug = {g.id: g.slug for g in ring_groups}
    queue_slug = {q.id: q.slug for q in queues}
    out = []
    policies = db.scalars(
        select(RecordingPolicy)
        .where(RecordingPolicy.is_enabled.is_(True))
        .order_by(RecordingPolicy.name)
    ).all()
    for pol in policies:
        if pol.organization_id not in active:
            continue
        if not (pol.inbound or pol.outbound or pol.internal):
            continue
        prompt = prompts.get(pol.announcement_prompt_id) if pol.announcement_prompt_id else None
        out.append(
            {
                "id": str(pol.id),
                "organization": org_slug.get(pol.organization_id, ""),
                "organization_id": str(pol.organization_id),
                "inbound": pol.inbound,
                "outbound": pol.outbound,
                "internal": pol.internal,
                "all": pol.scope == "all",
                "extensions": sorted(
                    ext_by_id[i].number for i in pol.extension_ids or [] if i in ext_by_id
                ),
                "endpoints": sorted(
                    ext_by_id[i].endpoint_name for i in pol.extension_ids or [] if i in ext_by_id
                ),
                "ring_groups": sorted(
                    group_slug[i] for i in pol.ring_group_ids or [] if i in group_slug
                ),
                "queues": sorted(queue_slug[i] for i in pol.queue_ids or [] if i in queue_slug),
                "routes": sorted(routes[i].did for i in pol.inbound_route_ids or [] if i in routes),
                "announcement": prompt.slug
                if prompt is not None and prompt.organization_id == pol.organization_id
                else None,
            }
        )
    return out


PAGING_BASE_PORT = 40000


def _paging(
    db: Session, active_orgs: set[Any], org_slug: dict[Any, str], ext_by_id: dict[Any, Extension]
) -> dict[str, Any]:
    """Zones with their sender ports and pages (docs/PAGING_RECORDINGS.md §2):
    the dialplan and ``paging.json`` come from the same table, so the port a
    zone is paged on is the one the sender listens on."""
    zones = sorted(
        (
            z
            for z in db.scalars(select(PagingZone)).all()
            if z.is_enabled and z.organization_id in active_orgs
        ),
        key=lambda z: (org_slug.get(z.organization_id, ""), z.slug),
    )
    zone_members: dict[Any, list[str]] = {}
    for m in db.scalars(select(PagingZoneMember)).all():
        ext = ext_by_id.get(m.extension_id)
        if ext is not None:
            zone_members.setdefault(m.zone_id, []).append(ext.number)
    zone_rows = []
    for i, z in enumerate(zones):
        zone_rows.append(
            {
                "slug": z.slug,
                "name": z.name,
                "organization": org_slug.get(z.organization_id, ""),
                "number": z.number,
                "port": PAGING_BASE_PORT + i,
                "multicast_address": z.multicast_address,
                "multicast_port": z.multicast_port,
                "poly_address": z.poly_address,
                "poly_port": z.poly_port,
                "poly_group": z.poly_group,
                "kind": z.kind,
                "codec": z.codec,
                "allowed": z.allowed,
                "members": sorted(zone_members.get(z.id, [])),
                "max_seconds": z.max_seconds,
            }
        )
    zone_by_id = {z.id: z for z in zones}
    page_zones: dict[Any, list[str]] = {}
    for pz in db.scalars(select(PageZone)).all():
        linked = zone_by_id.get(pz.zone_id)
        if linked is not None:
            page_zones.setdefault(pz.page_id, []).append(linked.slug)
    page_members: dict[Any, list[str]] = {}
    for pm in db.scalars(select(PageMember)).all():
        ext = ext_by_id.get(pm.extension_id)
        if ext is not None:
            page_members.setdefault(pm.page_id, []).append(ext.number)
    prompts = {p.id: p for p in db.scalars(select(Prompt)).all()}
    page_rows = []
    for p in db.scalars(select(Page).order_by(Page.slug)).all():
        if not p.is_enabled or p.organization_id not in active_orgs:
            continue
        audio = prompts.get(p.audio_id) if p.audio_id else None
        page_rows.append(
            {
                "slug": p.slug,
                "name": p.name,
                "organization": org_slug.get(p.organization_id, ""),
                "number": p.number,
                "zones": sorted(page_zones.get(p.id, [])),
                "audio": audio.slug if audio else None,
                "pre_tone": bool(p.pre_tone),
                "repeat": int(p.repeat),
                "priority": p.priority,
                "allowed": p.allowed,
                "members": sorted(page_members.get(p.id, [])),
                "max_seconds": p.max_seconds,
            }
        )
    return {"zones": zone_rows, "pages": page_rows, "defaults": {"delay_ms": 200, "ttl": 1}}


def provisioned_phones(db: Session, extension_ids: set[Any]) -> dict[Any, int]:
    """How many enabled devices carry each extension (line 1 or an extra line,
    docs/DEVICE_PROVISIONING.md §2). Extensions on no device are absent."""
    counts: dict[Any, int] = {}
    if not extension_ids:
        return counts
    for d in db.scalars(select(Device).where(Device.is_enabled.is_(True))):
        ids = [d.primary_extension_id] if d.primary_extension_id else []
        for line in d.lines or []:
            try:
                ids.append(uuid.UUID(str(line.get("extension_id"))))
            except (ValueError, AttributeError):
                continue
        for ext_id in ids:
            if ext_id in extension_ids:
                counts[ext_id] = counts.get(ext_id, 0) + 1
    return counts


def registration_limit(max_registrations: int | None, phones: int) -> int:
    """The number of phones an extension accepts: the administrator's limit
    or the provisioned count, whichever is larger, at least one."""
    return max(max_registrations or 1, phones, 1)


def _contacts(db: Session, ext_by_id: dict[Any, Extension]) -> dict[Any, int]:
    """Extensions carried by more than one device register more than once."""
    counts = provisioned_phones(db, set(ext_by_id))
    return {k: v for k, v in counts.items() if v > 1}


class Targets:
    """What the deployable destinations of this snapshot may point at: the
    numbers of enabled extensions, the numbers that have an enabled box,
    the slugs of enabled menus, ring groups, queues, announcements and
    conference rooms."""

    def __init__(
        self,
        *,
        number_of: dict[Any, str],
        box_numbers: set[str],
        ivr_slug: dict[Any, str],
        ring_group_slug: dict[Any, str],
        queue_slug: dict[Any, str],
        shared_box_number: dict[Any, str] | None = None,
        announcement_slug: dict[Any, str] | None = None,
        conference_slug: dict[Any, str] | None = None,
        call_flow_slug: dict[Any, str] | None = None,
    ) -> None:
        self.number_of = number_of
        self.box_numbers = box_numbers
        # Shared inboxes by id → their own number (docs/PAGING_RECORDINGS.md §5).
        self.shared_box_number = shared_box_number if shared_box_number is not None else {}
        self.ivr_slug = ivr_slug
        self.ring_group_slug = ring_group_slug
        self.queue_slug = queue_slug
        self.announcement_slug = announcement_slug if announcement_slug is not None else {}
        self.conference_slug = conference_slug if conference_slug is not None else {}
        self.call_flow_slug = call_flow_slug if call_flow_slug is not None else {}

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
        if kind == "directory":
            return {"type": "directory"}
        if kind == "announcement":
            slug = self.announcement_slug.get(getattr(obj, f"{prefix}_announcement_id", None))
            return {"type": "announcement", "announcement": slug} if slug else {"type": "missing"}
        if kind == "conference":
            slug = self.conference_slug.get(getattr(obj, f"{prefix}_conference_id", None))
            return {"type": "conference", "conference": slug} if slug else {"type": "missing"}
        if kind == "call_flow":
            slug = self.call_flow_slug.get(getattr(obj, f"{prefix}_call_flow_id", None))
            return {"type": "call_flow", "call_flow": slug} if slug else {"type": "missing"}
        if kind == "ivr":
            slug = self.ivr_slug.get(getattr(obj, f"{prefix}_ivr_id"))
            return {"type": "ivr", "ivr": slug} if slug else {"type": "missing"}
        if kind == "ring_group":
            slug = self.ring_group_slug.get(getattr(obj, f"{prefix}_ring_group_id"))
            return {"type": "ring_group", "ring_group": slug} if slug else {"type": "missing"}
        if kind == "queue":
            slug = self.queue_slug.get(getattr(obj, f"{prefix}_queue_id"))
            return {"type": "queue", "queue": slug} if slug else {"type": "missing"}
        if kind == "voicemail_box":
            shared = self.shared_box_number.get(getattr(obj, f"{prefix}_voicemail_box_id", None))
            return {"type": "voicemail", "number": shared} if shared else {"type": "missing"}
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
    rooms: list[ConferenceRoom] | None = None,
) -> dict[str, Any]:
    """Voicemail boxes and IVR menus of active organizations
    (docs/VOICEMAIL_IVR.md §3, §5). Fills ``targets`` with the deployable
    boxes and menus."""
    ext_by_id = {e.id: e for e in extensions}
    boxes = [
        b
        for b in db.scalars(select(VoicemailBox).order_by(VoicemailBox.created_at)).all()
        if b.is_enabled
        and (
            b.extension_id in ext_by_id
            or (b.extension_id is None and b.number and b.organization_id in active_orgs)
        )
    ]

    def box_number(b: VoicemailBox) -> str:
        return ext_by_id[b.extension_id].number if b.extension_id else str(b.number)

    boxes.sort(key=box_number)
    targets.box_numbers.update(box_number(b) for b in boxes)
    targets.shared_box_number.update({b.id: box_number(b) for b in boxes if not b.extension_id})
    # Member lamps of shared inboxes (docs/PAGING_RECORDINGS.md §5).
    shared_by_ext: dict[Any, list[str]] = {}
    shared_ids = {b.id: box_number(b) for b in boxes if not b.extension_id}
    if shared_ids:
        for m in db.scalars(
            select(VoicemailBoxMember).where(VoicemailBoxMember.box_id.in_(shared_ids))
        ):
            if m.extension_id in ext_by_id:
                shared_by_ext.setdefault(m.extension_id, []).append(shared_ids[m.box_id])
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
    for r in rooms or []:
        numbers_by_org.setdefault(r.organization_id, []).append(r.number)

    def prompt_slug(prompt_id: Any, org_id: Any) -> str | None:
        p = prompts.get(prompt_id) if prompt_id else None
        return p.slug if p is not None and p.organization_id == org_id else None

    return {
        # Per extension id for the extension rows (popped by build_snapshot).
        "_shared_by_extension": {e: sorted(numbers) for e, numbers in shared_by_ext.items()},
        "shared_mailboxes": {
            ext_by_id[e].number: sorted(numbers) for e, numbers in shared_by_ext.items()
        },
        "voicemail_boxes": [
            {
                "number": box_number(b),
                "name": ext_by_id[b.extension_id].display_name if b.extension_id else b.name,
                "shared": b.extension_id is None,
                "organization": org_slug.get(b.organization_id, ""),
                "timezone": org_tz.get(b.organization_id) or "UTC",
                "pin": _pin(b, box_number(b), key),
                "email": b.email,
                "attach_audio": b.attach_audio,
                "delete_after_email": b.delete_after_email,
                "ring_seconds": b.ring_seconds,
                "operator_extension": b.operator_extension,
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


def _hold_music(
    db: Session, active_orgs: set[Any], org_slug: dict[Any, str]
) -> tuple[list[dict[str, Any]], Callable[[Any, Any], str | None]]:
    """Hold music sets of active organizations with their track file names
    (docs/PAGING_RECORDINGS.md §3.2), and a lookup of a set's slug that
    ignores sets of another organization."""
    classes = {
        c.id: c
        for c in db.scalars(select(MohClass).order_by(MohClass.slug)).all()
        if c.organization_id in active_orgs
    }
    prompts = {p.id: p for p in db.scalars(select(Prompt)).all()}
    tracks: dict[Any, list[MohClassTrack]] = {}
    for t in db.scalars(select(MohClassTrack).order_by(MohClassTrack.position)).all():
        if t.class_id in classes:
            tracks.setdefault(t.class_id, []).append(t)
    sets = [
        {
            "slug": c.slug,
            "name": c.name,
            "organization": org_slug.get(c.organization_id, ""),
            "random": c.random,
            "files": [
                moh.track_name(i, prompts[t.prompt_id].slug)
                for i, t in enumerate(tracks.get(c.id, []))
                if t.prompt_id in prompts
            ],
        }
        for c in classes.values()
    ]

    def moh_slug(class_id: Any, org_id: Any) -> str | None:
        c = classes.get(class_id) if class_id else None
        return c.slug if c is not None and c.organization_id == org_id else None

    return sets, moh_slug


def _groups(
    db: Session,
    extensions: list[Extension],
    org_slug: dict[Any, str],
    targets: Targets,
    ring_groups: list[RingGroup],
    queues: list[CallQueue],
    moh_slug: Callable[[Any, Any], str | None] = lambda _c, _o: None,
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
                "external_members": list(g.external_members or []),
                "confirm_external": g.confirm_external,
                "caller_id_prefix": g.caller_id_prefix,
                "music": g.music,
                "hold_music": moh_slug(g.moh_class_id, g.organization_id),
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
                "hold_music": moh_slug(q.moh_class_id, q.organization_id),
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
    org_slug: dict[Any, str] | None = None,
) -> dict[str, Any]:
    """Trunks, routes and time conditions (docs/TRUNKS_ROUTING.md §8)."""
    org_slug = org_slug or {}
    trunks = db.scalars(select(SipTrunk).order_by(SipTrunk.slug)).all()
    enabled_trunks = {t.id: t for t in trunks if t.is_enabled}
    conditions = db.scalars(select(TimeCondition).order_by(TimeCondition.name)).all()
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
                "organization_slug": org_slug.get(r.organization_id, ""),
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
                "site": str(r.site_id) if r.site_id else None,
                "patterns": list(r.patterns or []),
                "trunks": route_trunks.get(r.id, []),
                "caller_id_number": r.caller_id_number,
                "caller_id_force": bool(r.caller_id_force),
                # None: every organization (docs/MULTI_TENANCY.md §4).
                "organization": org_slug.get(r.organization_id) if r.organization_id else None,
            }
            for r in outbound
            if r.organization_id is None or r.organization_id in active_orgs
        ],
        # Used by a route, or carrying an override code (docs/CALL_FEATURES.md
        # §4.6): the code must work before a route points at the condition.
        "time_conditions": [
            {
                "key": str(c.id),
                "name": c.name,
                "organization": org_slug.get(c.organization_id, ""),
                "timezone": c.timezone,
                "ranges": list(c.ranges or []),
                "holidays": list(c.holidays or []),
                "code_index": c.code_index,
                "pin": _switch_pin(
                    c, time_condition_pin_purpose(c.id), f"time condition {c.name}", key
                ),
                "override": c.override,
            }
            for c in conditions
            if c.organization_id in active_orgs
            and (c.id in used_conditions or c.code_index is not None)
        ],
    }
