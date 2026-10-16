# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 16 unit tests (docs/HIGH_AVAILABILITY.md §15): epoch rules,
switchover preconditions, state files, PostgreSQL fragments and pg_hba
editing, manifests and file transfer, the join bundle, the fencing client."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from veyra.ha import fencing, join, postgres, rules, sync
from veyra.ha.state import NodeState, Operation, Peer, StateDir, SyncState

# ------------------------------------------------------------------ rules


@pytest.mark.parametrize(
    ("role", "epoch", "peer", "expected"),
    [
        ("standalone", 0, rules.PeerHealth.unreachable(), rules.STANDALONE),
        ("primary", 3, rules.PeerHealth.unreachable(), rules.ISOLATE),
        ("primary", 3, rules.PeerHealth(True, "primary", 4), rules.DEMOTE),
        ("primary", 3, rules.PeerHealth(True, "secondary", 4), rules.DEMOTE),
        ("primary", 3, rules.PeerHealth(True, "primary", 3), rules.DEMOTE),
        ("primary", 3, rules.PeerHealth(True, "secondary", 3), rules.RESUME),
        ("primary", 3, rules.PeerHealth(True, "secondary", 2), rules.RESUME),
        ("primary", 3, rules.PeerHealth(True, "primary", 2), rules.RESUME),
        ("secondary", 3, rules.PeerHealth.unreachable(), rules.WAIT),
        ("secondary", 3, rules.PeerHealth(True, "primary", 3), rules.FOLLOW),
        ("secondary", 3, rules.PeerHealth(True, "primary", 5), rules.FOLLOW),
        ("secondary", 3, rules.PeerHealth(True, "secondary", 3), rules.WAIT),
    ],
)
def test_epoch_rules(role, epoch, peer, expected):
    decision, reason = rules.decide(role, epoch, peer)
    assert decision == expected
    assert reason


def _facts(**over):
    base = dict(
        local_role="primary",
        target_role="secondary",
        target_online=True,
        local_version="0.22.0",
        target_version="0.22.0",
        replication_state="streaming",
        lag_bytes=1024,
        sync_age=timedelta(seconds=30),
        operation_running=False,
        deployment_running=False,
        upgrade_running=False,
        frozen=False,
    )
    base.update(over)
    return rules.SwitchoverFacts(**base)


def test_switchover_preconditions():
    assert rules.switchover_problems(_facts()) == []
    problems = rules.switchover_problems(
        _facts(
            target_version="0.21.0",
            replication_state="catchup",
            lag_bytes=rules.MAX_CATCHUP_BYTES + 1,
            sync_age=timedelta(minutes=6),
            operation_running=True,
            upgrade_running=True,
            frozen=True,
        )
    )
    assert len(problems) == 7
    assert any("different versions" in p for p in problems)
    assert any("too far behind" in p for p in problems)
    assert rules.switchover_problems(_facts(local_role="secondary"))[0].startswith(
        "A switchover starts"
    )
    assert rules.switchover_problems(_facts(sync_age=None)) == [
        "The file sync did not succeed in the last 5 minutes."
    ]


# ------------------------------------------------------------------ state


def test_state_files_round_trip(tmp_path: Path):
    d = StateDir(tmp_path / "ha")
    assert d.node() is None
    node = NodeState(
        node_id="n1",
        node_name="dev1",
        address="172.16.2.250",
        role="primary",
        epoch=2,
        peer=Peer("n2", "dev2", "172.16.2.251", "https://veyra-dev2", "pk"),
    )
    node.service.address, node.service.interface = "172.16.2.10", "eth0"
    d.save_node(node)
    back = d.node()
    assert back is not None
    assert (
        back.role == "primary" and back.epoch == 2 and back.peer and back.peer.node_name == "dev2"
    )
    assert back.service.configured and back.updated_at
    assert oct(os.stat(d.node_path).st_mode & 0o777) == "0o640"

    op = Operation(kind="switchover", target="dev2", actor="admin")
    s1 = op.start_step("freeze")
    op.finish_step(s1)
    s2 = op.start_step("catch-up")
    op.finish(status="aborted", error="timeout")
    d.save_operation(op)
    back_op = d.operation()
    assert back_op is not None and back_op.status == "aborted" and not back_op.running
    assert [s.status for s in back_op.steps] == ["ok", "failed"]
    assert back_op.steps[0].seconds is not None and s2.finished_at

    d.save_sync(SyncState(last_success_at="now", backlog=3))
    assert d.sync().backlog == 3


# ------------------------------------------------------------------ postgres


