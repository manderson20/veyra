# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conference rules that need someone watching (issue #392): end a room after
a time with nobody talking, and start recording when it reaches a number of
members. ConfBridge has neither, so the API's ARI event listener feeds this
state machine and runs what it returns through the engine adapter's
conference actions. Both actions are idempotent, so several API processes
watching the same engine do no harm.

The room's bridge is the ConfBridge bridge named after the conference;
``TALK_DETECT`` on each member (set by the room's dialplan) raises the
talking events. Recorder and announcer channels (``CBRec/``, ``CBAnn/``) are
not members.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("veyra.conferences")

NOT_MEMBERS = ("CBRec/", "CBAnn/")
EVENTS = frozenset(
    {
        "ChannelEnteredBridge",
        "ChannelLeftBridge",
        "ChannelTalkingStarted",
        "ChannelTalkingFinished",
    }
)


@dataclass(frozen=True)
class Rule:
    record_at: int | None = None
    silence_seconds: int | None = None


@dataclass
class _Room:
    members: set[str] = field(default_factory=set)
    talking: set[str] = field(default_factory=set)
    quiet_since: float | None = None
    recording_started: bool = False
    ended: bool = False


Action = tuple[str, str]  # (conference name, "record_start" | "end")


class ConferenceWatch:
    def __init__(self) -> None:
        self.rules: dict[str, Rule] = {}
        self.rooms: dict[str, _Room] = {}
        self.channel_room: dict[str, str] = {}

    def set_rules(self, rules: dict[str, Rule]) -> None:
        self.rules = dict(rules)

    def handle(self, event: dict[str, Any], now: float) -> list[Action]:
        kind = event.get("type")
        channel = event.get("channel") or {}
        cid, cname = str(channel.get("id") or ""), str(channel.get("name") or "")
        if not cid:
            return []
        if kind in ("ChannelEnteredBridge", "ChannelLeftBridge"):
            name = str((event.get("bridge") or {}).get("name") or "")
            if name not in self.rules or cname.startswith(NOT_MEMBERS):
                return []
            if kind == "ChannelEnteredBridge":
                return self._entered(name, cid, now)
            self._left(name, cid, now)
            return []
        room_name = self.channel_room.get(cid)
        room = self.rooms.get(room_name) if room_name else None
        if room is None:
            return []
        if kind == "ChannelTalkingStarted":
            room.talking.add(cid)
            room.quiet_since = None
        elif kind == "ChannelTalkingFinished":
            room.talking.discard(cid)
            if not room.talking:
                room.quiet_since = now
        return []

    def _entered(self, name: str, cid: str, now: float) -> list[Action]:
        room = self.rooms.setdefault(name, _Room())
        room.members.add(cid)
        self.channel_room[cid] = name
        if not room.talking and room.quiet_since is None:
            room.quiet_since = now
        rule = self.rules[name]
        if rule.record_at and len(room.members) >= rule.record_at and not room.recording_started:
            room.recording_started = True
            return [(name, "record_start")]
        return []

    def _left(self, name: str, cid: str, now: float) -> None:
        self.channel_room.pop(cid, None)
        room = self.rooms.get(name)
        if room is None:
            return
        room.members.discard(cid)
        room.talking.discard(cid)
        if not room.members:
            # The conference is over; the next one starts afresh.
            del self.rooms[name]
        elif not room.talking:
            room.quiet_since = room.quiet_since or now

    def tick(self, now: float) -> list[Action]:
        """Rooms quiet for their rule's time: end them once."""
        out: list[Action] = []
        for name, room in self.rooms.items():
            rule = self.rules.get(name)
            if rule is None or not rule.silence_seconds or room.ended or not room.members:
                continue
            if room.talking or room.quiet_since is None:
                continue
            if now - room.quiet_since >= rule.silence_seconds:
                room.ended = True
                out.append((name, "end"))
        return out

    def reset(self) -> None:
        """The event stream was lost: what we knew of the rooms is stale."""
        self.rooms.clear()
        self.channel_room.clear()


def load_rules(db: Any) -> dict[str, Rule]:
    """The watched rooms, by conference name, from the database."""
    from sqlalchemy import or_, select

    from veyra.core import tenancy
    from veyra.core.models import ConferenceRoom

    out: dict[str, Rule] = {}
    rows = db.scalars(
        select(ConferenceRoom).where(
            ConferenceRoom.is_enabled.is_(True),
            or_(
                ConferenceRoom.record_at_members.is_not(None),
                ConferenceRoom.end_on_silence_seconds.is_not(None),
            ),
        )
    )
    for r in rows:
        names = tenancy.names_of(db, r.organization_id)
        out[names.conference(r.slug)] = Rule(
            # A room that records every conference needs no trigger.
            record_at=None if r.record else r.record_at_members,
            silence_seconds=r.end_on_silence_seconds,
        )
    return out
