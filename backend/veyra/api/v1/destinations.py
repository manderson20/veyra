# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call destinations shared by inbound routes, IVR menus, ring groups,
queues and announcements (docs/VOICEMAIL_IVR.md §6, docs/RING_GROUPS_QUEUES.md
§5, docs/CALL_FEATURES.md §4): an extension, an extension's voicemail box, an
IVR menu, a ring group, a call queue, an announcement, a conference room, the
dial-by-name directory, a fax inbox, or (where allowed) a hang-up. Validation checks that
the target exists in the organization and is usable; output carries a label
and a ``missing`` flag so the interface can show a broken target."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.errors import ProblemError
from veyra.core.models import (
    Announcement,
    CallFlow,
    CallQueue,
    ConferenceRoom,
    Extension,
    FaxInbox,
    IvrMenu,
    RingGroup,
    VoicemailBox,
)

DestinationType = Literal[
    "extension",
    "voicemail",
    "voicemail_box",
    "ivr",
    "ring_group",
    "queue",
    "announcement",
    "conference",
    "call_flow",
    "fax",
    "directory",
    "hangup",
]
# The column suffix that holds each kind's target.
TARGET_FIELDS: dict[str, str] = {
    "extension": "extension_id",
    "voicemail": "extension_id",
    "voicemail_box": "voicemail_box_id",
    "ivr": "ivr_id",
    "ring_group": "ring_group_id",
    "queue": "queue_id",
    "announcement": "announcement_id",
    "conference": "conference_id",
    "call_flow": "call_flow_id",
    "fax": "fax_inbox_id",
}
# Kinds that need no target row: the dial-by-name directory of the
# organization, and hanging up.
TARGETLESS = frozenset({"directory", "hangup"})
ID_FIELDS = (
    "extension_id",
    "ivr_id",
    "ring_group_id",
    "queue_id",
    "voicemail_box_id",
    "announcement_id",
    "conference_id",
    "call_flow_id",
    "fax_inbox_id",
)
# A reference as stored: (type, extension_id, ivr_id, ring_group_id, queue_id,
# voicemail_box_id, announcement_id, conference_id, call_flow_id, fax_inbox_id).
Ref = tuple[str | None, Any, Any, Any, Any, Any, Any, Any, Any, Any]


def validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


class DestinationIn(BaseModel):
    type: DestinationType = "extension"
    extension_id: uuid.UUID | None = None
    ivr_id: uuid.UUID | None = None
    ring_group_id: uuid.UUID | None = None
    queue_id: uuid.UUID | None = None
    voicemail_box_id: uuid.UUID | None = None
    announcement_id: uuid.UUID | None = None
    conference_id: uuid.UUID | None = None
    call_flow_id: uuid.UUID | None = None
    fax_inbox_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _shape(self) -> DestinationIn:
        keep = TARGET_FIELDS.get(self.type)
        for field in ID_FIELDS:
            if field != keep:
                setattr(self, field, None)
        return self

    def as_ref(self) -> Ref:
        return (
            self.type,
            self.extension_id,
            self.ivr_id,
            self.ring_group_id,
            self.queue_id,
            self.voicemail_box_id,
            self.announcement_id,
            self.conference_id,
            self.call_flow_id,
            self.fax_inbox_id,
        )


class DestinationOut(BaseModel):
    type: str
    extension_id: uuid.UUID | None
    ivr_id: uuid.UUID | None
    ring_group_id: uuid.UUID | None = None
    queue_id: uuid.UUID | None = None
    voicemail_box_id: uuid.UUID | None = None
    announcement_id: uuid.UUID | None = None
    conference_id: uuid.UUID | None = None
    call_flow_id: uuid.UUID | None = None
    fax_inbox_id: uuid.UUID | None = None
    # Human form: "2214 — Front Office", "Voicemail of 2214 (Front Office)",
    # "Menu: Main menu", "Ring group: Sales (2300)", "Queue: Support (2400)",
    # "Announcement: Closed today", "Conference: Board room (2500)",
    # "Fax to email: Front office", "Dial-by-name directory", "Hang up";
    # None when the target is gone.
    label: str | None
    missing: bool


