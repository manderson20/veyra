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
from contextvars import ContextVar
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
FILE_PARKING = "res_parking.conf"
FILE_FEATURES = "features.conf"
FFMPEG = "/usr/bin/ffmpeg"
_STREAM_URL_RE = re.compile(
    r"^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~%/?&=+:@!$*-]*)?$"
)
# The dial-by-name directory's names (issue #135): read by Directory() through
# its c() option on every call, so it needs no module reload.
FILE_DIRECTORY = "directory.conf"
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
    FILE_PARKING,
    FILE_FEATURES,
    FILE_DIRECTORY,
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
    FILE_PARKING: "res_parking.so",
    # Not a module: the adapter runs "features reload" for this scope.
    FILE_FEATURES: "features",
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
    "res_parking.so",
    "features",
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
# max_retries of a trunk registration that never gives up (Asterisk's limit is
# an unsigned int; a million attempts a minute apart is years).
REGISTER_FOREVER = 1_000_000
# Engine switches (docs/CALL_FEATURES.md §4.5, §4.6): the store family the
# dialplan reads, the UserEvent that tells the API, the code indexes.
SWITCH_FAMILY = "veyra/switch"
SWITCH_EVENT = "VeyraSwitch"
SWITCH_PIN_TRIES = 3
MAX_CODE_INDEX = 99
# Parking (docs/CALL_FEATURES.md §4.7).
PARKING_MAX_SLOTS = 50
# Caller block list (docs/CALL_FEATURES.md §4.8).
BLACKLIST_FAMILY = "veyra/blacklist"
LASTCID_FAMILY = "veyra/lastcid"
BLACKLIST_EVENT = "VeyraBlacklist"
BLOCKED_EVENT = "VeyraBlocked"
ANONYMOUS_VALUES = ("", "anonymous", "restricted", "unavailable", "unknown", "private")
# Queue dynamic agents (docs/CALL_FEATURES.md §4.9).
AGENT_FAMILY = "veyra/agent"
AGENT_EVENT = "VeyraAgent"
FAX_EVENT = "VeyraFax"
_FAX_STATION_RE = re.compile(r"^[0-9+ ]{1,32}$")
# In-call codes (docs/CALL_FEATURES.md §4.11): the applicationmap feature and
# the pseudo policy id of on-demand recordings (no policy row).
CONTEXT_ONDEMAND = "veyra-ondemand"
ONDEMAND_FEATURE = "veyra-record"
ONDEMAND_POLICY = "00000000-0000-0000-0000-000000000000"
MAX_GROUP_DEPTH = 6
RING_GROUP_STRATEGIES = ("ringall", "sequential", "circular", "roundrobin", "longest_idle")
# One member at a time in a moving order (issue #166).
HUNT_STRATEGIES = ("circular", "roundrobin", "longest_idle")
RG_STATE_FAMILY = "veyra/rg"
# Runs on the member that answers a hunting ring group: the last-caller
# record (as veyra-lastcid) and the group's order state (issue #166).
CONTEXT_RG_ANSWERED = "veyra-rg-answered"
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
# Runs on the phone that answers a ring group or queue call (Dial U(), the
# Queue gosub): remembers the outside caller for *32 (issue #135).
CONTEXT_LASTCID = "veyra-lastcid"
# Hangup handler of a *70 call (issue #163): call waiting comes back.
CONTEXT_CW_CLEAR = "veyra-cw-clear"
ASTDB_CALLBACK = "veyra_ecb"
DEFAULT_RING_SECONDS = 30
# Where the prompts live and the script Asterisk hands notifications to;
# the adapter passes the installation's paths (veyra.core.config).
DEFAULT_PROMPTS_DIR = "/var/lib/veyra/prompts"
DEFAULT_MOH_DIR = "/var/lib/veyra/moh"
DEFAULT_RECORDINGS_DIR = "/var/lib/veyra/recordings"
DEFAULT_FAX_DIR = "/var/lib/veyra/fax"
CONTEXT_RECORD = "veyra-record"
# Engine class of a hold music set (docs/PAGING_RECORDINGS.md §3.2).
MOH_CLASS_PREFIX = "veyra-"
MOH_BUILTIN = "default"
DEFAULT_MAILQUEUE_COMMAND = "/opt/veyra/current/installer/bin/veyra-mailqueue"
# Plays a stream set's station, falling back to its recordings (issue #138).
MOH_STREAM_COMMAND = "/opt/veyra/current/installer/bin/veyra-moh-stream"
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


PAGE_EVENT = "VeyraPage"


def _page_event(org: str, kind: str, slug: str) -> str:
    """Tell Veyra a phone started a page (page log and the ``page.sent``
    webhook, issue #139); pages Veyra starts itself are logged by the API."""
    return (
        f' same => n,ExecIf($["${{VEYRA_PAGE_BY}}"!="veyra"]?UserEvent({PAGE_EVENT},'
        f"Org: {org},Kind: {kind},Slug: {slug},By: ${{CALLERID(num)}}))"
    )


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
            _page_event(org, "zone", slug),
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
        if zone_slugs:
            lines.append(_page_event(org, "page", slug))
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
    fax_dir: str = DEFAULT_FAX_DIR,
) -> list[GeneratedFile]:
    sip = SipSettings.model_validate(snapshot.get("sip") or {})
    problems = sip.problems()
    if problems:
        raise GenerationError("; ".join(problems))
    mapping = {
        str(o.get("slug") or ""): str(o.get("namespace") or "")
        for o in snapshot.get("organizations") or []
    }
    dtmf = frozenset(
        (engine_names.Names(mapping.get(str(b.get("organization") or ""), "")).voicemail, num)
        for b in snapshot.get("voicemail_boxes") or []
        if (num := str(b.get("number") or "")) and _locaters(b)
    )
    token = _vm_dtmf.set(dtmf)
    try:
        with engine_names.namespaces(mapping):
            files = _generate(
                snapshot,
                sip,
                prompts_dir=prompts_dir,
                mailqueue_command=mailqueue_command,
                moh_dir=moh_dir,
                recordings_dir=recordings_dir,
                fax_dir=fax_dir,
            )
    finally:
        _vm_dtmf.reset(token)
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
    fax_dir: str = DEFAULT_FAX_DIR,
) -> list[GeneratedFile]:
    extensions = list(snapshot.get("extensions") or [])
    trunks = list(snapshot.get("trunks") or [])
    boxes = _check_boxes(list(snapshot.get("voicemail_boxes") or []), extensions)
    prompts = _path(prompts_dir, "prompts directory")
    ring_groups = list(snapshot.get("ring_groups") or [])
    queues = list(snapshot.get("queues") or [])
    rooms = list(snapshot.get("conference_rooms") or [])
    lots = list(snapshot.get("parking_lots") or [])
    _check_group_numbers(extensions, ring_groups, queues, rooms, lots)
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
            _path(fax_dir, "fax directory"),
        ),
        _rtp(sip),
        _voicemail(snapshot, boxes, _path(mailqueue_command, "mail queue command")),
        _queues(queues, extensions, prompts, moh),
        _notify_conf(),
        _paging_json(snapshot.get("paging") or {}),
        _moh_conf(moh, _path(moh_dir, "hold music directory")),
        _confbridge(rooms, moh, _path(recordings_dir, "recordings directory")),
        _parking_conf(lots),
        _features_conf(_feature_codes(snapshot)),
        _directory_conf(snapshot, boxes),
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
        stream = str(m.get("stream_url") or "")
        if stream:
            # An internet station (issue #138): the helper decodes it with
            # ffmpeg to the raw 8 kHz signed linear audio a custom class reads,
            # and plays the set's recordings while the station is unreachable.
            if not _STREAM_URL_RE.match(stream):
                raise GenerationError(f"hold music {slug}: stream address is not valid")
            lines += [
                f"[{n.moh_class(slug)}]",
                f"; {name} ({org}); stream, fallback tracks: {', '.join(files) or 'none'}",
                "mode=custom",
                f"application={MOH_STREAM_COMMAND} {stream} {moh_dir}/{n.moh_dir(slug)}",
                "format=slin",
                "",
            ]
            continue
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
            # A withheld number (*67) still reaches the carrier in the
            # identity header, marked private (issue #163).
            "trust_id_outbound=yes",
            f"send_pai={'yes' if header == 'pai' else 'no'}",
            f"send_rpid={'yes' if header == 'rpid' else 'no'}",
            f"dtmf_mode={dtmf}",
            f"set_var=VEYRA_TRUNK={slug}",
        ]
        if t.get("fax_t38"):
            # T.38 fax relay (docs/USER_PORTAL.md §9): offered to the carrier,
            # audio (G.711) fax when it declines.
            lines += ["t38_udptl=yes", "t38_udptl_ec=redundancy", "t38_udptl_nat=yes"]
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
            retry = int(t.get("register_retry_interval") or 60)
            forbidden = int(t.get("register_forbidden_retry") or 600)
            # Asterisk stops after 10 failed attempts and for good after one
            # rejected challenge unless told otherwise (issue #142): a carrier
            # outage must not leave the trunk unregistered until a reload.
            max_retries = int(t.get("register_max_retries") or REGISTER_FOREVER)
            if not (10 <= retry <= 3600 and 30 <= forbidden <= 86400 and max_retries >= 1):
                raise GenerationError(f"trunk {slug}: registration retry settings are out of range")
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
                f"retry_interval={retry}",
                f"forbidden_retry_interval={forbidden}",
                f"fatal_retry_interval={forbidden}",
                f"max_retries={max_retries}",
                "auth_rejection_permanent=no",
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


def _features_conf(codes: dict[str, str]) -> GeneratedFile:
    """``features.conf`` (docs/CALL_FEATURES.md §4.11): the DTMF transfer keys
    (featuremap) and the on-demand recording feature (applicationmap). Applied
    with ``features reload``."""
    lines = [
        HEADER,
        "[general]",
        "transferdigittimeout=3",
        "xfersound=beep",
        "xferfailsound=beeperr",
        "atxfernoanswertimeout=15",
        "atxferdropcall=no",
        "featuredigittimeout=1000",
        "",
        "[featuremap]",
    ]
    if "blind_transfer" in codes:
        lines.append(f"blindxfer={codes['blind_transfer']}")
    if "attended_transfer" in codes:
        lines.append(f"atxfer={codes['attended_transfer']}")
    lines += ["", "[applicationmap]"]
    if "record_toggle" in codes:
        lines.append(
            f"{ONDEMAND_FEATURE} => {codes['record_toggle']},self/both,Gosub,"
            f'"{CONTEXT_ONDEMAND},s,1"'
        )
    return GeneratedFile(FILE_FEATURES, "\n".join(lines).rstrip("\n") + "\n")


