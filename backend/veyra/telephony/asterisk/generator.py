# SPDX-License-Identifier: AGPL-3.0-or-later
"""Asterisk configuration generation: a pure function from a snapshot to files.

Files land in the Veyra-managed include directory (``/etc/asterisk/veyra``),
which the stub ``pjsip.conf``, ``extensions.conf`` and ``rtp.conf`` installed
by the installer ``#tryinclude``. Nothing here is time-dependent and every
value is validated before it is written, because a config file is the one
place where user input reaches the engine.

Reload scopes map a changed file to the one module reload it needs, so a
dialplan change never touches SIP registrations and vice versa.
"""

from __future__ import annotations

import re
from typing import Any

from veyra.telephony.adapter import GeneratedFile
from veyra.telephony.settings import SipSettings

HEADER = (
    "; Managed by Veyra. Do not edit: this file is regenerated from the Veyra\n"
    "; database on every deployment and hand edits are overwritten.\n"
)

FILE_TRANSPORTS = "pjsip.transports.conf"
FILE_ENDPOINTS = "pjsip.endpoints.conf"
FILE_DIALPLAN = "extensions.conf"
FILE_RTP = "rtp.conf"
MANAGED_FILES = [FILE_TRANSPORTS, FILE_ENDPOINTS, FILE_DIALPLAN, FILE_RTP]

# Module reload per file. Order matters: transports before endpoints is the
# same module, so it collapses; the dialplan is independent.
RELOAD_SCOPES: dict[str, str] = {
    FILE_TRANSPORTS: "res_pjsip.so",
    FILE_ENDPOINTS: "res_pjsip.so",
    FILE_DIALPLAN: "pbx_config.so",
    FILE_RTP: "res_rtp_asterisk.so",
}
SCOPE_ORDER = ["res_rtp_asterisk.so", "res_pjsip.so", "pbx_config.so"]

CONTEXT_INTERNAL = "veyra-internal"
CONTEXT_FEATURES = "veyra-features"
CONTEXT_FROM_TRUNK = "veyra-from-trunk"

_SECTION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_NUMBER_RE = re.compile(r"^[0-9*#+]{1,32}$")
_SAFE_VALUE_RE = re.compile(r"^[^\r\n\[\];]*$")


class GenerationError(ValueError):
    pass


def _check_section(name: str, what: str) -> str:
    if not _SECTION_RE.match(name):
        raise GenerationError(f"{what} {name!r} is not a valid section name")
    return name


def _check_value(value: str, what: str) -> str:
    if not _SAFE_VALUE_RE.match(value):
        raise GenerationError(f"{what} contains characters that are not allowed: {value!r}")
    return value


def _display(value: str | None) -> str:
    """Caller ID names: printable, no quotes or brackets, at most 60 characters."""
    v = re.sub(r"[^\w .'&()-]", "", (value or ""), flags=re.UNICODE).strip()[:60]
    return v


def generate(snapshot: dict[str, Any]) -> list[GeneratedFile]:
    sip = SipSettings.model_validate(snapshot.get("sip") or {})
    problems = sip.problems()
    if problems:
        raise GenerationError("; ".join(problems))
    extensions = list(snapshot.get("extensions") or [])
    return [
        _transports(sip),
        _endpoints(sip, extensions),
        _dialplan(snapshot, extensions),
        _rtp(sip),
    ]


def _transports(sip: SipSettings) -> GeneratedFile:
    lines = [HEADER]
    nat = []
    if sip.external_signaling_address:
        ext = _check_value(sip.external_signaling_address, "external address")
        nat.append(f"external_signaling_address={ext}")
    if sip.external_media_address:
        ext = _check_value(sip.external_media_address, "external address")
        nat.append(f"external_media_address={ext}")
    nat.extend(f"local_net={net}" for net in sip.local_nets)
    transports = [("udp", sip.udp_port, True), ("tcp", sip.tcp_port, sip.tcp_enabled)]
    for proto, port, enabled in transports:
        if not enabled:
            continue
        lines += [
            f"[veyra-transport-{proto}]",
            "type=transport",
            f"protocol={proto}",
            f"bind={_bind(sip.bind_address, port)}",
            "allow_reload=yes",
            *nat,
            "",
        ]
    if sip.tls_enabled:
        lines += [
            "[veyra-transport-tls]",
            "type=transport",
            "protocol=tls",
            f"bind={_bind(sip.bind_address, sip.tls_port)}",
            "allow_reload=yes",
            "cert_file=/etc/veyra/tls/veyra.crt",
            "priv_key_file=/etc/veyra/tls/veyra.key",
            "method=tlsv1_2",
            *nat,
            "",
        ]
    return GeneratedFile(FILE_TRANSPORTS, "\n".join(lines).rstrip("\n") + "\n")


def _bind(address: str, port: int) -> str:
    return f"[{address}]:{port}" if ":" in address else f"{address}:{port}"


