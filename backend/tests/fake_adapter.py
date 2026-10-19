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
    Registration,
    TelephonyAdapter,
    TrunkRegistration,
)
from veyra.telephony.asterisk import adapter as asterisk_adapter
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
        self.contacts: list[Registration] = [
            Registration(
                endpoint="1001",
                uri="sip:1001@192.168.10.20:5060;transport=tls",
                contact_host="192.168.10.20",
                contact_port=5060,
                source_host="203.0.113.7",
                source_port=41234,
                transport="tls",
                user_agent="PolycomVVX-VVX_411-UA/6.4.3",
                expires_at="2026-10-16T22:00:00Z",
                status="Avail",
                rtt_ms=12.5,
            )
        ]
        self.calls = [ActiveCall("ch1", "1001", "1002", "Up", 12, endpoint="example-1001")]
        self.originated: list[tuple[str, str, str]] = []
        self.fail_originate: str | None = None
        # (organization slug, number) -> {field: value}, as "the engine" has it.
        self.states: dict[tuple[str, str], dict[str, str]] = {}
        self.state_calls: list[tuple[str, str, str, str | None]] = []
        self.switch_calls: list[tuple[str, str, str, str | None]] = []
        self.switch_states: dict[tuple[str, str, str], str] = {}
        self.store: dict[str, dict[str, str]] = {}
        self.store_calls: list[tuple[str, str, str | None]] = []
        self.queue_state: dict[str, dict[str, dict[str, Any]]] = {}
        self.queue_calls: list[tuple[str, str, bool, bool]] = []
        # trunk section -> registration status word, as "the engine" reports it.
        self.trunk_regs: dict[str, str] = {}

    def capabilities(self) -> set[Capability]:
        return {
            Capability.HEALTH,
            Capability.ENDPOINT_STATUS,
            Capability.ACTIVE_CALLS,
            Capability.CONFIG_GENERATION,
            Capability.CONFIG_RELOAD,
            Capability.CLICK_TO_DIAL,
            Capability.REGISTRATIONS,
            Capability.EXTENSION_STATE,
            Capability.TRUNK_REGISTRATIONS,
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

    def registrations(self) -> list[Registration]:
        return list(self.contacts)

    def trunk_registrations(self) -> list[TrunkRegistration]:
        return [
            TrunkRegistration(section=k, server_uri=f"sip:{k}.example", status=v)
            for k, v in self.trunk_regs.items()
        ]

    def set_extension_state(
        self, organization: str, number: str, field: str, value: str | None
    ) -> None:
        self.state_calls.append((organization, number, field, value))
        fields = self.states.setdefault((organization, number), {})
        if value:
            fields[field] = value
        else:
            fields.pop(field, None)
        if not fields:
            self.states.pop((organization, number), None)

    def extension_states(self) -> dict[tuple[str, str], dict[str, str]]:
        return {k: dict(v) for k, v in self.states.items()}

    def set_switch(self, kind: str, organization: str, key: str, value: str | None) -> None:
        self.switch_calls.append((kind, organization, key, value))
        if value:
            self.switch_states[(kind, organization, key)] = value
        else:
            self.switch_states.pop((kind, organization, key), None)

    def switches(self) -> dict[tuple[str, str, str], str]:
        return dict(self.switch_states)

    def queue_members(self, queue: str) -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in self.queue_state.get(queue, {}).items()}

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
        self.queue_calls.append((queue, interface, present, paused))
        members = self.queue_state.setdefault(queue, {})
        if present:
            members[interface] = {"dynamic": True, "paused": paused, "penalty": penalty}
        else:
            members.pop(interface, None)

    def store_entries(self, family: str) -> dict[str, str]:
        return dict(self.store.get(family, {}))

    def store_put(self, family: str, key: str, value: str | None) -> None:
        # The same checks as the engine adapter, so a key it would refuse
        # (and only log) fails the test instead.
        asterisk_adapter._check_family(family)
        asterisk_adapter._check_store_key(key)
        if value is not None and not asterisk_adapter._STORE_VALUE_RE.match(value):
            raise ValueError(f"store value {value!r} is not valid")
        self.store_calls.append((family, key, value))
        fam = self.store.setdefault(family, {})
        if value:
            fam[key] = value
        else:
            fam.pop(key, None)

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
