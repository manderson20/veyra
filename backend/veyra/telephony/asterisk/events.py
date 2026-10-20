# SPDX-License-Identifier: AGPL-3.0-or-later
"""ARI event listener: one WebSocket to Asterisk, normalised into call events.

Subscribes to every event (``subscribeAll=true``) under the application name
``veyra`` without ever putting a channel into Stasis, so the dialplan is not
affected. Channel events for ``PJSIP/<endpoint>-…`` channels become
:class:`CallEvent` objects for the hub (docs/COMPANION.md §4). Reconnects with
backoff when Asterisk is unavailable.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from veyra.core.callevents import CallEvent, CallEventHub
from veyra.telephony.asterisk.ari import AriClient

log = logging.getLogger("veyra.events")

APP_NAME = "veyra"
_BACKOFF = (2, 5, 10, 30)


@dataclass
class _Channel:
    endpoint: str
    direction: str  # "in" (the phone is being called) or "out" (the phone dials)
    remote_number: str | None
    remote_name: str | None
    answered: bool = False
    announced: bool = False  # ringing/dialing already published


def endpoint_of(channel_name: str) -> str | None:
    if not channel_name.startswith("PJSIP/"):
        return None
    rest = channel_name[len("PJSIP/") :]
    name, sep, _ = rest.rpartition("-")
    return name if sep else None


def _now_iso(event: dict[str, Any]) -> str:
    ts = event.get("timestamp")
    if isinstance(ts, str) and ts:
        return ts
    return datetime.now(UTC).isoformat(timespec="seconds")


class AriEventTranslator:
    """Pure state machine from ARI JSON events to call events (testable
    without a socket)."""

    def __init__(self) -> None:
        self.channels: dict[str, _Channel] = {}

    def translate(self, event: dict[str, Any]) -> list[CallEvent]:
        kind = event.get("type")
        ch = event.get("channel") or {}
        channel_id = str(ch.get("id") or "")
        if not channel_id:
            return []
        endpoint = endpoint_of(str(ch.get("name") or ""))
        if kind == "ChannelCreated":
            if endpoint is None:
                return []
            state = str(ch.get("state") or "")
            caller = ch.get("caller") or {}
            connected = ch.get("connected") or {}
            dialplan = ch.get("dialplan") or {}
            # A channel Asterisk creates towards a phone (Dial/originate) starts
            # "Down" with the far end in ``connected``; a call the phone places
            # starts "Ring" with the dialled digits in ``dialplan.exten``.
            if state in ("Ring", "Ringing") and not connected.get("number"):
                # The phone placed this call: it is already "dialing" when the
                # channel appears (a call that fails at once never changes state).
                out_ch = _Channel(endpoint, "out", dialplan.get("exten") or None, None)
                out_ch.announced = True
                self.channels[channel_id] = out_ch
                return [self._event("call.dialing", channel_id, out_ch, _now_iso(event))]
            else:
                self.channels[channel_id] = _Channel(
                    endpoint,
                    "in",
                    connected.get("number") or caller.get("number") or None,
                    connected.get("name") or caller.get("name") or None,
                )
            return []
        known = self.channels.get(channel_id)
        if known is None:
            return []
        at = _now_iso(event)
        if kind == "ChannelCallerId":
            connected = ch.get("connected") or {}
            if connected.get("number"):
                known.remote_number = connected.get("number")
            if connected.get("name"):
                known.remote_name = connected.get("name")
            return []
        if kind == "ChannelStateChange":
            state = str(ch.get("state") or "")
            out: list[CallEvent] = []
            if state in ("Ringing", "Ring") and not known.announced:
                known.announced = True
                if known.direction == "in":
                    connected = ch.get("connected") or {}
                    known.remote_number = connected.get("number") or known.remote_number
                    known.remote_name = connected.get("name") or known.remote_name
                out.append(
                    self._event(
                        "call.ringing" if known.direction == "in" else "call.dialing",
                        channel_id,
                        known,
                        at,
                    )
                )
            elif state == "Up" and not known.answered:
                known.answered = True
                if not known.announced:
                    known.announced = True
                    out.append(
                        self._event(
                            "call.ringing" if known.direction == "in" else "call.dialing",
                            channel_id,
                            known,
                            at,
                        )
                    )
                out.append(self._event("call.answered", channel_id, known, at))
            return out
        if kind == "ChannelDestroyed":
            self.channels.pop(channel_id, None)
            cause = event.get("cause_txt") or (str(event["cause"]) if "cause" in event else None)
            if not known.announced:
                return []
            return [self._event("call.ended", channel_id, known, at, cause=cause)]
        return []

    @staticmethod
    def _event(
        kind: str, channel_id: str, ch: _Channel, at: str, *, cause: str | None = None
    ) -> CallEvent:
        return CallEvent(
            type=kind,  # type: ignore[arg-type]
            channel_id=channel_id,
            endpoint=ch.endpoint,
            direction=ch.direction,  # type: ignore[arg-type]
            remote_number=ch.remote_number,
            remote_name=ch.remote_name,
            at=at,
            answered=ch.answered,
            cause=cause,
        )


LIVE_WEBHOOK_EVENTS = frozenset({"call.ringing", "call.answered"})


EMERGENCY_EVENT = "VeyraEmergency"


def _emergency(event: dict[str, Any]) -> tuple[set[Any], dict[str, Any]] | None:
    """``UserEvent(VeyraEmergency)`` from the emergency route: record the call
    and notify the site (docs/PRODUCTION_HARDENING.md §6); never raises.
    Returns the responders' user ids and the Companion alert (issue #127)."""
    try:
        from veyra.core.config import get_settings
        from veyra.core.db import session_scope
        from veyra.emergency import service
        from veyra.telephony import get_adapter

        settings = get_settings()
        adapter = get_adapter(settings) if settings.telephony_engine != "none" else None
        with session_scope() as db:
            call = service.handle_event(db, settings, adapter, event.get("userevent") or {})
            return service.companion_alert(db, call)
    except Exception:
        log.exception("Could not handle the emergency event")
    return None


