# SPDX-License-Identifier: AGPL-3.0-or-later
"""Node-local HA state (docs/HIGH_AVAILABILITY.md §3, §11): ``node.json`` is
what this node believes about itself and its peer, ``operation.json`` the
sequence that is running or last ran, ``sync.json`` the file sync's progress.

These files live in ``<data>/ha/`` and are written by the agent (root); the
API and the worker only read them. They exist so a node can decide its role
at boot before (and without) a database.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NODE_FILE = "node.json"
OPERATION_FILE = "operation.json"
SYNC_FILE = "sync.json"

ROLES = ("standalone", "primary", "secondary")
# What the node is doing within its role (``cluster_nodes.state`` mirrors it).
NODE_STATES = ("online", "joining", "rejoining", "diverged", "isolated", "frozen", "removed")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Peer:
    node_id: str
    node_name: str
    address: str
    url: str
    public_key: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Peer:
        return cls(
            node_id=str(d.get("node_id") or ""),
            node_name=str(d.get("node_name") or ""),
            address=str(d.get("address") or ""),
            url=str(d.get("url") or ""),
            public_key=str(d.get("public_key") or ""),
        )


@dataclass
class ServiceAddress:
    name: str = ""
    address: str = ""
    prefix: int = 24
    interface: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> ServiceAddress:
        d = d or {}
        return cls(
            name=str(d.get("name") or ""),
            address=str(d.get("address") or ""),
            prefix=int(d.get("prefix") or 24),
            interface=str(d.get("interface") or ""),
        )

    @property
    def configured(self) -> bool:
        return bool(self.address and self.interface)


@dataclass
class NodeState:
    node_id: str = ""
    node_name: str = ""
    address: str = ""
    role: str = "standalone"
    epoch: int = 0
    state: str = "online"
    peer: Peer | None = None
    service: ServiceAddress = field(default_factory=ServiceAddress)
    synchronous: bool = False
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NodeState:
        peer = d.get("peer")
        return cls(
            node_id=str(d.get("node_id") or ""),
            node_name=str(d.get("node_name") or ""),
            address=str(d.get("address") or ""),
            role=str(d.get("role") or "standalone"),
            epoch=int(d.get("epoch") or 0),
            state=str(d.get("state") or "online"),
            peer=Peer.from_dict(peer) if isinstance(peer, dict) else None,
            service=ServiceAddress.from_dict(d.get("service")),
            synchronous=bool(d.get("synchronous")),
            updated_at=str(d.get("updated_at") or ""),
        )

    @property
    def ha_enabled(self) -> bool:
        return self.role in ("primary", "secondary")


@dataclass
class Step:
    name: str
    status: str = "running"  # running | ok | failed | skipped
    started_at: str = field(default_factory=now_iso)
    finished_at: str | None = None
    detail: str = ""
    seconds: float | None = None


@dataclass
class Operation:
    """A switchover, failover, rejoin, enable or join sequence with its steps."""

    kind: str
    target: str = ""
    actor: str = ""
    status: str = "running"  # running | completed | aborted | failed
    started_at: str = field(default_factory=now_iso)
    finished_at: str | None = None
    error: str = ""
    steps: list[Step] = field(default_factory=list)
    _t0: float = field(default_factory=time.monotonic, repr=False, compare=False)

    def start_step(self, name: str, detail: str = "") -> Step:
        step = Step(name=name, detail=detail)
        step._t0 = time.monotonic()  # type: ignore[attr-defined]
        self.steps.append(step)
        return step

    def finish_step(self, step: Step, status: str = "ok", detail: str | None = None) -> None:
        step.status = status
        step.finished_at = now_iso()
        t0 = getattr(step, "_t0", None)
        step.seconds = round(time.monotonic() - t0, 3) if t0 is not None else None
        if detail is not None:
            step.detail = detail

    def finish(self, status: str, error: str = "") -> None:
        self.status = status
        self.error = error
        self.finished_at = now_iso()
        for step in self.steps:
            if step.status == "running":
                self.finish_step(step, "failed" if status != "completed" else "ok")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "actor": self.actor,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "steps": [
                {
                    "name": s.name,
                    "status": s.status,
                    "started_at": s.started_at,
                    "finished_at": s.finished_at,
                    "detail": s.detail,
                    "seconds": s.seconds,
                }
                for s in self.steps
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Operation:
        op = cls(
            kind=str(d.get("kind") or ""),
            target=str(d.get("target") or ""),
            actor=str(d.get("actor") or ""),
            status=str(d.get("status") or "running"),
            started_at=str(d.get("started_at") or ""),
            finished_at=d.get("finished_at"),
            error=str(d.get("error") or ""),
        )
        for s in d.get("steps") or []:
            if isinstance(s, dict):
                op.steps.append(
                    Step(
                        name=str(s.get("name") or ""),
                        status=str(s.get("status") or "ok"),
                        started_at=str(s.get("started_at") or ""),
                        finished_at=s.get("finished_at"),
                        detail=str(s.get("detail") or ""),
                        seconds=s.get("seconds"),
                    )
                )
        return op

    @property
    def running(self) -> bool:
        return self.status == "running"


@dataclass
class SyncState:
    last_success_at: str | None = None
    last_attempt_at: str | None = None
    last_error: str = ""
    backlog: int = 0
    transferred: int = 0
    manifest_at: float | None = None  # the primary's "since" cursor

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SyncState:
        return cls(
            last_success_at=d.get("last_success_at"),
            last_attempt_at=d.get("last_attempt_at"),
            last_error=str(d.get("last_error") or ""),
            backlog=int(d.get("backlog") or 0),
            transferred=int(d.get("transferred") or 0),
            manifest_at=d.get("manifest_at"),
        )


# ------------------------------------------------------------------ files


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, data: dict[str, Any], mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


class StateDir:
    """``<data>/ha``: the three state files."""

    def __init__(self, directory: Path) -> None:
        self.dir = directory

    @property
    def node_path(self) -> Path:
        return self.dir / NODE_FILE

    def node(self) -> NodeState | None:
        d = _read(self.node_path)
        return NodeState.from_dict(d) if d is not None else None

    def save_node(self, node: NodeState) -> None:
        node.updated_at = now_iso()
        _write(self.node_path, node.to_dict())

    def operation(self) -> Operation | None:
        d = _read(self.dir / OPERATION_FILE)
        return Operation.from_dict(d) if d is not None else None

    def save_operation(self, op: Operation) -> None:
        _write(self.dir / OPERATION_FILE, op.to_dict())

    def sync(self) -> SyncState:
        d = _read(self.dir / SYNC_FILE)
        return SyncState.from_dict(d) if d is not None else SyncState()

    def save_sync(self, s: SyncState) -> None:
        _write(self.dir / SYNC_FILE, s.to_dict())