def _ondemand_context(recordings_dir: str, cos: Cos | None = None) -> list[str]:
    """On-demand recording toggle (docs/CALL_FEATURES.md §4.11): the first
    press starts a MixMonitor into the incoming folder under the pseudo policy
    id, the next stops it; the worker files it like any other recording."""
    return [
        "",
        f"[{CONTEXT_ONDEMAND}]",
        "exten => s,1,NoOp(Veyra on-demand recording toggle)",
        # The pressing phone's class may not record (issue #135).
        *(
            cos.guard(
                cos._denied(
                    lambda c: (
                        c.get("allowed_feature_codes") is not None
                        and "record_toggle" not in c["allowed_feature_codes"]
                    )
                ),
                label="denied",
            )
            if cos
            else []
        ),
        ' same => n,GotoIf($["${VEYRA_CALLREC}"!=""]?stop)',
        " same => n,Set(__VEYRA_CALLREC=${UNIQUEID})",
        " same => n,Set(CDR(veyra_rec)=${VEYRA_CALLREC})",
        " same => n,Playback(beep)",
        f" same => n,MixMonitor({recordings_dir}/incoming/${{VEYRA_CALLREC}}--"
        f"{ONDEMAND_POLICY}.wav,b)",
        " same => n,Return()",
        " same => n(stop),StopMixMonitor()",
        " same => n,Playback(beep)",
        " same => n,Return()",
        " same => n(denied),Playback(beeperr)",
        " same => n,Return()",
        "",
    ]


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
    fax_dir: str = DEFAULT_FAX_DIR,
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
    lots = list(snapshot.get("parking_lots") or [])
    fax_inboxes = list(snapshot.get("fax_inboxes") or [])
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
    ]
    codes = _feature_codes(snapshot)
    # In-call codes (§4.11): Dial options that allow DTMF transfers, and the
    # dynamic feature that toggles recording; globals apply to every channel.
    transfers = "attended_transfer" in codes or "blind_transfer" in codes
    lines += [
        f"VEYRA_XFER={'tT' if transfers else ''}",
        f"VEYRA_XFER_OUT={'T' if transfers else ''}",
        f"DYNAMIC_FEATURES={ONDEMAND_FEATURE if 'record_toggle' in codes else ''}",
        "",
    ]

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
                mine(queues, ns),
                {
                    str(o.get("slug") or "")
                    for o in snapshot.get("organizations") or []
                    if o.get("directed_pickup") == "group"
                },
            )
            lines += _voicemail_exit_contexts(my_boxes(ns))
            lines += _voicemail_play_context()
            lines += _voicemail_absent_context()
            lines += _spy_context()
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
                _switch_hints(codes, mine(flows, ns), mine(tcs, ns))
                + _agent_hints(codes, mine(queues, ns)),
                mine(lots, ns),
                codes.get("presence_watch"),
                codes.get("park_pickup"),
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
    lines += _lastcid_context()
    lines += _rg_answered_context()
    lines += _cw_clear_context()
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
    policies = {
        str(p.get("organization") or ""): p for p in (snapshot.get("caller_block_policies") or [])
    }
    lines += _inbound_contexts(
        inbound,
        conditions,
        trunk_slugs,
        recording,
        prompts_dir,
        list(snapshot.get("sites") or []),
        policies,
    )
    for ns in spaces:
        with engine_names.using(Names(ns)):
            lines += _ivr_contexts(mine(menus, ns), prompts_dir)
            lines += _announcement_contexts(mine(announcements, ns), prompts_dir)
            lines += _conference_contexts(mine(rooms, ns))
            lines += _call_flow_contexts(mine(flows, ns))
            lines += _fax_contexts(mine(fax_inboxes, ns), fax_dir)
            lines += _agent_contexts(codes, mine(queues, ns))
            lines += _parking_contexts(mine(lots, ns))
            lines += _directory_context(_directory_operator(snapshot, ns))
    moh = _check_moh(list(snapshot.get("hold_music") or []))
    for ns in spaces:
        with engine_names.using(Names(ns)):
            lines += _ring_group_contexts(mine(ring_groups, ns), moh, recording, prompts_dir)
    for ns in spaces:
        with engine_names.using(Names(ns)):
            lines += _queue_contexts(mine(queues, ns), prompts_dir, recording)
    if recording:
        lines += _record_context(recordings_dir, prompts_dir)
    if "record_toggle" in codes:
        lines += _ondemand_context(
            recordings_dir,
            Cos(
                list(snapshot.get("classes_of_service") or []),
                int((snapshot.get("numbering") or {}).get("extension_length") or 4),
            ),
        )
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
    f"${{DB({STATE_KEY}/cf_busy)}}${{DB({STATE_KEY}/cf_no_answer)}}"
    f'${{DB({STATE_KEY}/cf_unavailable)}}"=""]?NOT_INUSE:INUSE)}})'
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

    def _no_transfers(self, c: dict[str, Any]) -> bool:
        # Dial's t/T switch both transfer codes on together, so a class is
        # held to "no transfers" only when it allows neither (issue #135).
        allowed = c.get("allowed_feature_codes")
        return allowed is not None and not ({"attended_transfer", "blind_transfer"} & set(allowed))

    def transfer_guard(self) -> list[str]:
        """The calling phone's class may not transfer: drop Dial's T."""
        denied = self._denied(self._no_transfers)
        if not denied:
            return []
        alternatives = "|".join(re.escape(d) for d in denied)
        return [
            f' same => n,ExecIf(${{REGEX("^({alternatives})$" ${{VEYRA_COS}})}}'
            "?Set(VEYRA_XFER=${REPLACE(VEYRA_XFER,T)}))"
        ]

    def callee_may_transfer(self, class_slug: Any) -> bool:
        for c in self.classes:
            if c.get("slug") == class_slug:
                return not self._no_transfers(c)
        return True

    def intercom_guard(self) -> list[str]:
        return self.guard(self._denied(lambda c: not c.get("allow_intercom", True)))

    def allows_external_follow_me(self, class_slug: Any) -> bool:
        for c in self.classes:
            if c.get("slug") == class_slug:
                return bool(c.get("allow_external_follow_me", True))
        return True


