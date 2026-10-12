# SPDX-License-Identifier: AGPL-3.0-or-later
"""Asterisk adapter: health and status over ARI, configuration generation
for the Veyra-managed include directory, targeted module reloads.

ARI runs on 127.0.0.1 only (installer). Reloads use ``PUT
/asterisk/modules/{name}``, which is the same as ``module reload`` on the
console, so no shell command and no CLI socket access is needed.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from veyra.telephony.adapter import (
    ActiveCall,
    Capability,
    EndpointStatus,
    EngineHealth,
    EngineInfo,
    EngineUnavailable,
    GeneratedFile,
    TelephonyAdapter,
)
from veyra.telephony.asterisk import generator
from veyra.telephony.asterisk.ari import AriClient

# Modules whose status the engine page shows and that reloads depend on.
WATCHED_MODULES = (
    "res_pjsip.so",
    "chan_pjsip.so",
    "res_pjsip_outbound_registration.so",
    "pbx_config.so",
    "res_rtp_asterisk.so",
    "res_ari.so",
    "app_voicemail.so",
    "app_queue.so",
)


class AsteriskAdapter(TelephonyAdapter):
    name = "asterisk"

    def __init__(self, ari_url: str, username: str, password_file: Path) -> None:
        self.ari = AriClient(ari_url, username, password_file)

    def capabilities(self) -> set[Capability]:
        return {
            Capability.HEALTH,
            Capability.ENDPOINT_STATUS,
            Capability.ACTIVE_CALLS,
            Capability.CONFIG_GENERATION,
            Capability.CONFIG_RELOAD,
        }

    # --- status -------------------------------------------------------------

    @staticmethod
    def _installed() -> bool:
        return shutil.which("asterisk") is not None or Path("/usr/sbin/asterisk").exists()

    def health(self) -> EngineHealth:
        if not self._installed():
            return EngineHealth("not_installed", self.name, message="Asterisk is not installed.")
        if self.ari.password() is None:
            return EngineHealth(
                "not_configured", self.name, message="ARI credentials are not configured."
            )
        if not self.ari.is_loopback:
            return EngineHealth(
                "not_configured", self.name, message="ARI must be reached over loopback."
            )
        try:
            info = self.ari.info()
        except EngineUnavailable as e:
            return EngineHealth("unreachable", self.name, message=str(e))
        system = info.get("system", {})
        return EngineHealth(
            "running",
            self.name,
            version=system.get("version") or info.get("build", {}).get("version"),
            message="Asterisk is running.",
            details={
                "entity_id": system.get("entity_id"),
                "started_at": info.get("status", {}).get("startup_time"),
                "last_reload_at": info.get("status", {}).get("last_reload_time"),
            },
        )

    def info(self) -> EngineInfo:
        info = self.ari.info()
        modules: dict[str, str] = {}
        for name in WATCHED_MODULES:
            try:
                modules[name] = str(self.ari.module(name).get("status") or "unknown")
            except EngineUnavailable as e:
                modules[name] = "not loaded" if "404" in str(e) else "unknown"
        return EngineInfo(
            version=info.get("system", {}).get("version"),
            started_at=info.get("status", {}).get("startup_time"),
            last_reload_at=info.get("status", {}).get("last_reload_time"),
            entity_id=info.get("system", {}).get("entity_id"),
            modules=modules,
        )

    def endpoint_statuses(self) -> list[EndpointStatus]:
        out = []
        for ep in self.ari.endpoints():
            if ep.get("technology") != "PJSIP":
                continue
            out.append(
                EndpointStatus(
                    endpoint=str(ep.get("resource")),
                    registered=ep.get("state") == "online",
                    contacts=[str(c) for c in ep.get("channel_ids", [])],
                )
            )
        return out

    def active_calls(self) -> list[ActiveCall]:
        out = []
        for ch in self.ari.channels():
            caller = ch.get("caller", {}) or {}
            connected = ch.get("connected", {}) or {}
            out.append(
                ActiveCall(
                    channel_id=str(ch.get("id")),
                    caller=caller.get("number") or caller.get("name"),
                    callee=connected.get("number") or ch.get("dialplan", {}).get("exten"),
                    state=str(ch.get("state", "unknown")),
                    duration_seconds=0,  # ARI gives creationtime; durations arrive with M5
                )
            )
        return out

    # --- configuration ------------------------------------------------------

    def managed_files(self) -> list[str]:
        return list(generator.MANAGED_FILES)

    def generate_config(self, snapshot: dict[str, Any]) -> list[GeneratedFile]:
        return generator.generate(snapshot)

    def validate_config(self, files: list[GeneratedFile]) -> list[str]:
        return generator.validate(files)

    def reload_scopes(self, changed_paths: list[str]) -> list[str]:
        return generator.reload_scopes(changed_paths)

    def reload(self, scope: str) -> None:
        if scope not in generator.SCOPE_ORDER:
            raise EngineUnavailable(f"unknown reload scope {scope!r}")
        self.ari.reload_module(scope)

    def verify_loaded(self, scopes: list[str]) -> list[str]:
        problems = []
        try:
            self.ari.info()
        except EngineUnavailable as e:
            return [f"Asterisk did not answer after the reload: {e}"]
        for scope in scopes:
            try:
                status = self.ari.module(scope).get("status")
            except EngineUnavailable as e:
                problems.append(f"{scope}: {e}")
                continue
            if status != "Running":
                problems.append(f"{scope}: status is {status!r}, expected 'Running'")
        return problems
