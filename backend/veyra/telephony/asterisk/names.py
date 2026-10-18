# SPDX-License-Identifier: AGPL-3.0-or-later
"""Engine names per organization (docs/MULTI_TENANCY.md §2).

Every context, voicemail context, queue, hold music class and pickup group
name the generator writes comes from a :class:`Names`. The empty namespace
gives today's names (``veyra-internal``, ``veyra``, ``veyra-<slug>``), so an
installation with one organization is unchanged. Other namespaces are
``[a-z0-9]`` only and written as ``veyra_<ns>-…``: today's names never
contain ``_`` and a namespace never contains ``-``, so no name of one
organization can equal a name of another.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

NAMESPACE_RE = re.compile(r"^[a-z0-9]{1,16}$")
LEGACY = ""


@dataclass(frozen=True)
class Names:
    ns: str = LEGACY

    def __post_init__(self) -> None:
        if self.ns and not NAMESPACE_RE.match(self.ns):
            raise ValueError(f"engine namespace {self.ns!r} is not valid")

    def _p(self, x: str) -> str:
        return f"veyra_{self.ns}-{x}" if self.ns else f"veyra-{x}"

    # Contexts owned by the organization.
    @property
    def internal(self) -> str:
        return self._p("internal")

    @property
    def features(self) -> str:
        return self._p("features")

    def voicemail_exit(self, number: str) -> str:
        """Where 0 and * go during a box's greeting (docs/CALL_FEATURES.md §3.7)."""
        return self._p(f"vmx-{number}")

    @property
    def intercom(self) -> str:
        """Intercom targets of the namespace (docs/CALL_FEATURES.md §3.6)."""
        return self._p("intercom")

    @property
    def follow_me_confirm(self) -> str:
        """The press-1 routine of follow-me legs (docs/CALL_FEATURES.md §3.4)."""
        return self._p("fm-confirm")

    @property
    def intercom_headers(self) -> str:
        """Adds the auto-answer headers on an intercom leg (docs/CALL_FEATURES.md §3.6)."""
        return self._p("intercom-hdr")

    @property
    def follow_me_out(self) -> str:
        """Outside legs of find me / follow me (docs/CALL_FEATURES.md §3.4)."""
        return self._p("fm-out")

    @property
    def paging(self) -> str:
        return self._p("paging")

    @property
    def page_play(self) -> str:
        return self._p("page-play")

    @property
    def outbound(self) -> str:
        return self._p("outbound")

    def ivr(self, slug: str) -> str:
        return self._p(f"ivr-{slug}")

    def ring_group(self, slug: str) -> str:
        return self._p(f"rg-{slug}")

    def queue_context(self, slug: str) -> str:
        return self._p(f"queue-{slug}")

    def announcement(self, slug: str) -> str:
        """Plays a prompt, then goes on (docs/CALL_FEATURES.md §4.1)."""
        return self._p(f"ann-{slug}")

    def conference(self, slug: str) -> str:
        """Context of a conference room; also the stem of its ConfBridge
        profile names (docs/CALL_FEATURES.md §4.3)."""
        return self._p(f"conf-{slug}")

    def call_flow(self, slug: str) -> str:
        """A day/night switch's routing context (docs/CALL_FEATURES.md §4.5)."""
        return self._p(f"flow-{slug}")

    def parking(self, slug: str) -> str:
        """A parking lot's context, filled by res_parking (docs/CALL_FEATURES.md §4.7)."""
        return self._p(f"park-{slug}")

    def parking_timeout(self, slug: str) -> str:
        """Where a parked call goes when its time is up."""
        return self._p(f"park-{slug}-timeout")

    @property
    def directory(self) -> str:
        """Dial-by-name directory of the namespace (docs/CALL_FEATURES.md §4.2)."""
        return self._p("directory")

    # Other engine objects.
    @property
    def voicemail(self) -> str:
        return f"veyra_{self.ns}" if self.ns else "veyra"

    def queue(self, slug: str) -> str:
        return self._p(slug)

    def moh_class(self, slug: str) -> str:
        return self._p(slug)

    def moh_dir(self, slug: str) -> str:
        """The folder of a hold music set below the hold music directory."""
        return f"{self.ns}_{slug}" if self.ns else slug

    def pickup_group(self, slug: str) -> str:
        return f"{self.ns}_{slug}" if self.ns else slug

    def queue_key(self, slug: str) -> str:
        """How the queue log rows name the queue (its slug, or ``<ns>_<slug>``)."""
        return f"{self.ns}_{slug}" if self.ns else slug

    def owns_context(self, name: str) -> bool:
        if self.ns:
            return name.startswith(f"veyra_{self.ns}-")
        return (
            name.startswith("veyra-")
            and name not in SHARED_CONTEXTS
            and not any(name.startswith(p) for p in SHARED_CONTEXT_PREFIXES)
        )


# Contexts every organization may reach (docs/MULTI_TENANCY.md §5).
SHARED_CONTEXTS = frozenset({"veyra-invalid", "veyra-record", "veyra-from-trunk"})
SHARED_CONTEXT_PREFIXES = ("veyra-out-", "veyra-from-trunk-")

_current: ContextVar[Names | None] = ContextVar("veyra_engine_names", default=None)


def current() -> Names:
    """The names of the organization being generated (legacy by default)."""
    return _current.get() or Names()


@contextmanager
def using(names: Names) -> Iterator[Names]:
    token = _current.set(names)
    try:
        yield names
    finally:
        _current.reset(token)


def namespace_for(slug: str, taken: set[str]) -> str:
    """A new organization's namespace: the slug's letters and digits,
    shortened, made unique; never the empty (legacy) namespace."""
    base = re.sub(r"[^a-z0-9]", "", slug.lower())[:12] or "org"
    candidate = base
    n = 2
    while candidate in taken or candidate == LEGACY:
        suffix = str(n)
        candidate = base[: 16 - len(suffix)] + suffix
        n += 1
    return candidate


_ns_by_org: ContextVar[dict[str, str] | None] = ContextVar("veyra_engine_namespaces", default=None)


def for_org(org_slug: str) -> Names:
    """The names of an organization (by slug) in the generation under way."""
    return Names((_ns_by_org.get() or {}).get(org_slug, LEGACY))


@contextmanager
def namespaces(mapping: dict[str, str]) -> Iterator[None]:
    token = _ns_by_org.set(dict(mapping))
    try:
        yield
    finally:
        _ns_by_org.reset(token)


_GROUP_CONTEXT = re.compile(r"^veyra(?:_([a-z0-9]{1,16}))?-(queue|rg)-(.+)$")
_QUEUE_NAME = re.compile(r"^veyra(?:_([a-z0-9]{1,16}))?-(.+)$")


def group_of_context(context: str, kind: str) -> str | None:
    """The slug of a queue (``kind`` ``queue``) or ring group (``rg``) context,
    in any namespace."""
    m = _GROUP_CONTEXT.match(context)
    return m.group(3) if m and m.group(2) == kind else None


def queue_key_of(name: str) -> str | None:
    """The queue log key of an engine queue name, or None for foreign queues."""
    m = _QUEUE_NAME.match(name)
    if not m:
        return None
    return Names(m.group(1) or LEGACY).queue_key(m.group(2))
