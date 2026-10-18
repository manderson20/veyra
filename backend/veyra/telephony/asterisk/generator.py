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
import posixpath
import re
from typing import Any

from veyra.telephony import routing
from veyra.telephony.adapter import GeneratedFile
from veyra.telephony.asterisk import names as engine_names
from veyra.telephony.asterisk.names import Names
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
FILE_CONFBRIDGE = "confbridge.conf"
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
    FILE_CONFBRIDGE,
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
    FILE_CONFBRIDGE: "app_confbridge.so",
}
SCOPE_ORDER = [
    "res_rtp_asterisk.so",
    "res_pjsip.so",
    "pbx_config.so",
    "app_voicemail.so",
    "app_queue.so",
    "res_pjsip_notify.so",
    "res_musiconhold.so",
    "app_confbridge.so",
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
# Milestone 19 (docs/CALL_FEATURES.md §4): announcements, conference rooms and
# the dial-by-name directory, one context each (names.py).
CONFERENCE_PIN_TRIES = 3
CONFERENCE_MAX_MEMBERS = 500
DEFAULT_CONFERENCES_SUBDIR = "conferences"
# Engine switches (docs/CALL_FEATURES.md §4.5, §4.6): the store family the
# dialplan reads, the UserEvent that tells the API, the code indexes.
SWITCH_FAMILY = "veyra/switch"
SWITCH_EVENT = "VeyraSwitch"
SWITCH_PIN_TRIES = 3
MAX_CODE_INDEX = 99
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
_SITE_RE = re.compile(r"^[0-9a-f-]{36}$")
EMERGENCY_EVENT = "VeyraEmergency"
EXTSTATE_EVENT = "VeyraExtState"  # a phone changed its own state (CALL_FEATURES.md §3.2)
CONTEXT_EMERGENCY_NOTIFY = "veyra-emergency-notify"
ASTDB_CALLBACK = "veyra_ecb"
DEFAULT_RING_SECONDS = 30
# Where the prompts live and the script Asterisk hands notifications to;
# the adapter passes the installation's paths (veyra.core.config).
DEFAULT_PROMPTS_DIR = "/var/lib/veyra/prompts"
DEFAULT_MOH_DIR = "/var/lib/veyra/moh"
DEFAULT_RECORDINGS_DIR = "/var/lib/veyra/recordings"
CONTEXT_RECORD = "veyra-record"
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
        f"[{engine_names.current().paging}]",
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
                f" same => n,Originate(Local/play-{slug}@{engine_names.current().page_play},exten,"
                f"{engine_names.current().page_play},{slug},1,,a)",
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
        f"[{engine_names.current().page_play}]",
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
    recordings_dir: str = DEFAULT_RECORDINGS_DIR,
) -> list[GeneratedFile]:
    sip = SipSettings.model_validate(snapshot.get("sip") or {})
    problems = sip.problems()
    if problems:
        raise GenerationError("; ".join(problems))
    mapping = {
        str(o.get("slug") or ""): str(o.get("namespace") or "")
        for o in snapshot.get("organizations") or []
    }
    with engine_names.namespaces(mapping):
        files = _generate(
            snapshot,
            sip,
            prompts_dir=prompts_dir,
            mailqueue_command=mailqueue_command,
            moh_dir=moh_dir,
            recordings_dir=recordings_dir,
        )
    # Prove the organizations cannot reach each other (docs/MULTI_TENANCY.md §5).
    strict = bool((snapshot.get("installation") or {}).get("multi_tenancy_enabled"))
    if len(set(mapping.values())) > 1 or strict:
        from veyra.telephony.asterisk import isolation

        problems = isolation.verify(files, strict=strict)
        if problems:
            raise GenerationError("isolation check failed: " + "; ".join(problems[:10]))
    return files


def _generate(
    snapshot: dict[str, Any],
    sip: SipSettings,
    *,
    prompts_dir: str,
    mailqueue_command: str,
    moh_dir: str,
    recordings_dir: str,
) -> list[GeneratedFile]:
    extensions = list(snapshot.get("extensions") or [])
    trunks = list(snapshot.get("trunks") or [])
    boxes = _check_boxes(list(snapshot.get("voicemail_boxes") or []), extensions)
    prompts = _path(prompts_dir, "prompts directory")
    ring_groups = list(snapshot.get("ring_groups") or [])
    queues = list(snapshot.get("queues") or [])
    rooms = list(snapshot.get("conference_rooms") or [])
    _check_group_numbers(extensions, ring_groups, queues, rooms)
    moh = _check_moh(list(snapshot.get("hold_music") or []))
    org_moh = {
        str(o["slug"]): _moh_class(
            o.get("hold_music"), moh, f"organization {o['slug']}", str(o["slug"])
        )
        for o in (snapshot.get("organizations") or [])
        if o.get("hold_music")
    }
    recording = _check_recording(list(snapshot.get("recording") or []))
    return [
        _transports(sip),
        _endpoints(
            sip,
            extensions,
            {k for k, b in boxes.items() if not b.get("shared")},
            dict(snapshot.get("shared_mailboxes") or {}),
            org_moh,
        ),
        _trunks(sip, trunks),
        _dialplan(
            snapshot,
            extensions,
            trunks,
            boxes,
            prompts,
            recording,
            _path(recordings_dir, "recordings directory"),
        ),
        _rtp(sip),
        _voicemail(snapshot, boxes, _path(mailqueue_command, "mail queue command")),
        _queues(queues, extensions, prompts, moh),
        _notify_conf(),
        _paging_json(snapshot.get("paging") or {}),
        _moh_conf(moh, _path(moh_dir, "hold music directory")),
        _confbridge(rooms, moh, _path(recordings_dir, "recordings directory")),
    ]


MohSets = dict[tuple[str, str], dict[str, Any]]


def _check_moh(sets: list[dict[str, Any]]) -> MohSets:
    """Hold music sets by (organization, slug) (docs/PAGING_RECORDINGS.md §3.2)."""
    out: MohSets = {}
    for m in sets:
        slug = _slug(str(m.get("slug") or ""), "hold music slug")
        org = str(m.get("organization") or "")
        if (org, slug) in out:
            raise GenerationError(f"duplicate hold music slug {slug!r}")
        for f in m.get("files") or []:
            if not _FILE_RE.match(str(f)):
                raise GenerationError(f"hold music set {slug}: file name {f!r} is not valid")
        out[(org, slug)] = m
    return out


def _moh_class(slug: Any, moh: MohSets, what: str, org: str = "") -> str:
    """The engine class for a set slug of ``org``; the built-in class when none."""
    if not slug:
        return MOH_BUILTIN
    slug = _slug(str(slug), f"hold music of {what}")
    if (org, slug) not in moh:
        # Snapshots before Milestone 14 do not always say whose set it is.
        matches = [k for k in moh if k[1] == slug]
        if len(matches) != 1 or (org and matches[0][0] not in ("", org)):
            raise GenerationError(f"{what}: hold music set {slug!r} is not in the snapshot")
        org = matches[0][0]
    return engine_names.for_org(org).moh_class(slug)


