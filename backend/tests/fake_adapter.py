# SPDX-License-Identifier: AGPL-3.0-or-later
"""A telephony adapter for tests: real Asterisk generation, no engine.

It records reloads, can be told to fail verification, and reports a
configurable health state, so the revision service, deployer and API can be
exercised end to end without Asterisk.
"""

from __future__ import annotations

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


class FakeAdapter(TelephonyAdapter):
    name = "asterisk"  # revisions are recorded per engine name

    def __init__(
        self,
        state: str = "running",
        *,
        prompts_dir: Any = generator.DEFAULT_PROMPTS_DIR,
        mailqueue_command: str = generator.DEFAULT_MAILQUEUE_COMMAND,
        moh_dir: Any = generator.DEFAULT_MOH_DIR,
    ) -> None:
        self.state = state
        self.prompts_dir = str(prompts_dir)
        self.mailqueue_command = mailqueue_command
        self.moh_dir = str(moh_dir)
        self.reloads: list[str] = []
        self.fail_verify: list[str] = []
        self.fail_reload: str | None = None
        self.endpoints = [EndpointStatus("1001", True), EndpointStatus("1002", False)]
        self.calls = [ActiveCall("ch1", "1001", "1002", "Up", 12, endpoint="example-1001")]
        self.originated: list[tuple[str, str, str]] = []
        self.fail_originate: str | None = None

    def capabilities(self) -> set[Capability]:
        return {
            Capability.HEALTH,
            Capability.ENDPOINT_STATUS,
            Capability.ACTIVE_CALLS,
            Capability.CONFIG_GENERATION,
            Capability.CONFIG_RELOAD,
            Capability.CLICK_TO_DIAL,
        }

    def health(self) -> EngineHealth:
        if self.state == "running":
            return EngineHealth(
                "running", self.name, version="22.5.2", message="Asterisk is running."
            )
        return EngineHealth(self.state, self.name, message=f"engine is {self.state}")  # type: ignore[arg-type]

    def info(self) -> EngineInfo:
        return EngineInfo(
            "22.5.2", "2026-10-12T17:23:49+0000", None, "aa:bb", {"res_pjsip.so": "Running"}
        )

    def endpoint_statuses(self) -> list[EndpointStatus]:
        return list(self.endpoints)

    def active_calls(self) -> list[ActiveCall]:
        return list(self.calls)

    def originate(
        self, endpoint: str, number: str, *, caller_id: str, context: str, timeout: int = 30
    ) -> str:
        if self.fail_originate:
            raise EngineUnavailable(self.fail_originate)
        self.originated.append((endpoint, number, context))
        return f"orig-{len(self.originated)}"

    def managed_files(self) -> list[str]:
        return list(generator.MANAGED_FILES)

    def generate_config(self, snapshot: dict[str, Any]) -> list[GeneratedFile]:
        return generator.generate(
            snapshot,
            prompts_dir=self.prompts_dir,
            mailqueue_command=self.mailqueue_command,
            moh_dir=self.moh_dir,
        )

    def validate_config(self, files: list[GeneratedFile]) -> list[str]:
        return generator.validate(files)

    def reload_scopes(self, changed_paths: list[str]) -> list[str]:
        return generator.reload_scopes(changed_paths)

    def reload(self, scope: str) -> None:
        if scope == self.fail_reload:
            raise EngineUnavailable(f"reload of {scope} failed")
        self.reloads.append(scope)

    def verify_loaded(self, scopes: list[str]) -> list[str]:
        return list(self.fail_verify)