COS_DENIED = [
    " same => n(cosdenied),NoOp(Veyra: not allowed by the class of service)",
    # Call history shows the refusal (issue #135).
    " same => n,Set(CDR(veyra_flag)=denied)",
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


def _acr_codes(codes: dict[str, str], cos: Cos | None = None) -> list[str]:
    """``*77``/``*87`` (issue #163): the phone refuses or accepts outside
    callers who withhold their number; like DND, the engine's copy first."""
    lines: list[str] = []
    for key, on in (("acr_on", True), ("acr_off", False)):
        if key not in codes:
            continue
        value = "1" if on else "0"
        head = (
            f"exten => {codes[key]},1,NoOp(Veyra anonymous call rejection {value} "
            "for ${VEYRA_EXT})"
        )
        body = [
            f" same => n,Set(DB({STATE_KEY}/acr)={value})",
            _state_event("acr", value),
            f" same => n,Playback({'activated' if on else 'de-activated'})",
            " same => n,Hangup()",
        ]
        lines += _code_block(head, body, cos, key)
    return lines


def _call_codes(codes: dict[str, str], cos: Cos | None = None) -> list[str]:
    """``*67<number>``, ``*69`` and ``*70<number>`` (issue #163). Each places a
    call, so nothing answers the phone's channel first: the caller hears the
    far end ring. The call goes on through the phone context, where the
    class of service and the outbound routes apply as to any call."""
    n = engine_names.current()
    phone = ' same => n,GotoIf($["${VEYRA_EXT}"=""]?nophone)'

    def block(head: str, key: str, body: list[str]) -> list[str]:
        guard = cos.code_guard(key) if cos else []
        return [head, phone, *guard, *body, *_STATE_TAIL, *(COS_DENIED if guard else [])]

    lines: list[str] = []
    code = codes.get("cid_block")
    if code:
        lines += block(
            f"exten => _{code}.,1,NoOp(Veyra {code}: ${{VEYRA_EXT}} calls "
            f"${{EXTEN:{len(code)}}} with the number withheld)",
            "cid_block",
            [
                # An emergency route presents the number again.
                " same => n,Set(CALLERID(pres)=prohib)",
                f" same => n,Goto({n.internal},${{EXTEN:{len(code)}}},1)",
            ],
        )
    code = codes.get("call_return")
    if code:
        lines += block(
            f"exten => {code},1,NoOp(Veyra call return for ${{VEYRA_EXT}})",
            "call_return",
            [
                f" same => n,Set(VEYRA_NUM=${{DB({LASTCID_FAMILY}/"
                "${VEYRA_ORG}/${VEYRA_EXT})})",
                # A withheld or missing number cannot be called back.
                ' same => n,GotoIf($[${REGEX("^\\+?[0-9]{2,20}$" ${VEYRA_NUM})}]?call)',
                " same => n,Answer()",
                " same => n,Playback(vm-nonumber)",
                " same => n,Hangup()",
                # Ten digits for a North American number, as the routes expect.
                ' same => n(call),ExecIf($[${REGEX("^\\+?1[2-9][0-9]{9}$" ${VEYRA_NUM})}]'
                "?Set(VEYRA_NUM=${VEYRA_NUM:-10}))",
                f" same => n,Goto({n.internal},${{VEYRA_NUM}},1)",
            ],
        )
    code = codes.get("cw_off_once")
    if code:
        lines += block(
            f"exten => _{code}.,1,NoOp(Veyra {code}: ${{VEYRA_EXT}} calls "
            f"${{EXTEN:{len(code)}}} with call waiting off)",
            "cw_off_once",
            [
                # The phone's incoming dialplan sees the key while this call is up.
                f" same => n,Set(DB({STATE_KEY}/nocw_call)=${{UNIQUEID}})",
                f" same => n,Set(CHANNEL(hangup_handler_push)={CONTEXT_CW_CLEAR},s,1"
                "(${VEYRA_ORG},${VEYRA_EXT},${UNIQUEID}))",
                f" same => n,Goto({n.internal},${{EXTEN:{len(code)}}},1)",
            ],
        )
    return lines


SPY_MODES = {
    "spy_listen": ("listen", ""),
    "spy_whisper": ("whisper", "w"),
    "spy_barge": ("barge", "B"),
}
MONITOR_EVENT = "VeyraMonitor"


def _spy_codes(
    codes: dict[str, str], cos: Cos | None, extensions: list[dict[str, Any]]
) -> list[str]:
    """``*222``/``*223``/``*224`` + extension (issue #167): listen, whisper or
    join that phone's call. Only phones of a class that allows supervising
    may use them (a phone without a class may not); extensions of a protected
    class have their own entry that refuses. The target's device comes from
    its hint, so only this namespace's extensions can be reached."""
    n = engine_names.current()
    allowed = sorted(str(c["slug"]) for c in (cos.classes if cos else []) if c.get("allow_monitor"))
    protected = {str(c["slug"]) for c in (cos.classes if cos else []) if c.get("monitor_protected")}
    if not allowed:
        return []
    alternatives = "|".join(re.escape(a) for a in allowed)
    lines: list[str] = []
    for key, (mode, opt) in SPY_MODES.items():
        code = codes.get(key)
        if not code:
            continue
        cut = len(code)
        for ext in extensions:
            if str(ext.get("class_of_service") or "") in protected:
                lines += [
                    f"exten => {code}{ext['number']},1,NoOp(Veyra: {ext['number']} may not be "
                    "monitored)",
                    " same => n,Answer()",
                    " same => n,Playback(pbx-invalid)",
                    " same => n,Hangup()",
                ]
        lines += [
            f"exten => _{code}.,1,NoOp(Veyra {mode} on ${{EXTEN:{cut}}} by ${{VEYRA_EXT}})",
            ' same => n,GotoIf($["${VEYRA_EXT}"=""]?nophone)',
            f' same => n,GotoIf(${{REGEX("^({alternatives})$" ${{VEYRA_COS}})}}?spy:cosdenied)',
            f" same => n(spy),Set(VEYRA_SPYDEV=${{HINT(${{EXTEN:{cut}}}@{n.internal})}})",
            ' same => n,GotoIf($[!${REGEX("^PJSIP/[A-Za-z0-9_.-]+$" ${VEYRA_SPYDEV})}]?cosdenied)',
            f' same => n,GotoIf($["${{EXTEN:{cut}}}"="${{VEYRA_EXT}}"]?cosdenied)',
            f" same => n,UserEvent({MONITOR_EVENT},Org: ${{VEYRA_ORG}},By: ${{VEYRA_EXT}},"
            f"Target: ${{EXTEN:{cut}}},Mode: {mode})",
            " same => n,Answer()",
            # The "-" keeps 1001 from matching 10010's channels.
            f" same => n,ChanSpy(${{VEYRA_SPYDEV}}-,qE{opt})",
            " same => n,Hangup()",
            *_STATE_TAIL,
            *COS_DENIED,
        ]
    return lines


def _spy_context() -> list[str]:
    """The supervisor's phone, rung from the web (issue #167): the API passes
    the call's channel name and the mode; both are checked again here."""
    n = engine_names.current()
    return [
        f"[{n.spy}]",
        "exten => s,1,NoOp(Veyra supervisor ${VEYRA_SPY_MODE} on ${VEYRA_SPY_CHAN})",
        ' same => n,GotoIf($[!${REGEX("^PJSIP/[A-Za-z0-9_.-]+-[0-9a-f]+$" '
        "${VEYRA_SPY_CHAN})}]?bad)",
        ' same => n,Set(VEYRA_OPT=${IF($["${VEYRA_SPY_MODE}"="whisper"]?w:'
        '${IF($["${VEYRA_SPY_MODE}"="barge"]?B:)})})',
        " same => n,Answer()",
        " same => n,ChanSpy(${VEYRA_SPY_CHAN},qE${VEYRA_OPT})",
        " same => n(bad),Hangup()",
        "",
    ]


def _cw_clear_context() -> list[str]:
    """The *70 call ended: its key goes, unless a newer *70 call set it."""
    return [
        f"[{CONTEXT_CW_CLEAR}]",
        'exten => s,1,GotoIf($["${DB(veyra/ext/${ARG1}/${ARG2}/nocw_call)}"!="${ARG3}"]?done)',
        " same => n,Set(VEYRA_GONE=${DB_DELETE(veyra/ext/${ARG1}/${ARG2}/nocw_call)})",
        " same => n(done),Return()",
        "",
    ]


PRESENCE_EVENT = "VeyraPresence"


def _presence_codes(codes: dict[str, str], cos: Cos | None = None) -> list[str]:
    """``*37<1-6>`` (issue #136): the phone sets its user's presence; the API
    applies it (and the user's automatic actions) from the UserEvent."""
    code = codes.get("presence_set")
    if not code:
        return []
    body = [
        f" same => n,UserEvent({PRESENCE_EVENT},Org: ${{VEYRA_ORG}},Extension: ${{VEYRA_EXT}},"
        "State: ${VEYRA_PRESENCE})",
        " same => n,Playback(beep)",
        " same => n,Hangup()",
    ]
    lines = _code_block(f"exten => {code},1,Set(VEYRA_PRESENCE=1)", body, cos, "presence_set")
    lines += _code_block(
        f"exten => _{code}[1-6],1,Set(VEYRA_PRESENCE=${{EXTEN:{len(code)}}})",
        body,
        cos,
        "presence_set",
    )
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
    guard = cos.code_guard("vm_direct") if cos else []
    lines: list[str] = []
    for number, _b in sorted(boxes, key=lambda kv: (len(kv[0]), kv[0])):
        lines += [
            f"exten => {code}{number},1,NoOp(Veyra direct to voicemail {number})",
            *guard,
            " same => n,Answer()",
            # The unavailable greeting (u); without it VoiceMail plays none.
            *_vm_steps(number, "u"),
            " same => n,Hangup()",
            *(COS_DENIED if guard else []),
        ]
    return lines


def _has_exit(b: dict[str, Any]) -> bool:
    return bool(b.get("operator_extension") or _locaters(b))


def _locaters(b: dict[str, Any]) -> dict[str, str]:
    """Key -> target of a box's locater (issue #131): ``followme`` (key 1,
    when the extension has a follow-me list) or a number of the organization."""
    out = {}
    for key in ("1", "2"):
        value = str(b.get(f"locater_{key}") or "")
        if not value or (value == "followme" and (key != "1" or not b.get("follow_me"))):
            continue
        if value != "followme" and not _NUMBER_RE.match(value):
            raise GenerationError(f"voicemail box: locater {key} {value!r} is not valid")
        out[key] = value
    return out


# (voicemail context, box number) of boxes with a locater: their VoiceMail()
# takes d(<exit context>) so 1 and 2 pressed during the greeting leave.
_vm_dtmf: ContextVar[frozenset[tuple[str, str]]] = ContextVar("veyra_vm_dtmf", default=frozenset())


def _vm(number: str, flags: str) -> str:
    """``VoiceMail(<box>@<ns>,<flags>)``, with the locater's ``d()`` when set."""
    n = engine_names.current()
    if (n.voicemail, number) in _vm_dtmf.get():
        flags += f"d({n.voicemail_exit(number)})"
    return f"VoiceMail({number}@{n.voicemail},{flags})"


# Where Asterisk keeps the boxes; the absent context plays a box's
# temporary greeting from here (issue #169).
VOICEMAIL_SPOOL = "/var/spool/asterisk/voicemail"
VMABS_FAMILY = "veyra/vmabs"


def _vm_steps(number: str, flags: str) -> list[str]:
    """``VoiceMail`` after the extended-absence check (issue #169): a box that
    takes no messages while its owner is away only plays the greeting."""
    n = engine_names.current()
    return [
        f' same => n,GotoIf($["${{DB({VMABS_FAMILY}/{n.voicemail}/{number})}}"="refuse"]'
        f"?{n.voicemail_absent},{number},1)",
        f" same => n,{_vm(number, flags)}",
    ]


def _voicemail_absent_context() -> list[str]:
    n = engine_names.current()
    return [
        f"[{n.voicemail_absent}]",
        "exten => _X.,1,NoOp(Veyra: voicemail ${EXTEN} is away and takes no messages)",
        " same => n,Answer()",
        " same => n,Wait(1)",
        f" same => n,Playback({VOICEMAIL_SPOOL}/{n.voicemail}/${{EXTEN}}/temp)",
        " same => n,Playback(vm-goodbye)",
        " same => n,Hangup()",
        "",
    ]


def _voicemail_exit_contexts(boxes: list[tuple[str, dict[str, Any]]]) -> list[str]:
    """Per box with an operator or a locater: 0 rings the operator, * opens
    the box, 1 and 2 go to the locater's targets (docs/CALL_FEATURES.md §3.7)."""
    n = engine_names.current()
    lines: list[str] = []
    for number, b in sorted(boxes, key=lambda kv: (len(kv[0]), kv[0])):
        if not _has_exit(b):
            continue
        lines += [f"[{n.voicemail_exit(number)}]"]
        operator = b.get("operator_extension")
        if operator:
            lines += [
                f"exten => o,1,NoOp(Veyra: voicemail {number} operator)",
                f" same => n,Goto({n.internal},{operator},1)",
            ]
        for key, target in _locaters(b).items():
            lines.append(f"exten => {key},1,NoOp(Veyra: voicemail {number} locater {key})")
            if target == "followme":
                lines.append(f" same => n,Goto({n.internal},{number},fm)")
            else:
                lines.append(f" same => n,Goto({n.internal},{target},1)")
        lines += [
            f"exten => a,1,VoiceMailMain({number}@{n.voicemail})",
            " same => n,Hangup()",
            "",
        ]
    return lines


def _voicemail_play_context() -> list[str]:
    """Call-me-to-play (issue #136): the API rings the user's phone into this
    context with the box and the message id as channel variables (checked by
    the API; the dialplan only accepts digits and id characters)."""
    n = engine_names.current()
    return [
        f"[{n.voicemail_play}]",
        "exten => s,1,NoOp(Veyra: play voicemail ${VEYRA_VM_BOX} ${VEYRA_VM_MSG})",
        ' same => n,GotoIf($["${FILTER(0-9,${VEYRA_VM_BOX})}" != "${VEYRA_VM_BOX}"]?bad)',
        ' same => n,GotoIf($["${FILTER(0-9A-Za-z_.-,${VEYRA_VM_MSG})}" != "${VEYRA_VM_MSG}"]?bad)',
        " same => n,Answer()",
        " same => n,Wait(1)",
        f" same => n,VoiceMailPlayMsg(${{VEYRA_VM_BOX}}@{n.voicemail},${{VEYRA_VM_MSG}})",
        " same => n,Playback(vm-goodbye)",
        " same => n,Hangup()",
        " same => n(bad),Hangup()",
        "",
    ]


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
    queues: list[dict[str, Any]] | None = None,
    group_pickup_orgs: set[str] | None = None,
) -> list[str]:
    """Feature codes of one namespace; ``**<ext>`` reaches only its phones."""
    n = engine_names.current()
    codes = codes or {}
    lines = [
        f"[{n.features}]",
        *_dnd_codes(codes, cos),
        *_acr_codes(codes, cos),
        *_presence_codes(codes, cos),
        *_forward_codes(codes, cos),
        *_follow_me_codes(codes, cos),
        *_intercom_code(codes, cos),
        *_voicemail_direct(codes, boxes or [], cos),
        *_call_flow_codes(codes, flows or [], cos),
        *_tc_override_codes(codes, conditions or [], cos),
        *_blacklist_codes(codes, cos),
        *_agent_codes(codes, queues or [], cos),
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
    # Pickup-group peers: who may answer a phone when the organization limits
    # **<extension> to its pickup groups (issue #138).
    groups_of = {str(e["number"]): set(e.get("pickup_groups") or []) for e in extensions}
    for ext in extensions:
        number = str(ext["number"])
        endpoint = str(ext["endpoint_name"])
        org = _check_value(str(ext.get("organization") or ""), "organization")
        peers: list[str] = []
        if org in (group_pickup_orgs or set()):
            mine = groups_of.get(number, set())
            peers = sorted(
                (
                    str(e["number"])
                    for e in extensions
                    if e.get("organization") == org
                    and str(e["number"]) != number
                    and mine & groups_of.get(str(e["number"]), set())
                ),
                key=lambda x: (len(x), x),
            )
            guard = [
                " same => n,Set(VEYRA_PEER=0)",
                *(f' same => n,ExecIf($["${{VEYRA_EXT}}"="{p}"]?Set(VEYRA_PEER=1))' for p in peers),
                ' same => n,GotoIf($["${VEYRA_PEER}"!="1"]?denied)',
            ]
        else:
            guard = []
        lines += [
            f"exten => **{number},1,NoOp(Veyra directed pickup of {number} by ${{CALLERID(num)}})",
            f' same => n,GotoIf($["${{VEYRA_ORG}}"!="{org}"]?denied)',
            *guard,
            f" same => n,PickupChan(PJSIP/{endpoint},,p)",
            " same => n,Hangup()",
            " same => n(denied),Playback(pbx-invalid)",
            " same => n,Hangup()",
        ]
    lines += [
        "",
        f"[{n.call_codes}]",
        *_call_codes(codes, cos),
        *_spy_codes(codes, cos, extensions),
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
    parking: list[dict[str, Any]] | None = None,
    presence_code: str | None = None,
    park_code: str | None = None,
) -> list[str]:
    """The phone context of one namespace."""
    n = engine_names.current()
    by_number = {number: b for (_org, number), b in boxes.items()}
    # Parking lots: res_parking fills each lot's context with the park
    # extension, the slots and their hints (docs/CALL_FEATURES.md §4.7).
    lot_includes = [
        f"include => {n.parking(_slug(lot['slug'], 'parking lot slug'))}" for lot in parking or []
    ]
    lines = [
        f"[{n.internal}]",
        "; Extensions first; then feature codes, parking, outbound routes and the",
        "; catch-all (includes are searched in order, after this context's own entries).",
        f"include => {n.features}",
        *lot_includes,
        f"include => {n.paging}",
        f"include => {n.call_codes}",
        f"include => {n.outbound}",
        f"include => {CONTEXT_INVALID}",
        *(extra_hints or []),
    ]
    if park_code:
        # *85<slot> (issue #135): the slot's own extension, with its lamp.
        for lot in parking or []:
            slug = _slug(lot["slug"], "parking lot slug")
            ctx = n.parking(slug)
            for slot in _parking_numbers(lot)[1:]:
                lines += [
                    f"exten => {park_code}{slot},hint,park:{slot}@{ctx}",
                    f"exten => {park_code}{slot},1,Goto({ctx},{slot},1)",
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
        if presence_code:
            # A presence key (issue #132): a BLF on the colleague's presence
            # state (extension_state.PRESENCE_LAMP); pressing it calls them.
            lines += [
                f"exten => {presence_code}{number},hint,Custom:veyra-presence-{org_slug}-{number}",
                f"exten => {presence_code}{number},1,Goto({n.internal},{number},1)",
            ]
        if dnd_toggle:
            lines.append(f"exten => {dnd_toggle}{number},hint,Custom:veyra-dnd-{org_slug}-{number}")
            # A DND key on the phone (docs/PROVISIONING_BREADTH.md §3) is a BLF
            # on this hint; pressing it dials the hint: the owner's phone
            # toggles, any other phone is refused.
            lines += [
                f'exten => {dnd_toggle}{number},1,GotoIf($["${{VEYRA_EXT}}"="{number}"]'
                f"?{dnd_toggle},1)",
                " same => n,Playback(beeperr)",
                " same => n,Hangup()",
            ]
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
        # A called phone whose class may not transfer gets no Dial t (#135).
        xfer = (
            "${VEYRA_XFER}"
            if cos is None or cos.callee_may_transfer(ext.get("class_of_service"))
            else "${REPLACE(VEYRA_XFER,t)}"
        )
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
            # The last outside caller, for the block-last-caller code (§4.8).
            f' same => n,ExecIf($["${{VEYRA_DID}}"!="" & "${{CALLERID(num)}}"!=""]'
            f"?Set(DB({LASTCID_FAMILY}/{org_slug}/{number})=${{CALLERID(num)}}))",
            # An outside caller without a number, when the phone refuses them (#163).
            f' same => n,GotoIf($["${{DB({state}/acr)}}"="1" & "${{VEYRA_DID}}"!=""]?acr)',
            f' same => n,GotoIf($["${{DB({state}/dnd)}}"="1"]?dndallow)',
            f" same => n(ring),Set(VEYRA_CF=${{DB({state}/cf_always)}})",
            ' same => n,GotoIf($["${VEYRA_CF}"!=""]?forward)',
            # Call waiting off (#163): busy while the phone is on a call.
            f' same => n,GotoIf($["${{DB({state}/nocw)}}${{DB({state}/nocw_call)}}"=""]?cw)',
            f' same => n,GotoIf(${{REGEX("^(NOT_INUSE|UNAVAILABLE|UNKNOWN|INVALID)$" '
            f"${{DEVICE_STATE(PJSIP/{endpoint})}})}}?cw:busy)",
            " same => n(cw),NoOp()",
            *rec,
            *([f' same => n,GotoIf($["${{DB({state}/fmfm)}}"="1"]?fm)'] if fm_branch else []),
            *(cos.transfer_guard() if cos else []),
            f" same => n,Dial(PJSIP/{endpoint},{ring},{xfer})",
            ' same => n,GotoIf($["${DIALSTATUS}"="BUSY"]?busy)',
            # No phone registered (#165): the offline forward, else as unanswered.
            ' same => n,GotoIf($["${DIALSTATUS}"!="CHANUNAVAIL"]?noanswer)',
            f" same => n,Set(VEYRA_CF=${{DB({state}/cf_unavailable)}})",
            ' same => n,GotoIf($["${VEYRA_CF}"!=""]?forward)',
            f" same => n(noanswer),Set(VEYRA_CF=${{DB({state}/cf_no_answer)}})",
            ' same => n,GotoIf($["${VEYRA_CF}"!=""]?forward)',
        ]
        anonymous = " | ".join(
            f'"${{TOLOWER(${{CALLERID(num)}})}}"="{v}"' for v in ANONYMOUS_VALUES
        )
        rules_branch = [
            f" same => n(acr),GotoIf($[{anonymous} | "
            '${REGEX("^prohib" ${CALLERID(pres)})}]?refuse)',
            f' same => n,GotoIf($["${{DB({state}/dnd)}}"="1"]?dndallow:ring)',
            f" same => n(refuse),NoOp(Veyra: {number} refuses callers without a number)",
            " same => n,Set(CDR(veyra_flag)=blocked)",
            " same => n,Answer()",
            " same => n,Playback(privacy-unident)",
            " same => n,Hangup()",
            # Do Not Disturb exceptions (#170): the caller's digits, ten for
            # a North American number, looked up in "-<number>-" lists.
            " same => n(dndallow),Set(VEYRA_DA=${FILTER(0-9,${CALLERID(num)})})",
            ' same => n,ExecIf($[${LEN(${VEYRA_DA})} = 11 & "${VEYRA_DA:0:1}"="1"]'
            "?Set(VEYRA_DA=${VEYRA_DA:1}))",
            f' same => n,GotoIf($["${{VEYRA_DA}}"!="" & "${{DB({state}/dnd_allow)}}"!=""]'
            "?dndlist:dnd)",
            f' same => n(dndlist),GotoIf(${{REGEX("-${{VEYRA_DA}}-" ${{DB({state}/dnd_allow)}})}}'
            "?ring:dnd)",
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
                *rules_branch,
                *fm_branch,
            ]
        else:
            # Unanswered and unavailable go to the unavailable greeting, busy
            # (and Do Not Disturb) to the busy greeting (docs/VOICEMAIL_IVR.md §3.2).
            lines += [
                *head,
                *_vm_steps(number, "u"),
                " same => n,Hangup()",
                *busy_branch,
                *_vm_steps(number, "b"),
                " same => n,Hangup()",
                *forward,
                *rules_branch,
                *fm_branch,
            ]
    for number, b in sorted(by_number.items(), key=lambda kv: (len(kv[0]), kv[0])):
        if not b.get("shared"):
            continue
        lines += [
            f"exten => {number},1,NoOp(Veyra shared inbox {number})",
            *_vm_steps(number, "u"),
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
                    # *67 never hides the number from the 911 centre (issue #163).
                    " same => n,Set(CALLERID(pres)=allowed_not_screened)",
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
                    # Channels kept for emergency calls (issue #171): another
                    # call may use only the rest; an emergency call is never
                    # counted against the limit.
                    usable = max(
                        int(trunk["max_channels"])
                        - int(trunk.get("emergency_reserved_channels") or 0),
                        0,
                    )
                    step.append(
                        f" same => n,GotoIf($[${{GROUP_COUNT({tslug}@veyra_trunk)}} > "
                        f"{usable}]?{nxt})"
                    )
                if cid and not _NUMBER_RE.match(str(cid)):
                    raise GenerationError(f"trunk {tslug}: caller ID {cid!r} is not valid")
                step += _outbound_caller_id(cid, cid_force, emergency)
                step += [
                    f" same => n,Dial(PJSIP/${{VEYRA_DIAL}}@{TRUNK_PREFIX}{tslug},{timeout},"
                    "${VEYRA_XFER_OUT})",
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
    policies: dict[str, dict[str, Any]] | None = None,
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
        org = str(r.get("organization_slug") or "")
        out = [
            f"exten => {did},1,NoOp(Veyra inbound {did} via ${{VEYRA_TRUNK}})",
            " same => n,Set(__VEYRA_HOPS=1)",
            f" same => n,Set(__VEYRA_DID={did})",
            *_blacklist_check(org, (policies or {}).get(org)),
            *_record_inbound(recording or [], r, prompts_dir),
        ]
        site = elins.get(routing.canonical_did(did))
        if site is not None:
            out += callback_lines(site, did)
        out += _destination_lines(r, conditions)
        out += _blocked_tail(r, (policies or {}).get(org))
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
                org = str(catch.get("organization_slug") or "")
                lines += [
                    f"exten => {exten},1,NoOp(Veyra inbound ${{EXTEN}} via ${{VEYRA_TRUNK}}: any)",
                    " same => n,Set(__VEYRA_HOPS=1)",
                    " same => n,Set(__VEYRA_DID=${EXTEN})",
                    *_blacklist_check(org, (policies or {}).get(org)),
                ]
                lines += _destination_lines(catch, conditions)
                lines += _blocked_tail(catch, (policies or {}).get(org))
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
        opened = routing.gotoiftime_args(routing.check_ranges(list(cond.get("ranges") or [])), tz)
        closed = routing.holiday_apps(
            routing.check_holidays(list(cond.get("holidays") or [])), tz, "closed"
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
        out += [f" same => n,{app}" for app in closed]
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
    if kind == "fax":
        slug = _slug(dest.get("fax_inbox"), "fax inbox slug")
        ctx = engine_names.current().fax_in(slug)
        return [f" same => n,Goto({ctx},s,1)", " same => n,Hangup()"]
    if kind == "directory":
        return [f" same => n,Goto({engine_names.current().directory},s,1)", " same => n,Hangup()"]
    if kind in ("extension", "voicemail"):
        number = str(dest.get("number") or "")
        if not _NUMBER_RE.match(number):
            raise GenerationError(f"destination number {number!r} is not valid")
        if kind == "voicemail":
            return [
                *_vm_steps(number, "u"),
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


def _blacklist_check(org: str, policy: dict[str, Any] | None) -> list[str]:
    """Refuse blocked callers at the entry of an inbound route (docs/CALL_FEATURES.md
    §4.8): numbers in the organization's store family, and withheld numbers
    when the policy says so."""
    if not org:
        return []
    org = _slug(org, "organization")
    lines = [
        " same => n,Set(VEYRA_CID=${CALLERID(num)})",
        f" same => n,GotoIf(${{DB_EXISTS({BLACKLIST_FAMILY}/{org}/${{VEYRA_CID}})}}?blocked)",
    ]
    if policy and policy.get("block_anonymous"):
        tests = " | ".join(f'"${{TOLOWER(${{VEYRA_CID}})}}"="{v}"' for v in ANONYMOUS_VALUES)
        lines.append(
            f' same => n,GotoIf($[{tests} | "${{CALLERID(pres)}}"="prohib_passed_screen"'
            ' | "${CALLERID(pres)}"="prohib_failed_screen" | "${CALLERID(pres)}"="prohib"'
            ' | "${CALLERID(pres)}"="prohib_not_screened"]?blocked)'
        )
    return lines


def _blocked_tail(r: dict[str, Any], policy: dict[str, Any] | None) -> list[str]:
    """Where a refused call goes: the policy's destination, else "no service"."""
    org = str(r.get("organization_slug") or "")
    if not org:
        return []
    org = _slug(org, "organization")
    lines = [
        " same => n(blocked),NoOp(Veyra: blocked caller ${VEYRA_CID} on ${VEYRA_DID})",
        " same => n,Set(CDR(veyra_flag)=blocked)",
        f" same => n,UserEvent({BLOCKED_EVENT},Org: {org},Number: ${{VEYRA_CID}},"
        "Did: ${VEYRA_DID})",
    ]
    dest = (policy or {}).get("destination")
    if dest and dest.get("type") not in (None, "hangup", "missing"):
        with engine_names.using(engine_names.for_org(org)):
            lines += _goto(dest)
    else:
        lines += [
            " same => n,Answer()",
            " same => n,Wait(1)",
            " same => n,Playback(ss-noservice)",
            " same => n,Hangup()",
        ]
    return lines


def _blacklist_event(action: str) -> str:
    return (
        f" same => n,UserEvent({BLACKLIST_EVENT},Action: {action},Org: ${{VEYRA_ORG}},"
        "Number: ${VEYRA_NUM},By: ${VEYRA_EXT})"
    )


def _blacklist_codes(codes: dict[str, str], cos: Cos | None = None) -> list[str]:
    """``*30`` block a number, ``*31`` unblock, ``*32`` block the last outside
    caller of this phone (docs/CALL_FEATURES.md §4.8). The store is written at
    once and the API is told with a UserEvent."""
    lines: list[str] = []
    store = f"{BLACKLIST_FAMILY}/${{VEYRA_ORG}}"
    if "blacklist_add" in codes:
        head = f"exten => {codes['blacklist_add']},1,NoOp(Veyra block a caller from ${{VEYRA_EXT}})"
        body = [
            " same => n,Read(VEYRA_NUM,enter-num-blacklist,32,,1,10)",
            ' same => n,GotoIf($["${VEYRA_NUM}"=""]?nophone)',
            f" same => n,Set(DB({store}/${{VEYRA_NUM}})=1)",
            _blacklist_event("add"),
            " same => n,Playback(num-was-successfully&added)",
            " same => n,Hangup()",
        ]
        lines += _code_block(head, body, cos, "blacklist_add")
    if "blacklist_remove" in codes:
        code = codes["blacklist_remove"]
        head = f"exten => {code},1,NoOp(Veyra unblock a caller from ${{VEYRA_EXT}})"
        body = [
            " same => n,Read(VEYRA_NUM,enter-num-blacklist,32,,1,10)",
            ' same => n,GotoIf($["${VEYRA_NUM}"=""]?nophone)',
            f" same => n,Set(VEYRA_DEL=${{DB_DELETE({store}/${{VEYRA_NUM}})}})",
            _blacklist_event("remove"),
            " same => n,Playback(num-was-successfully&removed)",
            " same => n,Hangup()",
        ]
        lines += _code_block(head, body, cos, "blacklist_remove")
    if "blacklist_last" in codes:
        code = codes["blacklist_last"]
        head = f"exten => {code},1,NoOp(Veyra block the last caller of ${{VEYRA_EXT}})"
        body = [
            f" same => n,Set(VEYRA_NUM=${{DB({LASTCID_FAMILY}/${{VEYRA_ORG}}/${{VEYRA_EXT}})}})",
            ' same => n,GotoIf($["${VEYRA_NUM}"=""]?none)',
            f" same => n,Set(DB({store}/${{VEYRA_NUM}})=1)",
            _blacklist_event("add"),
            " same => n,SayDigits(${VEYRA_NUM})",
            " same => n,Playback(num-was-successfully&added)",
            " same => n,Hangup()",
            " same => n(none),Playback(vm-nonumber)",
            " same => n,Hangup()",
        ]
        lines += _code_block(head, body, cos, "blacklist_last")
    return lines


def _dynamic_agents(
    queues: list[dict[str, Any]],
) -> dict[str, list[tuple[dict[str, Any], dict[str, Any]]]]:
    """Extension number -> [(queue, member)] for every dynamic membership."""
    out: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for q in queues:
        for m in q.get("members") or []:
            if m.get("dynamic"):
                out.setdefault(str(m["number"]), []).append((q, m))
    return out


def _agent_lines(
    org: str,
    number: str,
    endpoint: str,
    memberships: list[tuple[dict[str, Any], dict[str, Any]]],
    others: list[str],
    scope: str | None,
) -> list[str]:
    """The login/logout toggle of one extension over ``memberships``;
    ``others`` are the slugs of its remaining dynamic queues (so the
    extension-wide lamp stays lit while any of them is still logged in);
    ``scope`` names the queue of a per-queue toggle (None: every queue)."""
    n = engine_names.current()
    key = f"{AGENT_FAMILY}/{org}/{number}"
    device = f"Custom:veyra-agent-{org}-{number}"
    adds, removes, marks, clears = [], [], [], []
    lamps_on, lamps_off = [], []
    for q, m in memberships:
        slug = _slug(q["slug"], "queue slug")
        qname = n.queue(slug)
        label = _display(m.get("name")) or number
        penalty = int(m.get("penalty") or 0)
        adds.append(
            f" same => n,AddQueueMember({qname},PJSIP/{endpoint},{penalty},,{label},"
            f"PJSIP/{endpoint})"
        )
        removes.append(f" same => n,RemoveQueueMember({qname},PJSIP/{endpoint})")
        marks.append(f" same => n,Set(DB({key}/{slug})=1)")
        clears.append(f" same => n,Set(VEYRA_DEL=${{DB_DELETE({key}/{slug})}})")
        # The lamp of a per-queue log-in key (issue #130).
        qdevice = f"Custom:veyra-agentq-{org}-{number}-{slug}"
        lamps_on.append(f" same => n,Set(DEVICE_STATE({qdevice})=INUSE)")
        lamps_off.append(f" same => n,Set(DEVICE_STATE({qdevice})=NOT_INUSE)")
    test = f"{key}/{_slug(memberships[0][0]['slug'], 'queue slug')}" if scope else key
    event_scope = f",Queue: {scope}" if scope else ""
    # After a logout, the extension-wide flag follows the queues still logged in.
    any_left = [" same => n,Set(VEYRA_ANY=0)"] + [
        f' same => n,ExecIf($["${{DB({key}/{o})}}"="1"]?Set(VEYRA_ANY=1))' for o in others
    ]
    return [
        f' same => n,GotoIf($["${{DB({test})}}"="1"]?logout)',
        *adds,
        *marks,
        *lamps_on,
        f" same => n,Set(DB({key})=1)",
        f" same => n,Set(DEVICE_STATE({device})=INUSE)",
        f" same => n,UserEvent({AGENT_EVENT},Org: {org},Extension: {number},"
        f"Action: login{event_scope})",
        " same => n,Playback(agent-loginok)",
        " same => n,Hangup()",
        f" same => n(logout),NoOp(Veyra agent {number} logs out)",
        *removes,
        *clears,
        *lamps_off,
        *any_left,
        ' same => n,GotoIf($["${VEYRA_ANY}"="1"]?told)',
        f" same => n,Set(VEYRA_DEL=${{DB_DELETE({key})}})",
        f" same => n,Set(VEYRA_DEL=${{DB_DELETE({key}/paused)}})",
        f" same => n,Set(DEVICE_STATE({device})=NOT_INUSE)",
        f" same => n,Set(DEVICE_STATE(Custom:veyra-agentpause-{org}-{number})=NOT_INUSE)",
        f" same => n(told),UserEvent({AGENT_EVENT},Org: {org},Extension: {number},"
        f"Action: logout{event_scope})",
        " same => n,Playback(agent-loggedoff)",
        " same => n,Hangup()",
    ]


def _agent_contexts(codes: dict[str, str], queues: list[dict[str, Any]]) -> list[str]:
    """``veyra-agent-login`` (all queues of the phone) and ``veyra-agent-login-<queue>``
    (one queue), one extension entry each: the feature codes jump here with
    the phone's own number (docs/CALL_FEATURES.md §4.9)."""
    if "queue_login" not in codes:
        return []
    n = engine_names.current()
    agents = _dynamic_agents(queues)
    if not agents:
        return []
    lines = [f"[{n.agent_login()}]"]
    endpoint_of = {
        str(m["number"]): str(m["endpoint_name"]) for q in queues for m in q.get("members") or []
    }
    for number, memberships in sorted(agents.items()):
        org = _slug(memberships[0][0].get("organization") or "", "organization")
        lines.append(f"exten => {number},1,NoOp(Veyra agent {number} toggles every queue)")
        lines += _agent_lines(org, number, endpoint_of[number], memberships, [], None)
    lines.append("")
    for q in queues:
        members = [(q, m) for m in q.get("members") or [] if m.get("dynamic")]
        if not members:
            continue
        slug = _slug(q["slug"], "queue slug")
        org = _slug(q.get("organization") or "", "organization")
        lines.append(f"[{n.agent_login(slug)}]")
        for _, m in members:
            number = str(m["number"])
            others = [
                _slug(oq["slug"], "queue slug") for oq, _ in agents.get(number, []) if oq is not q
            ]
            lines.append(f"exten => {number},1,NoOp(Veyra agent {number} toggles queue {slug})")
            lines += _agent_lines(org, number, str(m["endpoint_name"]), [(q, m)], others, slug)
        lines.append("")
    return lines


def _agent_codes(
    codes: dict[str, str], queues: list[dict[str, Any]], cos: Cos | None = None
) -> list[str]:
    """``*45[<queue>]`` log in / out, ``*46`` pause / unpause, ``*47<queue>``
    waiting count (docs/CALL_FEATURES.md §4.9)."""
    n = engine_names.current()
    lines: list[str] = []
    agents = _dynamic_agents(queues)
    login = codes.get("queue_login")
    if login and agents:
        head = f"exten => {login},1,NoOp(Veyra queue login toggle for ${{VEYRA_EXT}})"
        body = [f" same => n,Goto({n.agent_login()},${{VEYRA_EXT}},1)"]
        lines += _code_block(head, body, cos, "queue_login")
        for q in queues:
            if not any(m.get("dynamic") for m in q.get("members") or []):
                continue
            slug = _slug(q["slug"], "queue slug")
            number = str(q["number"])
            head = (
                f"exten => {login}{number},1,NoOp(Veyra queue {slug} login toggle "
                "for ${VEYRA_EXT})"
            )
            body = [f" same => n,Goto({n.agent_login(slug)},${{VEYRA_EXT}},1)"]
            lines += _code_block(head, body, cos, "queue_login")
    pause = codes.get("queue_pause")
    if pause and agents:
        key = f"{AGENT_FAMILY}/${{VEYRA_ORG}}/${{VEYRA_EXT}}"
        device = "Custom:veyra-agentpause-${VEYRA_ORG}-${VEYRA_EXT}"
        head = f"exten => {pause},1,NoOp(Veyra queue pause toggle for ${{VEYRA_EXT}})"
        body = [
            f' same => n,GotoIf($["${{DB({key})}}"!="1"]?notin)',
            f' same => n,GotoIf($["${{DB({key}/paused)}}"="1"]?unpause)',
            " same => n,PauseQueueMember(,PJSIP/${CHANNEL(endpoint)},,veyra)",
            f" same => n,Set(DB({key}/paused)=1)",
            f" same => n,Set(DEVICE_STATE({device})=INUSE)",
            f" same => n,UserEvent({AGENT_EVENT},Org: ${{VEYRA_ORG}},Extension: ${{VEYRA_EXT}},"
            "Action: pause)",
            " same => n,Playback(dictate/pause)",
            " same => n,Hangup()",
            " same => n(unpause),UnpauseQueueMember(,PJSIP/${CHANNEL(endpoint)})",
            f" same => n,Set(VEYRA_DEL=${{DB_DELETE({key}/paused)}})",
            f" same => n,Set(DEVICE_STATE({device})=NOT_INUSE)",
            f" same => n,UserEvent({AGENT_EVENT},Org: ${{VEYRA_ORG}},Extension: ${{VEYRA_EXT}},"
            "Action: unpause)",
            " same => n,Playback(agent-loginok)",
            " same => n,Hangup()",
            " same => n(notin),Playback(agent-loggedoff)",
            " same => n,Hangup()",
        ]
        lines += _code_block(head, body, cos, "queue_pause")
    count = codes.get("queue_count")
    if count:
        for q in queues:
            slug = _slug(q["slug"], "queue slug")
            number = str(q["number"])
            qname = n.queue(slug)
            head = f"exten => {count}{number},1,NoOp(Veyra queue {slug} waiting count)"
            body = [
                f" same => n,Set(VEYRA_WAITING=${{QUEUE_WAITING_COUNT({qname})}})",
                " same => n,SayNumber(${VEYRA_WAITING})",
                " same => n,Playback(queue-callswaiting)",
                " same => n,Hangup()",
            ]
            lines += _code_block(head, body, cos, "queue_count")
    return lines


def _agent_hints(codes: dict[str, str], queues: list[dict[str, Any]]) -> list[str]:
    """BLF lamps: ``*45*<ext>`` lit while the phone is logged in anywhere,
    ``*46*<ext>`` lit while paused."""
    hints: list[str] = []
    login, pause = codes.get("queue_login"), codes.get("queue_pause")
    for number, memberships in sorted(_dynamic_agents(queues).items()):
        org = _slug(memberships[0][0].get("organization") or "", "organization")
        if login:
            hints.append(f"exten => {login}*{number},hint,Custom:veyra-agent-{org}-{number}")
            # The queue log-in key's lamp is dialable from the agent's own phone.
            hints += [
                f'exten => {login}*{number},1,GotoIf($["${{VEYRA_EXT}}"="{number}"]?{login},1)',
                " same => n,Playback(beeperr)",
                " same => n,Hangup()",
            ]
        if pause:
            hints.append(f"exten => {pause}*{number},hint,Custom:veyra-agentpause-{org}-{number}")
        if login:
            # One queue's log-in key (issue #130): lit while logged into it,
            # pressing it from the agent's phone toggles that queue.
            for q, _m in memberships:
                slug = _slug(q["slug"], "queue slug")
                qnum = str(q["number"])
                hints += [
                    f"exten => {login}{qnum}*{number},hint,"
                    f"Custom:veyra-agentq-{org}-{number}-{slug}",
                    f'exten => {login}{qnum}*{number},1,GotoIf($["${{VEYRA_EXT}}"="{number}"]'
                    f"?{login}{qnum},1)",
                    " same => n,Playback(beeperr)",
                    " same => n,Hangup()",
                ]
    return hints


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
        opened = routing.gotoiftime_args(routing.check_ranges(list(c.get("ranges") or [])), tz)
        closed = routing.holiday_apps(
            routing.check_holidays(list(c.get("holidays") or [])), tz, "isclosed"
        )
        store = f"{SWITCH_FAMILY}/tc/{org}/{key}"
        device = f"Custom:veyra-tc-{org}-{key}"

        pin = _switch_pin_lines(c.get("pin"), f"time condition {name}")
        body = [
            f' same => n,GotoIf($["${{VEYRA_ORG}}"!="{org}"]?nophone)',
            *pin,
            f' same => n,GotoIf($["${{DB({store})}}"!=""]?clear)',
            *[f" same => n,{app}" for app in closed],
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
            # it, any other key ends it early when skipping is allowed and
            # replays it otherwise (a key always stops the playback).
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
            lines.append("exten => t,1,Goto(s,next)")
            lines.append(f"exten => i,1,Goto(s,{'next' if skip else 'play'})")
        lines.append("")
    return lines


def _directory_operator(snapshot: dict[str, Any], ns: str) -> str | None:
    """The operator number of the namespace's organization (issue #135)."""
    for o in snapshot.get("organizations") or []:
        if engine_names.for_org(str(o.get("slug") or "")).ns != ns:
            continue
        op = o.get("directory_operator")
        if op:
            if not _NUMBER_RE.match(str(op)):
                raise GenerationError(f"directory operator {op!r} is not valid")
            return str(op)
    return None


def _directory_context(operator: str | None = None) -> list[str]:
    """``veyra-directory``: dial by name over the organization's voicemail
    boxes and its own directory names (docs/CALL_FEATURES.md §4.2; the names
    are in ``directory.conf``); 0 reaches the operator when there is one, *
    leaves with a goodbye."""
    n = engine_names.current()
    zero = (
        [f"exten => o,1,Goto({n.internal},{operator},1)"]
        if operator
        else ["exten => o,1,Playback(vm-goodbye)", " same => n,Hangup()"]
    )
    return [
        f"[{n.directory}]",
        "exten => s,1,NoOp(Veyra dial-by-name directory)",
        " same => n,Answer()",
        f" same => n,Directory({n.voicemail},{n.internal},ebc(veyra/{FILE_DIRECTORY}))",
        " same => n,Playback(vm-goodbye)",
        " same => n,Hangup()",
        *zero,
        "exten => a,1,Playback(vm-goodbye)",
        " same => n,Hangup()",
        "",
    ]


def _directory_conf(snapshot: dict[str, Any], boxes: Boxes) -> GeneratedFile:
    """Directory()'s own file (voicemail.conf layout, no PINs): per voicemail
    context the people with a box and the organization's directory names."""
    sections: dict[str, list[str]] = {}
    for (org, number), b in sorted(
        boxes.items(), key=lambda kv: (kv[0][0], len(kv[0][1]), kv[0][1])
    ):
        name = _display(b.get("name"))
        if not name or not _NUMBER_RE.match(number):
            continue
        sections.setdefault(engine_names.for_org(org).voicemail, []).append(f"{number} => ,{name}")
    for o in snapshot.get("organizations") or []:
        ctx = engine_names.for_org(str(o.get("slug") or "")).voicemail
        for e in o.get("directory_entries") or []:
            number, name = str(e.get("number") or ""), _display(e.get("name"))
            if not _NUMBER_RE.match(number) or not name:
                raise GenerationError(f"directory name {e.get('name')!r} is not valid")
            sections.setdefault(ctx, []).append(f"{number} => ,{name}")
    lines = [HEADER]
    for ctx in sorted(sections):
        lines += [f"[{ctx}]", *sections[ctx], ""]
    if len(lines) == 1:
        lines += ["[veyra-empty]", ""]
    return GeneratedFile(FILE_DIRECTORY, "\n".join(lines).rstrip("\n") + "\n")


def _conference_profiles(slug: str) -> tuple[str, str, str, str, str]:
    """Room name, bridge, user, admin and menu profile names of a room."""
    stem = engine_names.current().conference(slug)
    return stem, f"{stem}-bridge", f"{stem}-user", f"{stem}-admin", f"{stem}-menu"


def _fax_contexts(inboxes: list[dict[str, Any]], fax_dir: str) -> list[str]:
    """``veyra-fax-out`` of the namespace (the worker originates a Local
    channel over the outbound routes; once it answers, ``send`` runs SendFAX
    of the job named in the channel variables) and one ``veyra-fax-in-<slug>``
    per enabled inbox (ReceiveFAX into the shared fax directory); both report
    the result with ``UserEvent(VeyraFax)``, which the API turns into the job's
    state and the PDF by email (docs/USER_PORTAL.md §9)."""
    names = engine_names.current()
    lines = [
        f"[{names.fax_out}]",
        "; Sends the queued fax named in VEYRA_FAX_JOB once the outbound leg answers.",
        "exten => send,1,NoOp(Veyra fax job ${VEYRA_FAX_JOB} to ${VEYRA_FAX_NUMBER})",
        ' same => n,ExecIf($["${VEYRA_FAX_HEADER}"!=""]'
        "?Set(FAXOPT(headerinfo)=${VEYRA_FAX_HEADER}))",
        ' same => n,ExecIf($["${VEYRA_FAX_STATION}"!=""]'
        "?Set(FAXOPT(localstationid)=${VEYRA_FAX_STATION}))",
        " same => n,Set(FAXOPT(ecm)=yes)",
        " same => n,SendFAX(${VEYRA_FAX_FILE},d)",
        " same => n,Hangup()",
        f"exten => h,1,UserEvent({FAX_EVENT},Direction: out,Job: ${{VEYRA_FAX_JOB}},"
        "Status: ${FAXSTATUS},Error: ${FAXERROR},Pages: ${FAXPAGES},"
        "Remote: ${REMOTESTATIONID},Cause: ${HANGUPCAUSE})",
        "",
    ]
    seen: set[str] = set()
    for i in inboxes:
        slug = _slug(i["slug"], "fax inbox slug")
        if slug in seen:
            raise GenerationError(f"duplicate fax inbox slug {slug!r}")
        seen.add(slug)
        name = _check_value(str(i.get("name") or slug), "fax inbox name")
        org = _slug(i.get("organization") or "", f"organization of fax inbox {slug}")
        header = str(i.get("header") or "")
        station = str(i.get("station_id") or "")
        if station and not _FAX_STATION_RE.match(station):
            raise GenerationError(f"fax inbox {slug}: station id {station!r} is not valid")
        ctx = names.fax_in(slug)
        lines += [
            f"[{ctx}]",
            f"; {name} ({org})",
            f"exten => s,1,NoOp(Veyra fax inbox {name})",
            f" same => n,Set(__VEYRA_FAX_INBOX={slug})",
            f" same => n,Set(__VEYRA_FAX_FILE={fax_dir}/incoming/{slug}-${{UNIQUEID}}.tiff)",
        ]
        if header:
            lines.append(f" same => n,Set(FAXOPT(headerinfo)={_check_value(header, 'fax header')})")
        if station:
            lines.append(f" same => n,Set(FAXOPT(localstationid)={station})")
        lines += [
            " same => n,Set(FAXOPT(ecm)=yes)",
            " same => n,Answer()",
            " same => n,Wait(1)",
            " same => n,ReceiveFAX(${VEYRA_FAX_FILE})",
            " same => n,Hangup()",
            f"exten => h,1,UserEvent({FAX_EVENT},Direction: in,Inbox: {slug},Org: {org},"
            "File: ${VEYRA_FAX_FILE},Status: ${FAXSTATUS},Error: ${FAXERROR},"
            "Pages: ${FAXPAGES},Remote: ${REMOTESTATIONID},Caller: ${CALLERID(num)})",
            "",
        ]
    return lines


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
    parking: list[dict[str, Any]] | None = None,
) -> None:
    """Ring group, queue, conference room and parking numbers share the
    extension number space of their engine namespace (docs/MULTI_TENANCY.md §3)."""

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
    for lot in parking or []:
        slug = str(lot.get("slug") or "")
        for number in _parking_numbers(lot):
            if key(lot, number) in taken:
                raise GenerationError(
                    f"number {number} is used by a {taken[key(lot, number)]} and parking lot {slug}"
                )
            taken[key(lot, number)] = "parking lot"


def _parking_numbers(lot: dict[str, Any]) -> list[str]:
    """The park extension and every slot of a lot, validated."""
    slug = _slug(lot.get("slug"), "parking lot slug")
    park = str(lot.get("park_exten") or "")
    if not re.fullmatch(r"[0-9]{1,32}", park):
        raise GenerationError(f"parking lot {slug}: park extension {park!r} is not valid")
    first, last = int(lot.get("slot_first") or 0), int(lot.get("slot_last") or 0)
    if first <= 0 or last < first or last - first + 1 > PARKING_MAX_SLOTS:
        raise GenerationError(
            f"parking lot {slug}: slots {first}-{last} are not a range of 1 to {PARKING_MAX_SLOTS}"
        )
    numbers = [park] + [str(n) for n in range(first, last + 1)]
    if len(set(numbers)) != len(numbers):
        raise GenerationError(f"parking lot {slug}: the park extension lies inside the slots")
    return numbers


def _parking_conf(lots: list[dict[str, Any]]) -> GeneratedFile:
    """``res_parking.conf`` (docs/CALL_FEATURES.md §4.7): one lot per section;
    res_parking creates the park and slot extensions with their hints in the
    lot's context; reloaded with ``res_parking.so``."""
    lines = [HEADER, "[general]", "parkeddynamic=no", ""]
    seen: set[str] = set()
    for lot in lots:
        slug = _slug(lot["slug"], "parking lot slug")
        org = _slug(lot.get("organization") or "", f"organization of parking lot {slug}")
        n = engine_names.for_org(org)
        if n.parking(slug) in seen:
            raise GenerationError(f"duplicate parking lot slug {slug!r}")
        seen.add(n.parking(slug))
        name = _check_value(str(lot.get("name") or slug), "parking lot name")
        numbers = _parking_numbers(lot)
        timeout = int(lot.get("timeout_seconds") or 45)
        ring = int(lot.get("return_ring_seconds") or 20)
        if not 10 <= timeout <= 1800:
            raise GenerationError(f"parking lot {slug}: timeout {timeout} is out of range")
        if not 5 <= ring <= 120:
            raise GenerationError(f"parking lot {slug}: return ring time {ring} is out of range")
        lines += [
            f"[{n.parking(slug)}]",
            f"; {name} ({org})",
            f"context={n.parking(slug)}",
            f"parkext={numbers[0]}",
            "parkext_exclusive=yes",
            f"parkpos={int(lot['slot_first'])}-{int(lot['slot_last'])}",
            "findslot=next",
            # Slot hints: a park key watching a slot lights while a call waits
            # there (docs/PROVISIONING_BREADTH.md §3).
            "parkinghints=yes",
            f"parkingtime={timeout}",
            "comebacktoorigin=no",
            f"comebackcontext={n.parking_timeout(slug)}",
            f"comebackdialtime={ring}",
            "parkedplay=caller",
            "courtesytone=" + ("beep" if lot.get("courtesy_tone", True) else ""),
            "parkedcalltransfers=caller",
            "parkedcallreparking=caller",
            "parkedcallhangup=no",
            "parkedcallrecording=no",
            "",
        ]
    return GeneratedFile(FILE_PARKING, "\n".join(lines).rstrip("\n") + "\n")


def _parking_contexts(lots: list[dict[str, Any]]) -> list[str]:
    """One timeout context per lot: ring the parker back for the lot's return
    time, then the lot's destination (docs/CALL_FEATURES.md §4.7). The lot's
    own context (park extension, slots, hints) is written by res_parking."""
    lines: list[str] = []
    n = engine_names.current()
    for lot in lots:
        slug = _slug(lot["slug"], "parking lot slug")
        name = _check_value(str(lot.get("name") or slug), "parking lot name")
        ring = int(lot.get("return_ring_seconds") or 20)
        lines += [
            f"[{n.parking(slug)}]",
            "; Filled by res_parking at load time (park extension, slots, hints).",
            f"exten => s,1,NoOp(Veyra parking lot {name})",
            " same => n,Hangup()",
            "",
            f"[{n.parking_timeout(slug)}]",
            f"exten => s,1,NoOp(Veyra parking lot {name}: slot ${{PARKINGSLOT}} timed out)",
            ' same => n,GotoIf($["${PARKER_FLAT}"=""]?gone)',
            f" same => n,Dial(${{PARKER}},{ring})",
            f" same => n(gone),NoOp(Veyra parking lot {name}: the parker did not answer)",
            *_goto(lot.get("timeout")),
            "",
        ]
    return lines


def _group_prologue(ctx: str, what: str, name: str, org: str) -> list[str]:
    return [
        f"[{ctx}]",
        f"exten => s,1,NoOp(Veyra {what} {name} ({org}))",
        " same => n,Set(__VEYRA_GROUP_DEPTH=$[0${VEYRA_GROUP_DEPTH} + 1])",
        f" same => n,GotoIf($[${{VEYRA_GROUP_DEPTH}} > {MAX_GROUP_DEPTH}]?toodeep)",
        # For the answering phone's last-caller record (CONTEXT_LASTCID): its
        # endpoint is "<org>-<number>", so the number starts after the prefix.
        f" same => n,Set(__VEYRA_LASTCID_ORG={org})",
        f" same => n,Set(__VEYRA_LASTCID_OFF={len(org) + 1})",
    ]


def _lastcid_context() -> list[str]:
    """The answering phone of a group or queue call records the outside
    caller, as a direct call does in the extension's dialplan (*32)."""
    return [
        f"[{CONTEXT_LASTCID}]",
        'exten => s,1,GotoIf($["${CHANNEL(channeltype)}"!="PJSIP" | "${VEYRA_DID}"=""'
        ' | "${CALLERID(num)}"="" | "${VEYRA_LASTCID_ORG}"=""]?done)',
        f" same => n,Set(DB({LASTCID_FAMILY}/${{VEYRA_LASTCID_ORG}}/"
        "${CHANNEL(endpoint):${VEYRA_LASTCID_OFF}})=${CALLERID(num)})",
        " same => n(done),Return()",
        "",
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
        member_rings = []
        for m in g.get("members") or []:
            seconds = int(m.get("ring_seconds") or ring)
            if not 5 <= seconds <= 120:
                raise GenerationError(
                    f"ring group {slug}: member ring time {seconds} is out of range"
                )
            member_rings.append(seconds)
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
        dial_opts = f",${{VEYRA_XFER}}U({CONTEXT_LASTCID})"
        if music == "default":
            moh_class = _moh_class(g.get("hold_music"), moh or {}, f"ring group {slug}", org)
            dial_opts = f",${{VEYRA_XFER}}U({CONTEXT_LASTCID})m({moh_class})"
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
        elif strategy in HUNT_STRATEGIES and members:
            lines += _hunt_members(
                org, slug, strategy, members, member_rings, ring_busy, dial_opts, music
            )
            for leg in outside:
                lines += [
                    f" same => n,Dial({leg},{ring}{dial_opts})",
                    ' same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?done)',
                ]
            lines.append(" same => n,Goto(failover)")
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
                    f" same => n{label},Dial(PJSIP/{m},{member_rings[i]}{dial_opts})",
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


def _hunt_members(
    org: str,
    slug: str,
    strategy: str,
    members: list[str],
    rings: list[int],
    ring_busy: bool,
    dial_opts: str,
    music: str,
) -> list[str]:
    """One member at a time in a moving order (issue #166). The members and
    their ring times are ``:``-separated lists picked by index in a While
    loop; the order's state is in AstDB ``veyra/rg/<org>/<slug>``: ``next``
    (circular, round robin) or ``idle_<endpoint>`` (the time a member last
    answered, longest idle). The answering member's channel writes it
    through Dial ``U()``, so a caller who hangs up first changes nothing."""
    count = len(members)
    family = f"{RG_STATE_FAMILY}/{org}/{slug}"
    lines = [
        f" same => n,Set(VEYRA_EPS={':'.join(members)})",
        f" same => n,Set(VEYRA_RINGS={':'.join(str(r) for r in rings)})",
        " same => n,Set(VEYRA_T=0)",
    ]
    if strategy == "longest_idle":
        lines.append(f" same => n,Set(VEYRA_LEFT=-{'-'.join(str(i) for i in range(count))}-)")
    else:
        lines += [
            f" same => n,Set(VEYRA_S=${{DB({family}/next)}})",
            f' same => n,ExecIf($[!${{REGEX("^[0-9]+$" ${{VEYRA_S}})}} | 0${{VEYRA_S}} >= {count}]'
            "?Set(VEYRA_S=0))",
        ]
        if strategy == "roundrobin":
            lines.append(f" same => n,Set(DB({family}/next)=$[(${{VEYRA_S}} + 1) % {count}])")
    lines.append(f" same => n,While($[${{VEYRA_T}} < {count}])")
    if strategy == "longest_idle":
        lines += [" same => n,Set(VEYRA_I=-1)", " same => n,Set(VEYRA_BT=99999999999)"]
        for i, ep in enumerate(members):
            idle = f"0${{DB({family}/idle_{ep})}}"
            lines += [
                f' same => n,Set(VEYRA_C=$[${{REGEX("-{i}-" ${{VEYRA_LEFT}})}} & '
                f"{idle} < ${{VEYRA_BT}}])",
                f" same => n,ExecIf(${{VEYRA_C}}?Set(VEYRA_I={i}))",
                f" same => n,ExecIf(${{VEYRA_C}}?Set(VEYRA_BT={idle}))",
            ]
        lines += [
            " same => n,ExecIf($[${VEYRA_I} < 0]?ExitWhile())",
            " same => n,Set(VEYRA_LEFT=${STRREPLACE(VEYRA_LEFT,-${VEYRA_I}-,-)})",
        ]
    else:
        lines.append(f" same => n,Set(VEYRA_I=$[(${{VEYRA_S}} + ${{VEYRA_T}}) % {count}])")
    lines += [
        " same => n,Set(VEYRA_T=$[${VEYRA_T} + 1])",
        " same => n,Set(VEYRA_EP=${CUT(VEYRA_EPS,:,$[${VEYRA_I} + 1])})",
    ]
    if not ring_busy:
        lines.append(
            ' same => n,GotoIf($["${DEVICE_STATE(PJSIP/${VEYRA_EP})}"'
            f' : "{BUSY_STATES}"]?hnext)'
        )
    if strategy == "circular":
        state = f"next^$[(${{VEYRA_I}} + 1) % {count}]"
    elif strategy == "longest_idle":
        state = "idle_${VEYRA_EP}^${EPOCH}"
    else:
        state = ""
    opts = dial_opts
    if state:
        opts = dial_opts.replace(
            f"U({CONTEXT_LASTCID})", f"U({CONTEXT_RG_ANSWERED}^{org}^{slug}^{state})"
        )
    lines += [
        f" same => n,Dial(PJSIP/${{VEYRA_EP}},${{CUT(VEYRA_RINGS,:,$[${{VEYRA_I}} + 1])}}{opts})",
        ' same => n,ExecIf($["${DIALSTATUS}"="ANSWER"]?ExitWhile())',
        " same => n(hnext),EndWhile()",
        ' same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?done)',
    ]
    return lines


def _rg_answered_context() -> list[str]:
    """Gosub on the answering member of a hunting group (issue #166): the
    last-caller record, then the group's state (ARG1 org, ARG2 group, ARG3
    key, ARG4 value)."""
    return [
        f"[{CONTEXT_RG_ANSWERED}]",
        f"exten => s,1,Gosub({CONTEXT_LASTCID},s,1)",
        f" same => n,Set(DB({RG_STATE_FAMILY}/${{ARG1}}/${{ARG2}}/${{ARG3}})=${{ARG4}})",
        " same => n,Return()",
        "",
    ]


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
            f" same => n,Queue({engine_names.current().queue(slug)},{options},,,{timeout},,"
            f"{CONTEXT_LASTCID})",
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
        # Dynamic agents (§4.9) survive a restart; the worker reconciles anyway.
        "persistentmembers=yes",
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
        # Break-out menu (§4.10): a key pressed while waiting leaves to that
        # key's extension in the menu's context.
        breakout = q.get("breakout")
        if breakout:
            lines.append(f"context={n.ivr(_slug(breakout, 'IVR menu slug'))}")
        for m in q.get("members") or []:
            endpoint = _check_section(str(m["endpoint_name"]), "endpoint name")
            if endpoint not in endpoints or endpoint_org.get(endpoint) != org:
                continue  # gone, or (never) another organization's phone
            if m.get("dynamic"):
                continue  # joins at login (§4.9), not from the file
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
    PINs in clear. Email addresses are only rendered when delivery is enabled.
    Asterisk never deletes after emailing (``delete=no``): the worker deletes
    a message once its email was accepted (issue #148)."""
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
        "${VM_DUR} long.\\n\\nThis message was sent by Veyra."
        # Which message this is, for delete-after-email (issue #148): the
        # mail queue turns it into a header and the worker strips it.
        "\\n\\n[veyra-vm:${VM_MESSAGEFILE}]",
        f"mailcmd={mailqueue_command}",
        # New-message counts for the voicemail.message webhook (docs/INTEGRATIONS.md §3.2).
        f"externnotify={posixpath.join(posixpath.dirname(mailqueue_command), 'veyra-vmnotify')}",
        # The web inbox moves and deletes messages outside the engine
        # (docs/USER_PORTAL.md §2.2): polling keeps the MWI lamps and the
        # externnotify counts right.
        "pollmailboxes=yes",
        "pollfreq=10",
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
        if delivery and b.get("email"):
            try:
                email = routing.check_email(str(b["email"]))
            except ValueError as e:
                raise GenerationError(f"voicemail box {number}: {e}") from e
        attach = "yes" if b.get("attach_audio", True) else "no"
        org = _slug(b.get("organization") or "", "organization")
        # Pressing 0 (operator) or * during the greeting leaves to the box's
        # exit context (docs/CALL_FEATURES.md §3.7).
        operator = b.get("operator_extension")
        exit_opts = ""
        if operator and not _NUMBER_RE.match(str(operator)):
            raise GenerationError(f"voicemail box {number}: operator {operator!r} is not valid")
        if _has_exit(b):
            ctx = engine_names.for_org(org).voicemail_exit(number)
            exit_opts = f"|operator={'yes' if operator else 'no'}|exitcontext={ctx}"
        lines.append(
            f"{number} => {pin},{name},{email},,"
            f"attach={attach}|delete=no|tz={org}|saycid=yes|envelope=yes{exit_opts}"
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
