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
import time
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
    Registration,
    TelephonyAdapter,
    TrunkRegistration,
)
from veyra.telephony.asterisk import cli, contacts, generator
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


STATE_FAMILY = "veyra/ext"
STATE_FIELDS = ("dnd", "cf_always", "cf_busy", "cf_no_answer", "fmfm")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$")
_VALUE_RE = re.compile(r"^[+0-9]{0,32}$")
# "/veyra/ext/example/1001/cf_always                 : 5735550100"
_STATE_ROW_RE = re.compile(
    r"^/veyra/ext/(?P<org>[^/]+)/(?P<number>[^/]+)/(?P<field>[a-z_]+)\s*:\s*(?P<value>.*)$"
)


SWITCH_FAMILY = "veyra/switch"
SWITCH_KINDS = ("flow", "tc")
_SWITCH_VALUE_RE = re.compile(r"^[a-z0-9]{1,16}$")
# "/veyra/switch/flow/example/night                   : 1"
_SWITCH_ROW_RE = re.compile(
    r"^/veyra/switch/(?P<kind>[a-z]+)/(?P<org>[^/]+)/(?P<key>[^/ ]+)\s*:\s*(?P<value>.*)$"
)


# "  trunk-carrier/sip:sip.carrier.example            trunk-carrier     Registered"
_TRUNK_REG_RE = re.compile(
    r"^\s*(?P<section>[A-Za-z0-9_.-]+)/(?P<uri>\S+)\s+(?P<auth>\S+)\s+"
    r"(?P<status>[A-Za-z][A-Za-z ]*?)\s*(?:\(.*\))?\s*$"
)


def parse_trunk_registrations(output: str) -> list[TrunkRegistration]:
    """``pjsip show registrations`` -> one entry per outbound registration."""
    out: list[TrunkRegistration] = []
    for line in output.splitlines():
        if "<Registration/ServerURI" in line or line.startswith("=") or "Objects found" in line:
            continue
        m = _TRUNK_REG_RE.match(line)
        if not m:
            continue
        out.append(
            TrunkRegistration(
                section=m.group("section"),
                server_uri=m.group("uri"),
                status=m.group("status").strip(),
            )
        )
    return out


def _check_token(value: str, what: str) -> str:
    if not _TOKEN_RE.match(value or ""):
        raise ValueError(f"{what} {value!r} is not valid for the engine store")
    return value


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