def ref_of(obj: Any, prefix: str) -> Ref:
    """The stored reference ``<prefix>_type`` + target columns of a row."""
    return (
        getattr(obj, f"{prefix}_type"),
        getattr(obj, f"{prefix}_extension_id"),
        getattr(obj, f"{prefix}_ivr_id"),
        getattr(obj, f"{prefix}_ring_group_id", None),
        getattr(obj, f"{prefix}_queue_id", None),
        getattr(obj, f"{prefix}_voicemail_box_id", None),
        getattr(obj, f"{prefix}_announcement_id", None),
        getattr(obj, f"{prefix}_conference_id", None),
        getattr(obj, f"{prefix}_call_flow_id", None),
        getattr(obj, f"{prefix}_fax_inbox_id", None),
    )


def apply(obj: Any, prefix: str, d: DestinationIn) -> None:
    """Store a destination into ``<prefix>_type`` + target columns."""
    setattr(obj, f"{prefix}_type", d.type)
    for field in ID_FIELDS:
        setattr(obj, f"{prefix}_{field}", getattr(d, field))


def has_target(ref: Ref) -> bool:
    """Whether the stored reference is complete: a target id for kinds that
    need one, any value for the targetless kinds."""
    kind = ref[0] or "extension"
    return kind in TARGETLESS or any(t is not None for t in ref[1:])


def as_input(ref: Ref) -> dict[str, Any]:
    kind, ext, ivr, rg, q, box, ann, conf, flow, fax = ref
    return {
        "type": kind or "extension",
        "extension_id": ext,
        "ivr_id": ivr,
        "ring_group_id": rg,
        "queue_id": q,
        "voicemail_box_id": box,
        "announcement_id": ann,
        "conference_id": conf,
        "call_flow_id": flow,
        "fax_inbox_id": fax,
    }


