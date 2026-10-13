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

from veyra.telephony import routing
from veyra.telephony.adapter import GeneratedFile
from veyra.telephony.settings import SipSettings

HEADER = (
    "; Managed by Veyra. Do not edit: this file is regenerated from the Veyra\n"
    "; database on every deployment and hand edits are overwritten.\n"
)

FILE_TRANSPORTS = "pjsip.transports.conf"
FILE_ENDPOINTS = "pjsip.endpoints.conf"
FILE_TRUNKS = "pjsip.trunks.conf"
FILE_DIALPLAN = "extensions.conf"
FILE_RTP = "rtp.conf"
MANAGED_FILES = [FILE_TRANSPORTS, FILE_ENDPOINTS, FILE_TRUNKS, FILE_DIALPLAN, FILE_RTP]

# Module reload per file. Order matters: transports before endpoints is the
# same module, so it collapses; the dialplan is independent.
RELOAD_SCOPES: dict[str, str] = {
    FILE_TRANSPORTS: "res_pjsip.so",
    FILE_ENDPOINTS: "res_pjsip.so",
    FILE_TRUNKS: "res_pjsip.so",
    FILE_DIALPLAN: "pbx_config.so",
    FILE_RTP: "res_rtp_asterisk.so",
}
SCOPE_ORDER = ["res_rtp_asterisk.so", "res_pjsip.so", "pbx_config.so"]

CONTEXT_INTERNAL = "veyra-internal"
CONTEXT_FEATURES = "veyra-features"
CONTEXT_FROM_TRUNK = "veyra-from-trunk"
# Catch-all for unknown numbers. It lives in its own context, included after the
# feature codes: Asterisk matches patterns in the current context before it looks
# at included ones, so a catch-all in veyra-internal itself would shadow *43/*60.
CONTEXT_INVALID = "veyra-invalid"
# Outbound: one context per route, included in evaluation order (docs/TRUNKS_ROUTING.md §4).
CONTEXT_OUTBOUND = "veyra-outbound"
CONTEXT_OUT_PREFIX = "veyra-out-"
# Inbound: each trunk enters its own context, which includes the shared DIDs
# and then the trunk's fallback (its catch-all route or a rejection).
CONTEXT_FROM_TRUNK_PREFIX = "veyra-from-trunk-"
TRUNK_PREFIX = "trunk-"
OUTBOUND_DIAL_TIMEOUT = 60
EMERGENCY_DIAL_TIMEOUT = 120

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


