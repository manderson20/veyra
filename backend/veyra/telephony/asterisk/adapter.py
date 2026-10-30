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
STATE_FIELDS = (
    "dnd",
    "cf_always",
    "cf_busy",
    "cf_no_answer",
    "cf_unavailable",
    "fmfm",
    "nocw",
    "acr",
    "dnd_allow",
)
FORWARD_FIELDS = ("cf_always", "cf_busy", "cf_no_answer", "cf_unavailable")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9+][A-Za-z0-9_.-]{0,62}$")
# A number, or the Do Not Disturb exceptions joined with "-" (issue #170).
_VALUE_RE = re.compile(r"^[+0-9-]{0,480}$")
# "/veyra/ext/example/1001/cf_always                 : 5735550100"
_STATE_ROW_RE = re.compile(
    r"^/veyra/ext/(?P<org>[^/]+)/(?P<number>[^/]+)/(?P<field>[a-z_]+)\s*:\s*(?P<value>.*)$"
)


_FAMILY_RE = re.compile(r"^veyra(/[A-Za-z0-9_.+-]{1,64}){1,3}$")
# A store key may carry a path of its own (``<org>/<ext>/<queue>`` under
# ``veyra/agent``); the dialplan reads the joined path with DB().
_STORE_KEY_RE = re.compile(r"^[A-Za-z0-9+][A-Za-z0-9_.+-]{0,63}(/[A-Za-z0-9_.+-]{1,64}){0,3}$")
_STORE_VALUE_RE = re.compile(r"^[A-Za-z0-9 ._+-]{1,200}$")


def _check_family(family: str) -> str:
    if not _FAMILY_RE.match(family):
        raise ValueError(f"store family {family!r} is not one of Veyra's")
    return family


def _check_store_key(key: str) -> str:
    if not _STORE_KEY_RE.match(key or "") or any(seg.strip(".") == "" for seg in key.split("/")):
        raise ValueError(f"store key {key!r} is not valid for the engine store")
    return key


_SECTION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_INTERFACE_RE = re.compile(r"^PJSIP/[A-Za-z0-9_.-]{1,63}$")
# Member lines of "queue show", with or without a name and a penalty:
#   PJSIP/example-1001 (ringinuse disabled) (dynamic) (paused:veyra ...) (Not in use) has taken ...
#   Front Office (PJSIP/example-1001 from PJSIP/example-1001) with penalty 2 (dynamic) ...
_QUEUE_MEMBER_RE = re.compile(
    r"^\s+(?:[^()]*\()?(?P<iface>PJSIP/[A-Za-z0-9_.-]+)(?: from [^)]*)?\)?"
    r"(?: with penalty (?P<penalty>[0-9]+))?.*\((?:Not in use|In use|Busy|Unavailable|Ringing|"
    r"Ring\+Inuse|On Hold|Invalid|Unknown)\)"
)


def _check_section_name(value: str) -> str:
    if not _SECTION_NAME_RE.match(value):
        raise ValueError(f"queue name {value!r} is not valid")
    return value


def _check_interface(value: str) -> str:
    if not _INTERFACE_RE.match(value):
        raise ValueError(f"interface {value!r} is not a PJSIP endpoint")
    return value


SWITCH_FAMILY = "veyra/switch"
_CONF_NAME_RE = re.compile(r"^veyra[A-Za-z0-9_-]{0,80}$")
_CONF_CHANNEL_RE = re.compile(r"^[A-Za-z]+/[A-Za-z0-9_.@;+-]{1,120}$")
# A phone's channel, as the spy context accepts it (issue #167).
_SPY_CHANNEL_RE = re.compile(r"^PJSIP/[A-Za-z0-9_.-]+-[0-9a-f]+$")


def _check_conference(room: str) -> str:
    if not _CONF_NAME_RE.match(room):
        raise ValueError(f"{room!r} is not a Veyra conference")
    return room


