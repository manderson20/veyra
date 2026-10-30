# SPDX-License-Identifier: AGPL-3.0-or-later
"""Telephony engine adapter interface.

Veyra services talk to the telephony engine only through this interface.
Engine-specific behaviour (Asterisk today) lives in its own package. An
adapter reports what it can do through :class:`Capability`; callers must
check capabilities instead of assuming them. See docs/ARCHITECTURE.md
§Telephony adapter, docs/TELEPHONY_ENGINE.md and docs/ENGINE_EVALUATION.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class Capability(StrEnum):
    HEALTH = "health"
    ENDPOINT_STATUS = "endpoint_status"  # SIP registration status
    ACTIVE_CALLS = "active_calls"
    CONFIG_GENERATION = "config_generation"
    CONFIG_RELOAD = "config_reload"
    CLICK_TO_DIAL = "click_to_dial"  # originate a call from an endpoint
    TRUNK_STATUS = "trunk_status"
    CALL_RECORDS = "call_records"
    VOICEMAIL = "voicemail"
    IVR = "ivr"
    RING_GROUPS = "ring_groups"
    QUEUES = "queues"
    PAGING = "paging"
    RECORDING = "recording"
    REGISTRATIONS = "registrations"  # per-contact registration details (addresses)
    EXTENSION_STATE = "extension_state"  # Do Not Disturb and forwards kept in the engine
    TRUNK_REGISTRATIONS = "trunk_registrations"  # outbound registration state per trunk


EngineState = Literal[
    "running", "stopped", "not_installed", "unreachable", "not_configured", "unknown"
]


@dataclass(frozen=True)
class EngineHealth:
    state: EngineState
    engine: str
    version: str | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EngineInfo:
    """Static and runtime facts about the engine process (for the engine page)."""

    version: str | None
    started_at: str | None  # ISO 8601 as reported by the engine
    last_reload_at: str | None
    entity_id: str | None
    modules: dict[str, str] = field(default_factory=dict)  # module -> status text


@dataclass(frozen=True)
class EndpointStatus:
    endpoint: str
    registered: bool
    contacts: list[str] = field(default_factory=list)
    user_agent: str | None = None


@dataclass(frozen=True)
class TrunkRegistration:
    """The engine's outbound registration to a carrier (docs/CALL_FEATURES.md
    §2.1, issue #45): ``status`` is the engine's word (Registered, Rejected,
    Unregistered, …)."""

    section: str  # the trunk's engine name, trunk-<slug>
    server_uri: str | None
    status: str


@dataclass(frozen=True)
class Registration:
    """One registered contact of an endpoint (docs/CALL_FEATURES.md §2.1).

    ``contact_host``/``contact_port`` is the address the phone put in its
    Contact header (its own, often private, address); ``source_host``/
    ``source_port`` is where the REGISTER actually came from (public when
    the phone is behind NAT). ``nat`` is true when they differ.
    """

    endpoint: str
    uri: str
    contact_host: str | None = None
    contact_port: int | None = None
    source_host: str | None = None
    source_port: int | None = None
    transport: str | None = None
    user_agent: str | None = None
    expires_at: str | None = None  # ISO 8601, UTC
    status: str | None = None  # engine wording: Avail, Unavail, NonQual, Unknown
    rtt_ms: float | None = None
    reg_server: str | None = None

    @property
    def nat(self) -> bool:
        return bool(
            self.source_host and self.contact_host and self.source_host != self.contact_host
        )


@dataclass(frozen=True)
class ActiveCall:
    channel_id: str
    caller: str | None
    callee: str | None
    state: str
    duration_seconds: int
    # The engine endpoint the channel belongs to (``PJSIP/<endpoint>-…``), when known.
    endpoint: str | None = None
    # The engine's channel name (``PJSIP/<endpoint>-…``), for recording_states.
    channel_name: str | None = None


@dataclass(frozen=True)
class RecordingState:
    """Whether a channel's call is being recorded right now (issue #351), and
    whether that recording was started from the web, so can be stopped there."""

    recording: bool
    stoppable: bool = False


@dataclass(frozen=True)
class GeneratedFile:
    """A configuration artifact produced from the database (never edited by hand)."""

    path: str  # relative to the engine's Veyra-managed include directory
    content: str
    sensitive: bool = False  # contains credentials; never logged or shown in diffs


class EngineUnavailable(RuntimeError):
    """The engine cannot be reached; callers must show data as unavailable."""


class NotSupported(RuntimeError):
    pass


class TelephonyAdapter(ABC):
    name: str

    @abstractmethod
    def capabilities(self) -> set[Capability]: ...

    @abstractmethod
    def health(self) -> EngineHealth: ...

    def info(self) -> EngineInfo:
        raise NotSupported(f"{self.name}: engine information not available")

    def endpoint_statuses(self) -> list[EndpointStatus]:
        raise NotSupported(f"{self.name}: endpoint status not implemented yet")

    def active_calls(self) -> list[ActiveCall]:
        raise NotSupported(f"{self.name}: active calls not implemented yet")

    def trunk_registrations(self) -> list[TrunkRegistration]:
        """Outbound registrations as the engine reports them (issue #45)."""
        raise NotSupported("trunk registration state is not supported by this engine")

    def set_extension_state(
        self, organization: str, number: str, field: str, value: str | None
    ) -> None:
        """One field of an extension's state (``dnd``, ``cf_always``, ``cf_busy``,
        ``cf_no_answer``, ``fmfm``) in the engine's own store, so the dialplan sees it at
        once (docs/CALL_FEATURES.md §3.2, §3.3); None clears it."""
        raise NotSupported("extension state is not supported by this engine")

    def extension_states(self) -> dict[tuple[str, str], dict[str, str]]:
        """(organization slug, number) -> {field: value}, as the engine has it."""
        raise NotSupported("extension state is not supported by this engine")

    def set_switch(self, kind: str, organization: str, key: str, value: str | None) -> None:
        """One engine switch (docs/CALL_FEATURES.md §4.5, §4.6): the store entry
        the dialplan reads and the custom device state behind its BLF lamp;
        None clears it. Capability.EXTENSION_STATE."""
        raise NotSupported("engine switches are not supported by this engine")

    def set_presence_lamp(self, organization: str, number: str, state: str) -> None:
        """The custom device state behind an extension's presence key
        (issue #132): ``INUSE``, ``ONHOLD``, ``UNAVAILABLE`` or ``NOT_INUSE``."""
        raise NotSupported("presence lamps are not supported by this engine")

    def switches(self) -> dict[tuple[str, str, str], str]:
        """(kind, organization slug, key) -> value for every switch that is on."""
        raise NotSupported("engine switches are not supported by this engine")

    def store_entries(self, family: str) -> dict[str, str]:
        """Every key -> value below a family of the engine's store
        (``veyra/blacklist/<org>`` and the like; Capability.EXTENSION_STATE)."""
        raise NotSupported("the engine store is not supported by this engine")

    def store_put(self, family: str, key: str, value: str | None) -> None:
        """Write (None: delete) one entry of the engine's store."""
        raise NotSupported("the engine store is not supported by this engine")

    def queue_members(self, queue: str) -> dict[str, dict[str, Any]]:
        """Interface -> {dynamic, paused, penalty} of a queue's current members
        (docs/CALL_FEATURES.md §4.9; Capability.QUEUES and the CLI)."""
        raise NotSupported("queue members are not supported by this engine")

    def set_queue_member(
        self,
        queue: str,
        interface: str,
        *,
        present: bool,
        paused: bool = False,
        penalty: int = 0,
        name: str = "",
    ) -> None:
        """Log a dynamic agent in or out of a queue and set its pause state live."""
        raise NotSupported("queue members are not supported by this engine")

    def registrations(self) -> list[Registration]:
        """Every registered contact with its addresses (Capability.REGISTRATIONS)."""
        raise NotSupported(f"{self.name}: registration details not implemented")

    def originate(
        self, endpoint: str, number: str, *, caller_id: str, context: str, timeout: int = 30
    ) -> str:
        """Ring ``endpoint`` and, when it answers, send the call to ``number``
        in ``context`` (click-to-dial). Returns the engine's channel id."""
        raise NotSupported(f"{self.name}: click-to-dial not implemented")

    def hangup(self, channel_id: str) -> None:
        """End one channel of a call in progress (Capability.ACTIVE_CALLS)."""
        raise NotSupported(f"{self.name}: hanging up calls not implemented")

    def originate_channel(
        self,
        endpoint: str,
        extension: str,
        *,
        context: str,
        caller_id: str,
        timeout: int = 60,
        variables: dict[str, str] | None = None,
    ) -> str:
        """Start a channel on ``endpoint`` (a full ``tech/resource``, for example
        ``Local/5551234@veyra-outbound/n``) with channel ``variables``; when it
        answers it runs the dialplan at ``extension@context`` (fax sending,
        docs/USER_PORTAL.md §9). Returns the engine's channel id."""
        raise NotSupported(f"{self.name}: originating channels not implemented")

    def record_call(self, channel_id: str, start: bool) -> None:
        """Start or stop recording a call in progress from the web (issue
        #135); the file is filed like the phone's on-demand recording."""
        raise NotSupported(f"{self.name}: recording from the web not implemented")

    def recording_states(self, calls: list[ActiveCall]) -> dict[str, RecordingState]:
        """By channel id, for these calls; a channel left out is not known to
        be recorded. Separate from active_calls, which many pages use: this
        asks the engine about every channel."""
        return {}

    def monitor_call(
        self,
        channel_id: str,
        supervisor_endpoint: str,
        mode: str,
        *,
        context: str,
        caller_id: str,
        beep: bool = False,
    ) -> str:
        """Ring a supervisor's phone and, when answered, listen to, whisper
        on or join (``listen``/``whisper``/``barge``) the call on
        ``channel_id`` (issue #167); ``beep``: both sides of the call hear a
        beep first. Returns the supervisor's channel id."""
        raise NotSupported(f"{self.name}: supervisor monitoring not implemented")

    def conference_live(self, room: str) -> dict[str, Any] | None:
        """A running conference (issue #96): ``{locked, participants: [{channel,
        caller_id, admin, muted, marked}]}``, or None when nobody is in it."""
        raise NotSupported(f"{self.name}: live conference control not implemented")

    def conference_action(self, room: str, action: str, channel: str | None = None) -> None:
        """``mute``/``unmute``/``kick`` one channel, ``mute_all``/``unmute_all``
        (the participants who are not administrators), ``lock``/``unlock``,
        ``end`` (everybody leaves)."""
        raise NotSupported(f"{self.name}: live conference control not implemented")

    # --- configuration -------------------------------------------------------

    def managed_files(self) -> list[str]:
        """Every file name the adapter may generate. The deployer removes a
        managed file that a new revision no longer produces, and never touches
        anything else in the configuration directory."""
        return []

    def generate_config(self, snapshot: dict[str, Any]) -> list[GeneratedFile]:
        raise NotSupported(f"{self.name}: configuration generation not implemented yet")

    def validate_config(self, files: list[GeneratedFile]) -> list[str]:
        """Static checks on generated files. Returns problems (empty = valid)."""
        return []

    def reload_scopes(self, changed_paths: list[str]) -> list[str]:
        """Which reloads a set of changed files needs, in order."""
        return []

    def reload(self, scope: str) -> None:
        raise NotSupported(f"{self.name}: reload not implemented yet")

    def verify_loaded(self, scopes: list[str]) -> list[str]:
        """After reloading, confirm the engine took the configuration. Returns problems."""
        return []


class NullAdapter(TelephonyAdapter):
    """Used when no engine is configured (e.g. development without Asterisk)."""

    name = "none"

    def capabilities(self) -> set[Capability]:
        return {Capability.HEALTH}

    def health(self) -> EngineHealth:
        return EngineHealth("not_configured", "none", message="No telephony engine is configured.")