def _prefix(value: str) -> str:
    """Caller ID name prefixes: like display names, plus ':' and kept spaces."""
    return re.sub(r"[^\w .'&():-]", "", value, flags=re.UNICODE)[:40]


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
    trunks = list(snapshot.get("trunks") or [])
    return [
        _transports(sip),
        _endpoints(sip, extensions),
        _trunks(sip, trunks),
        _dialplan(snapshot, extensions, trunks),
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
        org = _check_value(str(ext.get("organization") or ""), "organization")
        lines += [
            f"; {org} {number}",
            f"[{name}](veyra-endpoint)",
            f"auth={name}",
            f"aors={name}",
            f'callerid="{cid_name}" <{cid_num}>',
            f"set_var=VEYRA_ORG={org}",
            "",
            f"[{name}](veyra-auth)",
            f"username={name}",
            f"password={_check_value(str(secret), 'SIP secret')}",
            "",
            f"[{name}](veyra-aor)",
            "",
        ]
    return GeneratedFile(FILE_ENDPOINTS, "\n".join(lines).rstrip("\n") + "\n", sensitive=sensitive)


def _host(value: str, what: str) -> str:
    v = str(value).strip()
    if not re.match(r"^[A-Za-z0-9.:\[\]-]{1,253}$", v):
        raise GenerationError(f"{what} {v!r} is not a valid host name or address")
    return v


def _match(value: str, what: str) -> str:
    """An identify match: host name, address or CIDR."""
    v = str(value).strip()
    if not re.match(r"^[A-Za-z0-9.:\[\]-]{1,253}(/[0-9]{1,3})?$", v):
        raise GenerationError(f"{what} {v!r} is not a valid address, network or host name")
    return v


def _trunks(sip: SipSettings, trunks: list[dict[str, Any]]) -> GeneratedFile:
    """``pjsip.trunks.conf``: endpoint, AOR, identify and (registration mode)
    auth and registration sections per enabled trunk (docs/TRUNKS_ROUTING.md §8)."""
    lines = [HEADER]
    seen: set[str] = set()
    sensitive = False
    for t in trunks:
        slug = _check_section(str(t["slug"]), "trunk slug")
        if slug in seen:
            raise GenerationError(f"duplicate trunk slug {slug!r}")
        seen.add(slug)
        name = TRUNK_PREFIX + slug
        mode = str(t.get("auth_mode") or "ip")
        if mode not in routing.AUTH_MODES:
            raise GenerationError(f"trunk {slug}: unknown authentication mode {mode!r}")
        transport = str(t.get("transport") or "udp")
        if transport not in routing.TRANSPORTS:
            raise GenerationError(f"trunk {slug}: unknown transport {transport!r}")
        if transport == "tcp" and not sip.tcp_enabled:
            raise GenerationError(f"trunk {slug} uses TCP but the TCP transport is disabled")
        if transport == "tls" and not sip.tls_enabled:
            raise GenerationError(f"trunk {slug} uses TLS but the TLS transport is disabled")
        host = _host(t["host"], f"trunk {slug} host")
        port = int(t.get("port") or 5060)
        if not 1 <= port <= 65535:
            raise GenerationError(f"trunk {slug}: port {port} is out of range")
        codecs = [str(c) for c in (t.get("codecs") or sip.codecs)]
        for c in codecs:
            if not re.match(r"^[a-z0-9]{1,16}$", c):
                raise GenerationError(f"trunk {slug}: codec {c!r} is not valid")
        header = str(t.get("caller_id_header") or "pai")
        if header not in routing.CALLER_ID_HEADERS:
            raise GenerationError(f"trunk {slug}: unknown caller ID header {header!r}")
        dtmf = str(t.get("dtmf_mode") or "rfc4733")
        if dtmf not in routing.DTMF_MODES:
            raise GenerationError(f"trunk {slug}: unknown DTMF mode {dtmf!r}")
        qualify = int(t.get("qualify_frequency") or 0)
        matches = [
            _match(m, f"trunk {slug} match address") for m in (t.get("match_addresses") or [])
        ]
        if not matches:
            matches = [host]
        contact = f"sip:{host}:{port}"
        if transport != "udp":
            contact += f"\\;transport={transport}"
        lines += [
            f"; {_check_value(str(t.get('name') or slug), 'trunk name')} ({mode})",
            f"[{name}]",
            "type=endpoint",
            f"context={CONTEXT_FROM_TRUNK_PREFIX}{slug}",
            "disallow=all",
            f"allow={','.join(codecs)}",
            f"language={sip.default_language}",
            f"transport=veyra-transport-{transport}",
            f"aors={name}",
            "direct_media=no",
            "rtp_symmetric=yes",
            "force_rport=yes",
            "rewrite_contact=yes",
            "trust_id_inbound=yes",
            f"send_pai={'yes' if header == 'pai' else 'no'}",
            f"send_rpid={'yes' if header == 'rpid' else 'no'}",
            f"dtmf_mode={dtmf}",
            f"set_var=VEYRA_TRUNK={slug}",
        ]
        if t.get("from_user"):
            lines.append(f"from_user={_check_value(str(t['from_user']), 'from user')}")
        if t.get("from_domain"):
            lines.append(f"from_domain={_host(t['from_domain'], f'trunk {slug} from domain')}")
        if t.get("outbound_proxy"):
            proxy = _host(t["outbound_proxy"], f"trunk {slug} outbound proxy")
            lines.append(f"outbound_proxy=sip:{proxy}\\;lr")
        if mode == "registration":
            lines.append(f"outbound_auth={name}")
        lines += [
            "",
            f"[{name}]",
            "type=aor",
            f"contact={contact}",
            f"qualify_frequency={qualify}",
            "",
            f"[{name}]",
            "type=identify",
            f"endpoint={name}",
            f"match={','.join(matches)}",
            "",
        ]
        if mode == "registration":
            username = _check_value(str(t.get("username") or ""), "trunk user name")
            auth_user = _check_value(str(t.get("auth_username") or username), "trunk auth user")
            password = t.get("password")
            if not username or not password:
                raise GenerationError(
                    f"trunk {slug} registers to the carrier but has no user name or password"
                )
            sensitive = True
            expiry = int(t.get("register_expiry") or 3600)
            lines += [
                f"[{name}]",
                "type=auth",
                "auth_type=userpass",
                f"username={auth_user}",
                f"password={_check_value(str(password), 'trunk password')}",
                "",
                f"[{name}]",
                "type=registration",
                f"transport=veyra-transport-{transport}",
                f"outbound_auth={name}",
                f"server_uri=sip:{host}:{port}",
                f"client_uri=sip:{username}@{host}",
                f"contact_user={username}",
                "retry_interval=60",
                "forbidden_retry_interval=600",
                f"expiration={expiry}",
                "line=yes",
                f"endpoint={name}",
                "",
            ]
    return GeneratedFile(FILE_TRUNKS, "\n".join(lines).rstrip("\n") + "\n", sensitive=sensitive)


def _dialplan(
    snapshot: dict[str, Any], extensions: list[dict[str, Any]], trunks: list[dict[str, Any]]
) -> GeneratedFile:
    name = _check_value(str(snapshot.get("installation", {}).get("name") or "Veyra"), "name")
    outbound = list(snapshot.get("outbound_routes") or [])
    inbound = list(snapshot.get("inbound_routes") or [])
    conditions = {str(c["key"]): c for c in (snapshot.get("time_conditions") or [])}
    trunk_slugs = [_check_section(str(t["slug"]), "trunk slug") for t in trunks]
    trunk_info = {str(t["slug"]): t for t in trunks}
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
        "; Extensions first; then feature codes, outbound routes and the catch-all",
        "; (includes are searched in order, after this context's own entries).",
        f"include => {CONTEXT_FEATURES}",
        f"include => {CONTEXT_OUTBOUND}",
        f"include => {CONTEXT_INVALID}",
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
        "",
        f"[{CONTEXT_INVALID}]",
        "exten => _[0-9*#+].,1,NoOp(Veyra: no such extension ${EXTEN})",
        " same => n,Playback(pbx-invalid)",
        " same => n,Hangup()",
        "",
    ]
    lines += _outbound_contexts(outbound, trunk_info)
    lines += _inbound_contexts(inbound, conditions, trunk_slugs)
    return GeneratedFile(FILE_DIALPLAN, "\n".join(lines).rstrip("\n") + "\n")