def _moh_conf(moh: MohSets, moh_dir: str) -> GeneratedFile:
    """``musiconhold.conf``: one ``[veyra-<slug>]`` files class per set. The
    track list is written as a comment so a changed set changes the file and
    the deployer reloads ``res_musiconhold.so`` (which rescans the
    directories); the installer's stub keeps the built-in ``default``."""
    lines = [HEADER, "; Hold music sets (docs/PAGING_RECORDINGS.md §3.2).", ""]
    ordered = sorted(moh.items(), key=lambda kv: engine_names.for_org(kv[0][0]).moh_class(kv[0][1]))
    for (owner, slug), m in ordered:
        name = _check_value(str(m.get("name") or slug), "hold music name")
        org = _slug(str(m.get("organization") or ""), f"organization of hold music {slug}")
        files = [str(f) for f in (m.get("files") or [])]
        n = engine_names.for_org(owner)
        lines += [
            f"[{n.moh_class(slug)}]",
            f"; {name} ({org}); tracks: {', '.join(files) or 'none'}",
            "mode=files",
            f"directory={moh_dir}/{n.moh_dir(slug)}",
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
    mailboxes: set[tuple[str, str]] | None = None,
    shared_mailboxes: dict[str, list[str]] | None = None,
    org_moh: dict[str, str] | None = None,
) -> GeneratedFile:
    """``mailboxes`` holds (organization, number) of the extensions' own boxes."""
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
    numbers: set[tuple[str, str]] = set()
    sensitive = False
    for ext in extensions:
        name = _check_section(str(ext["endpoint_name"]), "endpoint name")
        if name in seen:
            raise GenerationError(f"duplicate endpoint name {name!r}")
        seen.add(name)
        number = str(ext["number"])
        if not _NUMBER_RE.match(number):
            raise GenerationError(f"extension number {number!r} is not valid")
        org_slug = str(ext.get("organization") or "")
        n = engine_names.for_org(org_slug)
        # Numbers are unique within an engine namespace (one phone context
        # each; docs/MULTI_TENANCY.md §3).
        if (n.ns, number) in numbers:
            raise GenerationError(f"extension number {number} is used more than once")
        numbers.add((n.ns, number))
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
        # Outbound caller ID (docs/CALL_FEATURES.md §3.5): read by the
        # outbound routes, which apply the precedence.
        ocid = ext.get("outbound_caller_id_number")
        if ocid and not _NUMBER_RE.match(str(ocid)):
            raise GenerationError(f"outbound caller ID {ocid!r} is not valid")
        outbound_cid = [f"set_var=VEYRA_OUT_CID={ocid}"] if ocid else []
        ocid_name = ext.get("outbound_caller_id_name")
        if ocid_name:
            shown = _check_value(_display(str(ocid_name)), "caller ID name")
            outbound_cid.append(f"set_var=VEYRA_OUT_CID_NAME={shown}")
        # The phone's site, read by site-bound emergency routes
        # (docs/PRODUCTION_HARDENING.md §6).
        site = str(ext.get("site") or "")
        if site and not _SITE_RE.match(site):
            raise GenerationError(f"site id {site!r} is not valid")
        emergency_cid += [f"set_var=__VEYRA_SITE={site}"] if site else []
        # Message waiting indication: the phone subscribes to, or is notified
        # about, its own mailbox (docs/VOICEMAIL_IVR.md §3.2).
        # Own box plus the shared inboxes the phone's lamp follows
        # (docs/PAGING_RECORDINGS.md §5).
        shared = ext.get("shared_mailboxes")
        if shared is None:
            shared = (shared_mailboxes or {}).get(number, [])
        boxes_of_phone = ([number] if (org_slug, number) in mailboxes else []) + [
            _check_value(str(b), "shared inbox number") for b in shared
        ]
        mwi = (
            [f"mailboxes={','.join(f'{b}@{n.voicemail}' for b in boxes_of_phone)}"]
            if boxes_of_phone
            else []
        )
        # Pickup groups (docs/RING_GROUPS_QUEUES.md §4): the phone can be
        # picked up by, and can pick up, every member of its groups.
        groups = ",".join(
            sorted(
                n.pickup_group(_slug(g, f"pickup group of {number}"))
                for g in (ext.get("pickup_groups") or [])
            )
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
            *([f"context={n.internal}"] if n.ns else []),
            f"auth={name}",
            f"aors={name}",
            f'callerid="{cid_name}" <{cid_num}>',
            f"set_var=VEYRA_ORG={org}",
            f"set_var=VEYRA_EXT={number}",
            *(
                [f"set_var=VEYRA_COS={_slug(str(ext['class_of_service']), 'class of service')}"]
                if ext.get("class_of_service")
                else []
            ),
            *emergency_cid,
            *outbound_cid,
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


# ------------------------------------------------------------- recording
# docs/REPORTING.md §4.2: policies become GosubIf lines in front of the
# places a call is connected; the subroutine records once per call.

_INBOUND = '"${VEYRA_DID}"!=""'
_INTERNAL = '"${VEYRA_DID}"=""'


def _check_recording(policies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for p in policies:
        pid = str(p.get("id") or "")
        if not re.fullmatch(r"[0-9a-f-]{36}", pid):
            raise GenerationError(f"recording policy id {pid!r} is not valid")
        org = _slug(p.get("organization") or "", f"organization of recording policy {pid}")
        numbers = [str(n) for n in (p.get("extensions") or [])]
        for n in numbers:
            if not _NUMBER_RE.match(n):
                raise GenerationError(f"recording policy {pid}: extension {n!r} is not valid")
        out.append(
            {
                "id": pid,
                "organization": org,
                "organization_id": str(p.get("organization_id") or ""),
                "inbound": bool(p.get("inbound")),
                "outbound": bool(p.get("outbound")),
                "internal": bool(p.get("internal")),
                "all": bool(p.get("all")),
                "extensions": set(numbers),
                "endpoints": [
                    _check_section(str(e), "recorded endpoint") for e in p.get("endpoints") or []
                ],
                "ring_groups": {
                    _slug(g, "recorded ring group") for g in p.get("ring_groups") or []
                },
                "queues": {_slug(q, "recorded queue") for q in p.get("queues") or []},
                "routes": {routing.normalize_did(str(d)) for d in p.get("routes") or []},
                "announcement": _slug(p["announcement"], "announcement prompt")
                if p.get("announcement")
                else "",
            }
        )
    return out


def _gosub_record(p: dict[str, Any], cond: str) -> str:
    ann = f"{p['organization']}/{p['announcement']}" if p["announcement"] else ""
    return (
        f" same => n,GosubIf($[{cond}]?{CONTEXT_RECORD},s,1({p['organization']},{p['id']},{ann}))"
    )


def _caller_in(endpoints: list[str]) -> str:
    return '${REGEX("^(' + "|".join(re.escape(e) for e in endpoints) + ')$" ${CHANNEL(endpoint)})}'


def _record_for_extension(
    recording: list[dict[str, Any]], ext: dict[str, Any], prompts_dir: str
) -> list[str]:
    org, number = str(ext.get("organization") or ""), str(ext["number"])
    out = []
    for p in recording:
        if p["organization"] != org:
            continue
        chosen = number in p["extensions"]
        # "All inbound" is recorded where the call enters (the inbound route).
        if p["inbound"] and not p["all"] and chosen:
            out.append(_gosub_record(p, _INBOUND))
        if p["internal"] and (p["all"] or chosen):
            out.append(_gosub_record(p, _INTERNAL))
        elif p["internal"] and p["endpoints"]:
            # A chosen phone calling this one.
            out.append(_gosub_record(p, f"{_INTERNAL} & {_caller_in(p['endpoints'])}"))
    return out


def _record_for_group(
    recording: list[dict[str, Any]], org: str, kind: str, slug: str, prompts_dir: str
) -> list[str]:
    out = []
    for p in recording:
        if p["organization"] != org:
            continue
        chosen = slug in p[kind]
        if p["inbound"] and not p["all"] and chosen:
            out.append(_gosub_record(p, _INBOUND))
        if p["internal"] and (p["all"] or chosen):
            out.append(_gosub_record(p, _INTERNAL))
    return out


def _record_inbound(
    recording: list[dict[str, Any]], route: dict[str, Any], prompts_dir: str
) -> list[str]:
    org_id = str(route.get("organization") or "")
    did = str(route.get("did") or "")
    return [
        _gosub_record(p, "1")
        for p in recording
        if p["inbound"] and p["organization_id"] == org_id and (p["all"] or did in p["routes"])
    ]


def _outbound_caller_id(fallback: Any, force: bool, emergency: bool) -> list[str]:
    """The caller ID presented on a trunk leg (docs/CALL_FEATURES.md §3.5):
    the extension's emergency caller ID on an emergency route, else the
    route's number when the route forces it, else the extension's outbound
    caller ID, else the route's number, else the trunk's default. The
    outbound name goes with the extension's number."""
    guard = '"${VEYRA_EMERGENCY_CID}"="" & ' if emergency else ""
    lines: list[str] = []
    if force and fallback:
        cond = '$["${VEYRA_EMERGENCY_CID}"=""]' if emergency else None
        lines.append(
            f" same => n,ExecIf({cond}?Set(CALLERID(num)={fallback}))"
            if cond
            else f" same => n,Set(CALLERID(num)={fallback})"
        )
        return lines
    lines.append(
        f' same => n,ExecIf($[{guard}"${{VEYRA_OUT_CID}}"!=""]'
        "?Set(CALLERID(num)=${VEYRA_OUT_CID}))"
    )
    lines.append(
        f' same => n,ExecIf($[{guard}"${{VEYRA_OUT_CID}}"!="" & "${{VEYRA_OUT_CID_NAME}}"!=""]'
        "?Set(CALLERID(name)=${VEYRA_OUT_CID_NAME}))"
    )
    if fallback:
        lines.append(
            f' same => n,ExecIf($[{guard}"${{VEYRA_OUT_CID}}"=""]?Set(CALLERID(num)={fallback}))'
        )
    return lines


def _record_outbound(recording: list[dict[str, Any]], prompts_dir: str) -> list[str]:
    out = []
    for p in recording:
        if not p["outbound"]:
            continue
        cond = f'"${{VEYRA_ORG}}"="{p["organization"]}"'
        if not p["all"]:
            if not p["endpoints"]:
                continue
            cond += f" & {_caller_in(p['endpoints'])}"
        out.append(_gosub_record(p, cond))
    return out


def _record_context(recordings_dir: str, prompts_dir: str) -> list[str]:
    """ARG1 organization, ARG2 policy, ARG3 announcement (``<org>/<slug>``)."""
    return [
        "",
        f"[{CONTEXT_RECORD}]",
        "; Record a call once (docs/REPORTING.md §4.2); the worker converts the file.",
        'exten => s,1,GotoIf($["${VEYRA_CALLREC}"!=""]?done)',
        " same => n,Set(__VEYRA_CALLREC=${UNIQUEID})",
        " same => n,Set(CDR(veyra_rec)=${VEYRA_CALLREC})",
        ' same => n,GotoIf($["${ARG3}"=""]?start)',
        f" same => n,Playback({prompts_dir}/${{ARG3}})",
        f" same => n(start),MixMonitor({recordings_dir}/incoming/"
        "${VEYRA_CALLREC}--${ARG2}.wav,b)",
        " same => n(done),Return()",
        "",
    ]


def _dialplan(
    snapshot: dict[str, Any],
    extensions: list[dict[str, Any]],
    trunks: list[dict[str, Any]],
    boxes: Boxes | None = None,
    prompts_dir: str = DEFAULT_PROMPTS_DIR,
    recording: list[dict[str, Any]] | None = None,
    recordings_dir: str = DEFAULT_RECORDINGS_DIR,
) -> GeneratedFile:
    """``extensions.conf``. Each engine namespace gets its own contexts
    (docs/MULTI_TENANCY.md §2); the sections keep their order, so an
    installation with one namespace is written exactly as before."""
    recording = recording or []
    name = _check_value(str(snapshot.get("installation", {}).get("name") or "Veyra"), "name")
    outbound = list(snapshot.get("outbound_routes") or [])
    inbound = list(snapshot.get("inbound_routes") or [])
    menus = list(snapshot.get("ivr_menus") or [])
    ring_groups = list(snapshot.get("ring_groups") or [])
    queues = list(snapshot.get("queues") or [])
    announcements = list(snapshot.get("announcements") or [])
    rooms = list(snapshot.get("conference_rooms") or [])
    flows = list(snapshot.get("call_flows") or [])
    boxes = boxes if boxes is not None else {}
    tcs = list(snapshot.get("time_conditions") or [])
    conditions = {str(c["key"]): c for c in tcs}
    trunk_slugs = [_check_section(str(t["slug"]), "trunk slug") for t in trunks]
    trunk_info = {str(t["slug"]): t for t in trunks}
    paging = snapshot.get("paging") or {}
    spaces = _namespaces(snapshot)

    def mine(items: list[dict[str, Any]], ns: str) -> list[dict[str, Any]]:
        return [i for i in items if engine_names.for_org(str(i.get("organization") or "")).ns == ns]

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
    ]
    codes = _feature_codes(snapshot)

    def my_boxes(ns: str) -> list[tuple[str, dict[str, Any]]]:
        return [
            (number, b)
            for (owner, number), b in boxes.items()
            if engine_names.for_org(owner).ns == ns
        ]

    cos_all = Cos(
        list(snapshot.get("classes_of_service") or []),
        int((snapshot.get("numbering") or {}).get("extension_length") or 4),
    )
    for ns in spaces:
        with engine_names.using(Names(ns)):
            lines += _features(
                mine(extensions, ns),
                prompts_dir,
                codes,
                my_boxes(ns),
                _cos_for(snapshot, ns),
                mine(flows, ns),
                mine(tcs, ns),
            )
            lines += _voicemail_exit_contexts(my_boxes(ns))
    for ns in spaces:
        with engine_names.using(Names(ns)):
            lines += _internal(
                mine(extensions, ns),
                {k: b for k, b in boxes.items() if engine_names.for_org(k[0]).ns == ns},
                mine(ring_groups, ns),
                mine(queues, ns),
                recording,
                prompts_dir,
                codes.get("dnd_toggle"),
                codes.get("cf_on"),
                codes.get("fmfm_toggle"),
                _cos_for(snapshot, ns),
                mine(rooms, ns),
                _switch_hints(codes, mine(flows, ns), mine(tcs, ns)),
            )
    lines += _follow_me_contexts(spaces)
    if "intercom" in codes:
        for ns in spaces:
            with engine_names.using(Names(ns)):
                lines += _intercom_context(mine(extensions, ns))
                lines += _intercom_headers_context()
    lines += [
        f"[{CONTEXT_INVALID}]",
        "exten => _[0-9*#+].,1,NoOp(Veyra: no such extension ${EXTEN})",
        " same => n,Playback(pbx-invalid)",
        " same => n,Hangup()",
        "",
    ]
    for ns in spaces:
        with engine_names.using(Names(ns)):
            part = {
                **paging,
                "zones": mine(list(paging.get("zones") or []), ns),
                "pages": mine(list(paging.get("pages") or []), ns),
            }
            lines += _paging_contexts(part, prompts_dir)
    lines += [
        f"[{CONTEXT_EMERGENCY_NOTIFY}]",
        "; A responder's phone rung by the on-site notification hears the",
        "; extension that placed the emergency call (docs/PRODUCTION_HARDENING.md §6).",
        "exten => _X.,1,Answer()",
        " same => n,Wait(1)",
        " same => n,Playback(beep)",
        " same => n,SayDigits(${EXTEN})",
        " same => n,Wait(1)",
        " same => n,SayDigits(${EXTEN})",
        " same => n,Hangup()",
        "",
    ]
    lines += _outbound_contexts(outbound, trunk_info, recording, prompts_dir, spaces, cos_all)
    lines += _inbound_contexts(
        inbound, conditions, trunk_slugs, recording, prompts_dir, list(snapshot.get("sites") or [])
    )
    for ns in spaces:
        with engine_names.using(Names(ns)):
            lines += _ivr_contexts(mine(menus, ns), prompts_dir)
            lines += _announcement_contexts(mine(announcements, ns), prompts_dir)
            lines += _conference_contexts(mine(rooms, ns))
            lines += _call_flow_contexts(mine(flows, ns))
            lines += _directory_context()
    moh = _check_moh(list(snapshot.get("hold_music") or []))
    for ns in spaces:
        with engine_names.using(Names(ns)):
            lines += _ring_group_contexts(mine(ring_groups, ns), moh, recording, prompts_dir)
    for ns in spaces:
        with engine_names.using(Names(ns)):
            lines += _queue_contexts(mine(queues, ns), prompts_dir, recording)
    if recording:
        lines += _record_context(recordings_dir, prompts_dir)
    return GeneratedFile(FILE_DIALPLAN, "\n".join(lines).rstrip("\n") + "\n")


def _namespaces(snapshot: dict[str, Any]) -> list[str]:
    """The engine namespaces in use, today's (empty) one first."""
    found = {
        engine_names.for_org(str(o.get("slug") or "")).ns
        for o in snapshot.get("organizations") or []
    }
    for key in ("extensions", "ring_groups", "queues", "ivr_menus", "voicemail_boxes"):
        for item in snapshot.get(key) or []:
            found.add(engine_names.for_org(str(item.get("organization") or "")).ns)
    found.add(engine_names.LEGACY)
    return sorted(found, key=lambda ns: (ns != engine_names.LEGACY, ns))


_FEATURE_CODE_RE = re.compile(r"^[*#][0-9*#]{0,6}$")


def _feature_codes(snapshot: dict[str, Any]) -> dict[str, str]:
    """The enabled configurable feature codes (docs/CALL_FEATURES.md §3.1)."""
    codes: dict[str, str] = {}
    seen: dict[str, str] = {}
    for key, code in (snapshot.get("feature_codes") or {}).items():
        code = str(code)
        if not _FEATURE_CODE_RE.match(code):
            raise GenerationError(f"feature code {key}: {code!r} is not valid")
        if code in seen:
            raise GenerationError(f"feature code {code} is used by {seen[code]} and {key}")
        seen[code] = str(key)
        codes[str(key)] = code
    return codes


STATE_KEY = "veyra/ext/${VEYRA_ORG}/${VEYRA_EXT}"
DND_DEVICE = "Custom:veyra-dnd-${VEYRA_ORG}-${VEYRA_EXT}"
CF_DEVICE = "Custom:veyra-cf-${VEYRA_ORG}-${VEYRA_EXT}"
_CF_PROMPTS = {
    "cf_always": "call-fwd-unconditional",
    "cf_busy": "call-fwd-on-busy",
    "cf_no_answer": "call-fwd-no-ans",
}
_CF_CODES = {
    "cf_always": ("cf_on", "cf_off"),
    "cf_busy": ("cfb_on", "cfb_off"),
    "cf_no_answer": ("cfu_on", "cfu_off"),
}


def _state_event(field: str, value: str) -> str:
    return (
        f" same => n,UserEvent({EXTSTATE_EVENT},Org: ${{VEYRA_ORG}},Extension: ${{VEYRA_EXT}},"
        f"Field: {field},Value: {value})"
    )


_STATE_GUARD = [
    " same => n,Answer()",
    ' same => n,GotoIf($["${VEYRA_EXT}"=""]?nophone)',
]
_STATE_TAIL = [
    " same => n(nophone),Playback(feature-not-avail-line)",
    " same => n,Hangup()",
]


def _code_block(head: str, body: list[str], cos: Cos | None, key: str) -> list[str]:
    """One feature code: the phone check, the class guard, the body, the tails."""
    guard = cos.code_guard(key) if cos else []
    return [head, *_STATE_GUARD, *guard, *body, *_STATE_TAIL, *(COS_DENIED if guard else [])]


# The forwarding lamp stays lit while any forward is set.
_CF_LAMP = (
    f' same => n,Set(DEVICE_STATE({CF_DEVICE})=${{IF($["${{DB({STATE_KEY}/cf_always)}}'
    f'${{DB({STATE_KEY}/cf_busy)}}${{DB({STATE_KEY}/cf_no_answer)}}"=""]?NOT_INUSE:INUSE)}})'
)


class Cos:
    """The classes of service of one namespace (docs/CALL_FEATURES.md §3.8) and
    the dialplan guards they produce. A phone without a class (empty
    ``VEYRA_COS``) is never denied."""

    def __init__(self, classes: list[dict[str, Any]], extension_length: int) -> None:
        self.classes = classes
        self.extension_length = extension_length
        for c in classes:
            _slug(str(c.get("slug") or ""), "class of service slug")

    def _denied(self, predicate: Any) -> list[str]:
        return sorted(str(c["slug"]) for c in self.classes if predicate(c))

    @staticmethod
    def guard(denied: list[str], label: str = "cosdenied", extra: str = "") -> list[str]:
        if not denied:
            return []
        alternatives = "|".join(re.escape(d) for d in denied)
        cond = f'${{REGEX("^({alternatives})$" ${{VEYRA_COS}})}}'
        if extra:
            cond = f"{cond} & {extra}"
        return [f" same => n,GotoIf($[{cond}]?{label})"]

    def route_guard(self, route_slug: str) -> list[str]:
        return self.guard(self._denied(lambda c: route_slug not in (c.get("allowed_routes") or [])))

    def route_limits(self) -> list[str]:
        """Simultaneous outside calls per class: the channel joins the class's
        group and is refused when the count is above the limit."""
        limited = [c for c in self.classes if c.get("max_outbound_calls")]
        if not limited:
            return []
        lines = [" same => n,Set(GROUP(veyra_cos)=${VEYRA_COS})"]
        for c in limited:
            slug = str(c["slug"])
            lines.append(
                f' same => n,GotoIf($["${{VEYRA_COS}}"="{slug}" & '
                f"${{GROUP_COUNT({slug}@veyra_cos)}} > {int(c['max_outbound_calls'])}]?cosbusy)"
            )
        return lines

    def code_guard(self, key: str) -> list[str]:
        return self.guard(
            self._denied(
                lambda c: (
                    c.get("allowed_feature_codes") is not None
                    and key not in c["allowed_feature_codes"]
                )
            )
        )

    def forward_guard(self) -> list[str]:
        """An outside forward target (longer than an extension number) by a
        class that may not forward outside."""
        return self.guard(
            self._denied(lambda c: not c.get("allow_external_forwards", True)),
            extra=f"${{LEN(${{VEYRA_CF}})}} > {self.extension_length}",
        )

    def intercom_guard(self) -> list[str]:
        return self.guard(self._denied(lambda c: not c.get("allow_intercom", True)))

    def allows_external_follow_me(self, class_slug: Any) -> bool:
        for c in self.classes:
            if c.get("slug") == class_slug:
                return bool(c.get("allow_external_follow_me", True))
        return True


COS_DENIED = [
    " same => n(cosdenied),NoOp(Veyra: not allowed by the class of service)",
    " same => n,Answer()",
    " same => n,Playback(pbx-invalid)",
    " same => n,Hangup(21)",
]
COS_BUSY = [
    " same => n(cosbusy),NoOp(Veyra: the class of service has too many outside calls up)",
    " same => n,Busy(10)",
    " same => n,Hangup()",
]


def _cos_for(snapshot: dict[str, Any], ns: str) -> Cos:
    classes = [
        c
        for c in (snapshot.get("classes_of_service") or [])
        if engine_names.for_org(str(c.get("organization") or "")).ns == ns
    ]
    length = int((snapshot.get("numbering") or {}).get("extension_length") or 4)
    return Cos(classes, length)


def _dnd_codes(codes: dict[str, str], cos: Cos | None = None) -> list[str]:
    """``*78``/``*79``/``*76`` (docs/CALL_FEATURES.md §3.2): the phone's own
    extension (``VEYRA_EXT`` from its endpoint) switches the engine's copy, the
    BLF device state, and tells the API through a UserEvent."""

    def switch(on: bool) -> list[str]:
        value = "1" if on else "0"
        return [
            f" same => n,Set(DB({STATE_KEY}/dnd)={value})",
            f" same => n,Set(DEVICE_STATE({DND_DEVICE})={'INUSE' if on else 'NOT_INUSE'})",
            _state_event("dnd", value),
            f" same => n,Playback(do-not-disturb&{'activated' if on else 'de-activated'})",
            " same => n,Hangup()",
        ]

    lines: list[str] = []
    if "dnd_on" in codes:
        head = f"exten => {codes['dnd_on']},1,NoOp(Veyra DND on for ${{VEYRA_EXT}})"
        lines += _code_block(head, switch(True), cos, "dnd_on")
    if "dnd_off" in codes:
        head = f"exten => {codes['dnd_off']},1,NoOp(Veyra DND off for ${{VEYRA_EXT}})"
        lines += _code_block(head, switch(False), cos, "dnd_off")
    if "dnd_toggle" in codes:
        head = f"exten => {codes['dnd_toggle']},1,NoOp(Veyra DND toggle for ${{VEYRA_EXT}})"
        body = [
            f' same => n,GotoIf($["${{DB({STATE_KEY}/dnd)}}"="1"]?off)',
            *switch(True),
            " same => n(off),NoOp()",
            *switch(False),
        ]
        lines += _code_block(head, body, cos, "dnd_toggle")
    return lines


FM_DEVICE = "Custom:veyra-fm-${VEYRA_ORG}-${VEYRA_EXT}"
FM_STRATEGIES = ("ringall", "sequential")
FM_CALLER_ID_MODES = ("caller", "extension")


def _follow_me_codes(codes: dict[str, str], cos: Cos | None = None) -> list[str]:
    """``*21`` toggles find me / follow me (docs/CALL_FEATURES.md §3.4)."""
    code = codes.get("fmfm_toggle")
    if not code:
        return []

    def switch(on: bool) -> list[str]:
        value = "1" if on else "0"
        return [
            f" same => n,Set(DB({STATE_KEY}/fmfm)={value})",
            f" same => n,Set(DEVICE_STATE({FM_DEVICE})={'INUSE' if on else 'NOT_INUSE'})",
            _state_event("fmfm", value),
            f" same => n,Playback(followme/status&{'activated' if on else 'de-activated'})",
            " same => n,Hangup()",
        ]

    return _code_block(
        f"exten => {code},1,NoOp(Veyra follow me toggle for ${{VEYRA_EXT}})",
        [
            f' same => n,GotoIf($["${{DB({STATE_KEY}/fmfm)}}"="1"]?off)',
            *switch(True),
            " same => n(off),NoOp()",
            *switch(False),
        ],
        cos,
        "fmfm_toggle",
    )


def _follow_me_contexts(spaces: list[str]) -> list[str]:
    """Per namespace: the outside leg of a follow-me (so the number leaves
    through that organization's routes) and the confirmation routine: the
    answering party presses 1, or the leg is dropped and the others keep
    ringing (``GOSUB_RESULT=CONTINUE``). Both stay inside the namespace so
    the isolation checks hold."""
    lines: list[str] = []
    for ns in spaces:
        n = Names(ns)
        lines += [
            f"[{n.follow_me_out}]",
            "; Follow-me legs to outside numbers; VEYRA_FM_OPTS carries the confirmation.",
            "exten => _[+0-9].,1,NoOp(Veyra follow-me leg to ${EXTEN})",
            " same => n,Set(__VEYRA_HOPS=0)",
            f" same => n,Dial(Local/${{EXTEN}}@{n.internal}/n,{OUTBOUND_DIAL_TIMEOUT},"
            "${VEYRA_FM_OPTS})",
            " same => n,Hangup()",
            "",
            f"[{n.follow_me_confirm}]",
            "exten => s,1,NoOp(Veyra follow-me confirmation)",
            " same => n,Read(VEYRA_OK,followme/options,1,,1,6)",
            ' same => n,GotoIf($["${VEYRA_OK}"="1"]?ok)',
            " same => n,Set(GOSUB_RESULT=CONTINUE)",
            " same => n,Return()",
            " same => n(ok),Return()",
            "",
        ]
    return lines


def _follow_me_branch(
    number: str,
    endpoint: str,
    fm: dict[str, Any],
    internal: str,
    fm_out: str,
    ocid: Any,
    *,
    external_allowed: bool = True,
) -> list[str]:
    """The ``fm`` label of an extension (docs/CALL_FEATURES.md §3.4). Outside
    legs are left out when the class of service forbids them (§3.8)."""
    strategy = str(fm.get("strategy") or "ringall")
    if strategy not in FM_STRATEGIES:
        raise GenerationError(f"extension {number}: unknown follow-me strategy {strategy!r}")
    mode = str(fm.get("caller_id_mode") or "caller")
    if mode not in FM_CALLER_ID_MODES:
        raise GenerationError(f"extension {number}: unknown follow-me caller ID mode {mode!r}")
    initial = int(fm.get("initial_ring_seconds") or 0)
    if not 0 <= initial <= 60:
        raise GenerationError(f"extension {number}: follow-me initial ring {initial} out of range")
    legs: list[tuple[str, int]] = []
    for m in fm.get("members") or []:
        ring = int(m.get("ring_seconds") or 20)
        if not 5 <= ring <= 60:
            raise GenerationError(f"extension {number}: follow-me ring time {ring} out of range")
        if m.get("type") == "external":
            target = str(m.get("target") or "")
            if not _NUMBER_RE.match(target):
                raise GenerationError(
                    f"extension {number}: follow-me number {target!r} is not valid"
                )
            if external_allowed:
                legs.append((f"Local/{target}@{fm_out}/n", ring))
        else:
            ep = m.get("endpoint")
            if ep:  # a disabled or removed extension is skipped
                legs.append((f"PJSIP/{_check_section(str(ep), 'endpoint name')}", ring))
    if not legs:
        return []
    dest = fm.get("no_answer_destination")
    if dest and not _NUMBER_RE.match(str(dest)):
        raise GenerationError(f"extension {number}: follow-me destination {dest!r} is not valid")
    cid = (
        " same => n,Set(__VEYRA_OUT_CID=${CALLERID(num)})"
        if mode == "caller"
        else (f" same => n,Set(__VEYRA_OUT_CID={ocid})" if ocid else "")
    )
    opts = f"U({engine_names.current().follow_me_confirm}^s)" if fm.get("confirm_calls") else ""
    lines = [
        f" same => n(fm),NoOp(Veyra: {number} follow me, {strategy})",
        *(
            [
                f" same => n,Dial(PJSIP/{endpoint},{initial})",
                ' same => n,GotoIf($["${DIALSTATUS}"="BUSY"]?busy)',
            ]
            if initial
            else []
        ),
        f" same => n,Set(__VEYRA_FM_OPTS={opts})",
        *([cid] if cid else []),
    ]
    if strategy == "ringall":
        ring = max(r for _, r in legs)
        lines.append(f" same => n,Dial({'&'.join(leg for leg, _ in legs)},{ring})")
        lines.append(' same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?fmdone)')
    else:
        for leg, ring in legs:
            lines += [
                f" same => n,Dial({leg},{ring})",
                ' same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?fmdone)',
            ]
    lines += [
        f" same => n,Goto({internal},{dest},1)" if dest else " same => n,Goto(noanswer)",
        " same => n(fmdone),Hangup()",
    ]
    return lines


INTERCOM_RING_SECONDS = 20


def _intercom_code(codes: dict[str, str], cos: Cos | None = None) -> list[str]:
    """``*80<ext>`` (docs/CALL_FEATURES.md §3.6): into the namespace's intercom
    context, which knows which phones may be made to answer on speaker. The
    caller's class may forbid intercom altogether."""
    code = codes.get("intercom")
    if not code:
        return []
    n = engine_names.current()
    guard = (cos.code_guard("intercom") + cos.intercom_guard()) if cos else []
    return [
        f"exten => _{code}.,1,NoOp(Veyra intercom from ${{VEYRA_EXT}} to ${{EXTEN:{len(code)}}})",
        ' same => n,GotoIf($["${VEYRA_EXT}"=""]?nophone)',
        *guard,
        f" same => n,Goto({n.intercom},${{EXTEN:{len(code)}}},1)",
        " same => n(nophone),Answer()",
        " same => n,Playback(feature-not-avail-line)",
        " same => n,Hangup()",
        *(COS_DENIED if guard else []),
    ]


def _intercom_context(extensions: list[dict[str, Any]]) -> list[str]:
    """One intercom context per namespace: allowed phones are rung with the
    auto-answer headers (Poly reads Alert-Info, Yealink and Grandstream
    Call-Info); denied and unknown numbers are refused. Do Not Disturb holds."""
    n = engine_names.current()
    lines = [f"[{n.intercom}]", "; Intercom targets; the phone answers on speaker."]
    for ext in extensions:
        number = str(ext["number"])
        org_slug = _check_value(str(ext.get("organization") or ""), "organization")
        if str(ext.get("intercom") or "allow") != "allow":
            lines += [
                f"exten => {number},1,NoOp(Veyra: intercom to {number} is not allowed)",
                " same => n,Answer()",
                " same => n,Playback(feature-not-avail-line)",
                " same => n,Hangup()",
            ]
            continue
        endpoint = _check_section(str(ext["endpoint_name"]), "endpoint name")
        lines += [
            f"exten => {number},1,NoOp(Veyra intercom to {number})",
            f' same => n,GotoIf($["${{DB(veyra/ext/{org_slug}/{number}/dnd)}}"="1"]?dnd)',
            f" same => n,Dial(PJSIP/{endpoint},{INTERCOM_RING_SECONDS},"
            f"b({n.intercom_headers}^s^1))",
            " same => n,Hangup()",
            " same => n(dnd),Busy(10)",
            " same => n,Hangup()",
        ]
    lines += [
        "exten => _X.,1,Answer()",
        " same => n,Playback(pbx-invalid)",
        " same => n,Hangup()",
        "",
    ]
    return lines


def _intercom_headers_context() -> list[str]:
    """Runs on the called phone's channel before it rings (Dial ``b()``)."""
    n = engine_names.current()
    return [
        f"[{n.intercom_headers}]",
        "exten => s,1,Set(PJSIP_HEADER(add,Alert-Info)=<http://www.notuse.com>"
        ";info=alert-autoanswer)",
        " same => n,Set(PJSIP_HEADER(add,Call-Info)=<sip:veyra>;answer-after=0)",
        " same => n,Return()",
        "",
    ]


def _voicemail_direct(
    codes: dict[str, str], boxes: list[tuple[str, dict[str, Any]]], cos: Cos | None = None
) -> list[str]:
    """``*<ext>`` (docs/CALL_FEATURES.md §3.7): straight to the box's unavailable
    greeting, dialled or as a transfer target. One exact entry per box, so no
    pattern can shadow another feature code. No phone check: a transferred
    caller's channel carries no ``VEYRA_EXT``."""
    code = codes.get("vm_direct")
    if not code:
        return []
    n = engine_names.current()
    guard = cos.code_guard("vm_direct") if cos else []
    lines: list[str] = []
    for number, _b in sorted(boxes, key=lambda kv: (len(kv[0]), kv[0])):
        lines += [
            f"exten => {code}{number},1,NoOp(Veyra direct to voicemail {number})",
            *guard,
            " same => n,Answer()",
            f" same => n,VoiceMail({number}@{n.voicemail},s)",
            " same => n,Hangup()",
            *(COS_DENIED if guard else []),
        ]
    return lines


def _voicemail_exit_contexts(boxes: list[tuple[str, dict[str, Any]]]) -> list[str]:
    """Per box with an operator: 0 rings the operator, * opens the box."""
    n = engine_names.current()
    lines: list[str] = []
    for number, b in sorted(boxes, key=lambda kv: (len(kv[0]), kv[0])):
        operator = b.get("operator_extension")
        if not operator:
            continue
        lines += [
            f"[{n.voicemail_exit(number)}]",
            f"exten => o,1,NoOp(Veyra: voicemail {number} operator)",
            f" same => n,Goto({n.internal},{operator},1)",
            f"exten => a,1,VoiceMailMain({number}@{n.voicemail})",
            " same => n,Hangup()",
            "",
        ]
    return lines


def _forward_codes(codes: dict[str, str], cos: Cos | None = None) -> list[str]:
    """``*72<number>`` / ``*72`` + prompt / ``*73`` and the busy and no-answer
    pairs (docs/CALL_FEATURES.md §3.3): the target goes into the engine's copy
    and to the API; the dialplan validates the digits."""
    lines: list[str] = []
    for field, (on_key, off_key) in _CF_CODES.items():
        prompt = _CF_PROMPTS[field]
        on = codes.get(on_key)
        if on:
            store = [
                f" same => n(store),Set(DB({STATE_KEY}/{field})=${{VEYRA_NUM}})",
                _CF_LAMP,
                _state_event(field, "${VEYRA_NUM}"),
                f" same => n,Playback({prompt}&activated)",
                " same => n,Hangup()",
                " same => n(bad),Playback(pbx-invalid)",
                " same => n,Hangup()",
            ]
            check = ' same => n,GotoIf($[${REGEX("^\\+?[0-9]{2,20}$" ${VEYRA_NUM})}]?store:bad)'
            lines += _code_block(
                f"exten => {on},1,NoOp(Veyra forward {field} for ${{VEYRA_EXT}})",
                [
                    f" same => n,Read(VEYRA_NUM,{prompt}&vm-enter-num-to-call,20,,2,10)",
                    check,
                    *store,
                ],
                cos,
                on_key,
            )
            lines += _code_block(
                f"exten => _{on}.,1,NoOp(Veyra forward {field} for ${{VEYRA_EXT}} "
                f"to ${{EXTEN:{len(on)}}})",
                [f" same => n,Set(VEYRA_NUM=${{EXTEN:{len(on)}}})", check, *store],
                cos,
                on_key,
            )
        off = codes.get(off_key)
        if off:
            lines += _code_block(
                f"exten => {off},1,NoOp(Veyra forward {field} off for ${{VEYRA_EXT}})",
                [
                    f" same => n,Set(VEYRA_GONE=${{DB_DELETE({STATE_KEY}/{field})}})",
                    _CF_LAMP,
                    _state_event(field, ""),
                    f" same => n,Playback({prompt}&de-activated)",
                    " same => n,Hangup()",
                ],
                cos,
                off_key,
            )
    return lines


def _features(
    extensions: list[dict[str, Any]],
    prompts_dir: str,
    codes: dict[str, str] | None = None,
    boxes: list[tuple[str, dict[str, Any]]] | None = None,
    cos: Cos | None = None,
    flows: list[dict[str, Any]] | None = None,
    conditions: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Feature codes of one namespace; ``**<ext>`` reaches only its phones."""
    n = engine_names.current()
    codes = codes or {}
    lines = [
        f"[{n.features}]",
        *_dnd_codes(codes, cos),
        *_forward_codes(codes, cos),
        *_follow_me_codes(codes, cos),
        *_intercom_code(codes, cos),
        *_voicemail_direct(codes, boxes or [], cos),
        *_call_flow_codes(codes, flows or [], cos),
        *_tc_override_codes(codes, conditions or [], cos),
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
        f" same => n,VoiceMailMain(${{CALLERID(num)}}@{n.voicemail})",
        " same => n,Hangup()",
        "exten => *98,1,NoOp(Veyra voicemail, any box)",
        " same => n,Answer()",
        f" same => n,VoiceMailMain(@{n.voicemail})",
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
    lines.append("")
    return lines


def _internal(
    extensions: list[dict[str, Any]],
    boxes: Boxes,
    ring_groups: list[dict[str, Any]],
    queues: list[dict[str, Any]],
    recording: list[dict[str, Any]],
    prompts_dir: str,
    dnd_toggle: str | None = None,
    cf_code: str | None = None,
    fm_code: str | None = None,
    cos: Cos | None = None,
    conferences: list[dict[str, Any]] | None = None,
    extra_hints: list[str] | None = None,
) -> list[str]:
    """The phone context of one namespace."""
    n = engine_names.current()
    by_number = {number: b for (_org, number), b in boxes.items()}
    lines = [
        f"[{n.internal}]",
        "; Extensions first; then feature codes, outbound routes and the catch-all",
        "; (includes are searched in order, after this context's own entries).",
        f"include => {n.features}",
        f"include => {n.paging}",
        f"include => {n.outbound}",
        f"include => {CONTEXT_INVALID}",
        *(extra_hints or []),
    ]
    for ext in extensions:
        number = str(ext["number"])
        endpoint = str(ext["endpoint_name"])
        box = by_number.get(number) if not (by_number.get(number) or {}).get("shared") else None
        # The hint lets busy lamp fields follow the phone (RING_GROUPS_QUEUES.md §4.2).
        lines.append(f"exten => {number},hint,PJSIP/{endpoint}")
        org_slug = _check_value(str(ext.get("organization") or ""), "organization")
        state = f"veyra/ext/{org_slug}/{number}"
        # Keys lit while Do Not Disturb or a forward is on (docs/CALL_FEATURES.md §3.2, §3.3).
        if dnd_toggle:
            lines.append(f"exten => {dnd_toggle}{number},hint,Custom:veyra-dnd-{org_slug}-{number}")
        if cf_code:
            lines.append(f"exten => {cf_code}{number},hint,Custom:veyra-cf-{org_slug}-{number}")
        fm_branch = _follow_me_branch(
            number,
            endpoint,
            ext.get("follow_me") or {},
            n.internal,
            n.follow_me_out,
            ext.get("outbound_caller_id_number"),
            external_allowed=(
                cos.allows_external_follow_me(ext.get("class_of_service")) if cos else True
            ),
        )
        # A class that may not forward outside (docs/CALL_FEATURES.md §3.8).
        forward_guard = cos.forward_guard() if cos else []
        if fm_code and fm_branch:
            lines.append(f"exten => {fm_code}{number},hint,Custom:veyra-fm-{org_slug}-{number}")
        ring = int(
            ext.get("ring_seconds") or (box or {}).get("ring_seconds") or DEFAULT_RING_SECONDS
        )
        if not 5 <= ring <= 120:
            raise GenerationError(f"extension {number}: ring time {ring} is out of range")
        rec = _record_for_extension(recording, ext, prompts_dir)
        ocid = ext.get("outbound_caller_id_number")
        # A forwarded leg leaves as this extension's call: its outbound caller
        # ID when it has one, else the route's and the trunk's (§3.5).
        forward_cid = [f" same => n,Set(__VEYRA_OUT_CID={ocid})"] if ocid else []
        forward = [
            f" same => n(forward),NoOp(Veyra: {number} forwards to ${{VEYRA_CF}})",
            *forward_guard,
            # A forward of a forward of a forward is enough; the loop guard of
            # the outbound routes does not apply to an administrator's forward.
            " same => n,GotoIf($[0${VEYRA_FWD} >= 3]?toomany)",
            " same => n,Set(__VEYRA_FWD=$[0${VEYRA_FWD} + 1])",
            " same => n,Set(__VEYRA_HOPS=0)",
            *forward_cid,
            f" same => n,Dial(Local/${{VEYRA_CF}}@{n.internal}/n,{OUTBOUND_DIAL_TIMEOUT})",
            " same => n,Hangup()",
            f" same => n(toomany),NoOp(Veyra: {number}: too many forwards)",
            " same => n,Playback(number-not-answering)",
            " same => n,Hangup()",
            *(COS_DENIED if forward_guard else []),
        ]
        head = [
            f"exten => {number},1,NoOp(Veyra extension {number})",
            f' same => n,GotoIf($["${{DB({state}/dnd)}}"="1"]?dnd)',
            f" same => n,Set(VEYRA_CF=${{DB({state}/cf_always)}})",
            ' same => n,GotoIf($["${VEYRA_CF}"!=""]?forward)',
            *rec,
            *([f' same => n,GotoIf($["${{DB({state}/fmfm)}}"="1"]?fm)'] if fm_branch else []),
            f" same => n,Dial(PJSIP/{endpoint},{ring})",
            ' same => n,GotoIf($["${DIALSTATUS}"="BUSY"]?busy)',
            f" same => n(noanswer),Set(VEYRA_CF=${{DB({state}/cf_no_answer)}})",
            ' same => n,GotoIf($["${VEYRA_CF}"!=""]?forward)',
        ]
        busy_branch = [
            f" same => n(dnd),NoOp(Veyra: {number} has Do Not Disturb on)",
            f" same => n(busy),Set(VEYRA_CF=${{DB({state}/cf_busy)}})",
            ' same => n,GotoIf($["${VEYRA_CF}"!=""]?forward)',
        ]
        if box is None:
            lines += [
                *head,
                " same => n,Hangup()",
                *busy_branch,
                " same => n,Busy(10)",
                " same => n,Hangup()",
                *forward,
                *fm_branch,
            ]
        else:
            # Unanswered and unavailable go to the unavailable greeting, busy
            # (and Do Not Disturb) to the busy greeting (docs/VOICEMAIL_IVR.md §3.2).
            lines += [
                *head,
                f" same => n,VoiceMail({number}@{n.voicemail},u)",
                " same => n,Hangup()",
                *busy_branch,
                f" same => n,VoiceMail({number}@{n.voicemail},b)",
                " same => n,Hangup()",
                *forward,
                *fm_branch,
            ]
    for number, b in sorted(by_number.items(), key=lambda kv: (len(kv[0]), kv[0])):
        if not b.get("shared"):
            continue
        lines += [
            f"exten => {number},1,NoOp(Veyra shared inbox {number})",
            f" same => n,VoiceMail({number}@{n.voicemail},u)",
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
            f" same => n,Goto({n.ring_group(slug)},s,1)",
        ]
    for q in queues:
        slug = _slug(q["slug"], "queue slug")
        number = str(q["number"])
        name = _check_value(str(q.get("name") or slug), "queue name")
        lines += [
            f"exten => {number},1,NoOp(Veyra queue {name})",
            f" same => n,Goto({n.queue_context(slug)},s,1)",
        ]
    for room in conferences or []:
        slug = _slug(room["slug"], "conference room slug")
        number = str(room["number"])
        name = _check_value(str(room.get("name") or slug), "conference room name")
        # The lamp of a key with the room's number is lit while anyone is in it.
        lines += [
            f"exten => {number},hint,confbridge:{n.conference(slug)}",
            f"exten => {number},1,NoOp(Veyra conference {name})",
            f" same => n,Goto({n.conference(slug)},s,1)",
        ]
    lines.append("")
    return lines


def _outbound_contexts(
    routes: list[dict[str, Any]],
    trunks: dict[str, dict[str, Any]],
    recording: list[dict[str, Any]] | None = None,
    prompts_dir: str = DEFAULT_PROMPTS_DIR,
    spaces: list[str] | None = None,
    cos: Cos | None = None,
) -> list[str]:
    """``veyra-outbound`` of each namespace and one shared ``veyra-out-<slug>``
    per route, emergency routes first (docs/TRUNKS_ROUTING.md §4, §6, §7). A
    route of one organization is included only in that organization's
    outbound context (docs/MULTI_TENANCY.md §4)."""
    # Emergency routes first; among them the site-bound ones before the
    # installation-wide ones, so a site's route is tried first and chains to
    # the next one when the caller's site differs (docs/PRODUCTION_HARDENING.md §6).
    ordered = sorted(
        routes,
        key=lambda r: (not bool(r.get("is_emergency")), not bool(r.get("site"))),
    )
    slugs: list[str] = []
    for r in ordered:
        slug = _check_section(str(r["slug"]), "outbound route slug")
        if slug in slugs:
            raise GenerationError(f"duplicate outbound route slug {slug!r}")
        slugs.append(slug)
    emergency_slugs = [sl for r, sl in zip(ordered, slugs, strict=True) if r.get("is_emergency")]
    lines: list[str] = []
    for ns in spaces if spaces is not None else [engine_names.LEGACY]:
        lines += [
            f"[{Names(ns).outbound}]",
            "; Routes in evaluation order; emergency routes first.",
        ]
        lines += [
            f"include => {CONTEXT_OUT_PREFIX}{slug}"
            for r, slug in zip(ordered, slugs, strict=True)
            if not r.get("organization") or engine_names.for_org(str(r["organization"])).ns == ns
        ]
        lines.append("")
    for r, slug in zip(ordered, slugs, strict=True):
        emergency = bool(r.get("is_emergency"))
        route_trunks = [str(t) for t in (r.get("trunks") or []) if str(t) in trunks]
        cid_override = r.get("caller_id_number")
        if cid_override and not _NUMBER_RE.match(str(cid_override)):
            raise GenerationError(f"outbound route {slug}: caller ID {cid_override!r} is not valid")
        cid_force = bool(cid_override) and bool(r.get("caller_id_force"))
        lines += [
            f"[{CONTEXT_OUT_PREFIX}{slug}]",
            f"; {_check_value(str(r.get('name') or slug), 'route name')}"
            + (" (emergency)" if emergency else ""),
        ]
        cos_guard = cos.route_guard(slug) if cos else []
        cos_limits = cos.route_limits() if cos else []
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
                # The class of service (docs/CALL_FEATURES.md §3.8) never blocks an emergency route.
                *(cos_guard if not emergency else []),
                *(cos_limits if not emergency else []),
                *_record_outbound(recording or [], prompts_dir),
            ]
            if emergency:
                site = str(r.get("site") or "")
                if site:
                    if not _SITE_RE.match(site):
                        raise GenerationError(f"outbound route {slug}: site {site!r} is not valid")
                    # Another site's phone: on to the next emergency route.
                    after = emergency_slugs[emergency_slugs.index(slug) + 1 :]
                    if after:
                        lines.append(
                            f' same => n,GotoIf($["${{VEYRA_SITE}}"!="{site}"]'
                            f"?{CONTEXT_OUT_PREFIX}{after[0]},${{EXTEN}},1)"
                        )
                # The extension's emergency caller ID wins over the route's
                # and the trunk's numbers (docs/TRUNKS_ROUTING.md §7).
                lines += [
                    " same => n,Set(__VEYRA_EMERGENCY=1)",
                    # On-site notification (Kari's Law): the API's event listener
                    # turns this into emergency.call (docs/PRODUCTION_HARDENING.md §6).
                    f" same => n,UserEvent({EMERGENCY_EVENT},Extension: ${{CALLERID(num)}},"
                    f"Site: ${{VEYRA_SITE}},Number: ${{EXTEN}},Route: {slug},"
                    "EmergencyCID: ${VEYRA_EMERGENCY_CID},Channel: ${CHANNEL})",
                    # The PSAP's callback finds the caller through the ELIN (§6).
                    ' same => n,ExecIf($["${VEYRA_EMERGENCY_CID}"!=""]'
                    f"?Set(DB({ASTDB_CALLBACK}/${{VEYRA_EMERGENCY_CID}})="
                    "${CALLERID(num)}|${EPOCH}))",
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
                if cid and not _NUMBER_RE.match(str(cid)):
                    raise GenerationError(f"trunk {tslug}: caller ID {cid!r} is not valid")
                step += _outbound_caller_id(cid, cid_force, emergency)
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
                    *(COS_DENIED if cos_guard else []),
                    *(COS_BUSY if cos_limits else []),
                ]
        lines.append("")
    return lines


def _inbound_contexts(
    routes: list[dict[str, Any]],
    conditions: dict[str, dict[str, Any]],
    trunk_slugs: list[str],
    recording: list[dict[str, Any]] | None = None,
    prompts_dir: str = DEFAULT_PROMPTS_DIR,
    sites: list[dict[str, Any]] | None = None,
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
    # The PSAP's callback to a site's ELIN (docs/PRODUCTION_HARDENING.md §6):
    # within the window it rings the extension that placed the emergency
    # call, else the site's responder, else the DID's own route.
    elins: dict[str, dict[str, Any]] = {}
    for site in sites or []:
        elin = routing.normalize_did(str(site.get("emergency_caller_id_number") or ""))
        if elin:
            elins[routing.canonical_did(elin)] = site

    def callback_lines(site: dict[str, Any], did: str) -> list[str]:
        window = int(site.get("callback_minutes") or 30) * 60
        ns = engine_names.for_org(str(site.get("organization") or "")).internal
        out = [
            f" same => n,Set(VEYRA_ECB=${{DB({ASTDB_CALLBACK}/{did})}})",
            ' same => n,GotoIf($["${VEYRA_ECB}"=""]?responder)',
            " same => n,Set(VEYRA_ECB_EXT=${CUT(VEYRA_ECB,|,1)})",
            " same => n,Set(VEYRA_ECB_AT=${CUT(VEYRA_ECB,|,2)})",
            f" same => n,GotoIf($[${{EPOCH}} - ${{VEYRA_ECB_AT}} > {window}]?responder)",
            " same => n,NoOp(Veyra: emergency callback to ${VEYRA_ECB_EXT})",
            f" same => n,Goto({ns},${{VEYRA_ECB_EXT}},1)",
            " same => n(responder),NoOp(Veyra: emergency callback outside the window)",
        ]
        responder = site.get("responder")
        if responder:
            out.append(f" same => n,Goto({ns},{_check_value(str(responder), 'responder')},1)")
        return out

    def body(r: dict[str, Any], context: str) -> list[str]:
        did = r["did"]
        if did == routing.DID_ANY:
            return []  # rendered by the fallback context
        out = [
            f"exten => {did},1,NoOp(Veyra inbound {did} via ${{VEYRA_TRUNK}})",
            " same => n,Set(__VEYRA_HOPS=1)",
            f" same => n,Set(__VEYRA_DID={did})",
            *_record_inbound(recording or [], r, prompts_dir),
        ]
        site = elins.get(routing.canonical_did(did))
        if site is not None:
            out += callback_lines(site, did)
        out += _destination_lines(r, conditions)
        for alias in routing.did_aliases(did):
            if (r.get("trunk") or None, alias) not in explicit:
                out.append(f"exten => {alias},1,Goto({context},{did},1)")
        return out

    lines = [f"[{CONTEXT_FROM_TRUNK}]", "; DIDs that match on every trunk."]
    for r in shared:
        lines += body(r, CONTEXT_FROM_TRUNK)
    # ELINs without an inbound route of their own still take the callback.
    routed = {routing.canonical_did(r["did"]) for r in shared} | {
        routing.canonical_did(r["did"]) for rs in per_trunk.values() for r in rs
    }
    for canonical, site in elins.items():
        if canonical in routed:
            continue
        did = routing.normalize_did(str(site["emergency_caller_id_number"]))
        lines += [
            f"exten => {did},1,NoOp(Veyra emergency callback for {site.get('slug')})",
            " same => n,Set(__VEYRA_HOPS=1)",
            f" same => n,Set(__VEYRA_DID={did})",
            *callback_lines(site, did),
            " same => n,Hangup(1)",
        ]
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
    """An inbound route's destination, in the names of the route's organization."""
    with engine_names.using(engine_names.for_org(str(r.get("organization_slug") or ""))):
        return _destination_lines_of(r, conditions)


def _destination_lines_of(r: dict[str, Any], conditions: dict[str, dict[str, Any]]) -> list[str]:
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
        # An override forced from a phone or the interface wins over the
        # schedule (docs/CALL_FEATURES.md §4.6).
        key = _check_value(str(cond_key), "time condition key")
        org_slug = str(cond.get("organization") or r.get("organization_slug") or "")
        if org_slug:
            org = _slug(org_slug, "organization")
            out += [
                f" same => n,Set(VEYRA_TC=${{DB({SWITCH_FAMILY}/tc/{org}/{key})}})",
                ' same => n,GotoIf($["${VEYRA_TC}"="open"]?open)',
                ' same => n,GotoIf($["${VEYRA_TC}"="closed"]?closed)',
            ]
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
        return [f" same => n,Goto({engine_names.current().ivr(slug)},s,1)", " same => n,Hangup()"]
    if kind == "ring_group":
        slug = _slug(dest.get("ring_group"), "ring group slug")
        ctx = engine_names.current().ring_group(slug)
        return [f" same => n,Goto({ctx},s,1)", " same => n,Hangup()"]
    if kind == "queue":
        slug = _slug(dest.get("queue"), "queue slug")
        ctx = engine_names.current().queue_context(slug)
        return [f" same => n,Goto({ctx},s,1)", " same => n,Hangup()"]
    if kind == "announcement":
        slug = _slug(dest.get("announcement"), "announcement slug")
        ctx = engine_names.current().announcement(slug)
        return [f" same => n,Goto({ctx},s,1)", " same => n,Hangup()"]
    if kind == "conference":
        slug = _slug(dest.get("conference"), "conference room slug")
        ctx = engine_names.current().conference(slug)
        return [f" same => n,Goto({ctx},s,1)", " same => n,Hangup()"]
    if kind == "call_flow":
        slug = _slug(dest.get("call_flow"), "call flow slug")
        ctx = engine_names.current().call_flow(slug)
        return [f" same => n,Goto({ctx},s,1)", " same => n,Hangup()"]
    if kind == "directory":
        return [f" same => n,Goto({engine_names.current().directory},s,1)", " same => n,Hangup()"]
    if kind in ("extension", "voicemail"):
        number = str(dest.get("number") or "")
        if not _NUMBER_RE.match(number):
            raise GenerationError(f"destination number {number!r} is not valid")
        if kind == "voicemail":
            return [
                f" same => n,VoiceMail({number}@{engine_names.current().voicemail},u)",
                " same => n,Hangup()",
            ]
        internal = engine_names.current().internal
        return [f" same => n,Goto({internal},{number},1)", " same => n,Hangup()"]
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
        ctx = engine_names.current().ivr(slug)
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
                internal = engine_names.current().internal
                lines.append(f"exten => {number},1,Goto({internal},{number},1)")
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


def _switch_pin_lines(pin: Any, what: str) -> list[str]:
    """Ask for and check a switch's PIN (three attempts) before it toggles."""
    pin = str(pin or "")
    if not pin:
        return []
    if not _PIN_RE.match(pin):
        raise GenerationError(f"{what}: the PIN must be 4 to 10 digits")
    return [
        " same => n,Set(VEYRA_PIN_TRIES=0)",
        " same => n(pin),Read(VEYRA_PIN,agent-pass,10,,1,10)",
        f' same => n,GotoIf($["${{VEYRA_PIN}}"="{pin}"]?ok)',
        " same => n,Set(VEYRA_PIN_TRIES=$[${VEYRA_PIN_TRIES} + 1])",
        f" same => n,GotoIf($[${{VEYRA_PIN_TRIES}} >= {SWITCH_PIN_TRIES}]?badpin)",
        " same => n,Playback(auth-incorrect)",
        " same => n,Goto(pin)",
        " same => n(ok),NoOp()",
    ]


_SWITCH_PIN_TAIL = [
    " same => n(badpin),Playback(auth-incorrect)",
    " same => n,Hangup()",
]


def _switch_event(kind: str, org: str, key: str, value: str) -> str:
    return f" same => n,UserEvent({SWITCH_EVENT},Kind: {kind},Org: {org},Key: {key},Value: {value})"


def _code_index(item: dict[str, Any], what: str) -> int:
    idx = item.get("code_index")
    if idx is None or not 0 <= int(idx) <= MAX_CODE_INDEX:
        raise GenerationError(
            f"{what}: the code index {idx!r} is out of range (0-{MAX_CODE_INDEX})"
        )
    return int(idx)


def _call_flow_codes(
    codes: dict[str, str], flows: list[dict[str, Any]], cos: Cos | None = None
) -> list[str]:
    """``*28<index>`` toggles a call flow (docs/CALL_FEATURES.md §4.5): the
    engine store and the lamp are switched and the API is told."""
    prefix = codes.get("callflow_toggle_prefix")
    if not prefix:
        return []
    lines: list[str] = []
    seen: dict[int, str] = {}
    for f in flows:
        slug = _slug(f["slug"], "call flow slug")
        org = _slug(f.get("organization") or "", f"organization of call flow {slug}")
        idx = _code_index(f, f"call flow {slug}")
        if idx in seen:
            raise GenerationError(f"call flows {seen[idx]} and {slug} share the code index {idx}")
        seen[idx] = slug
        name = _check_value(str(f.get("name") or slug), "call flow name")
        store = f"{SWITCH_FAMILY}/flow/{org}/{slug}"
        device = f"Custom:veyra-flow-{org}-{slug}"
        pin = _switch_pin_lines(f.get("pin"), f"call flow {slug}")
        body = [
            f' same => n,GotoIf($["${{VEYRA_ORG}}"!="{org}"]?nophone)',
            *pin,
            f' same => n,GotoIf($["${{DB({store})}}"="1"]?off)',
            f" same => n,Set(DB({store})=1)",
            f" same => n,Set(DEVICE_STATE({device})=INUSE)",
            _switch_event("flow", org, slug, "1"),
            " same => n,Playback(activated)",
            " same => n,Hangup()",
            f" same => n(off),NoOp(Veyra call flow {name}: back to normal)",
            f" same => n,Set(VEYRA_DEL=${{DB_DELETE({store})}})",
            f" same => n,Set(DEVICE_STATE({device})=NOT_INUSE)",
            _switch_event("flow", org, slug, "0"),
            " same => n,Playback(de-activated)",
            " same => n,Hangup()",
            *(_SWITCH_PIN_TAIL if pin else []),
        ]
        head = f"exten => {prefix}{idx},1,NoOp(Veyra call flow {name} toggle)"
        lines += _code_block(head, body, cos, "callflow_toggle_prefix")
    return lines


def _tc_force(store: str, device: str, org: str, key: str, state: str) -> list[str]:
    return [
        f" same => n,Set(DB({store})={state})",
        f" same => n,Set(DEVICE_STATE({device})=INUSE)",
        _switch_event("tc", org, key, state),
        " same => n,Playback(activated)",
        " same => n,Hangup()",
    ]


def _tc_override_codes(
    codes: dict[str, str], conditions: list[dict[str, Any]], cos: Cos | None = None
) -> list[str]:
    """``*27<index>`` overrides a time condition (docs/CALL_FEATURES.md §4.6):
    when no override is set, the schedule's current state is inverted until
    the schedule changes (the worker clears it); dialled again, it clears."""
    prefix = codes.get("tc_override_prefix")
    if not prefix:
        return []
    lines: list[str] = []
    seen: dict[int, str] = {}
    for c in conditions:
        if c.get("code_index") is None:
            continue
        key = _check_value(str(c["key"]), "time condition key")
        org = _slug(c.get("organization") or "", f"organization of time condition {key}")
        idx = _code_index(c, f"time condition {c.get('name') or key}")
        if idx in seen:
            raise GenerationError(
                f"time conditions {seen[idx]} and {c.get('name')} share the code index {idx}"
            )
        seen[idx] = str(c.get("name") or key)
        name = _check_value(str(c.get("name") or key), "time condition name")
        tz = routing.check_timezone(str(c.get("timezone") or "UTC"))
        closed, opened = routing.gotoiftime_args(
            routing.check_ranges(list(c.get("ranges") or [])),
            routing.check_holidays(list(c.get("holidays") or [])),
            tz,
        )
        store = f"{SWITCH_FAMILY}/tc/{org}/{key}"
        device = f"Custom:veyra-tc-{org}-{key}"

        pin = _switch_pin_lines(c.get("pin"), f"time condition {name}")
        body = [
            f' same => n,GotoIf($["${{VEYRA_ORG}}"!="{org}"]?nophone)',
            *pin,
            f' same => n,GotoIf($["${{DB({store})}}"!=""]?clear)',
            *[f" same => n,GotoIfTime({args}?isclosed)" for args in closed],
            *[f" same => n,GotoIfTime({args}?isopen)" for args in opened],
            f" same => n(isclosed),NoOp(Veyra time condition {name}: closed now, forcing open)",
            *_tc_force(store, device, org, key, "open"),
            f" same => n(isopen),NoOp(Veyra time condition {name}: open now, forcing closed)",
            *_tc_force(store, device, org, key, "closed"),
            f" same => n(clear),NoOp(Veyra time condition {name}: back to the schedule)",
            f" same => n,Set(VEYRA_DEL=${{DB_DELETE({store})}})",
            f" same => n,Set(DEVICE_STATE({device})=NOT_INUSE)",
            _switch_event("tc", org, key, ""),
            " same => n,Playback(de-activated)",
            " same => n,Hangup()",
            *(_SWITCH_PIN_TAIL if pin else []),
        ]
        head = f"exten => {prefix}{idx},1,NoOp(Veyra time condition {name} override)"
        lines += _code_block(head, body, cos, "tc_override_prefix")
    return lines


def _switch_hints(
    codes: dict[str, str], flows: list[dict[str, Any]], conditions: list[dict[str, Any]]
) -> list[str]:
    """BLF hints of the switch codes in the phone context: lit while a flow is
    switched or an override is set."""
    hints: list[str] = []
    prefix = codes.get("callflow_toggle_prefix")
    if prefix:
        for f in flows:
            slug = _slug(f["slug"], "call flow slug")
            org = _slug(f.get("organization") or "", "organization")
            hints.append(
                f"exten => {prefix}{_code_index(f, slug)},hint,Custom:veyra-flow-{org}-{slug}"
            )
    prefix = codes.get("tc_override_prefix")
    if prefix:
        for c in conditions:
            if c.get("code_index") is None:
                continue
            key = _check_value(str(c["key"]), "time condition key")
            org = _slug(c.get("organization") or "", "organization")
            hints.append(f"exten => {prefix}{_code_index(c, key)},hint,Custom:veyra-tc-{org}-{key}")
    return hints


def _call_flow_contexts(flows: list[dict[str, Any]]) -> list[str]:
    """One ``veyra-flow-<slug>`` per enabled call flow (docs/CALL_FEATURES.md
    §4.5): the normal destination, or the override while the switch is on."""
    lines: list[str] = []
    seen: set[str] = set()
    for f in flows:
        slug = _slug(f["slug"], "call flow slug")
        if slug in seen:
            raise GenerationError(f"duplicate call flow slug {slug!r}")
        seen.add(slug)
        name = _check_value(str(f.get("name") or slug), "call flow name")
        org = _slug(f.get("organization") or "", f"organization of call flow {slug}")
        store = f"{SWITCH_FAMILY}/flow/{org}/{slug}"
        lines += [
            f"[{engine_names.current().call_flow(slug)}]",
            f"exten => s,1,NoOp(Veyra call flow {name} ({org}))",
            " same => n,Set(__VEYRA_FLOW_DEPTH=$[0${VEYRA_FLOW_DEPTH} + 1])",
            f" same => n,GotoIf($[${{VEYRA_FLOW_DEPTH}} > {routing.MAX_IVR_DEPTH}]?toodeep)",
            f' same => n,GotoIf($["${{DB({store})}}"="1"]?override)',
            f" same => n,NoOp(Veyra call flow {name}: normal)",
            *_goto(f.get("normal")),
            f" same => n(override),NoOp(Veyra call flow {name}: switched)",
            *_goto(f.get("override_destination")),
            " same => n(toodeep),NoOp(Veyra: call flows point at each other in a loop)",
            " same => n,Playback(pbx-invalid)",
            " same => n,Hangup()",
            "",
        ]
    return lines


def _announcement_contexts(announcements: list[dict[str, Any]], prompts_dir: str) -> list[str]:
    """One ``veyra-ann-<slug>`` per enabled announcement (docs/CALL_FEATURES.md
    §4.1): play the prompt, optionally skippable or repeatable by a key, then
    continue to the destination."""
    lines: list[str] = []
    seen: set[str] = set()
    for a in announcements:
        slug = _slug(a["slug"], "announcement slug")
        if slug in seen:
            raise GenerationError(f"duplicate announcement slug {slug!r}")
        seen.add(slug)
        name = _check_value(str(a.get("name") or slug), "announcement name")
        org = _slug(a.get("organization") or "", f"organization of announcement {slug}")
        ctx = engine_names.current().announcement(slug)
        prompt = a.get("prompt")
        lines += [f"[{ctx}]", f"; {name} ({org})"]
        if not prompt:
            lines += [
                f"exten => s,1,NoOp(Veyra announcement {name}: no prompt, not deployable)",
                " same => n,Congestion(5)",
                " same => n,Hangup()",
                "",
            ]
            continue
        path = f"{prompts_dir}/{org}/{_slug(prompt, 'prompt slug')}"
        repeat = a.get("repeat_key")
        if repeat is not None and str(repeat) not in routing.IVR_DIGITS:
            raise GenerationError(f"announcement {slug}: repeat key {repeat!r} is not valid")
        skip = bool(a.get("allow_skip"))
        lines += [
            f"exten => s,1,NoOp(Veyra announcement {name})",
            " same => n,Set(__VEYRA_ANN_DEPTH=$[0${VEYRA_ANN_DEPTH} + 1])",
            f" same => n,GotoIf($[${{VEYRA_ANN_DEPTH}} > {routing.MAX_IVR_DEPTH}]?toodeep)",
            " same => n,Answer()",
        ]
        if skip or repeat is not None:
            # Keys are accepted while the prompt plays: the repeat key replays
            # it, any other key (when skipping is allowed) ends it early.
            lines += [
                f" same => n(play),Background({path})",
                " same => n,WaitExten(1)",
                " same => n,Goto(next)",
            ]
        else:
            lines.append(f" same => n(play),Playback({path})")
        lines += [
            f" same => n(next),NoOp(Veyra announcement {name}: continuing)",
            *_goto(a.get("destination")),
            " same => n(toodeep),NoOp(Veyra: announcements point at each other in a loop)",
            " same => n,Playback(pbx-invalid)",
            " same => n,Hangup()",
        ]
        if repeat is not None:
            lines.append(f"exten => {repeat},1,Goto(s,play)")
        if skip:
            lines.append("exten => _[0-9*#],1,Goto(s,next)")
        if skip or repeat is not None:
            lines += ["exten => t,1,Goto(s,next)", "exten => i,1,Goto(s,next)"]
        lines.append("")
    return lines


def _directory_context() -> list[str]:
    """``veyra-directory``: dial by name over the organization's voicemail
    boxes (docs/CALL_FEATURES.md §4.2); 0 or * leave with a goodbye."""
    n = engine_names.current()
    return [
        f"[{n.directory}]",
        "exten => s,1,NoOp(Veyra dial-by-name directory)",
        " same => n,Answer()",
        f" same => n,Directory({n.voicemail},{n.internal},eb)",
        " same => n,Playback(vm-goodbye)",
        " same => n,Hangup()",
        "exten => o,1,Playback(vm-goodbye)",
        " same => n,Hangup()",
        "exten => a,1,Playback(vm-goodbye)",
        " same => n,Hangup()",
        "",
    ]


def _conference_profiles(slug: str) -> tuple[str, str, str, str, str]:
    """Room name, bridge, user, admin and menu profile names of a room."""
    stem = engine_names.current().conference(slug)
    return stem, f"{stem}-bridge", f"{stem}-user", f"{stem}-admin", f"{stem}-menu"


def _conference_contexts(rooms: list[dict[str, Any]]) -> list[str]:
    """One ``veyra-conf-<slug>`` per enabled room (docs/CALL_FEATURES.md §4.3):
    the PIN check (user and administrator PINs, three attempts), then
    ``ConfBridge`` with the room's profiles from ``confbridge.conf``."""
    lines: list[str] = []
    seen: set[str] = set()
    for r in rooms:
        slug = _slug(r["slug"], "conference room slug")
        if slug in seen:
            raise GenerationError(f"duplicate conference room slug {slug!r}")
        seen.add(slug)
        name = _check_value(str(r.get("name") or slug), "conference room name")
        org = _slug(r.get("organization") or "", f"organization of conference room {slug}")
        room, bridge, user, admin, menu = _conference_profiles(slug)
        user_pin = str(r.get("user_pin") or "")
        admin_pin = str(r.get("admin_pin") or "")
        for which, pin in (("user", user_pin), ("admin", admin_pin)):
            if pin and not _PIN_RE.match(pin):
                raise GenerationError(
                    f"conference room {slug}: the {which} PIN must be 4 to 10 digits"
                )
        if user_pin and admin_pin and user_pin == admin_pin:
            raise GenerationError(f"conference room {slug}: the user and admin PINs are the same")
        lines += [
            f"[{engine_names.current().conference(slug)}]",
            f"exten => s,1,NoOp(Veyra conference {name} ({org}))",
            " same => n,Answer()",
            f" same => n,Set(VEYRA_CONF_PROFILE={user})",
        ]
        if user_pin or admin_pin:
            lines += [
                " same => n,Set(VEYRA_CONF_TRIES=0)",
                " same => n(pin),Read(VEYRA_PIN,conf-getpin,10,,1,10)",
            ]
            if admin_pin:
                lines.append(f' same => n,GotoIf($["${{VEYRA_PIN}}"="{admin_pin}"]?admin)')
            if user_pin:
                lines.append(f' same => n,GotoIf($["${{VEYRA_PIN}}"="{user_pin}"]?join)')
            else:
                # Only an administrator PIN: everyone else joins with # alone.
                lines.append(' same => n,GotoIf($["${VEYRA_PIN}"=""]?join)')
            lines += [
                " same => n,Set(VEYRA_CONF_TRIES=$[${VEYRA_CONF_TRIES} + 1])",
                f" same => n,GotoIf($[${{VEYRA_CONF_TRIES}} >= {CONFERENCE_PIN_TRIES}]?bye)",
                " same => n,Playback(conf-invalidpin)",
                " same => n,Goto(pin)",
            ]
            if admin_pin:
                lines.append(f" same => n(admin),Set(VEYRA_CONF_PROFILE={admin})")
        lines += [
            f" same => n(join),ConfBridge({room},{bridge},${{VEYRA_CONF_PROFILE}},{menu})",
            " same => n,Hangup()",
            " same => n(bye),Playback(vm-goodbye)",
            " same => n,Hangup()",
            "",
        ]
    return lines


def _confbridge(
    rooms: list[dict[str, Any]], moh: MohSets | None, recordings_dir: str
) -> GeneratedFile:
    """``confbridge.conf`` (docs/CALL_FEATURES.md §4.3): a bridge, a user and
    an administrator profile and the key menu of every enabled room; reloaded
    with ``app_confbridge.so``. Recordings land in ``<recordings>/conferences``."""
    lines = [HEADER, "[general]", ""]
    seen: set[str] = set()
    for r in rooms:
        slug = _slug(r["slug"], "conference room slug")
        org = _slug(r.get("organization") or "", f"organization of conference room {slug}")
        n = engine_names.for_org(org)
        with engine_names.using(n):
            room, bridge, user, admin, menu = _conference_profiles(slug)
        if room in seen:
            raise GenerationError(f"duplicate conference room slug {slug!r}")
        seen.add(room)
        name = _check_value(str(r.get("name") or slug), "conference room name")
        limit = int(r.get("max_participants") or 0)
        if not 0 <= limit <= CONFERENCE_MAX_MEMBERS:
            raise GenerationError(
                f"conference room {slug}: participant limit {limit} is out of range"
            )
        join_leave = "yes" if r.get("announce_join_leave", True) else "no"
        alone = "yes" if r.get("music_on_hold_alone", True) else "no"
        wait = "yes" if r.get("wait_for_admin") else "no"
        music = _moh_class(r.get("hold_music"), moh or {}, f"conference room {slug}", org)
        lines += [
            f"[{bridge}]",
            f"; {name} ({org})",
            "type=bridge",
            f"max_members={limit}" if limit else "; max_members: no limit",
            "record_conference=" + ("yes" if r.get("record") else "no"),
        ]
        if r.get("record"):
            lines += [
                # ConfBridge appends the timestamp and ".wav" itself.
                f"record_file={recordings_dir}/{DEFAULT_CONFERENCES_SUBDIR}/{org}--{slug}",
                "record_file_timestamp=yes",
            ]
        lines += [
            "language=en",
            f"[{user}]",
            "type=user",
            f"announce_join_leave={join_leave}",
            f"music_on_hold_when_empty={alone}",
            f"music_on_hold_class={music}",
            f"wait_marked={wait}",
            "dsp_drop_silence=yes",
            f"[{admin}]",
            "type=user",
            "admin=yes",
            "marked=yes",
            f"announce_join_leave={join_leave}",
            f"music_on_hold_when_empty={alone}",
            f"music_on_hold_class={music}",
            "dsp_drop_silence=yes",
            f"[{menu}]",
            "type=menu",
            "*1=toggle_mute",
            "*4=decrease_listening_volume",
            "*6=increase_listening_volume",
            "*7=decrease_talking_volume",
            "*9=increase_talking_volume",
            "*2=admin_toggle_conference_lock",
            "*3=admin_kick_last",
            "*8=admin_toggle_mute_participants",
            "",
        ]
    return GeneratedFile(FILE_CONFBRIDGE, "\n".join(lines).rstrip("\n") + "\n")


def _check_group_numbers(
    extensions: list[dict[str, Any]],
    ring_groups: list[dict[str, Any]],
    queues: list[dict[str, Any]],
    conferences: list[dict[str, Any]] | None = None,
) -> None:
    """Ring group, queue and conference room numbers share the extension number
    space of their engine namespace (docs/MULTI_TENANCY.md §3)."""

    def key(item: dict[str, Any], number: str) -> tuple[str, str]:
        return (engine_names.for_org(str(item.get("organization") or "")).ns, number)

    taken = {key(e, str(e["number"])): "extension" for e in extensions}
    for what, items in (
        ("ring group", ring_groups),
        ("queue", queues),
        ("conference room", conferences or []),
    ):
        for item in items:
            number = str(item.get("number") or "")
            if not _NUMBER_RE.match(number):
                raise GenerationError(f"{what} number {number!r} is not valid")
            if key(item, number) in taken:
                raise GenerationError(
                    f"number {number} is used by a {taken[key(item, number)]} and a {what}"
                )
            taken[key(item, number)] = what


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
    groups: list[dict[str, Any]],
    moh: MohSets | None = None,
    recording: list[dict[str, Any]] | None = None,
    prompts_dir: str = DEFAULT_PROMPTS_DIR,
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
        # Outside numbers (docs/CALL_FEATURES.md §3.4): Local legs through the
        # namespace's follow-me outbound context, confirmed with 1 when asked.
        outside: list[str] = []
        for number in g.get("external_members") or []:
            if not _NUMBER_RE.match(str(number)):
                raise GenerationError(f"ring group {slug}: outside number {number!r} is not valid")
            outside.append(f"Local/{number}@{engine_names.current().follow_me_out}/n")
        confirm = (
            f"U({engine_names.current().follow_me_confirm}^s)" if g.get("confirm_external") else ""
        )
        ring_busy = bool(g.get("ring_busy_members"))
        music = str(g.get("music") or "ring")
        if music not in QUEUE_MUSIC:
            raise GenerationError(f"ring group {slug}: unknown hold music {music!r}")
        # Callers hear ringing, or the group's (or built-in) hold music set.
        dial_opts = ""
        if music == "default":
            moh_class = _moh_class(g.get("hold_music"), moh or {}, f"ring group {slug}", org)
            dial_opts = f",m({moh_class})"
        ctx = engine_names.current().ring_group(slug)
        lines += _group_prologue(ctx, "ring group", name, org)
        lines += _record_for_group(recording or [], org, "ring_groups", slug, prompts_dir)
        prefix = g.get("caller_id_prefix")
        if prefix:
            lines.append(
                f" same => n,Set(CALLERID(name)={_prefix(str(prefix))}${{CALLERID(name)}})"
            )
        if outside:
            lines += [
                f" same => n,Set(__VEYRA_FM_OPTS={confirm})",
                " same => n,Set(__VEYRA_HOPS=0)",
            ]
        if not members and not outside:
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
            for leg in outside:
                lines.append(f" same => n,Set(VEYRA_DIAL=${{VEYRA_DIAL}}&{leg})")
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
            for leg in outside:
                lines += [
                    f" same => n,Dial({leg},{ring}{dial_opts})",
                    ' same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?done)',
                ]
            lines.append(" same => n,Goto(failover)")
        lines += [" same => n(done),Hangup()"]
        lines += _group_epilogue("ring group", name, g.get("failover"))
        lines.append("")
    return lines


def _queue_contexts(
    queues: list[dict[str, Any]],
    prompts_dir: str,
    recording: list[dict[str, Any]] | None = None,
) -> list[str]:
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
        lines += _group_prologue(engine_names.current().queue_context(slug), "queue", name, org)
        lines += _record_for_group(recording or [], org, "queues", slug, prompts_dir)
        lines.append(" same => n,Answer()")
        announcement = q.get("announcement_prompt")
        if announcement:
            lines.append(
                f" same => n,Playback({prompts_dir}/{org}/{_slug(announcement, 'prompt slug')})"
            )
        options = "tr" if music == "ring" else "t"
        timeout = str(wait) if wait else ""
        lines += [
            f" same => n,Queue({engine_names.current().queue(slug)},{options},,,{timeout})",
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
    moh: MohSets | None = None,
) -> GeneratedFile:
    """``queues.conf`` (docs/RING_GROUPS_QUEUES.md §3): one section per
    enabled queue with static members; reloaded with ``app_queue.so``."""
    endpoints = {str(e["endpoint_name"]) for e in extensions}
    endpoint_org = {str(e["endpoint_name"]): str(e.get("organization") or "") for e in extensions}
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
        org = _slug(q.get("organization") or "", f"organization of queue {slug}")
        n = engine_names.for_org(org)
        if n.queue(slug) in seen:
            raise GenerationError(f"duplicate queue slug {slug!r}")
        seen.add(n.queue(slug))
        name = _check_value(str(q.get("name") or slug), "queue name")
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
            f"[{n.queue(slug)}]",
            f"; {name} ({org})",
            f"strategy={strategy}",
            f"timeout={timeout}",
            f"retry={retry}",
            f"wrapuptime={wrapup}",
            f"maxlen={maxlen}",
            "ringinuse=no",
            f"joinempty={empty}",
            f"leavewhenempty={'no' if q.get('join_when_empty') else 'strict'}",
            f"musicclass={_moh_class(q.get('hold_music'), moh or {}, f'queue {slug}', org)}",
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
            if endpoint not in endpoints or endpoint_org.get(endpoint) != org:
                continue  # gone, or (never) another organization's phone
            penalty = int(m.get("penalty") or 0)
            if not 0 <= penalty <= 9:
                raise GenerationError(f"queue {slug}: penalty {penalty} is out of range")
            member_name = _display(m.get("name")) or str(m.get("number") or endpoint)
            lines.append(f"member => PJSIP/{endpoint},{penalty},{member_name},PJSIP/{endpoint}")
        lines.append("")
    return GeneratedFile(FILE_QUEUES, "\n".join(lines).rstrip("\n") + "\n")


Boxes = dict[tuple[str, str], dict[str, Any]]


def _check_boxes(boxes: list[dict[str, Any]], extensions: list[dict[str, Any]]) -> Boxes:
    """Voicemail boxes by (organization, number); only boxes of listed
    extensions and shared inboxes. Numbers are unique per engine namespace."""

    def key(org: str, number: str) -> tuple[str, str]:
        return (engine_names.for_org(org).ns, number)

    numbers = {key(str(e.get("organization") or ""), str(e["number"])) for e in extensions}
    out: Boxes = {}
    seen: set[tuple[str, str]] = set()
    for b in boxes:
        number = str(b.get("number") or "")
        org = str(b.get("organization") or "")
        if not _NUMBER_RE.match(number):
            raise GenerationError(f"voicemail box number {number!r} is not valid")
        if key(org, number) not in numbers and not b.get("shared"):
            continue
        if b.get("shared") and key(org, number) in numbers:
            raise GenerationError(f"shared inbox {number} uses an extension's number")
        if key(org, number) in seen:
            raise GenerationError(f"extension {number} has more than one voicemail box")
        seen.add(key(org, number))
        ring = int(b.get("ring_seconds") or 20)
        if not 5 <= ring <= 120:
            raise GenerationError(f"voicemail box {number}: ring time {ring} is out of range")
        out[(org, number)] = b
    return out


def _voicemail(snapshot: dict[str, Any], boxes: Boxes, mailqueue_command: str) -> GeneratedFile:
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
        # New-message counts for the voicemail.message webhook (docs/INTEGRATIONS.md §3.2).
        f"externnotify={posixpath.join(posixpath.dirname(mailqueue_command), 'veyra-vmnotify')}",
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
    sensitive = False
    # One voicemail context per engine namespace (docs/MULTI_TENANCY.md §2).
    contexts: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for (owner, number), b in boxes.items():
        contexts.setdefault(engine_names.for_org(owner).voicemail, []).append((number, b))
    if not contexts:
        contexts[Names().voicemail] = []
    for ctx in sorted(contexts, key=lambda c: (c != Names().voicemail, c)):
        lines += ["", f"[{ctx}]"]
        lines += _box_lines(contexts[ctx], delivery)
        sensitive = sensitive or bool(contexts[ctx])
    lines.append("")
    return GeneratedFile(FILE_VOICEMAIL, "\n".join(lines).rstrip("\n") + "\n", sensitive=sensitive)


def _box_lines(entries: list[tuple[str, dict[str, Any]]], delivery: bool) -> list[str]:
    lines: list[str] = []
    for number, b in sorted(entries, key=lambda kv: (len(kv[0]), kv[0])):
        pin = str(b.get("pin") or "")
        if not _PIN_RE.match(pin):
            raise GenerationError(f"voicemail box {number}: the PIN must be 4 to 10 digits")
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
        # Pressing 0 (operator) or * during the greeting leaves to the box's
        # exit context (docs/CALL_FEATURES.md §3.7).
        operator = b.get("operator_extension")
        exit_opts = ""
        if operator:
            if not _NUMBER_RE.match(str(operator)):
                raise GenerationError(f"voicemail box {number}: operator {operator!r} is not valid")
            ctx = engine_names.for_org(org).voicemail_exit(number)
            exit_opts = f"|operator=yes|exitcontext={ctx}"
        lines.append(
            f"{number} => {pin},{name},{email},,"
            f"attach={attach}|delete={delete}|tz={org}|saycid=yes|envelope=yes{exit_opts}"
        )
    return lines


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
