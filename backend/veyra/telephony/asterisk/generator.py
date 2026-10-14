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

import json
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
FILE_VOICEMAIL = "voicemail.conf"
FILE_QUEUES = "queues.conf"
FILE_NOTIFY = "pjsip_notify.conf"
FILE_PAGING = "paging.json"
FILE_MOH = "musiconhold.conf"
MANAGED_FILES = [
    FILE_TRANSPORTS,
    FILE_ENDPOINTS,
    FILE_TRUNKS,
    FILE_DIALPLAN,
    FILE_RTP,
    FILE_VOICEMAIL,
    FILE_QUEUES,
    FILE_NOTIFY,
    FILE_PAGING,
    FILE_MOH,
]

# Module reload per file. Order matters: transports before endpoints is the
# same module, so it collapses; the dialplan is independent.
RELOAD_SCOPES: dict[str, str] = {
    FILE_TRANSPORTS: "res_pjsip.so",
    FILE_ENDPOINTS: "res_pjsip.so",
    FILE_TRUNKS: "res_pjsip.so",
    FILE_DIALPLAN: "pbx_config.so",
    FILE_RTP: "res_rtp_asterisk.so",
    FILE_VOICEMAIL: "app_voicemail.so",
    FILE_QUEUES: "app_queue.so",
    FILE_NOTIFY: "res_pjsip_notify.so",
    FILE_MOH: "res_musiconhold.so",
}
SCOPE_ORDER = [
    "res_rtp_asterisk.so",
    "res_pjsip.so",
    "pbx_config.so",
    "app_voicemail.so",
    "app_queue.so",
    "res_pjsip_notify.so",
    "res_musiconhold.so",
]

CONTEXT_INTERNAL = "veyra-internal"
CONTEXT_FEATURES = "veyra-features"
CONTEXT_PAGING = "veyra-paging"
CONTEXT_PAGE_PLAY = "veyra-page-play"
PAGER_HOST = "127.0.0.1"
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
# IVR menus: one context per menu (docs/VOICEMAIL_IVR.md §5).
CONTEXT_IVR_PREFIX = "veyra-ivr-"
# Ring groups and queues: one context each (docs/RING_GROUPS_QUEUES.md §2, §3);
# the queue name in queues.conf carries the same prefix as the pickup groups
# so nothing of Veyra's collides with hand-written Asterisk configuration.
CONTEXT_RING_GROUP_PREFIX = "veyra-rg-"
CONTEXT_QUEUE_PREFIX = "veyra-queue-"
QUEUE_NAME_PREFIX = "veyra-"
MAX_GROUP_DEPTH = 6
RING_GROUP_STRATEGIES = ("ringall", "sequential")
QUEUE_STRATEGIES = ("ringall", "rrmemory", "leastrecent", "fewestcalls", "random", "linear")
QUEUE_MUSIC = ("default", "ring")
# Device states of a member that is already on a call (skipped unless the
# group rings busy members).
BUSY_STATES = "(INUSE|BUSY|RINGINUSE)"
# Voicemail context in voicemail.conf; mailbox number = extension number.
VOICEMAIL_CONTEXT = "veyra"
OUTBOUND_DIAL_TIMEOUT = 60
EMERGENCY_DIAL_TIMEOUT = 120
DEFAULT_RING_SECONDS = 30
# Where the prompts live and the script Asterisk hands notifications to;
# the adapter passes the installation's paths (veyra.core.config).
DEFAULT_PROMPTS_DIR = "/var/lib/veyra/prompts"
DEFAULT_MOH_DIR = "/var/lib/veyra/moh"
# Engine class of a hold music set (docs/PAGING_RECORDINGS.md §3.2).
MOH_CLASS_PREFIX = "veyra-"
MOH_BUILTIN = "default"
DEFAULT_MAILQUEUE_COMMAND = "/opt/veyra/current/installer/bin/veyra-mailqueue"
PROMPT_RECORD_MAX_SECONDS = 300
PROMPT_RECORD_SILENCE = 5

