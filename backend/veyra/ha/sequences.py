# SPDX-License-Identifier: AGPL-3.0-or-later
"""The role sequences (docs/HIGH_AVAILABILITY.md §5 to §8) as step lists over a
:class:`Node` interface: the agent implements it with real commands, the
tests with a fake that records calls. Every step is written to the
operation file as it starts and ends, so the page shows what is happening
and, after an abort, what remains.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

from veyra.ha.state import Operation

log = logging.getLogger("veyra.ha")

CATCHUP_TIMEOUT = 60.0
PROMOTE_TIMEOUT = 60.0
DEPLOY_TIMEOUT = 120.0


class SequenceError(Exception):
    pass


class Node(Protocol):
    """What a sequence may do on the node it runs on, and ask of the peer."""

    # --- node-local
    def save_operation(self, op: Operation) -> None: ...
    def local_role(self) -> str: ...
    def local_epoch(self) -> int: ...
    def engine_stop(self) -> None: ...
    def engine_start(self) -> None: ...
    def postgres_stop(self) -> None: ...
    def postgres_start(self) -> None: ...
    def postgres_in_recovery(self) -> bool | None: ...
    def postgres_promote(self) -> None: ...
    def replay_lsn(self) -> int | None: ...
    def hold_address(self) -> None: ...
    def release_address(self) -> None: ...
    def rewind_or_basebackup(self) -> str: ...  # returns "rewind" or "basebackup"
    def migrate(self) -> None: ...
    def deploy(self) -> None: ...
    def set_local_role(self, role: str, epoch: int, state: str) -> None: ...
    def db_set_roles(
        self, primary: str, secondary: str, epoch: int, secondary_state: str
    ) -> None: ...
    def db_set_frozen(self, frozen: bool) -> None: ...
    def db_event(self, event_type: str, details: dict[str, Any]) -> None: ...
    def fence_peer(self) -> str | None: ...  # None when no fencing is configured
    def sync_now(self) -> None: ...
    def local_name(self) -> str: ...
    def peer_name(self) -> str: ...
    # --- on the peer (node calls); raise PeerError when it fails
    def peer_run(self, verb: str, **args: Any) -> dict[str, Any]: ...
    def peer_reachable(self) -> bool: ...


def _step(node: Node, op: Operation, name: str, fn: Callable[[], Any], detail: str = "") -> Any:
    step = op.start_step(name, detail)
    node.save_operation(op)
    try:
        result = fn()
    except Exception as e:
        op.finish_step(step, "failed", f"{detail} {e}".strip())
        node.save_operation(op)
        raise
    if isinstance(result, str) and result:
        op.finish_step(step, "ok", result)
    else:
        op.finish_step(step, "ok")
    node.save_operation(op)
    return result


def _wait(predicate: Callable[[], bool], timeout: float, what: str, sleep: float = 0.5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(sleep)
    raise SequenceError(f"{what} did not happen within {int(timeout)} seconds")


# ------------------------------------------------------------------ switchover


def switchover(node: Node, op: Operation, *, sleep: float = 0.5) -> Operation:
    """§6, running on the *target* (the secondary that becomes primary).
    ``node`` is the target; the peer is the current primary."""
    if node.local_role() != "secondary":
        raise SequenceError("a switchover runs on the secondary that takes over")
    old_epoch = node.local_epoch()
    new_epoch = old_epoch + 1
    primary_frozen = False
    engine_stopped = False
    try:
        _step(node, op, "freeze", lambda: node.peer_run("freeze"), "the primary refuses writes")
        primary_frozen = True
        _step(node, op, "engine-stop", lambda: node.peer_run("engine-stop"), "calls end")
        engine_stopped = True

        def catch_up() -> str:
            node.peer_run("checkpoint")
            target = int(node.peer_run("current-lsn").get("lsn_bytes") or 0)

            def caught() -> bool:
                mine = node.replay_lsn()
                return mine is not None and mine >= target

            _wait(caught, CATCHUP_TIMEOUT, "the standby catching up", sleep)
            return f"replayed to {target}"

        _step(node, op, "catch-up", catch_up)
        _step(node, op, "release-address", lambda: node.peer_run("release-address"))
        _step(node, op, "postgres-stop", lambda: node.peer_run("postgres-stop"), "no writer exists")
    except Exception as e:
        # Before promotion: put A back.
        op.finish("aborted", str(e))
        node.save_operation(op)
        _rollback(node, primary_frozen, engine_stopped)
        return op
    try:

        def promote() -> None:
            node.postgres_promote()
            _wait(
                lambda: node.postgres_in_recovery() is False,
                PROMOTE_TIMEOUT,
                "the promotion",
                sleep,
            )

        _step(node, op, "promote", promote)
        _step(node, op, "epoch", lambda: _take_epoch(node, new_epoch, "switchover"))
        _step(node, op, "migrate", node.migrate, "schema at the new primary's version")
        _step(node, op, "deploy", lambda: _deploy_and_start(node))
        _step(node, op, "hold-address", node.hold_address, "gratuitous ARP")
        _step(node, op, "rejoin-peer", lambda: node.peer_run("rejoin"), "pg_rewind or base backup")
        _step(node, op, "unfreeze", lambda: node.db_set_frozen(False))
        op.finish("completed")
        node.db_event(
            "switchover_completed",
            {"target": node.local_name(), "epoch": new_epoch, "steps": op.to_dict()["steps"]},
        )
    except Exception as e:
        # After promotion there is no way back: this node is the primary; the
        # operator sees what remains (typically the peer's rejoin).
        op.finish("failed", str(e))
        node.db_event("switchover_failed", {"error": str(e), "steps": op.to_dict()["steps"]})
    node.save_operation(op)
    return op


def _rollback(node: Node, frozen: bool, engine_stopped: bool) -> None:
    try:
        if engine_stopped:
            node.peer_run("engine-start")
        node.peer_run("hold-address")
        if frozen:
            node.peer_run("unfreeze")
    except Exception:
        log.exception("Could not put the primary back after the abort")


def _take_epoch(node: Node, epoch: int, how: str) -> None:
    node.set_local_role("primary", epoch, "online")
    node.db_set_roles(
        node.local_name(),
        node.peer_name(),
        epoch,
        "rejoining" if how == "switchover" else "unknown",
    )
    node.db_event(f"{how}_epoch", {"epoch": epoch, "primary": node.local_name()})


def _deploy_and_start(node: Node) -> None:
    node.deploy()
    node.engine_start()


# ------------------------------------------------------------------ failover


def failover(node: Node, op: Operation, *, confirm_fenced: bool, sleep: float = 0.5) -> Operation:
    """§7.1, on the standby, the primary being down."""
    if node.local_role() != "secondary":
        raise SequenceError("a failover runs on the standby")
    if node.peer_reachable():
        raise SequenceError("the primary answers; use a switchover")
    new_epoch = node.local_epoch() + 1
    try:

        def fence() -> str:
            result = node.fence_peer()
            if result is None:
                if not confirm_fenced:
                    raise SequenceError("no fencing is configured and the operator did not confirm")
                return "operator confirmed the primary is off"
            return result

        _step(node, op, "fence", fence)

        def promote() -> None:
            node.postgres_promote()
            _wait(
                lambda: node.postgres_in_recovery() is False,
                PROMOTE_TIMEOUT,
                "the promotion",
                sleep,
            )

        _step(node, op, "promote", promote)
        _step(node, op, "epoch", lambda: _take_epoch(node, new_epoch, "failover"))
        _step(node, op, "migrate", node.migrate)
        _step(node, op, "deploy", lambda: _deploy_and_start(node))
        _step(node, op, "hold-address", node.hold_address)
        _step(node, op, "unfreeze", lambda: node.db_set_frozen(False))
        op.finish("completed")
        node.db_event(
            "failover_completed",
            {"primary": node.local_name(), "epoch": new_epoch, "steps": op.to_dict()["steps"]},
        )
    except Exception as e:
        op.finish("failed", str(e))
        try:
            node.db_event("ha_operation_failed", {"kind": "failover", "error": str(e)})
        except Exception:
            log.exception("Could not record the failed failover")
    node.save_operation(op)
    return op


# ------------------------------------------------------------------ rejoin, demote, resume


def rejoin(node: Node, op: Operation, *, peer_epoch: int) -> Operation:
    """§8: become (again) the standby of the peer, by ``pg_rewind`` or a
    fresh base backup."""
    try:
        _step(node, op, "engine-stop", node.engine_stop)
        _step(node, op, "release-address", node.release_address)
        _step(node, op, "postgres-stop", node.postgres_stop)
        _step(node, op, "resync", node.rewind_or_basebackup)
        _step(node, op, "postgres-start", node.postgres_start)
        _step(
            node,
            op,
            "role",
            lambda: node.set_local_role("secondary", peer_epoch, "online"),
            f"secondary, epoch {peer_epoch}",
        )
        _step(node, op, "sync", node.sync_now, "first file sync from the new primary")
        op.finish("completed")
    except Exception as e:
        op.finish("failed", str(e))
        node.set_local_role("secondary", peer_epoch, "diverged")
    node.save_operation(op)
    return op


def demote(node: Node, op: Operation, *, peer_epoch: int) -> Operation:
    """§7.3: this node is stale; give everything up, then rejoin."""
    s = op.start_step("demote", f"the peer is in epoch {peer_epoch}")
    node.save_operation(op)
    node.engine_stop()
    node.release_address()
    node.set_local_role("secondary", peer_epoch, "rejoining")
    op.finish_step(s)
    return rejoin(node, op, peer_epoch=peer_epoch)


def resume(node: Node, op: Operation) -> Operation:
    """§7.3: resume primary duties after a boot with the peer unreachable,
    on the operator's word, or at once when the peer agrees."""
    try:
        _step(node, op, "postgres-start", node.postgres_start)
        _step(node, op, "deploy", lambda: _deploy_and_start(node))
        _step(node, op, "hold-address", node.hold_address)
        _step(
            node,
            op,
            "role",
            lambda: node.set_local_role("primary", node.local_epoch(), "online"),
        )
        _step(node, op, "unfreeze", lambda: node.db_set_frozen(False))
        op.finish("completed")
        node.db_event("resumed", {"primary": node.local_name(), "epoch": node.local_epoch()})
    except Exception as e:
        op.finish("failed", str(e))
    node.save_operation(op)
    return op
