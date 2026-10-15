# SPDX-License-Identifier: AGPL-3.0-or-later
"""The isolation verifier (docs/MULTI_TENANCY.md §5).

Reads the generated ``extensions.conf``, ``pjsip.endpoints.conf`` and
``queues.conf`` and proves that no organization's phones or contexts can
reach another organization's phones, contexts, voicemail or queues. It works
on the text Asterisk will load, not on the snapshot, so a mistake anywhere
in the generator is caught before a revision is deployed.
"""

from __future__ import annotations

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

_SECTION = re.compile(r"^\[([^\]]+)\](?:\(([^)]*)\))?\s*$")
_ENDPOINT_REF = re.compile(r"PJSIP/([A-Za-z0-9_.-]+)")
_MAILBOX_REF = re.compile(r"[0-9*#]+@(veyra[A-Za-z0-9_-]*)")
_QUEUE_APP = re.compile(r"\bQueue\(([^,)]+)")
_TOKEN = re.compile(r"veyra[_-][A-Za-z0-9_-]+")
_NS_OF = re.compile(r"^veyra_([a-z0-9]{1,16})(?:-|$)")


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
        if key == "set_var" and value.startswith("VEYRA_ORG="):
            info["org"] = value.split("=", 1)[1]
        elif key == "context":
            info["context"] = value
        elif key == "mailboxes":
            info["mailboxes"] = [v for v in value.split(",") if v]
        elif key in ("named_call_group", "named_pickup_group"):
            info["groups"] = [v for v in value.split(",") if v]
    return out


def verify(files: Iterable[GeneratedFile], *, strict: bool = True) -> list[str]:
    """Problems found; empty when every organization is isolated. With
    ``strict``, two organizations in one namespace are a problem too (the
    multi-tenancy switch is on)."""
    by_path = {f.path: f.content for f in files}
    problems: list[str] = []
    endpoints = _endpoints(by_path.get("pjsip.endpoints.conf", ""))
    dial = _parse(by_path.get("extensions.conf", ""))
    queues = _parse(by_path.get("queues.conf", ""))

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

    sections = set(dial.sections)
    queue_names = set(queues.sections) - {"general"}

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
        for line in dial.sections[ctx]:
            problems += check_refs(owner, f"context {ctx}", line)

    # 3. Shared contexts: an outbound route reaches no organization; a DID of
    # the from-trunk contexts reaches exactly one.
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
            if ctx.startswith("veyra-out-") and reached:
                problems.append(f"context {ctx}: outbound route reaches an organization")
            elif len(reached) > 1:
                problems.append(f"context {ctx}, {exten}: one number reaches several organizations")

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
    return sorted(set(problems))