def is_emergency_event(event: dict[str, Any]) -> bool:
    return event.get("type") == "ChannelUserevent" and event.get("eventname") == EMERGENCY_EVENT


EXTSTATE_EVENT = "VeyraExtState"


def is_extstate_event(event: dict[str, Any]) -> bool:
    return event.get("type") == "ChannelUserevent" and event.get("eventname") == EXTSTATE_EVENT


def _extstate(event: dict[str, Any]) -> None:
    """``UserEvent(VeyraExtState)`` from a feature code: the phone changed its
    own state (docs/CALL_FEATURES.md §3.2); never raises."""
    try:
        from veyra.core.db import session_scope
        from veyra.telephony import extension_state

        with session_scope() as db:
            extension_state.handle_userevent(db, event.get("userevent") or {})
    except Exception:
        log.exception("Could not handle the extension state event")


PRESENCE_EVENT = "VeyraPresence"


def is_presence_event(event: dict[str, Any]) -> bool:
    return event.get("type") == "ChannelUserevent" and event.get("eventname") == PRESENCE_EVENT


def _presence(event: dict[str, Any]) -> None:
    """``UserEvent(VeyraPresence)`` from ``*37<n>`` (issue #136); never raises."""
    try:
        from veyra.core.db import session_scope
        from veyra.telephony import extension_state

        with session_scope() as db:
            extension_state.handle_presence_userevent(db, event.get("userevent") or {})
    except Exception:
        log.exception("Could not handle the presence event")


SWITCH_EVENT = "VeyraSwitch"


def is_switch_event(event: dict[str, Any]) -> bool:
    return event.get("type") == "ChannelUserevent" and event.get("eventname") == SWITCH_EVENT


def _switch(event: dict[str, Any]) -> None:
    """``UserEvent(VeyraSwitch)`` from a feature code: a phone flipped a call
    flow or a time-condition override (docs/CALL_FEATURES.md §4.5, §4.6)."""
    try:
        from veyra.core.db import session_scope
        from veyra.telephony import switches

        with session_scope() as db:
            switches.handle_userevent(db, event.get("userevent") or {})
    except Exception:
        log.exception("Could not handle the switch event")


PAGE_EVENT = "VeyraPage"


def is_page_event(event: dict[str, Any]) -> bool:
    return event.get("type") == "ChannelUserevent" and event.get("eventname") == PAGE_EVENT


def _page(event: dict[str, Any]) -> None:
    """``UserEvent(VeyraPage)``: a phone dialled a paging zone or a page
    (page log, ``page.sent`` webhook; issue #139); never raises."""
    try:
        from veyra.core.db import session_scope
        from veyra.paging import phone_pages

        with session_scope() as db:
            phone_pages.handle_userevent(db, event.get("userevent") or {})
    except Exception:
        log.exception("Could not handle the page event")


BLACKLIST_EVENT = "VeyraBlacklist"
BLOCKED_EVENT = "VeyraBlocked"


def is_blacklist_event(event: dict[str, Any]) -> bool:
    return event.get("type") == "ChannelUserevent" and event.get("eventname") in (
        BLACKLIST_EVENT,
        BLOCKED_EVENT,
    )


def _blacklist(event: dict[str, Any]) -> None:
    """``UserEvent(VeyraBlacklist)`` (a phone added or removed a number) or
    ``UserEvent(VeyraBlocked)`` (a call was refused) (docs/CALL_FEATURES.md §4.8)."""
    try:
        from veyra.core.db import session_scope
        from veyra.telephony import blacklist

        with session_scope() as db:
            if event.get("eventname") == BLOCKED_EVENT:
                blacklist.handle_blocked_event(db, event.get("userevent") or {})
            else:
                blacklist.handle_blacklist_event(db, event.get("userevent") or {})
    except Exception:
        log.exception("Could not handle the block list event")


AGENT_EVENT = "VeyraAgent"