def check_destination(
    db: Session,
    organization_id: uuid.UUID,
    dest: DestinationIn,
    *,
    field: str,
    allow_hangup: bool,
    exclude_ivr: uuid.UUID | None = None,
    exclude_ring_group: uuid.UUID | None = None,
    exclude_queue: uuid.UUID | None = None,
    exclude_announcement: uuid.UUID | None = None,
    exclude_call_flow: uuid.UUID | None = None,
) -> None:
    """422 when the target is absent, in another organization, unusable, or
    the object itself (``exclude_*``)."""
    if dest.type == "hangup":
        if not allow_hangup:
            raise validation(field, "choose where the call goes")
        return
    if dest.type == "directory":
        return  # the organization's own directory; nothing to point at
    if dest.type == "announcement":
        if dest.announcement_id is None:
            raise validation(field, "choose the announcement")
        if exclude_announcement is not None and dest.announcement_id == exclude_announcement:
            raise validation(field, "an announcement cannot continue to itself")
        ann = db.get(Announcement, dest.announcement_id)
        if ann is None or ann.organization_id != organization_id:
            raise validation(field, "announcement not found in this organization")
        if not ann.is_enabled:
            raise validation(field, f"the announcement {ann.name} is disabled")
        return
    if dest.type == "fax":
        if dest.fax_inbox_id is None:
            raise validation(field, "choose the fax inbox")
        inbox = db.get(FaxInbox, dest.fax_inbox_id)
        if inbox is None or inbox.organization_id != organization_id:
            raise validation(field, "fax inbox not found in this organization")
        if not inbox.is_enabled:
            raise validation(field, f"the fax inbox {inbox.name} is disabled")
        return
    if dest.type == "call_flow":
        if dest.call_flow_id is None:
            raise validation(field, "choose the call flow")
        if exclude_call_flow is not None and dest.call_flow_id == exclude_call_flow:
            raise validation(field, "a call flow cannot point at itself")
        flow = db.get(CallFlow, dest.call_flow_id)
        if flow is None or flow.organization_id != organization_id:
            raise validation(field, "call flow not found in this organization")
        if not flow.is_enabled:
            raise validation(field, f"the call flow {flow.name} is disabled")
        return
    if dest.type == "conference":
        if dest.conference_id is None:
            raise validation(field, "choose the conference room")
        room = db.get(ConferenceRoom, dest.conference_id)
        if room is None or room.organization_id != organization_id:
            raise validation(field, "conference room not found in this organization")
        if not room.is_enabled:
            raise validation(field, f"the conference room {room.name} is disabled")
        return
    if dest.type == "ivr":
        if dest.ivr_id is None:
            raise validation(field, "choose the IVR menu")
        if exclude_ivr is not None and dest.ivr_id == exclude_ivr:
            raise validation(field, "a menu cannot point at itself")
        menu = db.get(IvrMenu, dest.ivr_id)
        if menu is None or menu.organization_id != organization_id:
            raise validation(field, "IVR menu not found in this organization")
        if not menu.is_enabled:
            raise validation(field, f"the menu {menu.name} is disabled")
        return
    if dest.type == "voicemail_box":
        if dest.voicemail_box_id is None:
            raise validation(field, "choose the shared inbox")
        shared = db.get(VoicemailBox, dest.voicemail_box_id)
        if shared is None or shared.organization_id != organization_id or shared.extension_id:
            raise validation(field, "shared inbox not found in this organization")
        if not shared.is_enabled:
            raise validation(field, f"the inbox {shared.name} is disabled")
        return
    if dest.type == "ring_group":
        if dest.ring_group_id is None:
            raise validation(field, "choose the ring group")
        if exclude_ring_group is not None and dest.ring_group_id == exclude_ring_group:
            raise validation(field, "a ring group cannot fail over to itself")
        group = db.get(RingGroup, dest.ring_group_id)
        if group is None or group.organization_id != organization_id:
            raise validation(field, "ring group not found in this organization")
        if not group.is_enabled:
            raise validation(field, f"the ring group {group.name} is disabled")
        return
    if dest.type == "queue":
        if dest.queue_id is None:
            raise validation(field, "choose the queue")
        if exclude_queue is not None and dest.queue_id == exclude_queue:
            raise validation(field, "a queue cannot fail over to itself")
        queue = db.get(CallQueue, dest.queue_id)
        if queue is None or queue.organization_id != organization_id:
            raise validation(field, "queue not found in this organization")
        if not queue.is_enabled:
            raise validation(field, f"the queue {queue.name} is disabled")
        return
    if dest.extension_id is None:
        raise validation(field, "choose the extension")
    ext = db.get(Extension, dest.extension_id)
    if ext is None or ext.organization_id != organization_id:
        raise validation(field, "extension not found in this organization")
    if dest.type == "voicemail":
        box = db.scalar(select(VoicemailBox).where(VoicemailBox.extension_id == ext.id))
        if box is None:
            raise validation(field, f"extension {ext.number} has no voicemail box")
        if not box.is_enabled:
            raise validation(field, f"the voicemail box of {ext.number} is disabled")