def _outbound_contexts(
    routes: list[dict[str, Any]], trunks: dict[str, dict[str, Any]]
) -> list[str]:
    """``veyra-outbound`` and one ``veyra-out-<slug>`` per route, emergency
    routes first (docs/TRUNKS_ROUTING.md §4, §6, §7)."""
    ordered = sorted(routes, key=lambda r: not bool(r.get("is_emergency")))
    slugs: list[str] = []
    for r in ordered:
        slug = _check_section(str(r["slug"]), "outbound route slug")
        if slug in slugs:
            raise GenerationError(f"duplicate outbound route slug {slug!r}")
        slugs.append(slug)
    lines = [f"[{CONTEXT_OUTBOUND}]", "; Routes in evaluation order; emergency routes first."]
    lines += [f"include => {CONTEXT_OUT_PREFIX}{slug}" for slug in slugs]
    lines.append("")
    for r, slug in zip(ordered, slugs, strict=True):
        emergency = bool(r.get("is_emergency"))
        route_trunks = [str(t) for t in (r.get("trunks") or []) if str(t) in trunks]
        cid_override = r.get("caller_id_number")
        if cid_override and not _NUMBER_RE.match(str(cid_override)):
            raise GenerationError(f"outbound route {slug}: caller ID {cid_override!r} is not valid")
        lines += [
            f"[{CONTEXT_OUT_PREFIX}{slug}]",
            f"; {_check_value(str(r.get('name') or slug), 'route name')}"
            + (" (emergency)" if emergency else ""),
        ]
        for pat in r.get("patterns") or []:
            try:
                prefix, match, prepend = routing.check_pattern(
                    str(pat.get("prefix") or ""),
                    str(pat.get("match") or ""),
                    str(pat.get("prepend") or ""),
                )
            except ValueError as e:
                raise GenerationError(f"outbound route {slug}: {e}") from e
            exten = routing.exten_for(prefix, match)
            strip = f":{len(prefix)}" if prefix else ""
            lines += [
                f"exten => {exten},1,NoOp(Veyra outbound route {slug})",
                f" same => n,Set(__VEYRA_ROUTE={slug})",
            ]
            if emergency:
                lines += [
                    " same => n,Set(__VEYRA_EMERGENCY=1)",
                    " same => n,Log(WARNING,Veyra EMERGENCY call from ${CALLERID(num)}"
                    " to ${EXTEN})",
                ]
            else:
                lines.append(" same => n,GotoIf($[0${VEYRA_HOPS} > 0]?loop)")
            lines.append(f" same => n,Set(VEYRA_DIAL={prepend}${{EXTEN{strip}}})")
            timeout = EMERGENCY_DIAL_TIMEOUT if emergency else OUTBOUND_DIAL_TIMEOUT
            if not route_trunks:
                lines.append(" same => n,Goto(failed)")
            for i, tslug in enumerate(route_trunks):
                label = f"t{i + 1}" if i else None
                nxt = f"t{i + 2}" if i + 1 < len(route_trunks) else "failed"
                trunk = trunks[tslug]
                cid = cid_override or trunk.get("default_caller_id")
                first = f" same => n({label})," if label else " same => n,"
                step = [f"{first}Set(GROUP(veyra_trunk)={tslug})"]
                if trunk.get("max_channels") and not emergency:
                    step.append(
                        f" same => n,GotoIf($[${{GROUP_COUNT({tslug}@veyra_trunk)}} > "
                        f"{int(trunk['max_channels'])}]?{nxt})"
                    )
                if cid:
                    if not _NUMBER_RE.match(str(cid)):
                        raise GenerationError(f"trunk {tslug}: caller ID {cid!r} is not valid")
                    step.append(f" same => n,Set(CALLERID(num)={cid})")
                step += [
                    f" same => n,Dial(PJSIP/${{VEYRA_DIAL}}@{TRUNK_PREFIX}{tslug},{timeout})",
                    ' same => n,GotoIf($["${DIALSTATUS}"="CHANUNAVAIL"'
                    f' | "${{DIALSTATUS}}"="CONGESTION"]?{nxt})',
                    " same => n,Hangup()",
                ]
                lines += step
            lines += [
                " same => n(failed),NoOp(Veyra: no trunk could carry the call)",
                " same => n,Playback(all-circuits-busy)",
                " same => n,Congestion(5)",
                " same => n,Hangup()",
            ]
            if not emergency:
                lines += [
                    " same => n(loop),NoOp(Veyra: a trunk call may not leave through a trunk)",
                    " same => n,Hangup(21)",
                ]
        lines.append("")
    return lines


