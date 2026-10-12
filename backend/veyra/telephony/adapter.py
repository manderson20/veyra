# SPDX-License-Identifier: AGPL-3.0-or-later
"""Telephony engine adapter interface.

Veyra services talk to the telephony engine only through this interface.
Engine-specific behaviour (Asterisk today) lives in its own package. An
adapter reports what it can do through :class:`Capability`; callers must
check capabilities instead of assuming them. See docs/ARCHITECTURE.md
§Telephony adapter and docs/ENGINE_EVALUATION.md.
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
    TRUNK_STATUS = "trunk_status"
    CALL_RECORDS = "call_records"
    VOICEMAIL = "voicemail"
    IVR = "ivr"
    RING_GROUPS = "ring_groups"
    QUEUES = "queues"
    PAGING = "paging"
    RECORDING = "recording"


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
class EndpointStatus:
    endpoint: str
    registered: bool
    contacts: list[str] = field(default_factory=list)
    user_agent: str | None = None


@dataclass(frozen=True)
class ActiveCall:
    channel_id: str
    caller: str | None
    callee: str | None
    state: str
    duration_seconds: int


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

    def endpoint_statuses(self) -> list[EndpointStatus]:
        raise NotSupported(f"{self.name}: endpoint status not implemented yet")

    def active_calls(self) -> list[ActiveCall]:
        raise NotSupported(f"{self.name}: active calls not implemented yet")

    def generate_config(self, snapshot: dict[str, Any]) -> list[GeneratedFile]:
        raise NotSupported(f"{self.name}: configuration generation not implemented yet")

    def reload(self, scope: str = "all") -> None:
        raise NotSupported(f"{self.name}: reload not implemented yet")


class NullAdapter(TelephonyAdapter):
    """Used when no engine is configured (e.g. development without Asterisk)."""

    name = "none"

    def capabilities(self) -> set[Capability]:
        return {Capability.HEALTH}

    def health(self) -> EngineHealth:
        return EngineHealth("not_configured", "none", message="No telephony engine is configured.")