def test_conf_fragment_and_hba_block():
    conf = postgres.render_conf(
        node_address="172.16.2.250",
        cert_file="/etc/veyra/tls/postgres.crt",
        key_file="/etc/veyra/tls/postgres.key",
        ca_file="/etc/veyra/tls/ca.crt",
    )
    assert "wal_log_hints = on" in conf and "listen_addresses = 'localhost,172.16.2.250'" in conf
    assert "synchronous_standby_names = ''" in conf
    sync_conf = postgres.render_conf(
        node_address="a",
        cert_file="c",
        key_file="k",
        ca_file="ca",
        synchronous_standby="veyra_dev2",
    )
    assert "synchronous_standby_names = 'veyra_dev2'" in sync_conf

    original = "# default rules\nlocal all all peer\nhost all all 127.0.0.1/32 scram-sha-256\n"
    lines = postgres.hba_lines([("dev2", "172.16.2.251")], "veyra")
    assert lines == [
        "hostssl replication veyra_replication 172.16.2.251/32 scram-sha-256  # dev2",
        "hostssl veyra veyra_replication 172.16.2.251/32 scram-sha-256  # dev2",
    ]
    edited = postgres.update_hba(original, lines)
    assert edited.startswith(postgres.HBA_BEGIN) and edited.endswith(original)
    assert postgres.hba_block(edited) == lines
    # Replacing keeps the rest; removing the lines removes the block.
    again = postgres.update_hba(edited, postgres.hba_lines([("dev3", "::1")], "veyra"))
    assert "172.16.2.251" not in again and "::1/128" in again and again.endswith(original)
    assert postgres.update_hba(again, []) == original
    assert postgres.update_hba(original, []) == original


def test_lsn_and_replication_rows():
    assert postgres.parse_lsn("0/16B3748") == 0x16B3748
    assert postgres.parse_lsn("1/0") == 1 << 32
    assert postgres.parse_lsn(None) is None and postgres.parse_lsn("x") is None
    assert postgres.lag_bytes("0/2000", "0/1000") == 0x1000
    r = postgres.replication_from_rows(
        False, [["dev2", "streaming", "async", "0/2000", "0/1000", "0.5"]], "veyra_dev2"
    )
    assert r.db_role == "primary" and r.state == "streaming" and r.lag_bytes == 0x1000
    assert r.lag_seconds == 0.5 and r.synchronous is False and r.slot == "veyra_dev2"
    empty = postgres.replication_from_rows(False, [])
    assert empty.state is None and "no standby" in empty.detail
    s = postgres.replication_from_rows(
        True, [["0/3000", "0/2800", "2026-10-16 12:00:00+00", "streaming", "veyra_dev2"]]
    )
    assert s.db_role == "standby" and s.receiver == "streaming" and s.lag_bytes == 0x800
    stopped = postgres.replication_from_rows(True, [["0/3000", "0/3000", None, None, None]])
    assert stopped.receiver == "stopped" and stopped.state is None
    assert postgres.slot_name("Other-Node") == "veyra_other_node"
    assert postgres.slot_name("veyra_dev2") == "veyra_dev2"
    c = postgres.parse_lsclusters(
        "18  main    5432 online postgres /var/lib/postgresql/18/main /var/log/x"
    )
    assert c and c.version == "18" and c.data_dir == Path("/var/lib/postgresql/18/main")
    assert c.conf_d == Path("/etc/postgresql/18/main/conf.d")


def test_postgres_commands_use_runner():
    calls: list[list[str]] = []

    def run(argv):
        calls.append(list(argv))
        if "pg_is_in_recovery" in argv[-1]:
            return postgres.Result(0, "t\n")
        return postgres.Result(0, "")

    pg = postgres.Postgres(postgres.Cluster("18", "main", Path("/tmp/pgdata")), run)
    assert pg.in_recovery() is True
    assert calls[0][:4] == ["runuser", "-u", "postgres", "--"]
    pg.promote()
    assert calls[-1] == ["pg_ctlcluster", "18", "main", "promote"]
    pg.ensure_slot("dev2")
    assert "veyra_dev2" in calls[-1][-1]
    pg.stop()
    assert calls[-1] == ["systemctl", "stop", "postgresql@18-main"]


# ------------------------------------------------------------------ sync


def _tree(base: Path, files: dict[str, bytes]) -> None:
    for rel, content in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)


