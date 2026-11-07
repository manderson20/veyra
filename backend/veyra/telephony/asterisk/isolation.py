# SPDX-License-Identifier: AGPL-3.0-or-later
"""The isolation verifier (docs/MULTI_TENANCY.md §5, docs/MULTI_TENANCY_MSP.md §3.2).

Reads the generated configuration (``extensions.conf``, ``pjsip.endpoints.conf``,
``queues.conf``, ``voicemail.conf``, ``confbridge.conf``, ``res_parking.conf``,
``musiconhold.conf`` and ``paging.json``) and proves that no organization's
phones or contexts can reach another organization's phones, contexts,
voicemail, queues, conferences, parking lots, hold music, device states or
engine store keys. It works on the text Asterisk will load, not on the
snapshot, so a mistake anywhere in the generator is caught before a revision
is deployed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from veyra.telephony.adapter import GeneratedFile
from veyra.telephony.asterisk.names import (
    LEGACY,
    SHARED_CONTEXT_PREFIXES,
    SHARED_CONTEXTS,
    Names,
)
from veyra.telephony.routing import canonical_did

_SECTION = re.compile(r"^\[([^\]]+)\](?:\(([^)]*)\))?\s*$")
_ENDPOINT_REF = re.compile(r"PJSIP/([A-Za-z0-9_.-]+)")
_MAILBOX_REF = re.compile(r"[0-9*#]+@(veyra[A-Za-z0-9_-]*)")
_QUEUE_APP = re.compile(r"\bQueue\(([^,)]+)")
_TOKEN = re.compile(r"veyra[_-][A-Za-z0-9_-]+")
_NS_OF = re.compile(r"^veyra_([a-z0-9]{1,16})(?:-|$)")
_CUSTOM_REF = re.compile(r"Custom:veyra-([a-z]+)-([A-Za-z0-9_.${}-]+)")
_DB_REF = re.compile(r"DB(?:_DELETE|_EXISTS|_KEYS|_DELTREE)?\(([^)]+)\)")
_DID_EXTEN = re.compile(r"^exten\s*=>\s*([^,]+),")
# Engine store families whose next key is the organization's slug
# (docs/MULTI_TENANCY_MSP.md §3.2). Longest first.
ORG_FAMILIES = (
    "veyra/switch/flow",
    "veyra/switch/tc",
    "veyra/agent",
    "veyra/blacklist",
    "veyra/disa",
    "veyra/ext",
    "veyra/lastcid",
    "veyra/rg",
    "veyra/vmabs",
    "veyra/vmalt",
)
# Sections of these files that are not an organization's.
_GENERAL_SECTIONS = {"general", "globals", "zonemessages"}
FROM_TRUNK = "veyra-from-trunk"


def namespace_of(name: str) -> str | None:
    """The namespace an engine name belongs to; None for shared names."""
    if name in SHARED_CONTEXTS or any(name.startswith(p) for p in SHARED_CONTEXT_PREFIXES):
        return None
    m = _NS_OF.match(name)
    if m:
        return m.group(1)
    if name == "veyra" or name.startswith("veyra-"):
        return LEGACY
    return None


@dataclass
class _Config:
    sections: dict[str, list[str]] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)


def _parse(text: str) -> _Config:
    cfg = _Config()
    current: str | None = None
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].rstrip() if not raw.lstrip().startswith(";") else ""
        m = _SECTION.match(line.strip())
        if m:
            current = m.group(1)
            if current not in cfg.sections:
                cfg.sections[current] = []
                cfg.order.append(current)
            continue
        if current is not None and line.strip():
            cfg.sections[current].append(line)
    return cfg


def _endpoints(text: str) -> dict[str, dict[str, object]]:
    """Endpoint name -> {"org", "context", "mailboxes", "groups"} (type=endpoint
    sections only; templates and auth/aor sections are skipped)."""
    out: dict[str, dict[str, object]] = {}
    current: str | None = None
    template: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        m = _SECTION.match(line)
        if m:
            current, template = m.group(1), (m.group(2) or "")
            if template == "veyra-endpoint":
                out.setdefault(
                    current, {"org": "", "context": "veyra-internal", "mailboxes": [], "groups": []}
                )
            continue
        if current is None or template != "veyra-endpoint":
            continue
        key, _, value = line.partition("=")
        info = out[current]
        if key == "set_var" and value.lstrip("_").startswith("VEYRA_ORG="):
            info["org"] = value.split("=", 1)[1]
        elif key == "context":
            info["context"] = value
        elif key == "mailboxes":
            info["mailboxes"] = [v for v in value.split(",") if v]
        elif key in ("named_call_group", "named_pickup_group"):
            info["groups"] = [v for v in value.split(",") if v]
    return out


def _owner_slug(text: str, slugs: Iterable[str]) -> str | None:
    """The organization a ``<slug>-…`` or ``<slug>/…`` name belongs to: the
    longest slug it starts with, since slugs may hold hyphens."""
    best: str | None = None
    for slug in slugs:
        if (text == slug or text.startswith(slug + "-") or text.startswith(slug + "/")) and (
            best is None or len(slug) > len(best)
        ):
            best = slug
    return best


def _db_org(key: str) -> str | None:
    """The organization part of a literal engine store key, or None when the
    family is not per organization or the key is not literal there."""
    for family in ORG_FAMILIES:
        if key.startswith(family + "/"):
            return key[len(family) + 1 :]
    return None


def verify(
    files: Iterable[GeneratedFile],
    *,
    strict: bool = True,
    organizations: dict[str, str] | None = None,
    dids: dict[str, str] | None = None,
) -> list[str]:
    """Problems found; empty when every organization is isolated. With
    ``strict``, two organizations in one namespace are a problem too (the
    multi-tenancy switch is on). ``organizations`` maps each organization's
    slug to its namespace; without it, the phones' VEYRA_ORG tell. ``dids``
    maps each DID (canonical, ``routing.canonical_did``) to the namespace that
    owns the number (the number inventory, docs/MULTI_TENANCY_MSP.md §4)."""
    by_path = {f.path: f.content for f in files}
    problems: list[str] = []
    endpoints = _endpoints(by_path.get("pjsip.endpoints.conf", ""))
    dial = _parse(by_path.get("extensions.conf", ""))
    queues = _parse(by_path.get("queues.conf", ""))
    confbridge = _parse(by_path.get("confbridge.conf", ""))
    parking = _parse(by_path.get("res_parking.conf", ""))
    moh = _parse(by_path.get("musiconhold.conf", ""))
    voicemail = _parse(by_path.get("voicemail.conf", ""))

    # 1. Phones: own context, own mailboxes, own pickup groups.
    org_ns: dict[str, str] = {}
    endpoint_ns: dict[str, str] = {}
    for name, info in endpoints.items():
        org = str(info["org"])
        ns = namespace_of(str(info["context"]))
        if ns is None:
            problems.append(f"phone {name}: context {info['context']} is not an organization's")
            continue
        if Names(ns).internal != info["context"]:
            problems.append(f"phone {name}: context {info['context']} is not a phone context")
        endpoint_ns[name] = ns
        if org in org_ns and org_ns[org] != ns:
            problems.append(f"organization {org}: phones in two namespaces")
        org_ns.setdefault(org, ns)
        for mbox in info["mailboxes"]:  # type: ignore[attr-defined]
            ctx = str(mbox).split("@", 1)[1] if "@" in str(mbox) else ""
            if ctx != Names(ns).voicemail:
                problems.append(f"phone {name}: lamp of mailbox {mbox} outside its organization")
        for g in info["groups"]:  # type: ignore[attr-defined]
            if (str(g).split("_", 1)[0] if "_" in str(g) else LEGACY) != ns:
                problems.append(f"phone {name}: pickup group {g} outside its organization")
    if strict:
        seen: dict[str, str] = {}
        for org, ns in sorted(org_ns.items()):
            if ns in seen:
                problems.append(f"organizations {seen[ns]} and {org} share one engine namespace")
            seen[ns] = org

    slug_ns: dict[str, str] = dict(organizations or {})
    for org, ns in org_ns.items():
        slug_ns.setdefault(org, ns)
    # Every engine name an organization may own, from every file: contexts,
    # parking lots and their contexts, conference profiles, hold music
    # classes, queues and voicemail contexts.
    sections = set(dial.sections) | set(confbridge.sections) | set(moh.sections)
    sections |= set(queues.sections) | set(voicemail.sections)
    for lot, lines in parking.sections.items():
        sections.add(lot)
        for line in lines:
            key, _, value = line.strip().partition("=")
            if key.strip() in ("context", "comebackcontext"):
                sections.add(value.strip())
    sections -= _GENERAL_SECTIONS
    queue_names = set(queues.sections) - {"general"}

    def state_problems(owner_slug: str | None, where: str, line: str) -> list[str]:
        """Literal device state names and engine store keys must be the
        context's own organization's; a shared context may use only
        ${VEYRA_ORG}."""
        found: list[str] = []
        for m in _CUSTOM_REF.finditer(line):
            rest = m.group(2)
            if rest.startswith("${"):
                continue
            whose = _owner_slug(rest, slug_ns)
            if whose is not None and whose != owner_slug:
                found.append(f"{where}: device state Custom:veyra-{m.group(1)}-{rest}")
        for m in _DB_REF.finditer(line):
            key = m.group(1).split(",", 1)[0].strip()
            org_part = _db_org(key)
            if org_part is None or org_part.startswith("${"):
                continue
            whose = _owner_slug(org_part, slug_ns)
            if whose is not None and whose != owner_slug:
                found.append(f"{where}: engine store key {key}")
        return found

    ns_slugs: dict[str, set[str]] = {}
    for slug, ns in slug_ns.items():
        ns_slugs.setdefault(ns, set()).add(slug)

    def check_refs(owner: str | None, where: str, line: str) -> list[str]:
        """References in ``line`` to objects outside ``owner``'s namespace
        (``owner`` None: shared section, which may not reach any organization
        except through the per-DID rule below)."""
        found: list[str] = []
        for m in _ENDPOINT_REF.finditer(line):
            ep = m.group(1)
            if ep in endpoint_ns and endpoint_ns[ep] != owner:
                found.append(f"{where}: reaches phone {ep}")
        for m in _MAILBOX_REF.finditer(line):
            ctx = m.group(1)
            if namespace_of(ctx) not in (owner,):
                found.append(f"{where}: reaches voicemail context {ctx}")
        for m in _QUEUE_APP.finditer(line):
            q = m.group(1)
            if q in queue_names and namespace_of(q) != owner:
                found.append(f"{where}: reaches queue {q}")
        for tok in _TOKEN.findall(line):
            if tok in sections and namespace_of(tok) not in (owner, None):
                found.append(f"{where}: reaches context {tok}")
        return found

    # 2. Dialplan: an organization's contexts reach only its own objects.
    for ctx in dial.order:
        if ctx in ("general", "globals"):
            continue
        owner = namespace_of(ctx)
        if owner is None:
            continue
        own = ns_slugs.get(owner, set())
        for line in dial.sections[ctx]:
            problems += check_refs(owner, f"context {ctx}", line)
            found = state_problems(
                next(iter(own)) if len(own) == 1 else None, f"context {ctx}", line
            )
            if len(own) <= 1:
                problems += found

    # 3. Shared contexts: an outbound route reaches no organization; a DID of
    # the from-trunk contexts reaches exactly one, across all of them (the
    # shared context and each trunk's).
    did_reach: dict[str, set[str]] = {}
    for ctx in dial.order:
        if namespace_of(ctx) is not None or ctx in ("general", "globals"):
            continue
        blocks: dict[str, list[str]] = {}
        exten = ""
        for line in dial.sections[ctx]:
            m = re.match(r"^exten\s*=>\s*([^,]+),", line.strip())
            if m:
                exten = m.group(1)
            blocks.setdefault(exten, []).append(line)
        for exten, lines in blocks.items():
            reached: set[str] = set()
            for line in lines:
                for tok in _TOKEN.findall(line):
                    if tok in sections and (ns := namespace_of(tok)) is not None:
                        reached.add(ns)
                for m in _ENDPOINT_REF.finditer(line):
                    if m.group(1) in endpoint_ns:
                        reached.add(endpoint_ns[m.group(1)])
                for m in _MAILBOX_REF.finditer(line):
                    if (ns := namespace_of(m.group(1))) is not None:
                        reached.add(ns)
                for m in _CUSTOM_REF.finditer(line):
                    whose = _owner_slug(m.group(2), slug_ns)
                    if whose is not None:
                        reached.add(slug_ns[whose])
                for m in _DB_REF.finditer(line):
                    org_part = _db_org(m.group(1).split(",", 1)[0].strip())
                    whose = _owner_slug(org_part, slug_ns) if org_part else None
                    if whose is not None:
                        reached.add(slug_ns[whose])
            if ctx.startswith(FROM_TRUNK) and exten and not exten.startswith("_") and exten != "s":
                did_reach.setdefault(canonical_did(exten), set()).update(reached)
            if ctx.startswith("veyra-out-") and reached:
                problems.append(f"context {ctx}: outbound route reaches an organization")
            elif len(reached) > 1:
                problems.append(f"context {ctx}, {exten}: one number reaches several organizations")

    for exten, reached in sorted(did_reach.items()):
        if len(reached) > 1:
            problems.append(f"DID {exten}: routed to several organizations across trunks")
        if dids is not None and reached:
            owner = dids.get(canonical_did(exten))
            if owner is None or {owner} != reached:
                problems.append(f"DID {exten}: routed to an organization that does not own it")

    # 4. Queues: members are the queue's own organization's phones.
    for q in queues.order:
        if q == "general":
            continue
        owner = namespace_of(q)
        for line in queues.sections[q]:
            if line.strip().startswith("member"):
                for m in _ENDPOINT_REF.finditer(line):
                    ep = m.group(1)
                    if ep in endpoint_ns and endpoint_ns[ep] != owner:
                        problems.append(f"queue {q}: member {ep} of another organization")

    # 5. Conference profiles, parking lots, queues: each section's lines name
    # only its own organization's objects (hold music classes, contexts).
    for label, cfg in (("conference", confbridge), ("parking lot", parking), ("queue", queues)):
        for sec in cfg.order:
            owner = namespace_of(sec)
            if sec in _GENERAL_SECTIONS or owner is None:
                continue
            for line in cfg.sections[sec]:
                for tok in _TOKEN.findall(line):
                    if tok in sections and namespace_of(tok) not in (owner, None):
                        problems.append(f"{label} {sec}: reaches {tok}")

    # 6. Hold music: each class's folder is its own organization's.
    for sec in moh.order:
        owner = namespace_of(sec)
        if sec in _GENERAL_SECTIONS or owner is None:
            continue
        for line in moh.sections[sec]:
            key, _, value = line.strip().partition("=")
            if key.strip() != "directory":
                continue
            folder = value.strip().rstrip("/").rsplit("/", 1)[-1]
            folder_ns = folder.split("_", 1)[0] if "_" in folder else LEGACY
            if folder_ns != owner:
                problems.append(f"hold music {sec}: folder {value.strip()} of another organization")

    # 7. Voicemail: every mailbox context is an organization's.
    for sec in voicemail.order:
        if sec in _GENERAL_SECTIONS:
            continue
        ns = namespace_of(sec)
        if ns is None or Names(ns).voicemail != sec:
            problems.append(f"voicemail context {sec} is not an organization's")

    # 8. Paging: one sender port per zone across the server, or one
    # organization's page plays in another's zone.
    try:
        zones = json.loads(by_path.get("paging.json") or "{}").get("zones") or []
    except ValueError:
        zones = []
        problems.append("paging.json is not valid JSON")
    seen_port: dict[int, str] = {}
    for z in zones:
        port, org = z.get("port"), str(z.get("organization") or "")
        if port in seen_port and seen_port[port] != org:
            problems.append(f"paging port {port}: zones of {seen_port[port]} and {org}")
        seen_port.setdefault(port, org)
    return sorted(set(problems))