def is_agent_event(event: dict[str, Any]) -> bool:
    return event.get("type") == "ChannelUserevent" and event.get("eventname") == AGENT_EVENT


def _agent(event: dict[str, Any]) -> None:
    """``UserEvent(VeyraAgent)``: a phone logged in, out, paused or resumed
    (docs/CALL_FEATURES.md §4.9)."""
    try:
        from veyra.core.db import session_scope
        from veyra.telephony import agents

        with session_scope() as db:
            agents.handle_userevent(db, event.get("userevent") or {})
    except Exception:
        log.exception("Could not handle the agent event")


FAX_EVENT = "VeyraFax"


def is_fax_event(event: dict[str, Any]) -> bool:
    return event.get("type") == "ChannelUserevent" and event.get("eventname") == FAX_EVENT


def _fax(event: dict[str, Any]) -> None:
    """``UserEvent(VeyraFax)``: a fax was sent, failed or received
    (docs/USER_PORTAL.md §9)."""
    try:
        from veyra.core.config import get_settings
        from veyra.core.db import session_scope
        from veyra.fax import service as fax_service

        with session_scope() as db:
            fax_service.handle_userevent(db, get_settings(), event.get("userevent") or {})
    except Exception:
        log.exception("Could not handle the fax event")


def _fax_channel(event: dict[str, Any]) -> None:
    """A Local channel ended: when it was a fax job's outbound leg that never
    reached the fax context, the call did not connect."""
    channel = event.get("channel") or {}
    if not str(channel.get("name") or "").startswith("Local/") or not channel.get("id"):
        return
    try:
        from veyra.core.config import get_settings
        from veyra.core.db import session_scope
        from veyra.fax import service as fax_service

        with session_scope() as db:
            fax_service.channel_gone(
                db,
                get_settings(),
                str(channel["id"]),
                cause=event.get("cause"),
                cause_txt=event.get("cause_txt"),
            )
    except Exception:
        log.exception("Could not handle the ended fax channel")


def _webhook(ce: CallEvent) -> None:
    """Queue live call webhooks (docs/INTEGRATIONS.md §3.2); never raises."""
    try:
        from veyra.core.db import session_scope
        from veyra.integrations import sources

        with session_scope() as db:
            sources.call_live(db, ce)
    except Exception:
        log.exception("Could not queue a call webhook")


class AriEventListener:
    def __init__(self, ari: AriClient, hub: CallEventHub) -> None:
        self.ari = ari
        self.hub = hub
        self.translator = AriEventTranslator()
        self._task: asyncio.Task[None] | None = None

    def websocket_url(self) -> str | None:
        password = self.ari.password()
        if password is None or not self.ari.is_loopback:
            return None
        base = self.ari.url.replace("http://", "ws://", 1)
        query = urllib.parse.urlencode(
            {"app": APP_NAME, "subscribeAll": "true", "api_key": f"{self.ari.username}:{password}"}
        )
        return f"{base}/events?{query}"

    def start(self) -> None:
        if self._task is None:
            self.hub.state = "connecting"
            self._task = asyncio.create_task(self.run(), name="ari-events")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.hub.state = "disabled"

    async def run(self) -> None:
        import websockets

        attempt = 0
        while True:
            url = self.websocket_url()
            if url is None:
                self.hub.state = "disabled"
                self.hub.last_error = "ARI credentials are not configured"
                await asyncio.sleep(30)
                continue
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    self.hub.state = "connected"
                    self.hub.last_error = None
                    attempt = 0
                    log.info("ARI event stream connected")
                    async for raw in ws:
                        try:
                            event = json.loads(raw)
                        except ValueError:
                            continue
                        if is_emergency_event(event):
                            alert = await asyncio.to_thread(_emergency, event)
                            if alert is not None and alert[0]:
                                n = self.hub.alert(alert[0], alert[1])
                                log.warning("emergency alert shown in %d Companion sessions", n)
                        elif is_extstate_event(event):
                            await asyncio.to_thread(_extstate, event)
                        elif is_switch_event(event):
                            _switch(event)
                        elif is_presence_event(event):
                            _presence(event)
                        elif is_page_event(event):
                            await asyncio.to_thread(_page, event)
                        elif is_blacklist_event(event):
                            _blacklist(event)
                        elif is_agent_event(event):
                            _agent(event)
                        elif is_fax_event(event):
                            _fax(event)
                        elif event.get("type") == "ChannelDestroyed":
                            _fax_channel(event)
                        for ce in self.translator.translate(event):
                            self.hub.publish(ce)
                            if ce.type in LIVE_WEBHOOK_EVENTS:
                                await asyncio.to_thread(_webhook, ce)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.hub.last_error = str(e)[:200]
                log.warning("ARI event stream lost (%s); reconnecting", e)
            self.hub.state = "reconnecting"
            self.translator.channels.clear()
            await asyncio.sleep(_BACKOFF[min(attempt, len(_BACKOFF) - 1)])
            attempt += 1