def test_manifest_plan_and_transfer(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    _tree(a, {"prompts/x.wav": b"xx", "prompts/sub/y.wav": b"y", "secrets/node.key": b"k"})
    _tree(b, {"prompts/x.wav": b"old", "prompts/gone.wav": b"g"})
    roots_a = {"data/prompts": a / "prompts", "etc/secrets": a / "secrets"}
    roots_b = {"data/prompts": b / "prompts", "etc/secrets": b / "secrets"}
    cache: dict = {}
    ma = sync.manifest(roots_a, digest_cache=cache)
    assert [e.path for e in ma] == ["data/prompts/sub/y.wav", "data/prompts/x.wav"]
    assert "etc/secrets/node.key" not in {e.path for e in ma}  # never synced
    assert len(cache) == 2
    assert sync.manifest(roots_a, digest_cache=cache) == ma  # cached digests
    mb = sync.manifest(roots_b)
    p = sync.plan(mb, ma)
    assert {e.path for e in p.fetch} == {"data/prompts/sub/y.wav", "data/prompts/x.wav"}
    assert p.delete == ["data/prompts/gone.wav"] and p.backlog == 3

    def fetch(logical: str):
        target = sync.resolve(roots_a, logical)
        assert target is not None
        return sync.read_chunks(target)

    done, errors = sync.apply(roots_b, p, fetch)
    assert done == 2 and errors == []
    assert (b / "prompts/x.wav").read_bytes() == b"xx"
    assert (b / "prompts/sub/y.wav").read_bytes() == b"y"
    assert not (b / "prompts/gone.wav").exists()
    assert sync.plan(sync.manifest(roots_b), ma).backlog == 0
    # Round trip of the entry format and refusal of escaping paths.
    assert sync.Entry.from_dict(ma[0].to_dict()) == ma[0]
    assert sync.resolve(roots_b, "data/prompts/../x") is None
    assert sync.resolve(roots_b, "other/x") is None
    bad = sync.Entry("data/prompts/z", 1, 0.0, 0o640, "root", "root", "00" * 32)
    with pytest.raises(ValueError, match="digest"):
        sync.write_entry(roots_b, bad, [b"z"])
    assert not list((b / "prompts").glob("*.veyra-sync"))


# ------------------------------------------------------------------ join


def test_join_bundle_round_trip(tmp_path: Path):
    etc = tmp_path / "etc"
    _tree(
        etc,
        {
            "secrets/installation.key": b"key",
            "tls/ca.crt": b"cert",
            "trust/official/a.pub": b"pub",
            "secrets/node.key": b"mine",
        },
    )
    os.chmod(etc / "secrets/installation.key", 0o640)
    files = join.collect_files(etc, {"tls/node.crt": b"issued"})
    paths = [f["path"] for f in files]
    assert paths == [
        "secrets/installation.key",
        "tls/ca.crt",
        "trust/official/a.pub",
        "tls/node.crt",
    ]
    assert "secrets/node.key" not in paths
    bundle = {"version": 1, "files": files, "values": {"public_host": "veyra"}}
    sealed = join.encrypt_bundle("vyj_token", bundle)
    assert join.decrypt_bundle("vyj_token", sealed) == bundle
    with pytest.raises(join.JoinError):
        join.decrypt_bundle("vyj_other", sealed)
    with pytest.raises(join.JoinError):
        join.decrypt_bundle("vyj_token", "v9:zz")
    out = tmp_path / "out"
    written = join.write_files(out, files, chown=False)
    assert written == paths
    assert (out / "secrets/installation.key").read_bytes() == b"key"
    assert oct(os.stat(out / "secrets/installation.key").st_mode & 0o777) == "0o640"
    assert (out / "tls/node.crt").read_bytes() == b"issued"
    with pytest.raises(join.JoinError):
        join.write_files(out, [{"path": "../x", "content": ""}], chown=False)


# ------------------------------------------------------------------ fencing


def test_fencing_against_mock_proxmox(monkeypatch):
    state = {"status": "running", "stops": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "PVEAPIToken=root@pam!veyra=s3cret"
        if request.url.path.endswith("/status/current"):
            return httpx.Response(200, json={"data": {"status": state["status"]}})
        if request.url.path.endswith("/status/stop"):
            state["stops"] += 1
            state["status"] = "stopped"
            return httpx.Response(200, json={"data": "UPID:x"})
        return httpx.Response(404)

    monkeypatch.setattr(fencing, "transport", httpx.MockTransport(handler))
    target = fencing.settings_to_target(
        {
            "enabled": True,
            "url": "https://pve.example:8006/",
            "token_id": "root@pam!veyra",
            "pve_node": "pve1",
            "vms": {"veyra-dev1": {"vmid": 101}, "veyra-dev2": {"vmid": 102}},
        },
        "veyra-dev1",
        "s3cret",
    )
    assert target is not None and target.vmid == 101 and target.url == "https://pve.example:8006"
    assert fencing.check(target) == {"ok": True, "status": "running"}
    assert fencing.stop_vm(target, wait=5, sleep=0) == "stopped"
    assert state["stops"] == 1
    assert fencing.stop_vm(target, wait=5, sleep=0) == "already stopped"
    assert fencing.settings_to_target({"enabled": False}, "veyra-dev1", "") is None
    assert fencing.settings_to_target({"enabled": True, "vms": {}}, "veyra-dev1", "") is None