def _inbound_contexts(
    routes: list[dict[str, Any]], conditions: dict[str, dict[str, Any]], trunk_slugs: list[str]
) -> list[str]:
    """``veyra-from-trunk`` (shared DIDs), one ``veyra-from-trunk-<slug>`` per
    trunk (its restricted DIDs, then the shared ones, then its fallback), and
    ``veyra-from-trunk-<slug>-fallback`` (docs/TRUNKS_ROUTING.md §3)."""
    shared: list[dict[str, Any]] = []
    per_trunk: dict[str, list[dict[str, Any]]] = {s: [] for s in trunk_slugs}
    claimed: set[tuple[str | None, str]] = set()
    for r in routes:
        did = routing.normalize_did(str(r.get("did") or ""))
        trunk = r.get("trunk")
        trunk = str(trunk) if trunk else None
        if trunk is not None and trunk not in per_trunk:
            continue  # the trunk is disabled or gone; the route waits
        key = (trunk, routing.canonical_did(did))
        if key in claimed:
            raise GenerationError(f"DID {did} is routed more than once")
        claimed.add(key)
        entry = {**r, "did": did}
        (per_trunk[trunk] if trunk else shared).append(entry)
    explicit = {(r.get("trunk") or None, r["did"]) for r in shared}
    for slug, rs in per_trunk.items():
        explicit |= {(slug, r["did"]) for r in rs}

    def body(r: dict[str, Any], context: str) -> list[str]:
        did = r["did"]
        if did == routing.DID_ANY:
            return []  # rendered by the fallback context
        out = [
            f"exten => {did},1,NoOp(Veyra inbound {did} via ${{VEYRA_TRUNK}})",
            " same => n,Set(__VEYRA_HOPS=1)",
            f" same => n,Set(__VEYRA_DID={did})",
        ]
        out += _destination_lines(r, conditions)
        for alias in routing.did_aliases(did):
            if (r.get("trunk") or None, alias) not in explicit:
                out.append(f"exten => {alias},1,Goto({context},{did},1)")
        return out

    lines = [f"[{CONTEXT_FROM_TRUNK}]", "; DIDs that match on every trunk."]
    for r in shared:
        lines += body(r, CONTEXT_FROM_TRUNK)
    lines.append("")
    shared_any = next((r for r in shared if r["did"] == routing.DID_ANY), None)
    for slug in trunk_slugs:
        ctx = f"{CONTEXT_FROM_TRUNK_PREFIX}{slug}"
        lines += [f"[{ctx}]", f"include => {CONTEXT_FROM_TRUNK}", f"include => {ctx}-fallback"]
        for r in per_trunk[slug]:
            lines += body(r, ctx)
        lines.append("")
        trunk_any = next((r for r in per_trunk[slug] if r["did"] == routing.DID_ANY), None)
        catch = trunk_any or shared_any
        lines.append(f"[{ctx}-fallback]")
        if catch is not None:
            for exten in ("_[0-9+*#].", "s"):
                lines += [
                    f"exten => {exten},1,NoOp(Veyra inbound ${{EXTEN}} via ${{VEYRA_TRUNK}}: any)",
                    " same => n,Set(__VEYRA_HOPS=1)",
                    " same => n,Set(__VEYRA_DID=${EXTEN})",
                ]
                lines += _destination_lines(catch, conditions)
        else:
            lines += [
                "exten => _[0-9+*#].,1,NoOp(Veyra: no inbound route for ${EXTEN} on trunk)",
                " same => n,Hangup(1)",
                "exten => s,1,NoOp(Veyra: inbound call without a number via ${VEYRA_TRUNK})",
                " same => n,Hangup(1)",
            ]
        lines.append("")
    return lines