def _endpoints(sip: SipSettings, extensions: list[dict[str, Any]]) -> GeneratedFile:
    allow = ",".join(sip.codecs)
    lines = [
        HEADER,
        "; Templates shared by every Veyra endpoint.",
        "[veyra-endpoint](!)",
        "type=endpoint",
        f"context={CONTEXT_INTERNAL}",
        "disallow=all",
        f"allow={allow}",
        f"language={sip.default_language}",
        "direct_media=no",
        "rtp_symmetric=yes",
        "force_rport=yes",
        "rewrite_contact=yes",
        "send_rpid=yes",
        "trust_id_inbound=no",
        "device_state_busy_at=1",
        "",
        "[veyra-auth](!)",
        "type=auth",
        "auth_type=userpass",
        "",
        "[veyra-aor](!)",
        "type=aor",
        "max_contacts=1",
        "remove_existing=yes",
        "qualify_frequency=60",
        "",
    ]
    seen: set[str] = set()
    numbers: set[str] = set()
    sensitive = False
    for ext in extensions:
        name = _check_section(str(ext["endpoint_name"]), "endpoint name")
        if name in seen:
            raise GenerationError(f"duplicate endpoint name {name!r}")
        seen.add(name)
        number = str(ext["number"])
        if not _NUMBER_RE.match(number):
            raise GenerationError(f"extension number {number!r} is not valid")
        # One dialplan context for the whole installation until Milestone 14,
        # so a number can only be dialled to one endpoint.
        if number in numbers:
            raise GenerationError(f"extension number {number} is used more than once")
        numbers.add(number)
        secret = ext.get("secret")
        if not secret:
            raise GenerationError(f"endpoint {name!r} has no SIP secret")
        sensitive = True
        cid_name = _display(ext.get("caller_id_name") or ext.get("display_name"))
        cid_num = str(ext.get("caller_id_number") or number)
        if not _NUMBER_RE.match(cid_num):
            raise GenerationError(f"caller ID number {cid_num!r} is not valid")
        lines += [
            f"; {_check_value(str(ext.get('organization') or ''), 'organization')} {number}",
            f"[{name}](veyra-endpoint)",
            f"auth={name}",
            f"aors={name}",
            f'callerid="{cid_name}" <{cid_num}>',
            "",
            f"[{name}](veyra-auth)",
            f"username={name}",
            f"password={_check_value(str(secret), 'SIP secret')}",
            "",
            f"[{name}](veyra-aor)",
            "",
        ]
    return GeneratedFile(FILE_ENDPOINTS, "\n".join(lines).rstrip("\n") + "\n", sensitive=sensitive)


def _dialplan(snapshot: dict[str, Any], extensions: list[dict[str, Any]]) -> GeneratedFile:
    name = _check_value(str(snapshot.get("installation", {}).get("name") or "Veyra"), "name")
    lines = [
        HEADER,
        "[general]",
        "static=yes",
        "writeprotect=yes",
        "clearglobalvars=yes",
        "",
        "[globals]",
        f"VEYRA_INSTALLATION={name}",
        "",
        f"[{CONTEXT_FEATURES}]",
        "; *43 echo test, *60 speaking clock: always available for phone checks.",
        "exten => *43,1,NoOp(Veyra echo test)",
        " same => n,Answer()",
        " same => n,Wait(1)",
        " same => n,Playback(demo-echotest)",
        " same => n,Echo()",
        " same => n,Playback(demo-echodone)",
        " same => n,Hangup()",
        "exten => *60,1,NoOp(Veyra speaking clock)",
        " same => n,Answer()",
        " same => n,SayUnixTime()",
        " same => n,Hangup()",
        "",
        f"[{CONTEXT_INTERNAL}]",
        f"include => {CONTEXT_FEATURES}",
    ]
    for ext in extensions:
        number = str(ext["number"])
        endpoint = str(ext["endpoint_name"])
        lines += [
            f"exten => {number},1,NoOp(Veyra extension {number})",
            f" same => n,Dial(PJSIP/{endpoint},30)",
            " same => n,Hangup()",
        ]
    lines += [
        "exten => _[0-9*#+].,1,NoOp(Veyra: no such extension ${EXTEN})",
        " same => n,Playback(pbx-invalid)",
        " same => n,Hangup()",
        "",
        f"[{CONTEXT_FROM_TRUNK}]",
        "; Inbound routing arrives in Milestone 6. Until then calls from trunks are refused.",
        "exten => _[0-9*#+].,1,NoOp(Veyra: inbound routing is not configured)",
        " same => n,Congestion(5)",
        " same => n,Hangup()",
        "",
    ]
    return GeneratedFile(FILE_DIALPLAN, "\n".join(lines).rstrip("\n") + "\n")


def _rtp(sip: SipSettings) -> GeneratedFile:
    lines = [
        HEADER,
        "[general]",
        f"rtpstart={sip.rtp_start}",
        f"rtpend={sip.rtp_end}",
        "strictrtp=yes",
        "icesupport=no",
        "",
    ]
    return GeneratedFile(FILE_RTP, "\n".join(lines).rstrip("\n") + "\n")


def validate(files: list[GeneratedFile]) -> list[str]:
    """Static checks that do not need Asterisk: known file names, a section
    before any key, no stray control characters, balanced section brackets."""
    problems: list[str] = []
    for f in files:
        if f.path not in MANAGED_FILES:
            problems.append(f"{f.path}: not a file Veyra manages")
            continue
        section_seen = False
        for n, line in enumerate(f.content.splitlines(), start=1):
            if any(ord(ch) < 32 for ch in line):
                problems.append(f"{f.path}:{n}: control character in line")
                break
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                continue
            if stripped.startswith("["):
                if not re.match(r"^\[[A-Za-z0-9_.\-]+\](\([!A-Za-z0-9_,-]*\))?$", stripped):
                    problems.append(f"{f.path}:{n}: malformed section header {stripped!r}")
                section_seen = True
            elif not section_seen:
                problems.append(f"{f.path}:{n}: key outside a section")
                break
            elif "=" not in stripped:
                problems.append(f"{f.path}:{n}: not a key=value line: {stripped!r}")
    return problems


def reload_scopes(changed_paths: list[str]) -> list[str]:
    wanted = {RELOAD_SCOPES[p] for p in changed_paths if p in RELOAD_SCOPES}
    return [s for s in SCOPE_ORDER if s in wanted]
