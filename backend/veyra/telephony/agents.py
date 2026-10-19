# SPDX-License-Identifier: AGPL-3.0-or-later
"""Queue dynamic agents (docs/CALL_FEATURES.md §4.9). A dynamic member of a
queue is in it only while logged in, and rings only while not paused. The
rows (``queue_members.logged_in`` / ``paused``) are the truth: the API and
the interface write the row and the engine live, phones log in and pause
with feature codes (``UserEvent(VeyraAgent)``), and the worker's sync makes
the engine's member list match the rows every pass (and after a restart).
The engine also keeps a per-extension copy for the BLF lamps
(``veyra/agent/<org>/<ext>`` = ``1`` while logged into any queue,
``veyra/agent/<org>/<ext>/paused`` = ``1``; ``Custom:veyra-agent-<org>-<ext>``
and ``Custom:veyra-agentpause-<org>-<ext>``)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.events import Event, bus
from veyra.core.models import CallQueue, Extension, Organization, QueueMember
from veyra.core.models.base import utcnow
from veyra.telephony.adapter import Capability, EngineUnavailable, NotSupported
from veyra.telephony.asterisk import names as engine_names

log = logging.getLogger("veyra.agents")

FAMILY = "veyra/agent"
AGENT_EVENT = "VeyraAgent"


def supports(adapter: Any) -> bool:
    try:
        return adapter is not None and Capability.EXTENSION_STATE in adapter.capabilities()
    except Exception:
        return False


def queue_name(org_slug: str, queue_slug: str) -> str:
    return engine_names.for_org(org_slug).queue(queue_slug)


def _members_of(db: Session, extension: Extension) -> list[tuple[QueueMember, CallQueue]]:
    rows = db.execute(
        select(QueueMember, CallQueue)
        .join(CallQueue, CallQueue.id == QueueMember.queue_id)
        .where(QueueMember.extension_id == extension.id, QueueMember.dynamic.is_(True))
        .order_by(CallQueue.number)
    ).all()
    return [(m, q) for m, q in rows]


def _write_member(
    adapter: Any, org_slug: str, queue: CallQueue, ext: Extension, member: QueueMember
) -> None:
    if not supports(adapter):
        return
    try:
        adapter.set_queue_member(
            queue_name(org_slug, queue.slug),
            f"PJSIP/{ext.endpoint_name}",
            present=bool(member.logged_in),
            paused=bool(member.paused),
            penalty=int(member.penalty or 0),
            name=ext.display_name,
        )
        # The per-queue mark the phone's *45<queue> toggle reads
        # (generator._agent_codes), so a login from the page or the API and
        # one from the phone agree on the state.
        adapter.store_put(
            FAMILY, f"{org_slug}/{ext.number}/{queue.slug}", "1" if member.logged_in else None
        )
    except (EngineUnavailable, NotSupported, ValueError) as e:
        log.warning("Agent %s in queue %s not written to the engine: %s", ext.number, queue.slug, e)


def _write_lamps(adapter: Any, org_slug: str, ext: Extension, members: list[QueueMember]) -> None:
    """The per-extension copy behind the BLF lamps."""
    if not supports(adapter):
        return
    logged = any(m.logged_in for m in members)
    paused = logged and all(m.paused for m in members if m.logged_in)
    try:
        adapter.set_switch("agent", org_slug, ext.number, "1" if logged else None)
        adapter.set_switch("agentpause", org_slug, ext.number, "1" if paused else None)
        # The marks the phone's *45 and *46 toggles read (generator._agent_codes).
        adapter.store_put(FAMILY, f"{org_slug}/{ext.number}", "1" if logged else None)
        adapter.store_put(FAMILY, f"{org_slug}/{ext.number}/paused", "1" if paused else None)
    except (EngineUnavailable, NotSupported, ValueError) as e:
        log.warning("Agent lamps of %s not written to the engine: %s", ext.number, e)


def set_state(
    db: Session,
    queue: CallQueue,
    extension: Extension,
    *,
    logged_in: bool | None = None,
    paused: bool | None = None,
    by: str,
    adapter: Any = None,
) -> QueueMember | None:
    """Change an agent's state in one queue; returns the row when something
    changed, None otherwise (or when the extension is not a dynamic member)."""
    member = db.scalar(
        select(QueueMember).where(
            QueueMember.queue_id == queue.id, QueueMember.extension_id == extension.id
        )
    )
    if member is None or not member.dynamic:
        return None
    changed = False
    if logged_in is not None and bool(member.logged_in) != logged_in:
        member.logged_in = logged_in
        changed = True
        if not logged_in and member.paused:
            member.paused = False
    if paused is not None and bool(member.paused) != paused and member.logged_in:
        member.paused = paused
        changed = True
    if not changed:
        return None
    member.state_by = by
    member.state_at = utcnow()
    db.flush()
    org = db.get(Organization, queue.organization_id)
    slug = org.slug if org else ""
    _write_member(adapter, slug, queue, extension, member)
    _write_lamps(adapter, slug, extension, [m for m, _ in _members_of(db, extension)])
    bus.publish(
        Event(
            "queue.agent_state",
            {
                "queue_id": str(queue.id),
                "extension_id": str(extension.id),
                "organization_id": str(queue.organization_id),
                "logged_in": bool(member.logged_in),
                "paused": bool(member.paused),
                "by": by,
            },
        )
    )
    return member


def set_all(
    db: Session,
    extension: Extension,
    *,
    logged_in: bool | None = None,
    paused: bool | None = None,
    by: str,
    adapter: Any = None,
) -> int:
    """The same across every queue the extension is a dynamic member of."""
    n = 0
    for _, queue in _members_of(db, extension):
        if set_state(
            db, queue, extension, logged_in=logged_in, paused=paused, by=by, adapter=adapter
        ):
            n += 1
    return n


# ----------------------------------------------------------------- events


def handle_userevent(db: Session, userevent: dict[str, Any]) -> int:
    """A phone logged in or out or paused (the dialplan already told the queue
    engine); only the rows and the event remain. Fields: Org, Extension,
    Action (login | logout | pause | unpause), Queue (slug, optional)."""
    f = {
        k.lower(): str(userevent.get(k) or userevent.get(k.lower()) or "").strip()
        for k in ("Org", "Extension", "Action", "Queue")
    }
    org = db.scalar(select(Organization).where(Organization.slug == f["org"]))
    if org is None or not f["extension"]:
        return 0
    ext = db.scalar(
        select(Extension).where(
            Extension.organization_id == org.id, Extension.number == f["extension"]
        )
    )
    if ext is None:
        return 0
    kwargs: dict[str, Any] = {}
    if f["action"] in ("login", "logout"):
        kwargs["logged_in"] = f["action"] == "login"
    elif f["action"] in ("pause", "unpause"):
        kwargs["paused"] = f["action"] == "pause"
    else:
        return 0
    if f["queue"]:
        queue = db.scalar(
            select(CallQueue).where(
                CallQueue.organization_id == org.id, CallQueue.slug == f["queue"]
            )
        )
        if queue is None:
            return 0
        return 1 if set_state(db, queue, ext, by="phone", adapter=None, **kwargs) else 0
    return set_all(db, ext, by="phone", adapter=None, **kwargs)


# ----------------------------------------------------------------- sync


def sync(db: Session, adapter: Any) -> int:
    """Make every queue's dynamic members and the lamps match the rows
    (worker, every pass). Returns how many engine entries were corrected."""
    if not supports(adapter):
        return 0
    slugs = {o.id: o.slug for o in db.scalars(select(Organization))}
    exts = {e.id: e for e in db.scalars(select(Extension).where(Extension.is_enabled.is_(True)))}
    fixed = 0
    rows = db.execute(
        select(QueueMember, CallQueue)
        .join(CallQueue, CallQueue.id == QueueMember.queue_id)
        .where(QueueMember.dynamic.is_(True), CallQueue.is_enabled.is_(True))
    ).all()
    by_queue: dict[Any, list[tuple[QueueMember, CallQueue]]] = {}
    for m, q in rows:
        by_queue.setdefault(q.id, []).append((m, q))
    per_ext: dict[Any, list[QueueMember]] = {}
    for members in by_queue.values():
        queue = members[0][1]
        slug = slugs.get(queue.organization_id, "")
        try:
            have = adapter.queue_members(queue_name(slug, queue.slug))
        except (EngineUnavailable, NotSupported, ValueError):
            continue
        wanted: dict[str, tuple[QueueMember, Extension]] = {}
        for m, _ in members:
            ext = exts.get(m.extension_id)
            if ext is None:
                continue
            per_ext.setdefault(ext.id, []).append(m)
            if m.logged_in:
                wanted[f"PJSIP/{ext.endpoint_name}"] = (m, ext)
        for iface, (m, ext) in wanted.items():
            state = have.get(iface)
            if state is None or bool(state.get("paused")) != bool(m.paused):
                _write_member(adapter, slug, queue, ext, m)
                fixed += 1
        for iface, state in have.items():
            if state.get("dynamic") and iface not in wanted:
                try:
                    adapter.set_queue_member(queue_name(slug, queue.slug), iface, present=False)
                    fixed += 1
                except (EngineUnavailable, NotSupported, ValueError):
                    pass
    for ext_id, ext_members in per_ext.items():
        ext = exts[ext_id]
        org_slug = slugs.get(ext.organization_id, "")
        _write_lamps(adapter, org_slug, ext, ext_members)
    return fixed
