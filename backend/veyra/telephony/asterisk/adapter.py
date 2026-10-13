# SPDX-License-Identifier: AGPL-3.0-or-later
"""Asterisk adapter: health and status over ARI, configuration generation
for the Veyra-managed include directory, targeted module reloads.

ARI runs on 127.0.0.1 only (installer). Reloads use ``PUT
/asterisk/modules/{name}``, which is the same as ``module reload`` on the
console, so no shell command and no CLI socket access is needed.
"""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
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


_CHANNEL_ENDPOINT_RE = re.compile(r"^PJSIP/([A-Za-z0-9_.-]+)-[0-9a-f]+$")


def _endpoint_of(channel_name: str) -> str | None:
    m = _CHANNEL_ENDPOINT_RE.match(channel_name)
    return m.group(1) if m else None


def _age_seconds(creation: Any, now: datetime) -> int:
    """Seconds since an ARI ``creationtime`` (``2026-10-12T20:07:31.123+0000``)."""
    if not creation:
        return 0
    text = str(creation)
    if re.search(r"[+-]\d{4}$", text):
        text = text[:-2] + ":" + text[-2:]
    try:
        created = datetime.fromisoformat(text)
    except ValueError:
        return 0
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return max(0, int((now - created).total_seconds()))


class AsteriskAdapter(TelephonyAdapter):
    name = "asterisk"

    def __init__(
        self,
        ari_url: str,
        username: str,
        password_file: Path,
        *,
        prompts_dir: Path | str = generator.DEFAULT_PROMPTS_DIR,
        mailqueue_command: str = generator.DEFAULT_MAILQUEUE_COMMAND,
    ) -> None:
        self.ari = AriClient(ari_url, username, password_file)
        self.prompts_dir = str(prompts_dir)
        self.mailqueue_command = mailqueue_command

    def capabilities(self) -> set[Capability]:
        return {
            Capability.HEALTH,
            Capability.ENDPOINT_STATUS,
            Capability.ACTIVE_CALLS,
            Capability.CONFIG_GENERATION,
            Capability.CONFIG_RELOAD,
            Capability.CLICK_TO_DIAL,
            Capability.VOICEMAIL,
            Capability.IVR,
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
        now = datetime.now(UTC)
        for ch in self.ari.channels():
            caller = ch.get("caller", {}) or {}
            connected = ch.get("connected", {}) or {}
            out.append(
                ActiveCall(
                    channel_id=str(ch.get("id")),
                    caller=caller.get("number") or caller.get("name"),
                    callee=connected.get("number") or ch.get("dialplan", {}).get("exten"),
                    state=str(ch.get("state", "unknown")),
                    duration_seconds=_age_seconds(ch.get("creationtime"), now),
                    endpoint=_endpoint_of(str(ch.get("name", ""))),
                )
            )
        return out

    def originate(
        self, endpoint: str, number: str, *, caller_id: str, context: str, timeout: int = 30
    ) -> str:
        ch = self.ari.originate(f"PJSIP/{endpoint}", number, context, caller_id, timeout)
        return str(ch.get("id") or "")

    # --- configuration ------------------------------------------------------

    def managed_files(self) -> list[str]:
        return list(generator.MANAGED_FILES)

    def generate_config(self, snapshot: dict[str, Any]) -> list[GeneratedFile]:
        return generator.generate(
            snapshot, prompts_dir=self.prompts_dir, mailqueue_command=self.mailqueue_command
        )

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
