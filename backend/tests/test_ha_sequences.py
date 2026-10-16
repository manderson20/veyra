# SPDX-License-Identifier: AGPL-3.0-or-later
"""The switchover, failover, rejoin, demote and resume sequences against a
fake node that records every call (docs/HIGH_AVAILABILITY.md §15), and the
agent's verbs against a fake system."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from veyra.ha import agent as agent_mod
from veyra.ha import peer, postgres, sequences
from veyra.ha.state import NodeState, Operation, Peer, ServiceAddress


class FakeNode:
    def __init__(self, role="secondary", epoch=3, *, peer_up=True, fence: str | None = None):
        self.role, self.epoch = role, epoch
        self.calls: list[str] = []
        self.peer_calls: list[tuple[str, dict]] = []
        self.ops: list[dict] = []
        self.in_recovery = role == "secondary"
        self.replay = 1000
        self.peer_fail: set[str] = set()
        self.peer_up = peer_up
        self.fence = fence
        self.events: list[tuple[str, dict]] = []
        self.frozen = None

    def save_operation(self, op):
        self.ops.append(op.to_dict())

    def local_role(self):
        return self.role

    def local_epoch(self):
        return self.epoch

    def local_name(self):
        return "dev2"

    def peer_name(self):
        return "dev1"

    def _c(self, name):
        self.calls.append(name)

    def engine_stop(self):
        self._c("engine_stop")

    def engine_start(self):
        self._c("engine_start")

    def postgres_stop(self):
        self._c("postgres_stop")

    def postgres_start(self):
        self._c("postgres_start")

    def postgres_in_recovery(self):
        return self.in_recovery

    def postgres_promote(self):
        self._c("promote")
        self.in_recovery = False

    def replay_lsn(self):
        return self.replay

    def hold_address(self):
        self._c("hold_address")

    def release_address(self):
        self._c("release_address")

    def rewind_or_basebackup(self):
        self._c("resync")
        return "rewind"

    def migrate(self):
        self._c("migrate")

    def deploy(self):
        self._c("deploy")

    def set_local_role(self, role, epoch, state):
        self.role, self.epoch = role, epoch
        self._c(f"role:{role}:{epoch}:{state}")

    def db_set_roles(self, primary, secondary, epoch, secondary_state):
        self._c(f"db_roles:{primary}:{secondary}:{epoch}:{secondary_state}")

    def db_set_frozen(self, frozen):
        self.frozen = frozen
        self._c(f"frozen:{frozen}")

    def db_event(self, event_type, details):
        self.events.append((event_type, details))

    def fence_peer(self):
        self._c("fence")
        return self.fence

    def sync_now(self):
        self._c("sync")

    def peer_run(self, verb, **args):
        self.peer_calls.append((verb, args))
        if verb in self.peer_fail:
            raise peer.PeerError(502, "unreachable", f"{verb} failed")
        if verb == "current-lsn":
            return {"lsn_bytes": 1000}
        return {}

    def peer_reachable(self):
        return self.peer_up


def test_switchover_happy_path():
    node = FakeNode()
    op = sequences.switchover(node, Operation(kind="switchover", target="dev2"), sleep=0)
    assert op.status == "completed", op.error
    assert [s.name for s in op.steps] == [
        "freeze",
        "engine-stop",
        "catch-up",
        "release-address",
        "postgres-stop",
        "promote",
        "epoch",
        "migrate",
        "deploy",
        "hold-address",
        "rejoin-peer",
        "unfreeze",
    ]
    assert all(s.status == "ok" for s in op.steps)
    assert [v for v, _ in node.peer_calls] == [
        "freeze",
        "engine-stop",
        "checkpoint",
        "current-lsn",
        "release-address",
        "postgres-stop",
        "rejoin",
    ]
    assert node.calls == [
        "promote",
        "role:primary:4:online",
        "db_roles:dev2:dev1:4:rejoining",
        "migrate",
        "engine_start",
        "deploy",
        "hold_address",
        "frozen:False",
    ]
    assert node.role == "primary" and node.epoch == 4
    assert [e for e, _ in node.events] == ["switchover_epoch", "switchover_completed"]
    # Every step was written as it started and ended.
    assert len(node.ops) >= 2 * len(op.steps)


def test_switchover_abort_before_promotion_puts_primary_back():
    node = FakeNode()
    node.peer_fail = {"postgres-stop"}
    op = sequences.switchover(node, Operation(kind="switchover"), sleep=0)
    assert op.status == "aborted" and "postgres-stop" in op.error
    assert node.calls == []  # never promoted
    verbs = [v for v, _ in node.peer_calls]
    assert verbs[-3:] == ["engine-start", "hold-address", "unfreeze"]
    assert node.role == "secondary" and node.epoch == 3
    assert op.steps[-1].name == "postgres-stop" and op.steps[-1].status == "failed"


def test_switchover_catch_up_timeout(monkeypatch):
    monkeypatch.setattr(sequences, "CATCHUP_TIMEOUT", 0.01)
    node = FakeNode()
    node.replay = 10  # behind the primary's 1000
    op = sequences.switchover(node, Operation(kind="switchover"), sleep=0)
    assert op.status == "aborted" and "catching up" in op.error
    assert "promote" not in node.calls


def test_switchover_failure_after_promotion_stays_primary():
    node = FakeNode()
    node.peer_fail = {"rejoin"}
    op = sequences.switchover(node, Operation(kind="switchover"), sleep=0)
    assert op.status == "failed" and "rejoin" in op.error
    assert node.role == "primary" and node.epoch == 4
    assert "hold_address" in node.calls
    assert [e for e, _ in node.events][-1] == "switchover_failed"
    # The failed step is the one that remains for the operator.
    assert op.steps[-1].name == "rejoin-peer" and op.steps[-1].status == "failed"


def test_switchover_refuses_on_primary():
    with pytest.raises(sequences.SequenceError):
        sequences.switchover(FakeNode(role="primary"), Operation(kind="switchover"))


def test_failover_with_and_without_fencing():
    node = FakeNode(peer_up=False, fence="Proxmox: VM 101 stopped")
    op = sequences.failover(node, Operation(kind="failover"), confirm_fenced=False, sleep=0)
    assert op.status == "completed", op.error
    assert op.steps[0].name == "fence" and "Proxmox" in op.steps[0].detail
    assert node.role == "primary" and node.epoch == 4
    assert "db_roles:dev2:dev1:4:unknown" in node.calls

    node = FakeNode(peer_up=False)
    op = sequences.failover(node, Operation(kind="failover"), confirm_fenced=False, sleep=0)
    assert op.status == "failed" and "did not confirm" in op.error
    assert "promote" not in node.calls

    node = FakeNode(peer_up=False)
    op = sequences.failover(node, Operation(kind="failover"), confirm_fenced=True, sleep=0)
    assert op.status == "completed" and "operator confirmed" in op.steps[0].detail

    with pytest.raises(sequences.SequenceError, match="use a switchover"):
        sequences.failover(FakeNode(peer_up=True), Operation(kind="failover"), confirm_fenced=True)


def test_rejoin_demote_resume():
    node = FakeNode(role="primary", epoch=3)
    op = sequences.demote(node, Operation(kind="demote"), peer_epoch=5)
    assert op.status == "completed", op.error
    assert node.calls[:3] == ["engine_stop", "release_address", "role:secondary:5:rejoining"]
    assert "resync" in node.calls and node.calls[-1] == "sync"
    assert node.role == "secondary" and node.epoch == 5

    node = FakeNode(role="primary", epoch=5)
    op = sequences.resume(node, Operation(kind="resume"))
    assert op.status == "completed"
    assert node.calls == [
        "postgres_start",
        "engine_start",
        "deploy",
        "hold_address",
        "role:primary:5:online",
        "frozen:False",
    ]
    assert node.events[-1][0] == "resumed"


# ------------------------------------------------------------------ the agent


class FakeSystem:
    """Records commands; answers what the agent needs."""

    def __init__(self, tmp: Path):
        self.calls: list[list[str]] = []
        self.held: set[str] = set()
        self.active: set[str] = {"asterisk"}
        self.recovery = "f"
        self.db_calls: list[tuple[str, dict]] = []
        self.veyra_bin = tmp / "veyra"

    def run(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        if argv[:3] == ["runuser", "-u", "postgres"]:
            stmt = argv[-1]
            if "pg_is_in_recovery" in stmt:
                return postgres.Result(0, self.recovery + "\n")
            if "pg_current_wal_lsn()::text, replay" in stmt or "pg_stat_replication" in stmt:
                return postgres.Result(0, "dev2\tstreaming\tasync\t0/2000\t0/1000\t0.2\n")
            if "pg_last_wal_receive_lsn" in stmt:
                return postgres.Result(0, "0/3000\t0/2800\t\tstreaming\tveyra_dev2\n")
            if "SELECT pg_current_wal_lsn()::text" in stmt or "replay_lsn()::text" in stmt:
                return postgres.Result(0, "0/5000\n")
            return postgres.Result(0, "")
        if argv[:2] == ["ip", "-j"]:
            return postgres.Result(
                0, json.dumps([{"addr_info": [{"local": a} for a in self.held]}])
            )
        if argv[:3] == ["ip", "addr", "add"]:
            self.held.add(argv[3].split("/")[0])
            return postgres.Result(0)
        if argv[:3] == ["ip", "addr", "del"]:
            self.held.discard(argv[3].split("/")[0])
            return postgres.Result(0)
        if argv[0] == "systemctl" and argv[1] == "is-active":
            return postgres.Result(0 if argv[-1] in self.active else 3)
        if argv[0] == "systemctl" and argv[1] in ("start", "stop"):
            for u in argv[2:]:
                (self.active.add if argv[1] == "start" else self.active.discard)(u)
            return postgres.Result(0)
        if argv[0] == "pg_ctlcluster" and argv[-1] == "promote":
            self.recovery = "f"
            return postgres.Result(0)
        return postgres.Result(0)

    # The System interface the agent uses for DB actions.
    def systemctl(self, verb, *units):
        return self.run(["systemctl", verb, *units])

    def unit_active(self, unit):
        return self.run(["systemctl", "is-active", "--quiet", unit]).ok

    def address_held(self, address, interface):
        return agent_mod.System.address_held(self, address, interface)  # type: ignore[arg-type]

    def address_add(self, address, prefix, interface):
        return self.run(["ip", "addr", "add", f"{address}/{prefix}", "dev", interface])

    def address_del(self, address, prefix, interface):
        return self.run(["ip", "addr", "del", f"{address}/{prefix}", "dev", interface])

    def arping(self, address, interface):
        return self.run(["arping", "-U", "-I", interface, address])

    def veyra_db(self, action, payload):
        self.db_calls.append((action, payload))
        if action == "deploy":
            return {"sequence": 7, "state": "deploying", "errors": []}
        if action == "deploy-state":
            return {"state": "deployed"}
        if action == "remove-node":
            return {"removed": True, "deployment_mode": "standalone"}
        return {"id": "node-id"}

    def veyra_migrate(self):
        return self.run(["veyra", "db", "upgrade"])


@pytest.fixture
def ha_agent(tmp_path: Path):
    system = FakeSystem(tmp_path)
    pg = postgres.Postgres(postgres.Cluster("18", "main", tmp_path / "pgdata"), system.run)
    (tmp_path / "pgdata").mkdir()
    paths = agent_mod.Paths(tmp_path / "data", tmp_path / "etc", tmp_path / "log")
    (paths.config_dir / "secrets").mkdir(parents=True)
    a = agent_mod.Agent(paths, system, pg)  # type: ignore[arg-type]
    a.sleep = lambda s: None
    a.state.dir.mkdir(parents=True)
    a.ensure_node_key()
    a.state.save_node(
        NodeState(
            node_id="n2",
            node_name="dev2",
            address="172.16.2.251",
            role="secondary",
            epoch=3,
            peer=Peer("n1", "dev1", "172.16.2.250", "https://dev1", "pk"),
            service=ServiceAddress("veyra", "172.16.2.10", 24, "eth0"),
        )
    )
    system.recovery = "t"
    system.active = set()
    return a, system


def call(a: agent_mod.Agent, verb: str, **args: Any) -> Any:
    out = json.loads(a.handle(json.dumps({"verb": verb, "args": args}).encode()))
    if not out["ok"]:
        raise agent_mod.AgentError(out["code"], out["error"])
    return out["result"]


def test_agent_status_and_guards(ha_agent):
    a, system = ha_agent
    st = call(a, "status")
    assert st["node"]["role"] == "secondary" and st["holds_address"] is False
    assert (
        st["replication"]["db_role"] == "standby" and st["replication"]["receiver"] == "streaming"
    )
    with pytest.raises(agent_mod.AgentError, match="standby never holds"):
        call(a, "hold-address")
    with pytest.raises(agent_mod.AgentError, match="does not run the engine"):
        call(a, "engine", action="start")
    with pytest.raises(agent_mod.AgentError, match="Unknown verb"):
        call(a, "reboot")
    assert call(a, "current-lsn") == {"lsn": "0/5000", "lsn_bytes": 0x5000}
    # A primary promotes nothing; a standby does.
    system.recovery = "f"
    with pytest.raises(agent_mod.AgentError, match="not in recovery"):
        a.postgres_promote()
    system.recovery = "t"
    a.postgres_promote()
    assert system.recovery == "f"
    # Holding the address on a primary adds it and announces it.
    call(a, "hold-address")
    assert "172.16.2.10" in system.held
    assert any(c[0] == "arping" for c in system.calls)
    assert call(a, "release-address") == {"holds_address": False}


def test_agent_failover_runs_in_background(ha_agent, monkeypatch):
    a, system = ha_agent
    monkeypatch.setattr(a, "probe_peer", lambda: agent_mod.PeerHealth.unreachable("down"))
    out = call(a, "failover", confirm_fenced=True, actor="admin")
    assert out["kind"] == "failover"
    a.op_thread.join(5)
    op = a.state.operation()
    assert op.status == "completed", op.error
    assert a.node().role == "primary" and a.node().epoch == 4
    actions = [x for x, _ in system.db_calls]
    assert "set-roles" in actions and "deploy" in actions and "set-frozen" in actions
    assert "172.16.2.10" in system.held and "asterisk" in system.active
    with pytest.raises(agent_mod.AgentError, match="runs on the standby"):
        call(a, "failover", confirm_fenced=True)


def test_agent_epoch_rules_on_tick(ha_agent, monkeypatch):
    a, system = ha_agent
    # This node believes it is primary in epoch 3; the peer is primary in 4.
    n = a.node()
    n.role, n.state = "primary", "online"
    a.state.save_node(n)
    system.recovery = "f"
    system.active = {"asterisk"}
    system.held = {"172.16.2.10"}
    monkeypatch.setattr(
        a, "probe_peer", lambda: agent_mod.PeerHealth(True, "primary", 4, "primary", "0.22.0")
    )
    a.tick()
    a.op_thread.join(5)
    assert a.state.operation().kind == "demote"
    assert a.node().role == "secondary" and a.node().epoch == 4
    assert "172.16.2.10" not in system.held and "asterisk" not in system.active
    # Isolated: peer unreachable at start → no primary duties.
    n = a.node()
    n.role, n.epoch, n.state = "primary", 5, "online"
    a.state.save_node(n)
    a.decided_once = False
    system.active = {"asterisk"}
    system.held = {"172.16.2.10"}
    monkeypatch.setattr(a, "probe_peer", lambda: agent_mod.PeerHealth.unreachable())
    a.tick()
    assert a.node().state == "isolated"
    assert "asterisk" not in system.active and not system.held
    # The peer comes back as our secondary of the same epoch → resume.
    monkeypatch.setattr(a, "probe_peer", lambda: agent_mod.PeerHealth(True, "secondary", 5))
    a.tick()
    a.op_thread.join(5)
    assert a.node().state == "online" and "asterisk" in system.active and system.held


def test_agent_sync_now_uses_peer_manifest(ha_agent, monkeypatch, tmp_path):
    a, system = ha_agent
    (a.paths.data_dir / "prompts").mkdir(parents=True)
    content = b"hello"
    import hashlib

    entries = [
        {
            "path": "data/prompts/x.wav",
            "size": 5,
            "mtime": 1.0,
            "mode": 0o640,
            "owner": "root",
            "group": "root",
            "digest": hashlib.sha256(content).hexdigest(),
        }
    ]
    monkeypatch.setattr(a, "peer_call", lambda verb, payload, timeout=0: {"entries": entries})

    class R:
        status_code = 200
        content = b"hello"

    monkeypatch.setattr(peer, "post", lambda *args, **kw: R())
    st = call(a, "sync-now")
    assert st["last_error"] == ""
    assert st["last_success_at"] and st["backlog"] == 0 and st["transferred"] == 1
    assert (a.paths.data_dir / "prompts/x.wav").read_bytes() == content