REGISTRATIONS_TTL = 5.0


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
        moh_dir: Path | str = generator.DEFAULT_MOH_DIR,
        recordings_dir: Path | str = generator.DEFAULT_RECORDINGS_DIR,
    ) -> None:
        self.ari = AriClient(ari_url, username, password_file)
        self.prompts_dir = str(prompts_dir)
        self.mailqueue_command = mailqueue_command
        self.moh_dir = str(moh_dir)
        self.recordings_dir = str(recordings_dir)
        self._registrations_cache: tuple[float, list[Registration]] | None = None

    def capabilities(self) -> set[Capability]:
        caps = {
            Capability.HEALTH,
            Capability.ENDPOINT_STATUS,
            Capability.ACTIVE_CALLS,
            Capability.CONFIG_GENERATION,
            Capability.CONFIG_RELOAD,
            Capability.CLICK_TO_DIAL,
            Capability.VOICEMAIL,
            Capability.IVR,
        }
        if cli.asterisk_available():
            caps.add(Capability.REGISTRATIONS)
            caps.add(Capability.EXTENSION_STATE)
            caps.add(Capability.TRUNK_REGISTRATIONS)
        return caps

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

    def trunk_registrations(self) -> list[TrunkRegistration]:
        ok, out = cli.run("pjsip show registrations")
        if not ok:
            raise EngineUnavailable(f"could not read the trunk registrations: {out[:200]}")
        return parse_trunk_registrations(out)

    def set_extension_state(
        self, organization: str, number: str, field: str, value: str | None
    ) -> None:
        """AstDB key read by the dialplan and the custom device states behind the
        BLF hints (docs/CALL_FEATURES.md §3.2, §3.3), through the CLI socket."""
        org = _check_token(organization, "organization")
        num = _check_token(number, "extension")
        if field not in STATE_FIELDS:
            raise ValueError(f"unknown extension state field {field!r}")
        if value is not None and not _VALUE_RE.match(value):
            raise ValueError(f"state value {value!r} is not valid for the engine store")
        family = f"{STATE_FAMILY}/{org}/{num}"
        cmd = (
            f"database put {family} {field} {value}" if value else f"database del {family} {field}"
        )
        ok, out = cli.run(cmd)
        if not ok and not (not value and "not found" in out.lower()):
            raise EngineUnavailable(f"could not store the extension state: {out[:200]}")
        if field == "dnd":
            device, on = f"Custom:veyra-dnd-{org}-{num}", bool(value)
        elif field == "fmfm":
            device, on = f"Custom:veyra-fm-{org}-{num}", bool(value)
        else:
            # The forwarding lamp is lit while any of the three forwards is set.
            current = self.extension_states().get((org, num), {})
            device = f"Custom:veyra-cf-{org}-{num}"
            on = any(current.get(f) for f in ("cf_always", "cf_busy", "cf_no_answer"))
        cli.run(f"devstate change {device} {'INUSE' if on else 'NOT_INUSE'}")

    def set_switch(self, kind: str, organization: str, key: str, value: str | None) -> None:
        if kind not in SWITCH_KINDS:
            raise ValueError(f"unknown switch kind {kind!r}")
        org = _check_token(organization, "organization")
        k = _check_token(key, "switch key")
        if value is not None and not _SWITCH_VALUE_RE.match(value):
            raise ValueError(f"switch value {value!r} is not valid for the engine store")
        family = f"{SWITCH_FAMILY}/{kind}/{org}"
        cmd = f"database put {family} {k} {value}" if value else f"database del {family} {k}"
        ok, out = cli.run(cmd)
        if not ok and not (not value and "not found" in out.lower()):
            raise EngineUnavailable(f"could not store the switch: {out[:200]}")
        cli.run(
            f"devstate change Custom:veyra-{kind}-{org}-{k} {'INUSE' if value else 'NOT_INUSE'}"
        )

    def switches(self) -> dict[tuple[str, str, str], str]:
        ok, out = cli.run(f"database show {SWITCH_FAMILY}")
        if not ok:
            raise EngineUnavailable(f"could not read the switches: {out[:200]}")
        found: dict[tuple[str, str, str], str] = {}
        for line in out.splitlines():
            m = _SWITCH_ROW_RE.match(line.strip())
            if m and m.group("kind") in SWITCH_KINDS:
                value = m.group("value").strip()
                if value:
                    found[(m.group("kind"), m.group("org"), m.group("key"))] = value
        return found

    def extension_states(self) -> dict[tuple[str, str], dict[str, str]]:
        ok, out = cli.run(f"database show {STATE_FAMILY}")
        if not ok:
            raise EngineUnavailable(f"could not read the extension states: {out[:200]}")
        states: dict[tuple[str, str], dict[str, str]] = {}
        for line in out.splitlines():
            m = _STATE_ROW_RE.match(line.strip())
            if m and m.group("field") in STATE_FIELDS:
                value = m.group("value").strip()
                if value and value != "0":
                    states.setdefault((m.group("org"), m.group("number")), {})[m.group("field")] = (
                        value
                    )
        return states

    def registrations(self) -> list[Registration]:
        """Registered contacts with addresses (docs/CALL_FEATURES.md §2.1), from
        the AstDB contact store and ``pjsip show contacts`` over the CLI socket,
        cached for REGISTRATIONS_TTL seconds because several pages ask at once."""
        cached = self._registrations_cache
        now = time.monotonic()
        if cached is not None and now - cached[0] < REGISTRATIONS_TTL:
            return list(cached[1])
        ok_db, db_out = cli.run(contacts.CMD_DATABASE)
        ok_li, li_out = cli.run(contacts.CMD_CONTACTS)
        if not ok_db and not ok_li:
            raise EngineUnavailable(db_out or li_out or "the Asterisk CLI did not answer")
        rows = contacts.merge(
            contacts.parse_database(db_out if ok_db else ""),
            contacts.parse_contacts(li_out if ok_li else ""),
        )
        self._registrations_cache = (now, rows)
        return list(rows)

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
            snapshot,
            prompts_dir=self.prompts_dir,
            mailqueue_command=self.mailqueue_command,
            moh_dir=self.moh_dir,
            recordings_dir=self.recordings_dir,
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
