# SPDX-License-Identifier: AGPL-3.0-or-later
"""Firewall settings (docs/FIREWALL_TRUST.md §3-§4): one JSON document in
``system_settings`` under ``firewall``, validated by :class:`FirewallSettings`.
The ``veyra-firewall`` service writes its own state under ``firewall.status``."""

from __future__ import annotations

import ipaddress
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from veyra.core.models import SystemSetting

FIREWALL_SETTINGS_KEY = "firewall"
FIREWALL_STATUS_KEY = "firewall.status"

# Services a rule or the policy can name; ports come from the deployed
# configuration (veyra.firewall.ports).
SERVICES = ("sip", "rtp", "web", "ssh")
Policy = Literal["anywhere", "allow_list_only"]

EVENT_KINDS = (
    "sip_unknown_account",
    "sip_bad_password",
    "sip_acl",
    "sip_bad_request",
    "login_failed",
    "mfa_failed",
    "reset_invalid",
    "prov_unauthorized",
    "rate_limited",
)
DEFAULT_WEIGHTS: dict[str, int] = {
    "sip_unknown_account": 2,
    "sip_bad_password": 1,
    "sip_acl": 1,
    "sip_bad_request": 1,
    "login_failed": 1,
    "mfa_failed": 1,
    "reset_invalid": 1,
    "prov_unauthorized": 1,
    "rate_limited": 1,
}

# How long a policy-mode change waits for the browser's confirmation.
CONFIRM_SECONDS = 60


def _open_policy() -> dict[str, Policy]:
    return dict.fromkeys(SERVICES, "anywhere")


def check_cidr(value: str) -> str:
    """Normalise an address or network; raises ValueError."""
    return str(ipaddress.ip_network(value.strip(), strict=False))


class PendingConfirm(BaseModel):
    """A policy change applied but not yet confirmed (§3.4)."""

    previous_policy: dict[str, Policy]
    deadline: datetime
    by: str


class FirewallSettings(BaseModel):
    enabled: bool = False
    policy: dict[str, Policy] = Field(default_factory=lambda: _open_policy())
    ban_score: int = Field(10, ge=2, le=1000)
    window_minutes: int = Field(10, ge=1, le=1440)
    ban_minutes: int = Field(60, ge=1, le=10080)
    max_ban_days: int = Field(7, ge=1, le=365)
    weights: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    ssh_ports: list[int] = Field(default_factory=lambda: [22])
    # Networks allowed to fetch the plain-HTTP provisioning bootstrap; empty:
    # the SIP settings' local networks.
    bootstrap_networks: list[str] = Field(default_factory=list)
    pending_confirm: PendingConfirm | None = None

    @field_validator("policy")
    @classmethod
    def _policy(cls, v: dict[str, Policy]) -> dict[str, Policy]:
        unknown = set(v) - set(SERVICES)
        if unknown:
            raise ValueError(f"unknown service {sorted(unknown)[0]!r}")
        out = _open_policy()
        out.update(v)
        return out

    @field_validator("weights")
    @classmethod
    def _weights(cls, v: dict[str, int]) -> dict[str, int]:
        out = dict(DEFAULT_WEIGHTS)
        for kind, weight in v.items():
            if kind not in EVENT_KINDS:
                raise ValueError(f"unknown event kind {kind!r}")
            if not 0 <= weight <= 100:
                raise ValueError("weights must be between 0 and 100")
            out[kind] = weight
        return out

    @field_validator("ssh_ports")
    @classmethod
    def _ports(cls, v: list[int]) -> list[int]:
        if not v or any(not 1 <= p <= 65535 for p in v):
            raise ValueError("list at least one SSH port between 1 and 65535")
        return sorted(set(v))

    @field_validator("bootstrap_networks")
    @classmethod
    def _nets(cls, v: list[str]) -> list[str]:
        return [check_cidr(n) for n in v if n.strip()]

    def restricted(self) -> list[str]:
        return [s for s in SERVICES if self.policy.get(s) == "allow_list_only"]


def load_settings(db: Session) -> FirewallSettings:
    row = db.get(SystemSetting, FIREWALL_SETTINGS_KEY)
    if row is None or not isinstance(row.value, dict):
        return FirewallSettings()
    return FirewallSettings.model_validate(row.value)


def save_settings(db: Session, settings: FirewallSettings, updated_by: Any = None) -> None:
    _put(db, FIREWALL_SETTINGS_KEY, settings.model_dump(mode="json"), updated_by)


def load_status(db: Session) -> dict[str, Any]:
    row = db.get(SystemSetting, FIREWALL_STATUS_KEY)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


def save_status(db: Session, status: dict[str, Any]) -> None:
    _put(db, FIREWALL_STATUS_KEY, status, None)


def _put(db: Session, key: str, value: dict[str, Any], updated_by: Any) -> None:
    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=value, updated_by=updated_by))
    else:
        row.value = value
        row.updated_by = updated_by
    db.flush()
