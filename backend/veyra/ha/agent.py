# SPDX-License-Identifier: AGPL-3.0-or-later
"""``veyra-ha-agent`` (docs/HIGH_AVAILABILITY.md §3): the root service on
each node. It listens on ``/run/veyra/ha.sock`` for the fixed list of verbs,
holds or releases the service address, runs the role sequences, polls the
peer every 10 s and, on a secondary, pulls the file sync every 30 s.

Everything that touches the system goes through :class:`System` so the
agent can run under a fake in tests. Database writes go through
``veyra ha db <action>`` as the service account.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import secrets
import shutil
import socket
import socketserver
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from veyra import __version__
from veyra.central import protocol
from veyra.ha import certs, join, peer, postgres, public_cert, rules, sequences, sync
from veyra.ha.client import SOCKET_PATH
from veyra.ha.postgres import Result, Runner
from veyra.ha.rules import PeerHealth
from veyra.ha.state import NodeState, Operation, Peer, ServiceAddress, StateDir, SyncState, now_iso

log = logging.getLogger("veyra.ha.agent")

POLL_SECONDS = 10.0
SYNC_SECONDS = 30.0
REPORT_SECONDS = 30.0
ENGINE_UNITS = ("asterisk", "veyra-pager", "veyra-deployer")
NODE_KEY = "secrets/node.key"
REPLICATION_PASSWORD = "secrets/replication_password"  # noqa: S105 - a path


class AgentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


# ------------------------------------------------------------------ the system


@dataclass
class System:
    """Commands the agent runs; replaced by a fake in tests."""

    run: Runner
    veyra_bin: Path

    def systemctl(self, verb: str, *units: str) -> Result:
        return self.run(["systemctl", verb, *units])

    def unit_active(self, unit: str) -> bool:
        return self.run(["systemctl", "is-active", "--quiet", unit]).ok

    def address_held(self, address: str, interface: str) -> bool:
        r = self.run(["ip", "-j", "addr", "show", "dev", interface])
        if not r.ok:
            return False
        try:
            data = json.loads(r.stdout or "[]")
        except ValueError:
            return False
        for link in data:
            for info in link.get("addr_info", []):
                if info.get("local") == address:
                    return True
        return False

    def interface_for(self, address: str) -> str | None:
        """The interface that carries ``address`` on this node."""
        r = self.run(["ip", "-j", "addr", "show"])
        if not r.ok:
            return None
        try:
            data = json.loads(r.stdout or "[]")
        except ValueError:
            return None
        for link in data:
            for info in link.get("addr_info", []):
                if info.get("local") == address:
                    return str(link.get("ifname") or "") or None
        return None

    def address_add(self, address: str, prefix: int, interface: str) -> Result:
        return self.run(
            [
                "ip",
                "addr",
                "add",
                f"{address}/{prefix}",
                "dev",
                interface,
                "label",
                f"{interface}:veyra",
            ]
        )

    def address_del(self, address: str, prefix: int, interface: str) -> Result:
        return self.run(["ip", "addr", "del", f"{address}/{prefix}", "dev", interface])

    def arping(self, address: str, interface: str) -> Result:
        return self.run(["arping", "-U", "-c", "3", "-w", "3", "-I", interface, address])

    def veyra_db(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        r = self.run(
            [
                "runuser",
                "-u",
                "veyra",
                "--",
                str(self.veyra_bin),
                "ha",
                "db",
                action,
                "--json",
                json.dumps(payload, separators=(",", ":")),
            ]
        )
        if not r.ok:
            raise AgentError(
                "db_action_failed", f"{action}: {(r.stderr or r.stdout).strip()[:500]}"
            )
        try:
            out = json.loads(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "{}")
        except ValueError:
            out = {}
        return out if isinstance(out, dict) else {}

    def veyra_migrate(self) -> Result:
        return self.run(["runuser", "-u", "veyra", "--", str(self.veyra_bin), "db", "upgrade"])


def default_system() -> System:
    # The wrapper sources veyra.env and runs as the service account; the venv
    # binary is the fallback for a checkout without an installation.
    wrapper = Path("/usr/local/bin/veyra")
    return System(
        postgres.subprocess_runner(),
        wrapper if wrapper.exists() else Path(sys.executable).parent / "veyra",
    )


VERBS: dict[str, str] = {
    "status": "verb_status",
    "enable": "verb_enable",
    "make-bundle": "verb_make_bundle",
    "join-prepare": "verb_join_prepare",
    "switchover": "verb_switchover",
    "failover": "verb_failover",
    "rejoin": "verb_rejoin",
    "demote": "verb_demote",
    "resume": "verb_resume",
    "freeze": "verb_freeze",
    "unfreeze": "verb_unfreeze",
    "engine": "verb_engine",
    "engine-stop": "verb_engine_stop",
    "engine-start": "verb_engine_start",
    "postgres": "verb_postgres",
    "postgres-stop": "verb_postgres_stop",
    "postgres-start": "verb_postgres_start",
    "checkpoint": "verb_checkpoint",
    "current-lsn": "verb_current_lsn",
    "hold-address": "verb_hold_address",
    "release-address": "verb_release_address",
    "sync-now": "verb_sync_now",
    "set-sync": "verb_set_sync",
    "set-fencing": "verb_set_fencing",
    "fence": "verb_fence",
    "set-synchronous": "verb_set_synchronous",
    "set-peer-epoch": "verb_set_peer_epoch",
    "remove-peer": "verb_remove_peer",
    "remove-node": "verb_remove_node",
    "standalone": "verb_standalone",
    "upgrade": "verb_upgrade",
    "event": "verb_event",
    "manifest-etc": "verb_manifest_etc",
    "read-file": "verb_read_file",
}


# ------------------------------------------------------------------ the agent


@dataclass
class Paths:
    data_dir: Path
    config_dir: Path
    log_dir: Path
    database: str = "veyra"

    @property
    def state(self) -> Path:
        return self.data_dir / "ha"

    @property
    def tls(self) -> Path:
        return self.config_dir / "tls"

    @property
    def node_key(self) -> Path:
        return self.config_dir / NODE_KEY

    @property
    def replication_password(self) -> Path:
        return self.config_dir / REPLICATION_PASSWORD

    @property
    def ca_crt(self) -> Path:
        return self.tls / "ca.crt"

    @property
    def pg_tls(self) -> Path:
        """Copies of the CA and the node's PostgreSQL certificate that the
        ``postgres`` user can read (``/etc/veyra/tls`` is root-only)."""
        return Path("/var/lib/postgresql/veyra-tls")

    @property
    def pg_ca(self) -> Path:
        return self.pg_tls / "ca.crt"


@dataclass
class Agent:
    paths: Paths
    system: System
    pg: postgres.Postgres | None
    state: StateDir = field(init=False)
    lock: threading.RLock = field(default_factory=threading.RLock)
    op_thread: threading.Thread | None = None
    last_peer: PeerHealth | None = None
    last_sync: float = -1e9
    last_report: float = -1e9
    decided_once: bool = False
    digest_cache: dict[str, tuple[float, int, str]] = field(default_factory=dict)
    sleep: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        self.state = StateDir(self.paths.state)

    # --- identity

    def node(self) -> NodeState:
        n = self.state.node()
        if n is None:
            n = NodeState(node_name=socket.gethostname())
        return n

    def private_key(self) -> str:
        return self.paths.node_key.read_text().strip()

    def ensure_node_key(self) -> str:
        """The node's Ed25519 key, created on first use; returns the public key."""
        if not self.paths.node_key.exists():
            priv, _pub = protocol.new_keypair()
            self.paths.node_key.parent.mkdir(parents=True, exist_ok=True)
            self.paths.node_key.write_text(priv + "\n")
        priv = self.private_key()
        # root:veyra 0640 like the installation key: the API signs with it too.
        os.chmod(self.paths.node_key, 0o640)
        with contextlib.suppress(KeyError, PermissionError, OSError):
            import grp

            os.chown(self.paths.node_key, 0, grp.getgrnam("veyra").gr_gid)
        return base64.b64encode(
            protocol.load_private_key(priv).public_key().public_bytes_raw()
        ).decode()

    def ca_pem(self) -> str | None:
        try:
            return self.paths.ca_crt.read_text()
        except OSError:
            return None

    def replication_password(self) -> str:
        return self.paths.replication_password.read_text().strip()

    # --- peer channel

    def peer_call(
        self, verb: str, payload: dict[str, Any], timeout: float = peer.CALL_TIMEOUT
    ) -> dict[str, Any]:
        n = self.node()
        if n.peer is None:
            raise AgentError("no_peer", "This node has no peer.")
        return peer.call(
            n.peer.url,
            verb,
            payload,
            node_id=n.node_id,
            private_key=self.private_key(),
            peer_public_key=n.peer.public_key,
            ca_pem=self.ca_pem(),
            timeout=timeout,
        )

    def probe_peer(self) -> PeerHealth:
        try:
            data = self.peer_call("health", {}, timeout=peer.HEALTH_TIMEOUT)
        except (peer.PeerError, AgentError, OSError) as e:
            return PeerHealth.unreachable(str(e))
        return PeerHealth.from_dict(data)

    # --- local facts

    def holds_address(self) -> bool:
        s = self.node().service
        return s.configured and self.system.address_held(s.address, s.interface)

    def replication(self) -> dict[str, Any]:
        if self.pg is None:
            return postgres.Replication(db_role="down", detail="no cluster").to_dict()
        n = self.node()
        slot = postgres.slot_name(n.peer.node_name) if n.peer else None
        return self.pg.replication(slot).to_dict()

    def status(self) -> dict[str, Any]:
        n = self.node()
        op = self.state.operation()
        return {
            "node": n.to_dict(),
            "version": __version__,
            "holds_address": self.holds_address(),
            "replication": self.replication(),
            "sync": self.state.sync().to_dict(),
            "operation": op.to_dict() if op else None,
            "peer_reachable": self.last_peer.reachable if self.last_peer else None,
            "peer": {
                "role": self.last_peer.role,
                "epoch": self.last_peer.epoch,
                "version": self.last_peer.version,
                "detail": self.last_peer.detail,
            }
            if self.last_peer
            else None,
            "engine_running": self.system.unit_active("asterisk"),
            "busy": self.busy,
        }

    @property
    def busy(self) -> bool:
        return self.op_thread is not None and self.op_thread.is_alive()

    # ------------------------------------------------------------ Node interface

    def save_operation(self, op: Operation) -> None:
        self.state.save_operation(op)

    def local_role(self) -> str:
        return self.node().role

    def local_epoch(self) -> int:
        return self.node().epoch

    def local_name(self) -> str:
        return self.node().node_name

    def peer_name(self) -> str:
        n = self.node()
        return n.peer.node_name if n.peer else ""

    def engine_stop(self) -> None:
        self.system.systemctl("stop", *ENGINE_UNITS)

    def engine_start(self) -> None:
        r = self.system.systemctl("start", *ENGINE_UNITS)
        if not r.ok:
            raise AgentError("engine_start_failed", r.stderr.strip()[:300])

    def postgres_stop(self) -> None:
        if self.pg:
            self.pg.stop()

    def postgres_start(self) -> None:
        if self.pg:
            r = self.pg.start()
            if not r.ok:
                raise AgentError("postgres_start_failed", r.stderr.strip()[:300])

    def postgres_in_recovery(self) -> bool | None:
        return self.pg.in_recovery() if self.pg else None

    def postgres_promote(self) -> None:
        if self.pg is None:
            raise AgentError("no_cluster", "No PostgreSQL cluster.")
        if self.pg.in_recovery() is not True:
            raise AgentError("not_standby", "The database is not in recovery; nothing to promote.")
        r = self.pg.promote()
        if not r.ok:
            raise AgentError("promote_failed", r.stderr.strip()[:300])
        self.pg.clear_standby()

    def replay_lsn(self) -> int | None:
        if self.pg is None:
            return None
        return postgres.parse_lsn(self.pg.current_lsn())

    def hold_address(self) -> None:
        s = self.node().service
        if not s.configured:
            return
        if self.pg and self.pg.in_recovery():
            raise AgentError("in_recovery", "A standby never holds the service address.")
        if not self.system.address_held(s.address, s.interface):
            r = self.system.address_add(s.address, s.prefix, s.interface)
            if not r.ok and "exists" not in r.stderr.lower():
                raise AgentError("address_failed", r.stderr.strip()[:300])
        self.system.arping(s.address, s.interface)
        self._report_soon()

    def release_address(self) -> None:
        s = self.node().service
        if s.configured and self.system.address_held(s.address, s.interface):
            self.system.address_del(s.address, s.prefix, s.interface)
        self._report_soon()

    def rewind_or_basebackup(self) -> str:
        n = self.node()
        if self.pg is None or n.peer is None:
            raise AgentError("no_peer", "No peer to rejoin.")
        password = self.replication_password()
        slot = postgres.slot_name(n.node_name)
        self._install_pg_tls()
        ca = str(self.paths.pg_ca)
        r = self.pg.rewind(n.peer.address, password, ca)
        if r.ok:
            self.pg.write_standby(n.peer.address, password, ca, slot)
            return "rewind"
        log.warning("pg_rewind failed (%s); taking a fresh base backup", r.stderr.strip()[:200])
        r = self.pg.basebackup(n.peer.address, password, ca, slot)
        if not r.ok:
            raise AgentError("basebackup_failed", r.stderr.strip()[:400])
        return "basebackup"

    def migrate(self) -> None:
        r = self.system.veyra_migrate()
        if not r.ok:
            raise AgentError("migrate_failed", (r.stderr or r.stdout).strip()[:400])

    def deploy(self) -> None:
        out = self.system.veyra_db("deploy", {})
        if out.get("state") not in ("deploying", "validated", "deployed"):
            raise AgentError(
                "deploy_failed", f"revision {out.get('sequence')}: {out.get('errors')}"
            )
        self.system.systemctl("start", "veyra-deployer")
        seq = out.get("sequence")
        deadline = time.monotonic() + sequences.DEPLOY_TIMEOUT
        while time.monotonic() < deadline:
            st = self.system.veyra_db("deploy-state", {"sequence": seq}).get("state")
            if st in ("deployed", "validated"):
                return
            if st in ("failed", "rolled_back", "missing"):
                raise AgentError("deploy_failed", f"revision {seq} is {st}")
            self.sleep(1.0)
        raise AgentError("deploy_timeout", f"revision {seq} was not deployed in time")

    def set_local_role(self, role: str, epoch: int, state: str) -> None:
        n = self.node()
        n.role, n.epoch, n.state = role, epoch, state
        self.state.save_node(n)

    def db_set_roles(self, primary: str, secondary: str, epoch: int, secondary_state: str) -> None:
        self.system.veyra_db(
            "set-roles",
            {
                "primary": primary,
                "secondary": secondary,
                "epoch": epoch,
                "secondary_state": secondary_state,
            },
        )

    def db_set_frozen(self, frozen: bool) -> None:
        self.system.veyra_db("set-frozen", {"frozen": frozen})

    def db_event(self, event_type: str, details: dict[str, Any]) -> None:
        with contextlib.suppress(AgentError):
            self.system.veyra_db(
                "event",
                {"event_type": event_type, "details": details, "node_name": self.local_name()},
            )

    def fence_peer(self) -> str | None:
        from veyra.ha import fencing

        cfg = self.fencing_config()
        if cfg is None:
            return None
        target = fencing.settings_to_target(cfg, self.peer_name(), str(cfg.get("secret") or ""))
        if target is None:
            return None
        try:
            result = fencing.stop_vm(target)
        except fencing.FencingError as e:
            raise AgentError("fence_failed", str(e)) from e
        self.db_event("fenced", {"node": self.peer_name(), "result": result})
        return f"Proxmox: VM {target.vmid} {result}"

    def fencing_config(self) -> dict[str, Any] | None:
        """The decrypted fencing settings, cached in the state directory by
        the API when they are saved (a standby cannot read the key's
        purpose-bound secret from a replica? it can: the table replicates)."""
        path = self.paths.state / "fencing.json"
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and data.get("enabled") else None

    def sync_now(self) -> None:
        self.run_sync(force=True)

    def ensure_peer_slot(self) -> None:
        """The replication slot the peer will stream from once it rejoins."""
        n = self.node()
        if self.pg and n.peer:
            r = self.pg.ensure_slot(postgres.slot_name(n.peer.node_name))
            if not r.ok:
                raise AgentError("slot_failed", r.stderr.strip()[:300])

    def peer_run(self, verb: str, **args: Any) -> dict[str, Any]:
        """Ask the peer's agent for a verb; returns the verb's result."""
        answer = self.peer_call("run", {"verb": verb, "args": args})
        result = answer.get("result")
        return result if isinstance(result, dict) else answer

    def peer_reachable(self) -> bool:
        return self.probe_peer().reachable

    # ------------------------------------------------------------ file sync

    def roots(self) -> dict[str, Path]:
        recordings = True
        with contextlib.suppress(OSError, ValueError):
            recordings = bool(
                json.loads((self.paths.state / "sync.conf.json").read_text()).get(
                    "recordings", True
                )
            )
        return sync.roots_for(self.paths.data_dir, self.paths.config_dir, recordings=recordings)

    def run_sync(self, force: bool = False) -> SyncState:
        n = self.node()
        st = self.state.sync()
        if n.role != "secondary" or n.peer is None:
            return st
        st.last_attempt_at = now_iso()
        try:
            answer = self.peer_call("manifest", {})
            remote = [sync.Entry.from_dict(e) for e in answer["entries"]]
            covered = answer.get("roots")  # None from an older primary: no deletions
            local = sync.manifest(self.roots(), digest_cache=self.digest_cache)
            plan = sync.plan(local, remote, covered if isinstance(covered, list) else [])
            st.backlog = plan.backlog
            done, errors = sync.apply(self.roots(), plan, self._fetch)
            st.transferred += done
            if errors:
                st.last_error = "; ".join(errors[:3])
                st.backlog = len(errors)
            else:
                st.last_error = ""
                st.backlog = 0
                st.last_success_at = now_iso()
                public_cert.apply(self.paths.config_dir, self.system)
        except (peer.PeerError, AgentError, OSError, KeyError, ValueError) as e:
            st.last_error = str(e)[:300]
        self.state.save_sync(st)
        return st

    def _fetch(self, logical: str) -> Iterator[bytes]:
        n = self.node()
        assert n.peer is not None
        r = peer.post(
            n.peer.url,
            "file",
            {"path": logical},
            node_id=n.node_id,
            private_key=self.private_key(),
            peer_public_key=n.peer.public_key,
            ca_pem=self.ca_pem(),
            timeout=peer.FILE_TIMEOUT,
        )
        if r.status_code != 200:
            raise OSError(f"the primary answered {r.status_code} for {logical}")
        yield r.content

    # ------------------------------------------------------------ the loop

    def _report_soon(self) -> None:
        self.last_report = -1e9

    def report(self) -> None:
        """This node's figures into ``cluster_nodes`` (primary: directly;
        secondary: as a heartbeat to the primary)."""
        n = self.node()
        payload = {
            "node_name": n.node_name,
            "hostname": socket.gethostname(),
            "address": n.address,
            "role": n.role,
            "state": n.state,
            "epoch": n.epoch,
            "db_role": self.replication().get("db_role"),
            "replication": self.replication(),
            "holds_address": self.holds_address(),
            "software_version": __version__,
            "sync_at": self.state.sync().last_success_at,
        }
        if n.role == "primary" and self.pg and self.pg.in_recovery() is False:
            with contextlib.suppress(AgentError):
                self.system.veyra_db("node-report", payload)
        elif n.role == "secondary":
            with contextlib.suppress(peer.PeerError, AgentError, OSError):
                self.peer_call("heartbeat", payload, timeout=peer.HEALTH_TIMEOUT)

    def tick(self) -> None:
        n = self.node()
        if not n.ha_enabled or n.peer is None:
            return
        health = self.probe_peer()
        became_reachable = (
            self.last_peer is None or not self.last_peer.reachable
        ) and health.reachable
        self.last_peer = health
        # The §7.3 rules apply at the agent's start (a boot) and whenever the
        # peer becomes reachable again. A running primary whose peer goes
        # away keeps serving (§1 principle 6): it is never isolated while up.
        first = not self.decided_once
        self.decided_once = True
        if not self.busy and (first or became_reachable):
            self.apply_decision(health)
        now = time.monotonic()
        if n.role == "secondary":
            if health.reachable and health.role == "primary" and (health.epoch or 0) > n.epoch:
                n.epoch = int(health.epoch or 0)
                self.state.save_node(n)
            if health.reachable and now - self.last_sync >= SYNC_SECONDS and not self.busy:
                self.last_sync = now
                self.run_sync()
            # A standby never holds the address.
            if self.holds_address() and self.postgres_in_recovery():
                self.release_address()
        if now - self.last_report >= REPORT_SECONDS:
            self.last_report = now
            self.report()

    def apply_decision(self, health: PeerHealth) -> None:
        n = self.node()
        decision, reason = rules.decide(n.role, n.epoch, health)
        log.info("Decision for %s (epoch %d): %s - %s", n.role, n.epoch, decision, reason)
        if decision == rules.DEMOTE:
            self.start(
                Operation(kind="demote", target=n.peer.node_name if n.peer else "", actor="agent"),
                lambda op: sequences.demote(self, op, peer_epoch=int(health.epoch or 0)),
            )
            self.db_event("demoted", {"reason": reason})
        elif decision == rules.ISOLATE:
            if n.state != "isolated":
                n.state = "isolated"
                self.state.save_node(n)
            self.engine_stop()
            self.release_address()
            with contextlib.suppress(AgentError):
                self.postgres_start()
            self.db_event("isolated", {"reason": reason})
        elif decision == rules.RESUME:
            if (
                n.state == "isolated"
                or not self.holds_address()
                or not self.system.unit_active("asterisk")
            ):
                self.start(
                    Operation(kind="resume", actor="agent"), lambda op: sequences.resume(self, op)
                )
        elif decision == rules.FOLLOW and n.state in ("isolated", "unknown"):
            n.state = "online"
            self.state.save_node(n)

    # ------------------------------------------------------------ operations

    def start(self, op: Operation, fn: Callable[[Operation], Operation]) -> Operation:
        with self.lock:
            if self.busy:
                raise AgentError("busy", "Another HA operation is running.")
            self.state.save_operation(op)

            def run() -> None:
                try:
                    fn(op)
                except Exception as e:
                    log.exception("Operation %s failed", op.kind)
                    op.finish("failed", str(e))
                    self.state.save_operation(op)
                self._report_soon()

            self.op_thread = threading.Thread(target=run, name=f"ha-{op.kind}", daemon=True)
            self.op_thread.start()
        return op

    # ------------------------------------------------------------ verbs

    def verb_status(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.status()

    def verb_enable(self, args: dict[str, Any]) -> dict[str, Any]:
        """Standalone becomes primary (§5): node key, PostgreSQL, certificates."""
        n = self.node()
        if n.ha_enabled:
            raise AgentError("already_enabled", "High availability is already enabled.")
        service = ServiceAddress.from_dict(args.get("service"))
        if not service.configured or not service.name:
            raise AgentError("bad_service", "The service name, address and interface are required.")
        pub = self.ensure_node_key()
        n.node_name = socket.gethostname()
        n.address = str(args.get("address") or n.address)
        n.service = service
        n.synchronous = bool(args.get("synchronous"))
        self.state.save_node(n)  # the steps below re-read node.json
        op = Operation(kind="enable", actor=str(args.get("actor") or "operator"))

        def run(op: Operation) -> Operation:
            sequences._step(self, op, "node-key", lambda: pub[:8] + "...")
            sequences._step(self, op, "replication-password", self._ensure_replication_password)
            sequences._step(
                self,
                op,
                "certificates",
                lambda: self._certificates(
                    service.name, [n.node_name], [n.address, service.address]
                ),
            )
            sequences._step(
                self,
                op,
                "nginx",
                lambda: self._nginx_service_listen(service.address),
                "service address",
            )
            sequences._step(self, op, "postgres", lambda: self._configure_postgres(n, restart=True))
            sequences._step(
                self,
                op,
                "database",
                lambda: self.system.veyra_db(
                    "enable",
                    {
                        "node_name": n.node_name,
                        "address": n.address,
                        "public_key": pub,
                        "service": {
                            "name": service.name,
                            "address": service.address,
                            "prefix": service.prefix,
                            "interface": service.interface,
                            "synchronous": n.synchronous,
                        },
                        "actor": op.actor,
                    },
                ),
            )
            n.role, n.epoch, n.state = "primary", 1, "online"
            n.node_id = str(
                self.system.veyra_db("node-report", {"node_name": n.node_name}).get("id")
                or n.node_id
            )
            self.state.save_node(n)
            sequences._step(self, op, "hold-address", self.hold_address)
            # The engine units are the agent's to start from now on (§7.3).
            self.system.systemctl("disable", *ENGINE_UNITS)
            op.finish("completed")
            self.state.save_operation(op)
            return op

        return self.start(op, run).to_dict()

    def _ensure_replication_password(self) -> None:
        p = self.paths.replication_password
        if not p.exists():
            p.write_text(secrets.token_urlsafe(24) + "\n")
            os.chmod(p, 0o600)
        if self.pg:
            r = self.pg.ensure_replication_role(self.replication_password())
            if not r.ok:
                raise AgentError("replication_role", r.stderr.strip()[:300])
            self.pg.grant_monitor(self.paths.database)

    def _certificates(
        self, service_name: str, node_names: list[str], addresses: list[str] | None = None
    ) -> str:
        """HTTPS certificate for the service name, the nodes and their
        addresses (node calls verify by address); PostgreSQL server
        certificate for this node."""
        n = self.node()
        names = list(dict.fromkeys([service_name, *node_names, socket.gethostname(), "localhost"]))
        ips = list(
            dict.fromkeys(
                a
                for a in [
                    *(addresses or []),
                    n.address,
                    n.service.address,
                    n.peer.address if n.peer else "",
                ]
                if a
            )
        )
        changed = certs.widen_ca(self.paths.tls, names, self.system.run)
        certs.issue(
            self.paths.tls,
            names,
            self.paths.tls / "veyra.crt",
            self.paths.tls / "veyra.key",
            addresses=ips,
            run=self.system.run,
        )
        # The leaf followed by the CA, as the installer writes it (clients
        # without the CA still get the chain).
        leaf = (self.paths.tls / "veyra.crt").read_bytes()
        if self.paths.ca_crt.exists():
            (self.paths.tls / "veyra.crt").write_bytes(leaf + self.paths.ca_crt.read_bytes())
        os.chmod(self.paths.tls / "veyra.key", 0o600)
        certs.issue(
            self.paths.tls,
            [socket.gethostname()],
            self.paths.tls / "postgres.crt",
            self.paths.tls / "postgres.key",
            addresses=[n.address] if n.address else None,
            run=self.system.run,
        )
        self.system.run(
            [
                "chown",
                "postgres:postgres",
                str(self.paths.tls / "postgres.crt"),
                str(self.paths.tls / "postgres.key"),
            ]
        )
        os.chmod(self.paths.tls / "postgres.key", 0o600)
        for copy in (self.paths.config_dir / "veyra-ca.crt",):
            with contextlib.suppress(OSError):
                shutil.copyfile(self.paths.ca_crt, copy)
        self.system.systemctl("reload", "nginx")
        return (
            "CA re-signed with the new names; phones must trust it again" if changed else "issued"
        )

    def _configure_postgres(self, n: NodeState, *, restart: bool) -> None:
        if self.pg is None:
            raise AgentError("no_cluster", "No PostgreSQL cluster found.")
        self._install_pg_tls()
        conf = postgres.render_conf(
            node_address=n.address or "localhost",
            cert_file=str(self.paths.pg_tls / "postgres.crt"),
            key_file=str(self.paths.pg_tls / "postgres.key"),
            ca_file=str(self.paths.pg_ca),
            synchronous_standby=postgres.slot_name(n.peer.node_name)
            if n.synchronous and n.peer
            else None,
        )
        self.pg.cluster.conf_d.mkdir(parents=True, exist_ok=True)
        fragment = self.pg.cluster.conf_d / postgres.CONF_NAME
        fragment.write_text(conf)
        os.chmod(fragment, 0o644)  # the agent's umask would hide it from postgres
        self._hba(n)
        if restart:
            r = self.pg.ctl("restart")
            if not r.ok:
                raise AgentError("postgres_restart", r.stderr.strip()[:300])

    def _nginx_service_listen(self, address: str | None) -> None:
        """NGINX listens on the service address on both nodes (§2): the
        include files the installer's site template reads, plus
        ``ip_nonlocal_bind`` so the standby's NGINX starts without the
        address. Empty files when the node leaves the cluster."""
        http = self.paths.config_dir / "nginx-ha-listen-http.conf"
        https = self.paths.config_dir / "nginx-ha-listen-https.conf"
        if address:
            http.write_text(f"    listen {address}:80;\n")
            https.write_text(f"    listen {address}:443 ssl;\n")
            sysctl = Path("/etc/sysctl.d/90-veyra-ha.conf")
            with contextlib.suppress(OSError):
                sysctl.write_text(
                    "# Managed by Veyra: NGINX binds the HA service address before it is held.\n"
                    "net.ipv4.ip_nonlocal_bind = 1\n"
                )
            self.system.run(["sysctl", "-q", "-w", "net.ipv4.ip_nonlocal_bind=1"])
        else:
            http.write_text("")
            https.write_text("")
        for f in (http, https):
            os.chmod(f, 0o644)
        r = self.system.run(["nginx", "-t"])
        if r.ok:
            self.system.systemctl("reload", "nginx")
        else:
            log.warning("nginx -t failed after the HA listen change: %s", r.stderr.strip()[:300])

    def _install_pg_tls(self) -> None:
        """Copy the CA and this node's PostgreSQL certificate where the
        ``postgres`` user can read them."""
        self.system.run(
            [
                "install",
                "-d",
                "-o",
                "postgres",
                "-g",
                "postgres",
                "-m",
                "0700",
                str(self.paths.pg_tls),
            ]
        )
        for name, mode in (("ca.crt", "0644"), ("postgres.crt", "0644"), ("postgres.key", "0600")):
            src = self.paths.tls / name
            if src.exists():
                self.system.run(
                    [
                        "install",
                        "-o",
                        "postgres",
                        "-g",
                        "postgres",
                        "-m",
                        mode,
                        str(src),
                        str(self.paths.pg_tls / name),
                    ]
                )

    def _hba(self, n: NodeState) -> None:
        if self.pg is None:
            return
        peers = [(n.peer.node_name, n.peer.address)] if n.peer else []
        path = self.pg.cluster.hba_path
        text = path.read_text() if path.exists() else ""
        new = postgres.update_hba(text, postgres.hba_lines(peers, self.paths.database))
        if new != text:
            backup = path.with_name(path.name + ".veyra-bak")
            with contextlib.suppress(OSError):
                shutil.copyfile(path, backup)
            path.write_text(new)
            self.pg.reload()

    def verb_make_bundle(self, args: dict[str, Any]) -> dict[str, Any]:
        """The primary's side of a join (§5 step 1): record the peer, open
        pg_hba, issue its certificate, encrypt the bundle with the token."""
        n = self.node()
        if n.role != "primary":
            raise AgentError("not_primary", "Only the primary admits nodes.")
        token = str(args["token"])
        peer_name = str(args["node_name"])
        peer_address = str(args["address"])
        peer_public = str(args["public_key"])
        # Node calls go to the node address (§2), never through DNS.
        n.peer = Peer(
            node_id=str(args.get("node_id") or ""),
            node_name=peer_name,
            address=peer_address,
            url=f"https://{peer_address}",
            public_key=peer_public,
        )
        self.state.save_node(n)
        out = self.system.veyra_db(
            "register-peer",
            {
                "node_name": peer_name,
                "hostname": peer_name,
                "address": peer_address,
                "public_key": peer_public,
                "actor": str(args.get("actor") or "join"),
            },
        )
        n.peer.node_id = str(out.get("node_id") or n.peer.node_id)
        self.state.save_node(n)
        if self.pg:
            self.pg.ensure_slot(postgres.slot_name(peer_name))
        self._configure_postgres(n, restart=False)
        self._certificates(n.service.name, [n.node_name, peer_name], [peer_address])
        # The new node's own PostgreSQL certificate, issued here with the CA key.
        tmp_crt, tmp_key = (
            self.paths.state / "peer-postgres.crt",
            self.paths.state / "peer-postgres.key",
        )
        certs.issue(
            self.paths.tls,
            [peer_name],
            tmp_crt,
            tmp_key,
            addresses=[peer_address],
            run=self.system.run,
        )
        extra = {
            "tls/postgres.crt": tmp_crt.read_bytes(),
            "tls/postgres.key": tmp_key.read_bytes(),
            "tls/veyra.crt": (self.paths.tls / "veyra.crt").read_bytes(),
            "tls/veyra.key": (self.paths.tls / "veyra.key").read_bytes(),
        }
        tmp_crt.unlink(missing_ok=True)
        tmp_key.unlink(missing_ok=True)
        bundle = {
            "version": join.BUNDLE_VERSION,
            "files": join.collect_files(self.paths.config_dir, extra),
            "values": {
                "public_host": n.service.name,
                "service": {
                    "name": n.service.name,
                    "address": n.service.address,
                    "prefix": n.service.prefix,
                    "interface": n.service.interface,
                },
                "primary": {
                    "node_id": n.node_id,
                    "node_name": n.node_name,
                    "address": n.address,
                    "url": f"https://{n.address}",
                    "public_key": self.ensure_node_key(),
                },
                "epoch": n.epoch,
                "database": self.paths.database,
            },
        }
        return {
            "bundle": join.encrypt_bundle(token, bundle),
            "node_id": n.peer.node_id,
            "epoch": n.epoch,
        }

    def verb_join_prepare(self, args: dict[str, Any]) -> dict[str, Any]:
        """The new node's side (§5 steps 1-3), run by the installer."""
        n = self.node()
        if n.ha_enabled:
            raise AgentError("already_enabled", "This node is already part of a cluster.")
        url = str(args["url"]).rstrip("/")
        token = str(args["token"])
        address = str(args["address"])
        n.node_name = socket.gethostname()
        n.address = address
        pub = self.ensure_node_key()
        op = Operation(kind="join", target=url, actor="installer")

        def run(op: Operation) -> Operation:
            def ask() -> str:
                r = peer.post(
                    url,
                    "join",
                    {
                        "token": token,
                        "node_name": n.node_name,
                        "address": address,
                        "public_key": pub,
                        "version": __version__,
                    },
                    node_id="joining",
                    private_key=self.private_key(),
                    peer_public_key=None,
                    ca_pem=self.ca_pem(),
                    timeout=peer.CALL_TIMEOUT,
                    # No CA yet on a fresh node: the token protects the bundle.
                    verify_tls=self.ca_pem() is not None and not args.get("insecure"),
                )
                if r.status_code != 200:
                    raise AgentError(
                        "join_refused", f"the primary answered {r.status_code}: {r.text[:200]}"
                    )
                data = r.json()
                bundle = join.decrypt_bundle(token, str(data["bundle"]))
                values = bundle["values"]
                join.write_files(self.paths.config_dir, bundle["files"])
                primary = values["primary"]
                n.peer = Peer(
                    node_id=str(primary["node_id"]),
                    node_name=str(primary["node_name"]),
                    address=str(primary["address"]),
                    url=str(primary["url"]),
                    public_key=str(primary["public_key"]),
                )
                n.service = ServiceAddress.from_dict(values.get("service"))
                # The interface is this node's own (§13 question 1): the
                # one that carries its node address.
                mine = self.system.interface_for(address)
                if mine:
                    n.service.interface = mine
                n.epoch = int(values.get("epoch") or 1)
                n.node_id = str(data.get("node_id") or "")
                n.role, n.state = "secondary", "joining"
                self.state.save_node(n)
                return f"admitted by {n.peer.node_name}, epoch {n.epoch}"

            sequences._step(self, op, "join", ask)
            sequences._step(self, op, "basebackup", lambda: self._basebackup(n))
            sequences._step(
                self, op, "postgres-conf", lambda: self._configure_postgres(n, restart=False)
            )
            sequences._step(self, op, "postgres-start", self.postgres_start)
            sequences._step(
                self,
                op,
                "nginx",
                lambda: self._nginx_service_listen(n.service.address),
                "service address",
            )
            self.system.systemctl("disable", *ENGINE_UNITS)
            sequences._step(self, op, "sync", lambda: self.run_sync(force=True))
            n.state = "online"
            self.state.save_node(n)
            self._report_soon()
            op.finish("completed")
            self.state.save_operation(op)
            return op

        return self.start(op, run).to_dict()

    def _basebackup(self, n: NodeState) -> str:
        if self.pg is None or n.peer is None:
            raise AgentError("no_cluster", "No PostgreSQL cluster or peer.")
        self._install_pg_tls()
        r = self.pg.basebackup(
            n.peer.address,
            self.replication_password(),
            str(self.paths.pg_ca),
            postgres.slot_name(n.node_name),
        )
        if not r.ok:
            raise AgentError("basebackup_failed", (r.stderr or r.stdout).strip()[:400])
        return "standby of " + n.peer.node_name

    def verb_switchover(self, args: dict[str, Any]) -> dict[str, Any]:
        n = self.node()
        if n.role != "secondary":
            raise AgentError("not_secondary", "A switchover runs on the node that takes over.")
        op = Operation(
            kind="switchover", target=n.node_name, actor=str(args.get("actor") or "operator")
        )
        self.db_event_via_peer("switchover_started", {"target": n.node_name, "actor": op.actor})
        return self.start(op, lambda op: sequences.switchover(self, op)).to_dict()

    def db_event_via_peer(self, event_type: str, details: dict[str, Any]) -> None:
        with contextlib.suppress(peer.PeerError, AgentError, OSError):
            self.peer_run("event", event_type=event_type, details=details)

    def verb_failover(self, args: dict[str, Any]) -> dict[str, Any]:
        n = self.node()
        if n.role != "secondary":
            raise AgentError("not_secondary", "A failover runs on the standby.")
        op = Operation(
            kind="failover", target=n.node_name, actor=str(args.get("actor") or "operator")
        )
        confirm = bool(args.get("confirm_fenced"))
        return self.start(
            op, lambda op: sequences.failover(self, op, confirm_fenced=confirm)
        ).to_dict()

    def verb_rejoin(self, args: dict[str, Any]) -> dict[str, Any]:
        n = self.node()
        if n.peer is None:
            raise AgentError("no_peer", "No peer to rejoin.")
        health = self.probe_peer()
        epoch = int(args.get("epoch") or health.epoch or n.epoch)
        op = Operation(
            kind="rejoin", target=n.peer.node_name, actor=str(args.get("actor") or "peer")
        )
        self.set_local_role("secondary", epoch, "rejoining")
        return self.start(op, lambda op: sequences.rejoin(self, op, peer_epoch=epoch)).to_dict()

    def verb_demote(self, args: dict[str, Any]) -> dict[str, Any]:
        n = self.node()
        health = self.probe_peer()
        epoch = int(args.get("epoch") or health.epoch or n.epoch)
        op = Operation(kind="demote", target=n.peer.node_name if n.peer else "", actor="peer")
        return self.start(op, lambda op: sequences.demote(self, op, peer_epoch=epoch)).to_dict()

    def verb_resume(self, args: dict[str, Any]) -> dict[str, Any]:
        n = self.node()
        if n.role != "primary":
            raise AgentError("not_primary", "Only an isolated primary resumes.")
        health = self.probe_peer()
        if health.reachable and (health.epoch or 0) > n.epoch:
            raise AgentError("stale", "The peer moved on to a newer epoch; this node must rejoin.")
        op = Operation(kind="resume", actor=str(args.get("actor") or "operator"))
        return self.start(op, lambda op: sequences.resume(self, op)).to_dict()

    def verb_freeze(self, args: dict[str, Any]) -> dict[str, Any]:
        self.db_set_frozen(True)
        n = self.node()
        n.state = "frozen"
        self.state.save_node(n)
        return {"frozen": True}

    def verb_unfreeze(self, args: dict[str, Any]) -> dict[str, Any]:
        n = self.node()
        if n.role == "primary":
            with contextlib.suppress(AgentError):
                self.db_set_frozen(False)
        if n.state == "frozen":
            n.state = "online"
            self.state.save_node(n)
        return {"frozen": False}

    def verb_engine(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action"))
        if action == "stop":
            self.engine_stop()
        elif action == "start":
            if self.pg and self.pg.in_recovery():
                raise AgentError("in_recovery", "A standby does not run the engine.")
            self.engine_start()
        else:
            raise AgentError("bad_action", "engine start|stop")
        return {"running": self.system.unit_active("asterisk")}

    def verb_postgres(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action"))
        if self.pg is None:
            raise AgentError("no_cluster", "No PostgreSQL cluster.")
        if action == "stop":
            self.pg.stop()
        elif action == "start":
            self.postgres_start()
        elif action == "reload":
            self.pg.reload()
        elif action == "checkpoint":
            self.pg.checkpoint()
        else:
            raise AgentError("bad_action", "postgres start|stop|reload|checkpoint")
        return {"in_recovery": self.pg.in_recovery()}

    def verb_current_lsn(self, args: dict[str, Any]) -> dict[str, Any]:
        lsn = self.pg.current_lsn() if self.pg else None
        return {"lsn": lsn, "lsn_bytes": postgres.parse_lsn(lsn)}

    def verb_hold_address(self, args: dict[str, Any]) -> dict[str, Any]:
        self.hold_address()
        return {"holds_address": self.holds_address()}

    def verb_release_address(self, args: dict[str, Any]) -> dict[str, Any]:
        self.release_address()
        return {"holds_address": self.holds_address()}

    def verb_sync_now(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.run_sync(force=True).to_dict()

    def verb_set_sync(self, args: dict[str, Any]) -> dict[str, Any]:
        (self.paths.state / "sync.conf.json").write_text(
            json.dumps({"recordings": bool(args.get("recordings", True))})
        )
        return {"recordings": bool(args.get("recordings", True))}

    def verb_set_fencing(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self.paths.state / "fencing.json"
        path.write_text(json.dumps(args.get("config") or {}))
        os.chmod(path, 0o600)
        return {"configured": bool((args.get("config") or {}).get("enabled"))}

    def verb_fence(self, args: dict[str, Any]) -> dict[str, Any]:
        result = self.fence_peer()
        if result is None:
            raise AgentError("no_fencing", "Fencing is not configured.")
        return {"result": result}

    def verb_set_synchronous(self, args: dict[str, Any]) -> dict[str, Any]:
        """Synchronous replication on or off (§4.1); the setting is reloadable."""
        n = self.node()
        if n.role != "primary":
            raise AgentError("not_primary", "Replication mode is set on the primary.")
        n.synchronous = bool(args.get("synchronous"))
        self.state.save_node(n)
        self._configure_postgres(n, restart=False)
        if self.pg:
            self.pg.reload()
        return {"synchronous": n.synchronous}

    def verb_set_peer_epoch(self, args: dict[str, Any]) -> dict[str, Any]:
        n = self.node()
        n.epoch = int(args["epoch"])
        self.state.save_node(n)
        return {"epoch": n.epoch}

    def verb_remove_peer(self, args: dict[str, Any]) -> dict[str, Any]:
        """§8 on the primary: drop the slot and the pg_hba lines, forget the peer."""
        n = self.node()
        if n.role != "primary":
            raise AgentError("not_primary", "Nodes are removed from the primary.")
        if n.peer and self.pg:
            self.pg.drop_slot(postgres.slot_name(n.peer.node_name))
        name = n.peer.node_name if n.peer else ""
        n.peer = None
        self.state.save_node(n)
        self._hba(n)
        self._configure_postgres(n, restart=False)
        if self.pg:
            self.pg.reload()
        out = self.system.veyra_db(
            "remove-node", {"node_name": name, "actor": str(args.get("actor") or "operator")}
        )
        if out.get("deployment_mode") == "standalone":
            n.role, n.state = "standalone", "online"
            self.state.save_node(n)
            self.system.systemctl("enable", *ENGINE_UNITS)
            # The service address stays here (§8) but no longer moves.
            self._nginx_service_listen(n.service.address or None)
        return out

    def verb_remove_node(self, args: dict[str, Any]) -> dict[str, Any]:
        """§8 from the console: the peer becomes standalone (best effort),
        then it is removed here."""
        with contextlib.suppress(peer.PeerError, AgentError, OSError):
            self.peer_run("standalone")
        return self.verb_remove_peer(args)

    def verb_standalone(self, args: dict[str, Any]) -> dict[str, Any]:
        """A removed secondary becomes a standalone that may run the engine
        again (§8); PostgreSQL is promoted so it accepts writes."""
        n = self.node()
        if self.pg and self.pg.in_recovery():
            self.pg.promote()
            self.pg.clear_standby()
        n.role, n.state, n.peer = "standalone", "online", None
        self.state.save_node(n)
        self._hba(n)
        self.system.veyra_db("standalone", {"node_name": n.node_name})
        self.system.systemctl("enable", *ENGINE_UNITS)
        self.release_address()
        self._nginx_service_listen(None)
        return {"role": "standalone"}

    def verb_upgrade(self, args: dict[str, Any]) -> dict[str, Any]:
        version = str(args.get("version") or "")
        import re

        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?", version):
            raise AgentError("bad_version", "Not a release version.")
        r = self.system.systemctl("start", "--no-block", f"veyra-upgrade@{version}.service")
        if not r.ok:
            raise AgentError("upgrade_start_failed", r.stderr.strip()[:300])
        return {"started": version}

    def verb_manifest_etc(self, args: dict[str, Any]) -> dict[str, Any]:
        """The root-only roots of the file sync (secrets, TLS, trust) for the
        API, which cannot read them itself (§4.2)."""
        _readable, privileged = sync.split_roots(self.roots())
        entries = sync.manifest(privileged, digest_cache=self.digest_cache)
        return {"entries": [e.to_dict() for e in entries], "roots": list(privileged)}

    def verb_read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        """One file of a root-only root, base64 (they are small)."""
        _readable, privileged = sync.split_roots(self.roots())
        logical = str(args.get("path") or "")
        path = sync.resolve(privileged, logical)
        if path is None or not path.is_file() or sync.excluded(logical):
            raise AgentError("no_file", "No such file.")
        data = path.read_bytes()
        if len(data) > 4 * 1024 * 1024:
            raise AgentError("too_large", "The file is too large for the agent channel.")
        return {"content": base64.b64encode(data).decode(), "size": len(data)}

    def verb_event(self, args: dict[str, Any]) -> dict[str, Any]:
        self.db_event(str(args.get("event_type") or "ha_event"), dict(args.get("details") or {}))
        return {}

    def verb_checkpoint(self, args: dict[str, Any]) -> dict[str, Any]:
        if self.pg:
            self.pg.checkpoint()
        return {}

    def verb_engine_stop(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.verb_engine({"action": "stop"})

    def verb_engine_start(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.verb_engine({"action": "start"})

    def verb_postgres_stop(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.verb_postgres({"action": "stop"})

    def verb_postgres_start(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.verb_postgres({"action": "start"})

    def dispatch(self, verb: str, args: dict[str, Any]) -> Any:
        name = VERBS.get(verb)
        if name is None:
            raise AgentError("unknown_verb", f"Unknown verb {verb!r}.")
        log.info(
            "verb %s %s", verb, {k: v for k, v in args.items() if k not in ("token", "config")}
        )
        return getattr(self, name)(args)

    def handle(self, line: bytes) -> bytes:
        try:
            req = json.loads(line or b"{}")
            verb = str(req.get("verb") or "")
            args = req.get("args") if isinstance(req.get("args"), dict) else {}
            result = self.dispatch(verb, args)
            out: dict[str, Any] = {"ok": True, "result": result}
        except AgentError as e:
            out = {"ok": False, "code": e.code, "error": e.message}
        except (peer.PeerError, join.JoinError) as e:
            out = {"ok": False, "code": e.code, "error": e.message}
        except Exception as e:
            log.exception("verb failed")
            out = {"ok": False, "code": "agent_error", "error": f"{type(e).__name__}: {e}"}
        return json.dumps(out, separators=(",", ":"), default=str).encode() + b"\n"

    # ------------------------------------------------------------ serving

    def serve(self, path: Path = SOCKET_PATH, *, once: bool = False) -> None:
        agent = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                data = self.rfile.read()
                self.wfile.write(agent.handle(data))

        path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        server = socketserver.ThreadingUnixStreamServer(str(path), Handler)
        server.daemon_threads = True
        os.chmod(path, 0o660)
        with contextlib.suppress(KeyError, PermissionError, OSError):
            import grp

            gid = grp.getgrnam("veyra").gr_gid
            os.chown(path, 0, gid)
            # RuntimeDirectory= is root:root; the API connects as veyra.
            os.chown(path.parent, 0, gid)
            os.chmod(path.parent, 0o750)  # noqa: S103 - root:veyra, group reads only
        self.state.dir.mkdir(parents=True, exist_ok=True)
        log.info("HA agent listening on %s", path)
        t = threading.Thread(target=server.serve_forever, name="ha-socket", daemon=True)
        t.start()
        self.loop(once=once)
        server.shutdown()

    def ensure_nginx_listen(self) -> None:
        """At start: the include files match the node's service address."""
        n = self.node()
        want = (
            f"    listen {n.service.address}:443 ssl;\n"
            if n.ha_enabled and n.service.address
            else ""
        )
        https = self.paths.config_dir / "nginx-ha-listen-https.conf"
        try:
            current = https.read_text()
        except OSError:
            current = None
        if current != want:
            self._nginx_service_listen(n.service.address if n.ha_enabled else None)

    def loop(self, *, once: bool = False) -> None:
        with contextlib.suppress(Exception):
            self.ensure_nginx_listen()
        while True:
            try:
                self.tick()
            except Exception:
                log.exception("HA tick failed")
            if once:
                return
            self.sleep(POLL_SECONDS)


def build(settings: Any, system: System | None = None) -> Agent:
    system = system or default_system()
    cluster = None
    r = system.run(["pg_lsclusters", "--no-header"])
    if r.ok:
        cluster = postgres.parse_lsclusters(r.stdout)
    pg = postgres.Postgres(cluster, system.run, database="veyra") if cluster else None
    paths = Paths(settings.data_dir, settings.config_dir, settings.log_dir)
    return Agent(paths, system, pg)