# ``confbridge list`` ("%-32s %6u %6u %-6s %s") and ``confbridge list <room>``
# ("%-30s %-6s %-16s %-16s %-16s %s"): names may be wider than the columns,
# so the rows are read by pattern; Flags (A admin, M marked, m muted, W, E, w)
# may be empty.
_CONF_LIST_RE = re.compile(
    r"^(?P<name>\S+)\s+(?P<users>\d+)\s+(?P<marked>\d+)\s+(?P<locked>\S+)\s+(?P<muted>\S+)\s*$"
)
_CONF_USER_RE = re.compile(
    r"^(?P<channel>[A-Za-z]+/\S+)\s+(?P<flags>[AMWEmw]*)\s+(?P<user>\S+)\s+(?P<bridge>\S+)"
    r"\s+(?P<menu>\S+)\s*(?P<callerid>.*)$"
)


def parse_confbridge_list(out: str) -> dict[str, dict[str, str]]:
    """``confbridge list`` → {room: {users, marked, locked, muted}}."""
    rows = {}
    for line in out.splitlines():
        m = _CONF_LIST_RE.match(line.strip())
        if m and not line.startswith(("=", "Conference Bridge Name")):
            rows[m.group("name")] = m.groupdict()
    return rows


def parse_confbridge_users(out: str) -> list[dict[str, str]]:
    """``confbridge list <room>`` → participants."""
    return [m.groupdict() for line in out.splitlines() if (m := _CONF_USER_RE.match(line.strip()))]


