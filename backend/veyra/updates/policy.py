# SPDX-License-Identifier: AGPL-3.0-or-later
"""Update policy model and validation rules."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Component(StrEnum):
    VEYRA_CORE = "veyra_core"
    MODULES = "modules"
    PROVISIONING_TEMPLATES = "provisioning_templates"
    TELEPHONY_ENGINE = "telephony_engine"
    OPERATING_SYSTEM = "operating_system"


class Mode(StrEnum):
    MANUAL = "manual"  # A: never checks automatically; administrator checks and installs
    NOTIFY = "notify"  # B: checks on a schedule and notifies
    DOWNLOAD_APPROVE = "download_approve"  # C: downloads automatically, installs on approval
    AUTO_INSTALL_WINDOW = "auto_install_window"  # D: installs approved categories in a window


class Channel(StrEnum):
    STABLE = "stable"
    BETA = "beta"
    DEVELOPMENT = "development"


# Channels visible to a policy subscribed to a given channel.
CHANNEL_VISIBILITY: dict[Channel, set[Channel]] = {
    Channel.STABLE: {Channel.STABLE},
    Channel.BETA: {Channel.STABLE, Channel.BETA},
    Channel.DEVELOPMENT: {Channel.STABLE, Channel.BETA, Channel.DEVELOPMENT},
}

# Every mode works for Veyra itself (docs/SOFTWARE_UPDATES.md). Modules
# update from the module catalog and only notify (docs/MODULE_CATALOG.md §4).
AVAILABLE_MODES = set(Mode)
DOWNLOAD_COMPONENTS = {Component.VEYRA_CORE}

COMPONENT_LABELS = {
    Component.VEYRA_CORE: "Veyra application",
    Component.MODULES: "Modules",
    Component.PROVISIONING_TEMPLATES: "Provisioning templates",
    Component.TELEPHONY_ENGINE: "Telephony engine (Asterisk)",
    Component.OPERATING_SYSTEM: "Operating system",
}

Category = Literal["security", "bugfix", "feature"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class MaintenanceWindow(BaseModel):
    days: list[Weekday] = Field(min_length=1)
    start: str = Field(description="Local start time, HH:MM (24-hour)")
    duration_minutes: int = Field(ge=30, le=720)
    timezone: str = "UTC"

    @field_validator("start")
    @classmethod
    def _start(cls, v: str) -> str:
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError("must be HH:MM in 24-hour time")
        return v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError("unknown time zone") from e
        return v


class PolicyUpdate(BaseModel):
    mode: Mode
    channel: Channel = Channel.STABLE
    check_enabled: bool = True
    check_interval_hours: int = Field(24, ge=1, le=24 * 30)
    auto_download: bool = False
    auto_install_categories: list[Category] = Field(default_factory=list)
    require_approval: bool = True
    notify_admins: bool = True
    maintenance_window: MaintenanceWindow | None = None

    @model_validator(mode="after")
    def _rules(self) -> PolicyUpdate:
        if self.mode == Mode.AUTO_INSTALL_WINDOW and self.maintenance_window is None:
            raise ValueError("automatic installation requires a maintenance window")
        if self.mode != Mode.AUTO_INSTALL_WINDOW and self.auto_install_categories:
            raise ValueError("auto_install_categories only apply to auto_install_window mode")
        if self.mode in (Mode.MANUAL,) and self.auto_download:
            raise ValueError("manual mode does not download automatically")
        return self


def availability_problem(component: Component, update: PolicyUpdate) -> str | None:
    """Reason a requested policy cannot be applied in this release, or None."""
    if component not in DOWNLOAD_COMPONENTS and (
        update.mode in (Mode.DOWNLOAD_APPROVE, Mode.AUTO_INSTALL_WINDOW) or update.auto_download
    ):
        return (
            "Only Veyra itself is downloaded and installed automatically; modules are "
            "updated from the module catalog."
        )
    if (
        component in (Component.OPERATING_SYSTEM, Component.TELEPHONY_ENGINE)
        and update.check_enabled
    ):
        return (
            "Operating system and telephony engine updates are applied with the system "
            "package manager; System → Updates lists the upgradable packages."
        )
    return None