class Resolver:
    """Loads the targets of many destinations at once and labels them."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.extensions: dict[uuid.UUID, Extension] = {}
        self.menus: dict[uuid.UUID, IvrMenu] = {}
        self.boxes: dict[uuid.UUID, VoicemailBox] = {}
        self.ring_groups: dict[uuid.UUID, RingGroup] = {}
        self.queues: dict[uuid.UUID, CallQueue] = {}
        self.shared: dict[uuid.UUID, VoicemailBox] = {}
        self.announcements: dict[uuid.UUID, Announcement] = {}
        self.conferences: dict[uuid.UUID, ConferenceRoom] = {}
        self.call_flows: dict[uuid.UUID, CallFlow] = {}
        self.fax_inboxes: dict[uuid.UUID, FaxInbox] = {}
        self._loaded: set[uuid.UUID] = set()

    def load(self, refs: list[Ref]) -> None:
        full = refs
        ext_ids = {r[1] for r in full if r[1] and r[0] in ("extension", "voicemail")}
        ivr_ids = {r[2] for r in full if r[2] and r[0] == "ivr"}
        rg_ids = {r[3] for r in full if r[3] and r[0] == "ring_group"}
        q_ids = {r[4] for r in full if r[4] and r[0] == "queue"}
        box_ids = {r[5] for r in full if r[5] and r[0] == "voicemail_box"}
        ann_ids = {r[6] for r in full if r[6] and r[0] == "announcement"}
        conf_ids = {r[7] for r in full if r[7] and r[0] == "conference"}
        flow_ids = {r[8] for r in full if r[8] and r[0] == "call_flow"}
        fax_ids = {r[9] for r in full if len(r) > 9 and r[9] and r[0] == "fax"}
        ext_ids -= self._loaded
        ivr_ids -= self._loaded
        rg_ids -= self._loaded
        q_ids -= self._loaded
        box_ids -= self._loaded
        ann_ids -= self._loaded
        conf_ids -= self._loaded
        flow_ids -= self._loaded
        fax_ids -= self._loaded
        if fax_ids:
            for i in self.db.scalars(select(FaxInbox).where(FaxInbox.id.in_(fax_ids))):
                self.fax_inboxes[i.id] = i
        if flow_ids:
            for f in self.db.scalars(select(CallFlow).where(CallFlow.id.in_(flow_ids))):
                self.call_flows[f.id] = f
        if ann_ids:
            for a in self.db.scalars(select(Announcement).where(Announcement.id.in_(ann_ids))):
                self.announcements[a.id] = a
        if conf_ids:
            for c in self.db.scalars(select(ConferenceRoom).where(ConferenceRoom.id.in_(conf_ids))):
                self.conferences[c.id] = c
        if box_ids:
            for b in self.db.scalars(select(VoicemailBox).where(VoicemailBox.id.in_(box_ids))):
                self.shared[b.id] = b
        if ext_ids:
            for e in self.db.scalars(select(Extension).where(Extension.id.in_(ext_ids))):
                self.extensions[e.id] = e
            for b in self.db.scalars(
                select(VoicemailBox).where(VoicemailBox.extension_id.in_(ext_ids))
            ):
                if b.extension_id is not None:
                    self.boxes[b.extension_id] = b
        if ivr_ids:
            for m in self.db.scalars(select(IvrMenu).where(IvrMenu.id.in_(ivr_ids))):
                self.menus[m.id] = m
        if rg_ids:
            for g in self.db.scalars(select(RingGroup).where(RingGroup.id.in_(rg_ids))):
                self.ring_groups[g.id] = g
        if q_ids:
            for q in self.db.scalars(select(CallQueue).where(CallQueue.id.in_(q_ids))):
                self.queues[q.id] = q
        self._loaded |= (
            ext_ids | ivr_ids | rg_ids | q_ids | box_ids | ann_ids | conf_ids | flow_ids | fax_ids
        )

    def out(
        self,
        kind: str | None,
        extension_id: Any,
        ivr_id: Any,
        ring_group_id: Any = None,
        queue_id: Any = None,
        voicemail_box_id: Any = None,
        announcement_id: Any = None,
        conference_id: Any = None,
        call_flow_id: Any = None,
        fax_inbox_id: Any = None,
    ) -> DestinationOut:
        kind = kind or "extension"
        if kind == "fax":
            inbox = self.fax_inboxes.get(fax_inbox_id) if fax_inbox_id else None
            ok = inbox is not None and inbox.is_enabled
            return DestinationOut(
                type="fax",
                extension_id=None,
                ivr_id=None,
                fax_inbox_id=fax_inbox_id,
                label=(
                    f"Fax to email: {inbox.name}" + ("" if inbox.is_enabled else " (disabled)")
                    if inbox
                    else None
                ),
                missing=not ok,
            )
        if kind == "call_flow":
            flow = self.call_flows.get(call_flow_id) if call_flow_id else None
            ok = flow is not None and flow.is_enabled
            return DestinationOut(
                type="call_flow",
                extension_id=None,
                ivr_id=None,
                call_flow_id=call_flow_id,
                label=(
                    f"Call flow: {flow.name}" + ("" if flow.is_enabled else " (disabled)")
                    if flow
                    else None
                ),
                missing=not ok,
            )
        if kind == "directory":
            return DestinationOut(
                type="directory",
                extension_id=None,
                ivr_id=None,
                label="Dial-by-name directory",
                missing=False,
            )
        if kind == "announcement":
            ann = self.announcements.get(announcement_id) if announcement_id else None
            ok = ann is not None and ann.is_enabled
            return DestinationOut(
                type="announcement",
                extension_id=None,
                ivr_id=None,
                announcement_id=announcement_id,
                label=(
                    f"Announcement: {ann.name}" + ("" if ann.is_enabled else " (disabled)")
                    if ann
                    else None
                ),
                missing=not ok,
            )
        if kind == "conference":
            room = self.conferences.get(conference_id) if conference_id else None
            ok = room is not None and room.is_enabled
            return DestinationOut(
                type="conference",
                extension_id=None,
                ivr_id=None,
                conference_id=conference_id,
                label=(
                    f"Conference: {room.name} ({room.number})"
                    + ("" if room.is_enabled else " (disabled)")
                    if room
                    else None
                ),
                missing=not ok,
            )
        if kind == "voicemail_box":
            shared = self.shared.get(voicemail_box_id) if voicemail_box_id else None
            ok = shared is not None and shared.is_enabled
            return DestinationOut(
                type="voicemail_box",
                extension_id=None,
                ivr_id=None,
                voicemail_box_id=voicemail_box_id,
                label=(
                    f"Shared inbox: {shared.name} ({shared.number})"
                    + ("" if shared.is_enabled else " (disabled)")
                    if shared
                    else None
                ),
                missing=not ok,
            )
        if kind == "hangup":
            return DestinationOut(
                type="hangup", extension_id=None, ivr_id=None, label="Hang up", missing=False
            )
        if kind == "ivr":
            menu = self.menus.get(ivr_id) if ivr_id else None
            ok = menu is not None and menu.is_enabled
            return DestinationOut(
                type="ivr",
                extension_id=None,
                ivr_id=ivr_id,
                label=(
                    f"Menu: {menu.name}" + ("" if menu.is_enabled else " (disabled)")
                    if menu
                    else None
                ),
                missing=not ok,
            )
        if kind == "ring_group":
            group = self.ring_groups.get(ring_group_id) if ring_group_id else None
            ok = group is not None and group.is_enabled
            return DestinationOut(
                type="ring_group",
                extension_id=None,
                ivr_id=None,
                ring_group_id=ring_group_id,
                label=(
                    f"Ring group: {group.name} ({group.number})"
                    + ("" if group.is_enabled else " (disabled)")
                    if group
                    else None
                ),
                missing=not ok,
            )
        if kind == "queue":
            queue = self.queues.get(queue_id) if queue_id else None
            ok = queue is not None and queue.is_enabled
            return DestinationOut(
                type="queue",
                extension_id=None,
                ivr_id=None,
                queue_id=queue_id,
                label=(
                    f"Queue: {queue.name} ({queue.number})"
                    + ("" if queue.is_enabled else " (disabled)")
                    if queue
                    else None
                ),
                missing=not ok,
            )
        ext = self.extensions.get(extension_id) if extension_id else None
        if ext is None:
            return DestinationOut(
                type=kind, extension_id=extension_id, ivr_id=None, label=None, missing=True
            )
        if kind == "voicemail":
            box = self.boxes.get(ext.id)
            ok = box is not None and box.is_enabled
            label = f"Voicemail of {ext.number} ({ext.display_name})"
            if box is None:
                label += " (no box)"
            elif not box.is_enabled:
                label += " (box disabled)"
            return DestinationOut(
                type="voicemail", extension_id=ext.id, ivr_id=None, label=label, missing=not ok
            )
        return DestinationOut(
            type="extension",
            extension_id=ext.id,
            ivr_id=None,
            label=f"{ext.number} — {ext.display_name}",
            missing=False,
        )

    def out_ref(self, ref: Ref) -> DestinationOut:
        return self.out(*ref)


# ------------------------------------------------------------- references


# Every place a destination is stored: (model, column prefix, label builder).
def _holders() -> list[tuple[Any, str, str]]:
    from veyra.core.models import (
        Announcement,
        CallFlow,
        CallQueue,
        InboundRoute,
        IvrEntry,
        IvrMenu,
        RingGroup,
    )

    return [
        (InboundRoute, "destination", "inbound route"),
        (InboundRoute, "after_hours", "inbound route"),
        (IvrMenu, "timeout", "menu"),
        (IvrMenu, "invalid", "menu"),
        (IvrEntry, "destination", "menu"),
        (RingGroup, "failover", "ring group"),
        (CallQueue, "failover", "queue"),
        (Announcement, "destination", "announcement"),
        (CallFlow, "normal", "call flow"),
        (CallFlow, "override", "call flow"),
    ]


def count_uses(db: Session, kind: str, ids: set[uuid.UUID]) -> dict[Any, int]:
    """How many stored destinations of ``kind`` point at each id (voicemail
    counts by extension id)."""
    from sqlalchemy import func

    counts: dict[Any, int] = {}
    if not ids:
        return counts
    column = TARGET_FIELDS[kind]
    for model, prefix, _ in _holders():
        col_type = getattr(model, f"{prefix}_type")
        col_id = getattr(model, f"{prefix}_{column}", None)
        if col_id is None:
            continue
        for target, n in db.execute(
            select(col_id, func.count()).where(col_type == kind, col_id.in_(ids)).group_by(col_id)
        ):
            counts[target] = counts.get(target, 0) + n
    return counts


def describe_uses(
    db: Session, kind: str, target: uuid.UUID, *, exclude_self: Any = None
) -> list[str]:
    """Human labels of everything pointing at ``target`` ("inbound route
    5551234", "menu Main menu", "ring group Sales"), without duplicates;
    ``exclude_self`` leaves out references from the object itself."""
    from veyra.core.models import IvrEntry, IvrMenu

    column = TARGET_FIELDS[kind]
    found: list[str] = []
    for model, prefix, label in _holders():
        col_type = getattr(model, f"{prefix}_type")
        col_id = getattr(model, f"{prefix}_{column}", None)
        if col_id is None:
            continue
        if model is IvrEntry:
            stmt = select(IvrMenu.name).where(
                IvrMenu.id.in_(select(IvrEntry.menu_id).where(col_type == kind, col_id == target))
            )
            if exclude_self is not None:
                stmt = stmt.where(IvrMenu.id != exclude_self)
            names = db.scalars(stmt.order_by(IvrMenu.name)).all()
        else:
            name_col = model.did if hasattr(model, "did") else model.name
            stmt = select(name_col).where(col_type == kind, col_id == target)
            if exclude_self is not None:
                stmt = stmt.where(model.id != exclude_self)
            names = db.scalars(stmt.order_by(name_col)).all()
        for n in names:
            what = f"{label} {n}"
            if what not in found:
                found.append(what)
    return found


def in_use_error(title: str, code: str, what: list[str]) -> ProblemError:
    return ProblemError(
        409,
        title,
        f"These point at it: {', '.join(what)}.",
        code=code,
        errors=[{"field": "references", "message": w} for w in what],
    )