SWITCH_KINDS = ("flow", "tc", "agent", "agentpause", "agentq")
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
        fax_dir: Path | str = generator.DEFAULT_FAX_DIR,
    ) -> None:
        self.ari = AriClient(ari_url, username, password_file)
        self.prompts_dir = str(prompts_dir)
        self.mailqueue_command = mailqueue_command
        self.moh_dir = str(moh_dir)
        self.recordings_dir = str(recordings_dir)
        self.fax_dir = str(fax_dir)
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
        elif field in FORWARD_FIELDS:
            # The forwarding lamp is lit while any forward is set.
            current = self.extension_states().get((org, num), {})
            device = f"Custom:veyra-cf-{org}-{num}"
            on = any(current.get(f) for f in FORWARD_FIELDS)
        else:
            return
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

    def set_presence_lamp(self, organization: str, number: str, state: str) -> None:
        org = _check_token(organization, "organization")
        num = _check_token(number, "extension")
        if state not in ("INUSE", "ONHOLD", "UNAVAILABLE", "NOT_INUSE"):
            raise ValueError(f"unknown device state {state!r}")
        ok, out = cli.run(f"devstate change Custom:veyra-presence-{org}-{num} {state}")
        if not ok:
            raise EngineUnavailable(f"could not set the presence lamp: {out[:200]}")

    def store_entries(self, family: str) -> dict[str, str]:
        fam = _check_family(family)
        ok, out = cli.run(f"database show {fam}")
        if not ok:
            raise EngineUnavailable(f"could not read the store family {fam}: {out[:200]}")
        found: dict[str, str] = {}
        prefix = f"/{fam}/"
        for line in out.splitlines():
            line = line.strip()
            if not line.startswith(prefix) or ":" not in line:
                continue
            path, _, value = line.partition(":")
            key = path[len(prefix) :].strip()
            if key and "/" not in key and value.strip():
                found[key] = value.strip()
        return found

    def store_put(self, family: str, key: str, value: str | None) -> None:
        fam = _check_family(family)
        k = _check_store_key(key)
        if value is not None and not _STORE_VALUE_RE.match(value):
            raise ValueError(f"store value {value!r} is not valid")
        cmd = f"database put {fam} {k} {value}" if value else f"database del {fam} {k}"
        ok, out = cli.run(cmd)
        if not ok and not (not value and "not found" in out.lower()):
            raise EngineUnavailable(f"could not write the store: {out[:200]}")

    def queue_members(self, queue: str) -> dict[str, dict[str, Any]]:
        q = _check_section_name(queue)
        ok, out = cli.run(f"queue show {q}")
        if not ok:
            raise EngineUnavailable(f"could not read the queue {q}: {out[:200]}")
        if "No such queue" in out:
            return {}
        members: dict[str, dict[str, Any]] = {}
        for line in out.splitlines():
            m = _QUEUE_MEMBER_RE.match(line)
            if m:
                members[m.group("iface")] = {
                    "dynamic": "(dynamic)" in line,
                    "paused": "(paused" in line,
                    "penalty": int(m.group("penalty") or 0),
                }
        return members

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
        q = _check_section_name(queue)
        iface = _check_interface(interface)
        if present:
            label = re.sub(r"[^A-Za-z0-9 ._-]", "", name)[:40] or iface
            ok, out = cli.run(
                f"queue add member {iface} to {q} penalty {int(penalty)} "
                f'as "{label}" state_interface {iface}'
            )
            if not ok or ("Unable" in out and "Already" not in out):
                raise EngineUnavailable(f"could not add {iface} to {q}: {out[:200]}")
            verb = "pause" if paused else "unpause"
            ok, out = cli.run(f"queue {verb} member {iface} queue {q} reason veyra")
            if not ok or "Unable" in out:
                raise EngineUnavailable(f"could not {verb} {iface} in {q}: {out[:200]}")
        else:
            ok, out = cli.run(f"queue remove member {iface} from {q}")
            if not ok or ("Unable" in out and "not there" not in out.lower()):
                raise EngineUnavailable(f"could not remove {iface} from {q}: {out[:200]}")

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

    def hangup(self, channel_id: str) -> None:
        self.ari.hangup(channel_id)

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
        ch = self.ari.originate(
            endpoint, extension, context, caller_id, timeout, variables=variables
        )
        return str(ch.get("id") or "")

    def record_call(self, channel_id: str, start: bool) -> None:
        ch = self.ari.channel(channel_id)
        name = str(ch.get("name") or "")
        if not _CONF_CHANNEL_RE.match(name):
            raise EngineUnavailable("the call's channel is not known")
        ours = self.ari.get_variable(channel_id, "VEYRA_ONDEMAND_WEB") == "1"
        if start:
            if self.ari.get_variable(channel_id, "VEYRA_CALLREC"):
                raise ValueError("this call is already being recorded")
            rec = re.sub(r"[^0-9A-Za-z.-]", "", channel_id)[:64]
            self.ari.set_variable(channel_id, "VEYRA_CALLREC", rec)
            self.ari.set_variable(channel_id, "CDR(veyra_rec)", rec)
            self.ari.set_variable(channel_id, "VEYRA_ONDEMAND_WEB", "1")
            path = f"{self.recordings_dir}/incoming/{rec}--{generator.ONDEMAND_POLICY}.wav"
            ok, out = cli.run(f"mixmonitor start {name} {path},b")
        else:
            if not ours:
                raise ValueError("only a recording started from the web can be stopped here")
            ok, out = cli.run(f"mixmonitor stop {name}")
            if ok:
                self.ari.set_variable(channel_id, "VEYRA_ONDEMAND_WEB", "")
        if not ok or "No such channel" in out or "Cannot" in out:
            raise EngineUnavailable(out[:200] or "the engine refused the command")

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
        if mode not in ("listen", "whisper", "barge"):
            raise ValueError(f"unknown monitor mode {mode!r}")
        name = str(self.ari.channel(channel_id).get("name") or "")
        if not _SPY_CHANNEL_RE.match(name):
            raise EngineUnavailable("the call's channel is not known")
        return self.originate_channel(
            f"PJSIP/{_check_token(supervisor_endpoint, 'endpoint')}",
            "s",
            context=context,
            caller_id=caller_id,
            timeout=30,
            variables={
                "VEYRA_SPY_CHAN": name,
                "VEYRA_SPY_MODE": mode,
                "VEYRA_SPY_BEEP": "1" if beep else "",
            },
        )

    def conference_live(self, room: str) -> dict[str, Any] | None:
        name = _check_conference(room)
        ok, out = cli.run("confbridge list")
        if not ok:
            raise EngineUnavailable(f"could not list the conferences: {out[:200]}")
        summary = parse_confbridge_list(out).get(name)
        if summary is None:
            return None
        ok, out = cli.run(f"confbridge list {name}")
        if not ok:
            raise EngineUnavailable(f"could not list the conference {name}: {out[:200]}")
        participants = [
            {
                "channel": r["channel"],
                "caller_id": r["callerid"].strip(),
                "admin": "A" in r["flags"],
                "marked": "M" in r["flags"],
                "muted": "m" in r["flags"],
            }
            for r in parse_confbridge_users(out)
        ]
        # The recorder is a channel of its own, CBRec/<room>-<8 hex digits>.
        ok, out = cli.run("core show channels concise")
        recorder = f"CBRec/{name}-"
        recording = ok and any(line.startswith(recorder) for line in out.splitlines())
        return {
            "locked": summary["locked"].lower().startswith("y"),
            "recording": recording,
            "participants": participants,
        }

    def conference_action(self, room: str, action: str, channel: str | None = None) -> None:
        name = _check_conference(room)
        if action in ("mute", "unmute", "kick"):
            if not channel or not _CONF_CHANNEL_RE.match(channel):
                raise ValueError("a participant's channel is required")
            command = f"confbridge {action} {name} {channel}"
        elif action in ("mute_all", "unmute_all"):
            # "participants": everyone who is not an administrator.
            command = f"confbridge {action.split('_')[0]} {name} participants"
        elif action in ("lock", "unlock"):
            command = f"confbridge {action} {name}"
        elif action == "end":
            command = f"confbridge kick {name} all"
        elif action in ("record_start", "record_stop"):
            command = f"confbridge record {action.split('_')[1]} {name}"
        else:
            raise ValueError(f"unknown conference action {action!r}")
        ok, out = cli.run(command)
        refusals = (
            "No conference bridge named",
            "No participant named",
            "already being recorded",
            "Could not start recording",
            "could not be stopped",
        )
        if not ok or any(r in out for r in refusals):
            raise EngineUnavailable(out[:200] or "the engine refused the command")

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
            fax_dir=self.fax_dir,
        )

    def validate_config(self, files: list[GeneratedFile]) -> list[str]:
        return generator.validate(files)

    def reload_scopes(self, changed_paths: list[str]) -> list[str]:
        return generator.reload_scopes(changed_paths)

    def reload(self, scope: str) -> None:
        if scope not in generator.SCOPE_ORDER:
            raise EngineUnavailable(f"unknown reload scope {scope!r}")
        if scope == "features":
            # features.conf belongs to the core, not to a loadable module: no
            # ARI module reload; the console's "module reload features" is the
            # only form current Asterisk accepts ("features reload" is gone).
            ok, out = cli.run("module reload features")
            if not ok:
                raise EngineUnavailable(f"features reload failed: {out[:200]}")
            return
        self.ari.reload_module(scope)

    def verify_loaded(self, scopes: list[str]) -> list[str]:
        problems = []
        try:
            self.ari.info()
        except EngineUnavailable as e:
            return [f"Asterisk did not answer after the reload: {e}"]
        for scope in scopes:
            if scope == "features":
                continue  # core component, no module status to check
            try:
                status = self.ari.module(scope).get("status")
            except EngineUnavailable as e:
                problems.append(f"{scope}: {e}")
                continue
            if status != "Running":
                problems.append(f"{scope}: status is {status!r}, expected 'Running'")
        return problems