def _destination_lines(r: dict[str, Any], conditions: dict[str, dict[str, Any]]) -> list[str]:
    out = []
    prefix = r.get("caller_id_prefix")
    if prefix:
        out.append(f" same => n,Set(CALLERID(name)={_prefix(str(prefix))}${{CALLERID(name)}})")
    dest = r.get("destination")
    if dest is not None and not _NUMBER_RE.match(str(dest)):
        raise GenerationError(f"inbound route {r.get('did')}: destination {dest!r} is not valid")
    after = r.get("after_hours")
    if after is not None and not _NUMBER_RE.match(str(after)):
        raise GenerationError(f"inbound route {r.get('did')}: destination {after!r} is not valid")
    cond_key = r.get("time_condition")
    cond = conditions.get(str(cond_key)) if cond_key else None
    if cond is not None:
        tz = routing.check_timezone(str(cond.get("timezone") or "UTC"))
        closed, opened = routing.gotoiftime_args(
            routing.check_ranges(list(cond.get("ranges") or [])),
            routing.check_holidays(list(cond.get("holidays") or [])),
            tz,
        )
        out += [f" same => n,GotoIfTime({args}?closed)" for args in closed]
        out += [f" same => n,GotoIfTime({args}?open)" for args in opened]
        out.append(" same => n(closed),NoOp(Veyra: outside the hours of ${VEYRA_DID})")
        out += _goto(after)
        out.append(" same => n(open),NoOp(Veyra: inside the hours of ${VEYRA_DID})")
        out += _goto(dest)
    else:
        out += _goto(dest)
    return out


def _goto(number: Any) -> list[str]:
    if number is None:
        return [
            " same => n,NoOp(Veyra: this route has no destination)",
            " same => n,Congestion(5)",
            " same => n,Hangup()",
        ]
    return [f" same => n,Goto({CONTEXT_INTERNAL},{number},1)", " same => n,Hangup()"]


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
