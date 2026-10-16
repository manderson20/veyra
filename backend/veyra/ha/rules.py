# SPDX-License-Identifier: AGPL-3.0-or-later
"""The decisions of docs/HIGH_AVAILABILITY.md §6 (switchover preconditions)
and §7.3 (what a node does at start and when its peer becomes reachable),
as pure functions so every combination is a unit test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# Decisions for a node that believes it is the primary.
RESUME = "resume"  # resume primary duties (database writable, engine, address)
DEMOTE = "demote"  # the peer moved on: release everything, rejoin as standby
ISOLATE = "isolate"  # peer unreachable: no primary duties until the operator says so
# Decisions for a secondary.
FOLLOW = "follow"  # keep replicating from the peer
WAIT = "wait"  # no primary known; stay a standby, never self-promote
# A node outside a cluster.
STANDALONE = "standalone"

MAX_CATCHUP_BYTES = 16 * 1024 * 1024
MAX_SYNC_AGE = timedelta(minutes=5)


@dataclass(frozen=True)
class PeerHealth:
    reachable: bool
    role: str | None = None
    epoch: int | None = None
    db_role: str | None = None
    version: str | None = None
    holds_address: bool = False
    detail: str = ""

    @classmethod
    def unreachable(cls, detail: str = "") -> PeerHealth:
        return cls(reachable=False, detail=detail)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PeerHealth:
        return cls(
            reachable=True,
            role=str(d.get("role") or "") or None,
            epoch=int(d["epoch"]) if d.get("epoch") is not None else None,
            db_role=str(d.get("db_role") or "") or None,
            version=str(d.get("version") or "") or None,
            holds_address=bool(d.get("holds_address")),
        )


def decide(local_role: str, local_epoch: int, peer: PeerHealth) -> tuple[str, str]:
    """(decision, reason) for a node with ``local_role`` and ``local_epoch``
    given what its peer answered (§7.3)."""
    if local_role not in ("primary", "secondary"):
        return STANDALONE, "not part of a cluster"
    if local_role == "secondary":
        if not peer.reachable:
            return WAIT, "the peer is unreachable; a standby never promotes itself"
        if peer.role == "primary":
            return FOLLOW, "the peer is the primary"
        return WAIT, f"the peer is {peer.role or 'unknown'}; no primary to follow"
    # primary
    if not peer.reachable:
        return ISOLATE, "the peer is unreachable; primary duties need the operator's confirmation"
    peer_epoch = peer.epoch if peer.epoch is not None else -1
    if peer_epoch > local_epoch:
        return DEMOTE, f"the peer is in epoch {peer_epoch}, this node stopped at {local_epoch}"
    if peer_epoch == local_epoch and peer.role == "primary":
        # Never by construction (a promotion raises the epoch); treated as stale.
        return DEMOTE, f"both nodes claim the primary role in epoch {local_epoch}"
    if peer_epoch < local_epoch:
        return RESUME, f"the peer is behind (epoch {peer_epoch}); it will rejoin"
    return RESUME, "the peer is the secondary of this epoch"


@dataclass(frozen=True)
class SwitchoverFacts:
    """What the preconditions look at."""

    local_role: str
    target_role: str
    target_online: bool
    local_version: str
    target_version: str | None
    replication_state: str | None  # streaming | catchup | None
    lag_bytes: int | None
    sync_age: timedelta | None
    operation_running: bool
    deployment_running: bool
    upgrade_running: bool
    frozen: bool


def switchover_problems(f: SwitchoverFacts) -> list[str]:
    problems: list[str] = []
    if f.local_role != "primary":
        problems.append("A switchover starts from the primary.")
    if f.target_role != "secondary":
        problems.append("The target is not a secondary.")
    if not f.target_online:
        problems.append("The target is not online.")
    if f.target_version is None or f.target_version != f.local_version:
        problems.append(
            f"The nodes run different versions ({f.local_version} here, "
            f"{f.target_version or 'unknown'} on the target)."
        )
    if f.replication_state != "streaming":
        problems.append(f"Replication is not streaming ({f.replication_state or 'no receiver'}).")
    if f.lag_bytes is None or f.lag_bytes > MAX_CATCHUP_BYTES:
        problems.append(
            "The standby is too far behind "
            f"({'unknown' if f.lag_bytes is None else f'{f.lag_bytes // (1024 * 1024)} MB'} "
            f"of WAL; at most {MAX_CATCHUP_BYTES // (1024 * 1024)} MB)."
        )
    if f.sync_age is None or f.sync_age > MAX_SYNC_AGE:
        problems.append("The file sync did not succeed in the last 5 minutes.")
    if f.operation_running:
        problems.append("Another HA operation is running.")
    if f.deployment_running:
        problems.append("A configuration deployment is in progress.")
    if f.upgrade_running:
        problems.append("A software upgrade is in progress.")
    if f.frozen:
        problems.append("The primary is frozen by a previous switchover; unfreeze it first.")
    return problems


def heartbeat_stale(last: datetime | None, now: datetime, after: timedelta) -> bool:
    return last is None or now - last > after