_SECTION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_NUMBER_RE = re.compile(r"^[0-9*#+]{1,32}$")
_SAFE_VALUE_RE = re.compile(r"^[^\r\n\[\];]*$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_PIN_RE = re.compile(r"^[0-9]{4,10}$")
_PATH_RE = re.compile(r"^/[A-Za-z0-9_./-]+$")
_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


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


def _slug(value: Any, what: str) -> str:
    v = str(value)
    if not _SLUG_RE.match(v):
        raise GenerationError(f"{what} {v!r} is not a valid slug")
    return v


def _path(value: str, what: str) -> str:
    if not _PATH_RE.match(value):
        raise GenerationError(f"{what} {value!r} is not an acceptable path")
    return value.rstrip("/")


def _page_dial(zones: list[dict[str, Any]], slugs: list[str], max_seconds: int) -> str:
    """The ``Page()`` line for ``slugs``: one sender port per zone."""
    by_slug = {str(z["slug"]): z for z in zones}
    targets = "&".join(
        f"MulticastRTP/basic/{PAGER_HOST}:{int(by_slug[slug]['port'])}"
        for slug in slugs
        if slug in by_slug
    )
    return f" same => n,Page({targets},i,{int(max_seconds)})"


def _allowed_lines(entry: dict[str, Any], org: str) -> list[str]:
    """Organization check plus the ``allowed`` policy (docs/PAGING_RECORDINGS.md §2.4)."""
    out = [f' same => n,GotoIf($["${{VEYRA_ORG}}"!="{org}"]?denied)']
    allowed = str(entry.get("allowed") or "everyone")
    if allowed == "administrators":
        out.append(' same => n,GotoIf($["${VEYRA_PAGE_BY}"!="veyra"]?denied)')
    elif allowed == "members":
        members = [_check_value(str(n), "member number") for n in entry.get("members") or []]
        if not members:
            out.append(" same => n,Goto(denied)")
        else:
            pattern = "|".join(members)
            out.append(
                f' same => n,GotoIf($["${{VEYRA_PAGE_BY}}"!="veyra" & '
                f'!${{REGEX("^({pattern})$" ${{CALLERID(num)}})}}]?denied)'
            )
    return out


def _paging_contexts(paging: dict[str, Any], prompts: str) -> list[str]:
    """``veyra-paging`` (zone and page numbers dialled from phones) and
    ``veyra-page-play`` (recordings played into a page by Veyra)."""
    zones = list(paging.get("zones") or [])
    pages = list(paging.get("pages") or [])
    lines = [
        f"[{CONTEXT_PAGING}]",
        "; Paging zones and pages dialled from phones (docs/PAGING_RECORDINGS.md §2.3).",
    ]
    seen: set[str] = set()
    for z in zones:
        number = z.get("number")
        if not number:
            continue
        number = _check_value(str(number), "zone number")
        if number in seen:
            raise GenerationError(f"paging number {number} is used twice")
        seen.add(number)
        org = _check_value(str(z.get("organization") or ""), "organization")
        slug = _check_section(str(z["slug"]), "zone slug")
        lines += [
            f"exten => {number},1,NoOp(Veyra page zone {slug} by ${{CALLERID(num)}})",
            *_allowed_lines(z, org),
            " same => n,Playback(beep)",
            _page_dial(zones, [slug], int(z.get("max_seconds") or 120)),
            " same => n,Hangup()",
            " same => n(denied),NoOp(Veyra: not allowed to page)",
            " same => n,Playback(pbx-invalid)",
            " same => n,Hangup()",
        ]
    for p in pages:
        number = p.get("number")
        if not number:
            continue
        number = _check_value(str(number), "page number")
        if number in seen:
            raise GenerationError(f"paging number {number} is used twice")
        seen.add(number)
        org = _check_value(str(p.get("organization") or ""), "organization")
        slug = _check_section(str(p["slug"]), "page slug")
        zone_slugs = [str(x) for x in p.get("zones") or []]
        lines += [
            f"exten => {number},1,NoOp(Veyra page {slug} by ${{CALLERID(num)}})",
            *_allowed_lines(p, org),
        ]
        if not zone_slugs:
            lines.append(" same => n,Goto(denied)")
        elif p.get("audio"):
            # A recorded page: start the play leg and let the caller go.
            lines += [
                f" same => n,Originate(Local/play-{slug}@{CONTEXT_PAGE_PLAY},exten,"
                f"{CONTEXT_PAGE_PLAY},{slug},1,,a)",
                " same => n,Playback(beep)",
            ]
        else:
            if p.get("pre_tone", True):
                lines.append(" same => n,Playback(beep)")
            lines.append(_page_dial(zones, zone_slugs, int(p.get("max_seconds") or 120)))
        lines += [
            " same => n,Hangup()",
            " same => n(denied),NoOp(Veyra: not allowed to page)",
            " same => n,Playback(pbx-invalid)",
            " same => n,Hangup()",
        ]
    lines += [
        "",
        f"[{CONTEXT_PAGE_PLAY}]",
        "; Recorded pages: the far leg plays the recording into the Page().",
    ]
    for p in pages:
        if not p.get("audio") or not p.get("zones"):
            continue
        slug = _check_section(str(p["slug"]), "page slug")
        org = _check_value(str(p.get("organization") or ""), "organization")
        audio = _check_section(str(p["audio"]), "audio slug")
        repeat = max(1, min(5, int(p.get("repeat") or 1)))
        zone_slugs = [str(x) for x in p.get("zones") or []]
        # The near leg of Local/play-<slug> runs Page() with the far leg's
        # playback as its audio (originated by the API, a bell or a phone).
        lines += [
            f"exten => {slug},1,NoOp(Veyra recorded page {slug})",
            " same => n,Answer()",
            _page_dial(zones, zone_slugs, int(p.get("max_seconds") or 120)),
            " same => n,Hangup()",
            f"exten => play-{slug},1,NoOp(Veyra plays {audio} into page {slug})",
            " same => n,Answer()",
            *([" same => n,Playback(beep)"] if p.get("pre_tone", True) else []),
            *[f" same => n,Playback({prompts}/{org}/{audio})" for _ in range(repeat)],
            " same => n,Hangup()",
        ]
    lines.append("")
    return lines


def _paging_json(paging: dict[str, Any]) -> GeneratedFile:
    """The sender's zone table (docs/PAGING_RECORDINGS.md §2.2)."""
    doc = {
        "defaults": paging.get("defaults") or {"delay_ms": 200, "ttl": 1},
        "zones": [
            {
                k: z[k]
                for k in (
                    "slug",
                    "organization",
                    "port",
                    "multicast_address",
                    "multicast_port",
                    "poly_address",
                    "poly_port",
                    "poly_group",
                    "kind",
                )
            }
            for z in paging.get("zones") or []
        ],
    }
    return GeneratedFile(FILE_PAGING, json.dumps(doc, indent=2, sort_keys=True) + "\n")


def _notify_conf() -> GeneratedFile:
    """``pjsip_notify.conf``: the NOTIFY types the device pages send with
    ``pjsip send notify`` (docs/DEVICE_PROVISIONING.md §3.5). ``check-sync``
    makes Poly and Yealink phones re-read their configuration; with
    ``reboot=true`` Yealink phones restart (Poly phones restart when the
    configuration changed)."""
    lines = [
        HEADER,
        "; NOTIFY types for device management: pjsip send notify <type> endpoint <endpoint>",
        "",
        "[veyra-check-config]",
        "Event=>check-sync;reboot=false",
        "Content-Length=>0",
        "",
        "[veyra-reboot]",
        "Event=>check-sync;reboot=true",
        "Content-Length=>0",
    ]
    return GeneratedFile(FILE_NOTIFY, "\n".join(lines) + "\n")


def generate(
    snapshot: dict[str, Any],
    *,
    prompts_dir: str = DEFAULT_PROMPTS_DIR,
    mailqueue_command: str = DEFAULT_MAILQUEUE_COMMAND,
    moh_dir: str = DEFAULT_MOH_DIR,
) -> list[GeneratedFile]:
    sip = SipSettings.model_validate(snapshot.get("sip") or {})
    problems = sip.problems()
    if problems:
        raise GenerationError("; ".join(problems))
    extensions = list(snapshot.get("extensions") or [])
    trunks = list(snapshot.get("trunks") or [])
    boxes = _check_boxes(list(snapshot.get("voicemail_boxes") or []), extensions)
    prompts = _path(prompts_dir, "prompts directory")
    ring_groups = list(snapshot.get("ring_groups") or [])
    queues = list(snapshot.get("queues") or [])
    _check_group_numbers(extensions, ring_groups, queues)
    moh = _check_moh(list(snapshot.get("hold_music") or []))
    org_moh = {
        str(o["slug"]): _moh_class(o.get("hold_music"), moh, f"organization {o['slug']}")
        for o in (snapshot.get("organizations") or [])
        if o.get("hold_music")
    }
    return [
        _transports(sip),
        _endpoints(
            sip,
            extensions,
            set(boxes),
            dict(snapshot.get("shared_mailboxes") or {}),
            org_moh,
        ),
        _trunks(sip, trunks),
        _dialplan(snapshot, extensions, trunks, boxes, prompts),
        _rtp(sip),
        _voicemail(snapshot, boxes, _path(mailqueue_command, "mail queue command")),
        _queues(queues, extensions, prompts, moh),
        _notify_conf(),
        _paging_json(snapshot.get("paging") or {}),
        _moh_conf(moh, _path(moh_dir, "hold music directory")),
    ]


def _check_moh(sets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Hold music sets by slug (docs/PAGING_RECORDINGS.md §3.2)."""
    out: dict[str, dict[str, Any]] = {}
    for m in sets:
        slug = _slug(str(m.get("slug") or ""), "hold music slug")
        if slug in out:
            raise GenerationError(f"duplicate hold music slug {slug!r}")
        for f in m.get("files") or []:
            if not _FILE_RE.match(str(f)):
                raise GenerationError(f"hold music set {slug}: file name {f!r} is not valid")
        out[slug] = m
    return out


def _moh_class(slug: Any, moh: dict[str, dict[str, Any]], what: str) -> str:
    """The engine class for a set slug; the built-in class when none."""
    if not slug:
        return MOH_BUILTIN
    slug = _slug(str(slug), f"hold music of {what}")
    if slug not in moh:
        raise GenerationError(f"{what}: hold music set {slug!r} is not in the snapshot")
    return f"{MOH_CLASS_PREFIX}{slug}"


def _moh_conf(moh: dict[str, dict[str, Any]], moh_dir: str) -> GeneratedFile:
    """``musiconhold.conf``: one ``[veyra-<slug>]`` files class per set. The
    track list is written as a comment so a changed set changes the file and
    the deployer reloads ``res_musiconhold.so`` (which rescans the
    directories); the installer's stub keeps the built-in ``default``."""
    lines = [HEADER, "; Hold music sets (docs/PAGING_RECORDINGS.md §3.2).", ""]
    for slug, m in sorted(moh.items()):
        name = _check_value(str(m.get("name") or slug), "hold music name")
        org = _slug(str(m.get("organization") or ""), f"organization of hold music {slug}")
        files = [str(f) for f in (m.get("files") or [])]
        lines += [
            f"[{MOH_CLASS_PREFIX}{slug}]",
            f"; {name} ({org}); tracks: {', '.join(files) or 'none'}",
            "mode=files",
            f"directory={moh_dir}/{slug}",
            f"sort={'random' if m.get('random') else 'alpha'}",
            "",
        ]
    return GeneratedFile(FILE_MOH, "\n".join(lines).rstrip("\n") + "\n")


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


def _endpoints(
    sip: SipSettings,
    extensions: list[dict[str, Any]],
    mailboxes: set[str] | None = None,
    shared_mailboxes: dict[str, list[str]] | None = None,
    org_moh: dict[str, str] | None = None,
) -> GeneratedFile:
    allow = ",".join(sip.codecs)
    mailboxes = mailboxes or set()
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
        # Emergency caller ID (docs/TRUNKS_ROUTING.md §7): read by the
        # emergency routes, which present it instead of the route's number.
        ecid = ext.get("emergency_caller_id_number")
        if ecid and not _NUMBER_RE.match(str(ecid)):
            raise GenerationError(f"emergency caller ID {ecid!r} is not valid")
        emergency_cid = [f"set_var=VEYRA_EMERGENCY_CID={ecid}"] if ecid else []
        # Message waiting indication: the phone subscribes to, or is notified
        # about, its own mailbox (docs/VOICEMAIL_IVR.md §3.2).
        # Own box plus the shared inboxes the phone's lamp follows
        # (docs/PAGING_RECORDINGS.md §5).
        boxes_of_phone = ([number] if number in mailboxes else []) + [
            _check_value(str(n), "shared inbox number")
            for n in (shared_mailboxes or {}).get(number, [])
        ]
        mwi = (
            [f"mailboxes={','.join(f'{n}@{VOICEMAIL_CONTEXT}' for n in boxes_of_phone)}"]
            if boxes_of_phone
            else []
        )
        # Pickup groups (docs/RING_GROUPS_QUEUES.md §4): the phone can be
        # picked up by, and can pick up, every member of its groups.
        groups = ",".join(
            sorted(_slug(g, f"pickup group of {number}") for g in (ext.get("pickup_groups") or []))
        )
        pickup = [f"named_call_group={groups}", f"named_pickup_group={groups}"] if groups else []
        # Several phones may carry one extension (docs/DEVICE_PROVISIONING.md §2).
        max_contacts = int(ext.get("max_contacts") or 1)
        if not 1 <= max_contacts <= 16:
            raise GenerationError(f"endpoint {name!r}: max_contacts {max_contacts} out of range")
        contacts = [f"max_contacts={max_contacts}"] if max_contacts > 1 else []
        # The organization's hold music set, heard by callers this phone
        # puts on hold (docs/PAGING_RECORDINGS.md §3.2).
        moh_class = (org_moh or {}).get(org)
        moh = [f"moh_suggest={_check_section(moh_class, 'hold music class')}"] if moh_class else []
        lines += [
            f"; {org} {number}",
            f"[{name}](veyra-endpoint)",
            f"auth={name}",
            f"aors={name}",
            f'callerid="{cid_name}" <{cid_num}>',
            f"set_var=VEYRA_ORG={org}",
            *emergency_cid,
            *moh,
            *mwi,
            *(["mwi_subscribe_replaces_unsolicited=yes"] if mwi else []),
            *pickup,
            "",
            f"[{name}](veyra-auth)",
            f"username={name}",
            f"password={_check_value(str(secret), 'SIP secret')}",
            "",
            f"[{name}](veyra-aor)",
            *contacts,
            *mwi,
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
    snapshot: dict[str, Any],
    extensions: list[dict[str, Any]],
    trunks: list[dict[str, Any]],
    boxes: dict[str, dict[str, Any]] | None = None,
    prompts_dir: str = DEFAULT_PROMPTS_DIR,
) -> GeneratedFile:
    name = _check_value(str(snapshot.get("installation", {}).get("name") or "Veyra"), "name")
    outbound = list(snapshot.get("outbound_routes") or [])
    inbound = list(snapshot.get("inbound_routes") or [])
    menus = list(snapshot.get("ivr_menus") or [])
    ring_groups = list(snapshot.get("ring_groups") or [])
    queues = list(snapshot.get("queues") or [])
    boxes = boxes if boxes is not None else {}
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
        "; *97 own voicemail box, *98 any box (mailbox and PIN asked).",
        "exten => *97,1,NoOp(Veyra voicemail for ${CALLERID(num)})",
        " same => n,Answer()",
        f" same => n,VoiceMailMain(${{CALLERID(num)}}@{VOICEMAIL_CONTEXT})",
        " same => n,Hangup()",
        "exten => *98,1,NoOp(Veyra voicemail, any box)",
        " same => n,Answer()",
        f" same => n,VoiceMailMain(@{VOICEMAIL_CONTEXT})",
        " same => n,Hangup()",
        "; *95 records a prompt from the phone into the organization's incoming",
        "; folder; it is named and adopted on the Prompts page (VOICEMAIL_IVR.md §4).",
        "exten => *95,1,NoOp(Veyra prompt recording from ${CALLERID(num)})",
        " same => n,Answer()",
        " same => n,Wait(1)",
        f" same => n,Set(VEYRA_REC={prompts_dir}/${{VEYRA_ORG}}/incoming/"
        "rec-${CALLERID(num)}-${EPOCH})",
        f" same => n(record),Record(${{VEYRA_REC}}.wav,{PROMPT_RECORD_SILENCE},"
        f"{PROMPT_RECORD_MAX_SECONDS},k)",
        " same => n(review),Wait(1)",
        " same => n,Playback(${VEYRA_REC})",
        " same => n,Read(VEYRA_CHOICE,vm-review,1,,1,5)",
        ' same => n,GotoIf($["${VEYRA_CHOICE}"="2"]?review)',
        ' same => n,GotoIf($["${VEYRA_CHOICE}"="3"]?record)',
        " same => n,Playback(vm-msgsaved)",
        " same => n,Playback(vm-goodbye)",
        " same => n,Hangup()",
        "; *8 answers a call ringing on another phone of the caller's pickup groups;",
        "; **<extension> answers the call ringing on that phone of the caller's",
        "; organization (docs/RING_GROUPS_QUEUES.md §4).",
        "exten => *8,1,NoOp(Veyra group pickup by ${CALLERID(num)})",
        " same => n,Pickup()",
        " same => n,Hangup()",
    ]
    for ext in extensions:
        number = str(ext["number"])
        endpoint = str(ext["endpoint_name"])
        org = _check_value(str(ext.get("organization") or ""), "organization")
        lines += [
            f"exten => **{number},1,NoOp(Veyra directed pickup of {number} by ${{CALLERID(num)}})",
            f' same => n,GotoIf($["${{VEYRA_ORG}}"!="{org}"]?denied)',
            f" same => n,PickupChan(PJSIP/{endpoint},,p)",
            " same => n,Hangup()",
            " same => n(denied),Playback(pbx-invalid)",
            " same => n,Hangup()",
        ]
    lines += [
        "",
        f"[{CONTEXT_INTERNAL}]",
        "; Extensions first; then feature codes, outbound routes and the catch-all",
        "; (includes are searched in order, after this context's own entries).",
        f"include => {CONTEXT_FEATURES}",
        f"include => {CONTEXT_PAGING}",
        f"include => {CONTEXT_OUTBOUND}",
        f"include => {CONTEXT_INVALID}",
    ]
    for ext in extensions:
        number = str(ext["number"])
        endpoint = str(ext["endpoint_name"])
        box = boxes.get(number)
        # The hint lets busy lamp fields follow the phone (RING_GROUPS_QUEUES.md §4.2).
        lines.append(f"exten => {number},hint,PJSIP/{endpoint}")
        if box is None:
            lines += [
                f"exten => {number},1,NoOp(Veyra extension {number})",
                f" same => n,Dial(PJSIP/{endpoint},{DEFAULT_RING_SECONDS})",
                " same => n,Hangup()",
            ]
        else:
            # Unanswered and unavailable go to the unavailable greeting, busy
            # to the busy greeting (docs/VOICEMAIL_IVR.md §3.2).
            lines += [
                f"exten => {number},1,NoOp(Veyra extension {number})",
                f" same => n,Dial(PJSIP/{endpoint},{int(box['ring_seconds'])})",
                ' same => n,GotoIf($["${DIALSTATUS}"="BUSY"]?busy)',
                f" same => n,VoiceMail({number}@{VOICEMAIL_CONTEXT},u)",
                " same => n,Hangup()",
                f" same => n(busy),VoiceMail({number}@{VOICEMAIL_CONTEXT},b)",
                " same => n,Hangup()",
            ]
    for number, b in sorted(boxes.items(), key=lambda kv: (len(kv[0]), kv[0])):
        if not b.get("shared"):
            continue
        lines += [
            f"exten => {number},1,NoOp(Veyra shared inbox {number})",
            f" same => n,VoiceMail({number}@{VOICEMAIL_CONTEXT},u)",
            " same => n,Hangup()",
        ]
    for g in ring_groups:
        slug = _slug(g["slug"], "ring group slug")
        number = str(g["number"])
        name = _check_value(str(g.get("name") or slug), "ring group name")
        members = [str(m["endpoint_name"]) for m in (g.get("members") or [])]
        if members:
            lines.append(f"exten => {number},hint," + "&".join(f"PJSIP/{m}" for m in members))
        lines += [
            f"exten => {number},1,NoOp(Veyra ring group {name})",
            f" same => n,Goto({CONTEXT_RING_GROUP_PREFIX}{slug},s,1)",
        ]
    for q in queues:
        slug = _slug(q["slug"], "queue slug")
        number = str(q["number"])
        name = _check_value(str(q.get("name") or slug), "queue name")
        lines += [
            f"exten => {number},1,NoOp(Veyra queue {name})",
            f" same => n,Goto({CONTEXT_QUEUE_PREFIX}{slug},s,1)",
        ]
    lines += [
        "",
        f"[{CONTEXT_INVALID}]",
        "exten => _[0-9*#+].,1,NoOp(Veyra: no such extension ${EXTEN})",
        " same => n,Playback(pbx-invalid)",
        " same => n,Hangup()",
        "",
    ]
    lines += _paging_contexts(snapshot.get("paging") or {}, prompts_dir)
    lines += _outbound_contexts(outbound, trunk_info)
    lines += _inbound_contexts(inbound, conditions, trunk_slugs)
    lines += _ivr_contexts(menus, prompts_dir)
    lines += _ring_group_contexts(ring_groups, _check_moh(list(snapshot.get("hold_music") or [])))
    lines += _queue_contexts(queues, prompts_dir)
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
                # The extension's emergency caller ID wins over the route's
                # and the trunk's numbers (docs/TRUNKS_ROUTING.md §7).
                lines += [
                    " same => n,Set(__VEYRA_EMERGENCY=1)",
                    " same => n,Log(WARNING,Veyra EMERGENCY call from ${CALLERID(num)}"
                    ' to ${EXTEN}; extension emergency caller ID: ${IF($["${VEYRA_EMERGENCY_CID}"'
                    '!=""]?${VEYRA_EMERGENCY_CID}:none)})',
                    ' same => n,ExecIf($["${VEYRA_EMERGENCY_CID}"!=""]'
                    "?Set(CALLERID(num)=${VEYRA_EMERGENCY_CID}))",
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
                    if emergency:
                        step.append(
                            ' same => n,ExecIf($["${VEYRA_EMERGENCY_CID}"=""]'
                            f"?Set(CALLERID(num)={cid}))"
                        )
                    else:
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
    after = r.get("after_hours")
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


def _goto(dest: Any) -> list[str]:
    """Dialplan lines that send the call to a destination: an extension
    number (string, Milestone 6 form), or a typed destination
    (docs/VOICEMAIL_IVR.md §6). Missing targets answer with congestion."""
    if dest is None:
        return [
            " same => n,NoOp(Veyra: this route has no destination)",
            " same => n,Congestion(5)",
            " same => n,Hangup()",
        ]
    if not isinstance(dest, dict):
        dest = {"type": "extension", "number": dest}
    kind = str(dest.get("type") or "extension")
    if kind == "hangup":
        return [" same => n,Playback(vm-goodbye)", " same => n,Hangup()"]
    if kind == "ivr":
        slug = _slug(dest.get("ivr"), "IVR menu slug")
        return [f" same => n,Goto({CONTEXT_IVR_PREFIX}{slug},s,1)", " same => n,Hangup()"]
    if kind == "ring_group":
        slug = _slug(dest.get("ring_group"), "ring group slug")
        return [f" same => n,Goto({CONTEXT_RING_GROUP_PREFIX}{slug},s,1)", " same => n,Hangup()"]
    if kind == "queue":
        slug = _slug(dest.get("queue"), "queue slug")
        return [f" same => n,Goto({CONTEXT_QUEUE_PREFIX}{slug},s,1)", " same => n,Hangup()"]
    if kind in ("extension", "voicemail"):
        number = str(dest.get("number") or "")
        if not _NUMBER_RE.match(number):
            raise GenerationError(f"destination number {number!r} is not valid")
        if kind == "voicemail":
            return [
                f" same => n,VoiceMail({number}@{VOICEMAIL_CONTEXT},u)",
                " same => n,Hangup()",
            ]
        return [f" same => n,Goto({CONTEXT_INTERNAL},{number},1)", " same => n,Hangup()"]
    return [
        " same => n,NoOp(Veyra: the destination no longer exists)",
        " same => n,Congestion(5)",
        " same => n,Hangup()",
    ]


def _ivr_contexts(menus: list[dict[str, Any]], prompts_dir: str) -> list[str]:
    """One ``veyra-ivr-<slug>`` per enabled menu (docs/VOICEMAIL_IVR.md §5)."""
    lines: list[str] = []
    seen: set[str] = set()
    for m in menus:
        slug = _slug(m["slug"], "IVR menu slug")
        if slug in seen:
            raise GenerationError(f"duplicate IVR menu slug {slug!r}")
        seen.add(slug)
        name = _check_value(str(m.get("name") or slug), "IVR menu name")
        org = _slug(m.get("organization") or "", f"organization of IVR menu {slug}")
        ctx = f"{CONTEXT_IVR_PREFIX}{slug}"
        timeout = min(max(int(m.get("timeout_seconds") or 5), 1), 30)
        retries = min(max(int(m.get("max_retries") or 3), 1), 9)
        prompt = m.get("prompt")
        lines += [f"[{ctx}]", f"; {name} ({org})"]
        if not prompt:
            lines += [
                f"exten => s,1,NoOp(Veyra IVR {name}: no prompt, menu not deployable)",
                " same => n,Congestion(5)",
                " same => n,Hangup()",
                "",
            ]
            continue
        prompt_path = f"{prompts_dir}/{org}/{_slug(prompt, 'prompt slug')}"
        invalid = m.get("invalid_prompt")
        invalid_path = (
            f"{prompts_dir}/{org}/{_slug(invalid, 'prompt slug')}" if invalid else "pbx-invalid"
        )
        lines += [
            f"exten => s,1,NoOp(Veyra IVR {name})",
            " same => n,Set(__VEYRA_IVR_DEPTH=$[0${VEYRA_IVR_DEPTH} + 1])",
            f" same => n,GotoIf($[${{VEYRA_IVR_DEPTH}} > {routing.MAX_IVR_DEPTH}]?toodeep)",
            " same => n,Answer()",
            " same => n,Set(VEYRA_IVR_TRIES=0)",
            f" same => n(menu),Background({prompt_path})",
            f" same => n,WaitExten({timeout})",
            # WaitExten only jumps to 't' by itself when no priority follows it;
            # make the timeout path explicit so it never falls through.
            " same => n,Goto(t,1)",
            " same => n(toodeep),NoOp(Veyra: IVR menus point at each other in a loop)",
            " same => n,Playback(pbx-invalid)",
            " same => n,Hangup()",
        ]
        digits: set[str] = set()
        for e in m.get("entries") or []:
            digit = str(e.get("digit") or "")
            if digit not in routing.IVR_DIGITS or digit in digits:
                raise GenerationError(f"IVR menu {slug}: key {digit!r} is not valid or repeated")
            digits.add(digit)
            lines.append(f"exten => {digit},1,NoOp(Veyra IVR {name} key {digit})")
            lines += _goto(e)
        if m.get("allow_direct_dial"):
            for number in m.get("direct_dial") or []:
                number = str(number)
                if not _NUMBER_RE.match(number):
                    raise GenerationError(f"IVR menu {slug}: extension {number!r} is not valid")
                if number in digits:
                    continue  # the key wins
                lines.append(f"exten => {number},1,Goto({CONTEXT_INTERNAL},{number},1)")
        # An invalid key is answered with the invalid prompt and the menu is
        # replayed; a timeout replays the menu without a prompt.
        for exten, label, dest in (
            ("i", "invalid key", m.get("invalid")),
            ("t", "no key pressed", m.get("timeout")),
        ):
            lines += [
                f"exten => {exten},1,Set(VEYRA_IVR_TRIES=$[${{VEYRA_IVR_TRIES}} + 1])",
                f" same => n,GotoIf($[${{VEYRA_IVR_TRIES}} >= {retries}]?giveup)",
                *([f" same => n,Playback({invalid_path})"] if exten == "i" else []),
                " same => n,Goto(s,menu)",
                f" same => n(giveup),NoOp(Veyra IVR {name}: {label} {retries} times)",
            ]
            lines += _goto(dest if dest is not None else {"type": "hangup"})
        lines.append("")
    return lines


def _check_group_numbers(
    extensions: list[dict[str, Any]],
    ring_groups: list[dict[str, Any]],
    queues: list[dict[str, Any]],
) -> None:
    """Ring group and queue numbers share the extension number space."""
    taken = {str(e["number"]): "extension" for e in extensions}
    for what, items in (("ring group", ring_groups), ("queue", queues)):
        for item in items:
            number = str(item.get("number") or "")
            if not _NUMBER_RE.match(number):
                raise GenerationError(f"{what} number {number!r} is not valid")
            if number in taken:
                raise GenerationError(f"number {number} is used by a {taken[number]} and a {what}")
            taken[number] = what


def _group_prologue(ctx: str, what: str, name: str, org: str) -> list[str]:
    return [
        f"[{ctx}]",
        f"exten => s,1,NoOp(Veyra {what} {name} ({org}))",
        " same => n,Set(__VEYRA_GROUP_DEPTH=$[0${VEYRA_GROUP_DEPTH} + 1])",
        f" same => n,GotoIf($[${{VEYRA_GROUP_DEPTH}} > {MAX_GROUP_DEPTH}]?toodeep)",
    ]


def _group_epilogue(what: str, name: str, failover: Any) -> list[str]:
    return [
        f" same => n(failover),NoOp(Veyra {what} {name}: not answered)",
        *_goto(failover if failover is not None else {"type": "hangup"}),
        " same => n(toodeep),NoOp(Veyra: groups and queues point at each other in a loop)",
        " same => n,Playback(pbx-invalid)",
        " same => n,Hangup()",
    ]


def _ring_group_contexts(
    groups: list[dict[str, Any]], moh: dict[str, dict[str, Any]] | None = None
) -> list[str]:
    """One ``veyra-rg-<slug>`` per enabled ring group (docs/RING_GROUPS_QUEUES.md §2)."""
    lines: list[str] = []
    seen: set[str] = set()
    for g in groups:
        slug = _slug(g["slug"], "ring group slug")
        if slug in seen:
            raise GenerationError(f"duplicate ring group slug {slug!r}")
        seen.add(slug)
        name = _check_value(str(g.get("name") or slug), "ring group name")
        org = _slug(g.get("organization") or "", f"organization of ring group {slug}")
        strategy = str(g.get("strategy") or "ringall")
        if strategy not in RING_GROUP_STRATEGIES:
            raise GenerationError(f"ring group {slug}: unknown strategy {strategy!r}")
        ring = int(g.get("ring_seconds") or 20)
        if not 5 <= ring <= 120:
            raise GenerationError(f"ring group {slug}: ring time {ring} is out of range")
        members = [
            _check_section(str(m["endpoint_name"]), "endpoint name")
            for m in (g.get("members") or [])
        ]
        ring_busy = bool(g.get("ring_busy_members"))
        music = str(g.get("music") or "ring")
        if music not in QUEUE_MUSIC:
            raise GenerationError(f"ring group {slug}: unknown hold music {music!r}")
        # Callers hear ringing, or the group's (or built-in) hold music set.
        dial_opts = ""
        if music == "default":
            moh_class = _moh_class(g.get("hold_music"), moh or {}, f"ring group {slug}")
            dial_opts = f",m({moh_class})"
        lines += _group_prologue(f"{CONTEXT_RING_GROUP_PREFIX}{slug}", "ring group", name, org)
        prefix = g.get("caller_id_prefix")
        if prefix:
            lines.append(
                f" same => n,Set(CALLERID(name)={_prefix(str(prefix))}${{CALLERID(name)}})"
            )
        if not members:
            lines.append(" same => n,Goto(failover)")
        elif strategy == "ringall":
            lines.append(" same => n,Set(VEYRA_DIAL=)")
            for i, m in enumerate(members):
                nxt = f"m{i + 2}" if i + 1 < len(members) else "dial"
                label = f"(m{i + 1})" if i else ""
                if not ring_busy:
                    lines.append(
                        f' same => n{label},GotoIf($["${{DEVICE_STATE(PJSIP/{m})}}"'
                        f' : "{BUSY_STATES}"]?{nxt})'
                    )
                    label = ""
                lines.append(f" same => n{label},Set(VEYRA_DIAL=${{VEYRA_DIAL}}&PJSIP/{m})")
            lines += [
                ' same => n(dial),GotoIf($["${VEYRA_DIAL}"=""]?failover)',
                f" same => n,Dial(${{VEYRA_DIAL:1}},{ring}{dial_opts})",
                ' same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?done)',
                " same => n,Goto(failover)",
            ]
        else:
            for i, m in enumerate(members):
                nxt = f"m{i + 2}" if i + 1 < len(members) else "failover"
                label = f"(m{i + 1})" if i else ""
                if not ring_busy:
                    lines.append(
                        f' same => n{label},GotoIf($["${{DEVICE_STATE(PJSIP/{m})}}"'
                        f' : "{BUSY_STATES}"]?{nxt})'
                    )
                    label = ""
                lines += [
                    f" same => n{label},Dial(PJSIP/{m},{ring}{dial_opts})",
                    ' same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?done)',
                ]
            lines.append(" same => n,Goto(failover)")
        lines += [" same => n(done),Hangup()"]
        lines += _group_epilogue("ring group", name, g.get("failover"))
        lines.append("")
    return lines


def _queue_contexts(queues: list[dict[str, Any]], prompts_dir: str) -> list[str]:
    """One ``veyra-queue-<slug>`` per enabled queue (docs/RING_GROUPS_QUEUES.md §3)."""
    lines: list[str] = []
    seen: set[str] = set()
    for q in queues:
        slug = _slug(q["slug"], "queue slug")
        if slug in seen:
            raise GenerationError(f"duplicate queue slug {slug!r}")
        seen.add(slug)
        name = _check_value(str(q.get("name") or slug), "queue name")
        org = _slug(q.get("organization") or "", f"organization of queue {slug}")
        music = str(q.get("music") or "default")
        if music not in QUEUE_MUSIC:
            raise GenerationError(f"queue {slug}: unknown hold music {music!r}")
        wait = int(q.get("max_wait_seconds") or 0)
        if wait and not 30 <= wait <= 3600:
            raise GenerationError(f"queue {slug}: maximum wait {wait} is out of range")
        lines += _group_prologue(f"{CONTEXT_QUEUE_PREFIX}{slug}", "queue", name, org)
        lines.append(" same => n,Answer()")
        announcement = q.get("announcement_prompt")
        if announcement:
            lines.append(
                f" same => n,Playback({prompts_dir}/{org}/{_slug(announcement, 'prompt slug')})"
            )
        options = "tr" if music == "ring" else "t"
        timeout = str(wait) if wait else ""
        lines += [
            f" same => n,Queue({QUEUE_NAME_PREFIX}{slug},{options},,,{timeout})",
            f" same => n,NoOp(Veyra queue {name} left with ${{QUEUESTATUS}})",
            " same => n,Goto(failover)",
        ]
        lines += _group_epilogue("queue", name, q.get("failover"))
        lines.append("")
    return lines


def _queues(
    queues: list[dict[str, Any]],
    extensions: list[dict[str, Any]],
    prompts_dir: str,
    moh: dict[str, dict[str, Any]] | None = None,
) -> GeneratedFile:
    """``queues.conf`` (docs/RING_GROUPS_QUEUES.md §3): one section per
    enabled queue with static members; reloaded with ``app_queue.so``."""
    endpoints = {str(e["endpoint_name"]) for e in extensions}
    lines = [
        HEADER,
        "[general]",
        "persistentmembers=no",
        "autofill=yes",
        "shared_lastcall=yes",
        "monitor-type=",
        "",
    ]
    seen: set[str] = set()
    for q in queues:
        slug = _slug(q["slug"], "queue slug")
        if slug in seen:
            raise GenerationError(f"duplicate queue slug {slug!r}")
        seen.add(slug)
        name = _check_value(str(q.get("name") or slug), "queue name")
        org = _slug(q.get("organization") or "", f"organization of queue {slug}")
        strategy = str(q.get("strategy") or "ringall")
        if strategy not in QUEUE_STRATEGIES:
            raise GenerationError(f"queue {slug}: unknown strategy {strategy!r}")
        timeout = int(q.get("member_timeout") or 15)
        retry = int(q.get("retry_seconds") or 5)
        wrapup = int(q.get("wrapup_seconds") or 0)
        maxlen = int(q.get("max_callers") or 0)
        freq = int(q.get("announce_frequency") or 60)
        periodic = int(q.get("periodic_seconds") or 60)
        for what, value, lo, hi in (
            ("agent ring time", timeout, 5, 60),
            ("retry", retry, 1, 30),
            ("wrap-up", wrapup, 0, 600),
            ("maximum callers", maxlen, 0, 100),
            ("announcement frequency", freq, 15, 600),
            ("periodic announcement frequency", periodic, 15, 600),
        ):
            if not lo <= value <= hi:
                raise GenerationError(f"queue {slug}: {what} {value} is out of range")
        empty = "yes" if q.get("join_when_empty") else "strict"
        position = "yes" if q.get("announce_position") else "no"
        lines += [
            f"[{QUEUE_NAME_PREFIX}{slug}]",
            f"; {name} ({org})",
            f"strategy={strategy}",
            f"timeout={timeout}",
            f"retry={retry}",
            f"wrapuptime={wrapup}",
            f"maxlen={maxlen}",
            "ringinuse=no",
            f"joinempty={empty}",
            f"leavewhenempty={'no' if q.get('join_when_empty') else 'strict'}",
            f"musicclass={_moh_class(q.get('hold_music'), moh or {}, f'queue {slug}')}",
            f"announce-position={position}",
            f"announce-frequency={freq if q.get('announce_position') else 0}",
            "announce-holdtime=no",
        ]
        prompt = q.get("periodic_prompt")
        if prompt:
            lines += [
                f"periodic-announce={prompts_dir}/{org}/{_slug(prompt, 'prompt slug')}",
                f"periodic-announce-frequency={periodic}",
            ]
        for m in q.get("members") or []:
            endpoint = _check_section(str(m["endpoint_name"]), "endpoint name")
            if endpoint not in endpoints:
                continue
            penalty = int(m.get("penalty") or 0)
            if not 0 <= penalty <= 9:
                raise GenerationError(f"queue {slug}: penalty {penalty} is out of range")
            member_name = _display(m.get("name")) or str(m.get("number") or endpoint)
            lines.append(f"member => PJSIP/{endpoint},{penalty},{member_name},PJSIP/{endpoint}")
        lines.append("")
    return GeneratedFile(FILE_QUEUES, "\n".join(lines).rstrip("\n") + "\n")


def _check_boxes(
    boxes: list[dict[str, Any]], extensions: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Voicemail boxes by extension number; only boxes of listed extensions."""
    numbers = {str(e["number"]) for e in extensions}
    out: dict[str, dict[str, Any]] = {}
    for b in boxes:
        number = str(b.get("number") or "")
        if not _NUMBER_RE.match(number):
            raise GenerationError(f"voicemail box number {number!r} is not valid")
        if number not in numbers and not b.get("shared"):
            continue
        if b.get("shared") and number in numbers:
            raise GenerationError(f"shared inbox {number} uses an extension's number")
        if number in out:
            raise GenerationError(f"extension {number} has more than one voicemail box")
        ring = int(b.get("ring_seconds") or 20)
        if not 5 <= ring <= 120:
            raise GenerationError(f"voicemail box {number}: ring time {ring} is out of range")
        out[number] = b
    return out


def _voicemail(
    snapshot: dict[str, Any], boxes: dict[str, dict[str, Any]], mailqueue_command: str
) -> GeneratedFile:
    """``voicemail.conf`` (docs/VOICEMAIL_IVR.md §3.2). Sensitive: it carries
    PINs in clear. Email addresses are only rendered when delivery is enabled,
    so messages are never deleted after an email that cannot be sent."""
    smtp = snapshot.get("smtp") or {}
    from_address = _check_value(str(smtp.get("from_address") or "veyra@localhost"), "sender")
    from_name = _display(str(smtp.get("from_name") or "Veyra")) or "Veyra"
    delivery = bool(smtp.get("enabled"))
    lines = [
        HEADER,
        "[general]",
        "format=wav49|gsm|wav",
        f"serveremail={from_address}",
        f"fromstring={from_name}",
        "attach=yes",
        "maxmsg=100",
        "maxsecs=180",
        "maxgreet=60",
        "maxsilence=10",
        "silencethreshold=128",
        "maxlogins=3",
        "pbxskip=yes",
        "emailsubject=New voicemail ${VM_MSGNUM} in mailbox ${VM_MAILBOX} (${VM_NAME})",
        "emailbody=${VM_NAME},\\n\\nYou have a new voicemail in mailbox ${VM_MAILBOX}: "
        "message ${VM_MSGNUM} from ${VM_CALLERID}, received ${VM_DATE}, "
        "${VM_DUR} long.\\n\\nThis message was sent by Veyra.",
        f"mailcmd={mailqueue_command}",
        "",
        "[zonemessages]",
    ]
    zones: dict[str, str] = {}
    for b in boxes.values():
        org = _slug(b.get("organization") or "", "organization")
        tz = routing.check_timezone(str(b.get("timezone") or "UTC"))
        zones.setdefault(org, tz)
    for org in sorted(zones):
        lines.append(f"{org}={zones[org]}|'vm-received' Q 'digits/at' IMp")
    lines += ["", f"[{VOICEMAIL_CONTEXT}]"]
    sensitive = False
    for number in sorted(boxes, key=lambda n: (len(n), n)):
        b = boxes[number]
        pin = str(b.get("pin") or "")
        if not _PIN_RE.match(pin):
            raise GenerationError(f"voicemail box {number}: the PIN must be 4 to 10 digits")
        sensitive = True
        name = _display(b.get("name")) or f"Extension {number}"
        email = ""
        delete = "no"
        if delivery and b.get("email"):
            try:
                email = routing.check_email(str(b["email"]))
            except ValueError as e:
                raise GenerationError(f"voicemail box {number}: {e}") from e
            delete = "yes" if b.get("delete_after_email") else "no"
        attach = "yes" if b.get("attach_audio", True) else "no"
        org = _slug(b.get("organization") or "", "organization")
        lines.append(
            f"{number} => {pin},{name},{email},,"
            f"attach={attach}|delete={delete}|tz={org}|saycid=yes|envelope=yes"
        )
    lines.append("")
    return GeneratedFile(FILE_VOICEMAIL, "\n".join(lines).rstrip("\n") + "\n", sensitive=sensitive)


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
        if f.path.endswith(".json"):
            # The page sender's table: must parse, nothing else.
            try:
                json.loads(f.content)
            except ValueError as e:
                problems.append(f"{f.path}: not valid JSON ({e})")
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
