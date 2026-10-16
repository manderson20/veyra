# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 16 API tests (docs/HIGH_AVAILABILITY.md §15): the HA routes with
the agent socket replaced by an in-process fake that records verbs, the
signed peer endpoints driven as the other node, the standby's 503 and
in-memory sign-in, and the HA alert checks."""

from __future__ import annotations

import json
import socketserver
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, csrf_headers, login, make_settings
from sqlalchemy import select

from veyra import __version__
from veyra.central import protocol
from veyra.core.db import session_scope
from veyra.core.models import ClusterNode, Installation
from veyra.core.models.base import utcnow
from veyra.ha import peer, service
from veyra.ha.standby import Flags, StandbySessions, write_blocked
from veyra.ha.state import NodeState, Peer, ServiceAddress, StateDir
from veyra.main import create_app


class FakeAgent:
    """Answers the agent socket; ``results`` per verb, ``calls`` recorded."""

    def __init__(self, path: Path):
        self.path = path
        self.calls: list[tuple[str, dict]] = []
        self.results: dict = {
            "status": {"holds_address": True, "replication": {"db_role": "primary"}}
        }
        self.hooks: dict = {}
        agent = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                req = json.loads(self.rfile.read())
                verb, args = req["verb"], req.get("args") or {}
                agent.calls.append((verb, args))
                if verb in agent.hooks:
                    out = agent.hooks[verb](args)
                elif verb in agent.results:
                    out = agent.results[verb]
                    if isinstance(out, Exception):
                        self.wfile.write(
                            json.dumps({"ok": False, "code": "refused", "error": str(out)}).encode()
                        )
                        return
                else:
                    out = {"kind": verb, "status": "running", "steps": []}
                self.wfile.write(json.dumps({"ok": True, "result": out}).encode())

        self.server = socketserver.ThreadingUnixStreamServer(str(path), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()

    def verbs(self) -> list[str]:
        return [v for v, _ in self.calls]


@pytest.fixture
def ha(database_url, tmp_path, db_ready_factory=None):
    """An app with a fake agent, a node key and an HA state directory."""
    sock = Path("/tmp") / f"veyra-ha-test-{uuid.uuid4().hex[:8]}.sock"
    settings = make_settings(database_url, tmp_path, ha_socket_path=sock)
    (settings.config_dir / "secrets").mkdir(parents=True, exist_ok=True)
    priv, pub = protocol.new_keypair()
    (settings.config_dir / "secrets" / "node.key").write_text(priv)
    fake = FakeAgent(sock)
    yield settings, fake, priv, pub
    fake.close()
    sock.unlink(missing_ok=True)


@pytest.fixture
def node(ha, db_ready, monkeypatch):
    settings, fake, priv, pub = ha
    app = create_app(settings)
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="https://veyra-a") as client:
        from conftest import complete_setup

        complete_setup(client)
        client.headers.update(csrf_headers(client))
        monkeypatch.setattr(protocol, "transport", client._transport)
        yield client, app, settings, fake, priv, pub


def _local_row(name: str) -> ClusterNode:
    with session_scope() as db:
        row = db.scalar(select(ClusterNode).where(ClusterNode.node_name == name))
        assert row is not None
        db.expunge(row)
        return row


def _state(settings) -> StateDir:
    return StateDir(settings.data_dir / "ha")


def _make_primary(
    settings, pub: str, peer_pub: str | None = None
) -> tuple[ClusterNode, ClusterNode | None]:
    """node.json and rows for a primary (this host) and, optionally, a peer."""
    me = service.local_name()
    with session_scope() as db:
        service.action_enable(
            db,
            {
                "node_name": me,
                "address": "10.0.0.1",
                "public_key": pub,
                "service": {
                    "name": "veyra",
                    "address": "10.0.0.10",
                    "prefix": 24,
                    "interface": "eth0",
                },
            },
        )
        peer_row = None
        if peer_pub:
            service.action_register_peer(
                db, {"node_name": "veyra-b", "address": "10.0.0.2", "public_key": peer_pub}
            )
            peer_row = service.node_by_name(db, "veyra-b")
            peer_row.state, peer_row.software_version = "online", __version__
            peer_row.last_heartbeat_at, peer_row.sync_at = utcnow(), utcnow()
            db.flush()
            db.expunge(peer_row)
        mine = service.node_by_name(db, me)
        db.expunge(mine)
    _state(settings).save_node(
        NodeState(
            node_id=str(mine.id),
            node_name=me,
            address="10.0.0.1",
            role="primary",
            epoch=1,
            peer=Peer(str(peer_row.id), "veyra-b", "10.0.0.2", "https://veyra-a", peer_pub)
            if peer_row
            else None,
            service=ServiceAddress("veyra", "10.0.0.10", 24, "eth0"),
        )
    )
    return mine, peer_row


def _signed(client, verb: str, payload: dict, *, node_id: str, key: str, path: str | None = None):
    body = peer.encode(payload)
    path = path or peer.path_for(verb)
    ts, nonce = str(int(time.time())), protocol.new_nonce()
    headers = {
        "Content-Type": "application/json",
        protocol.H_INSTANCE: node_id,
        protocol.H_TIMESTAMP: ts,
        protocol.H_NONCE: nonce,
        protocol.H_SIGNATURE: protocol.sign(
            key, protocol.request_string("POST", path, ts, nonce, body)
        ),
    }
    r = client.post(path, content=body, headers=headers)
    return r, nonce


def _verify_answer(r, nonce: str, pub: str) -> None:
    sig = r.headers[protocol.H_CONSOLE_SIGNATURE]
    ts = r.headers[protocol.H_TIMESTAMP]
    assert protocol.verify(pub, protocol.answer_string(ts, nonce, r.content), sig)


def _check_answer(r, nonce: str, pub: str) -> dict:
    _verify_answer(r, nonce, pub)
    return r.json()


# ------------------------------------------------------------------ enable, tokens, join


def test_status_enable_tokens_and_join(node):
    client, app, settings, fake, priv, pub = node  # noqa: RUF059
    st = client.get("/api/v1/ha/status").json()
    assert st["deployment_mode"] == "standalone" and st["local"]["agent"] is True
    assert st["local"]["holds_address"] is True  # from the fake agent's status
    assert client.post("/api/v1/ha/join-tokens", json={}).status_code == 409  # not enabled
    r = client.post(
        "/api/v1/ha/enable",
        json={"name": "veyra", "address": "10.0.0.10", "prefix": 24, "interface": "eth0"},
    )
    assert r.status_code == 200, r.text
    assert fake.verbs()[-1] == "enable"
    assert fake.calls[-1][1]["service"]["address"] == "10.0.0.10"
    # The agent (faked here) does the database side; do it by hand.
    mine, _ = _make_primary(settings, pub)
    st = client.get("/api/v1/ha/status").json()
    assert st["ha_enabled"] and st["local"]["role"] == "primary" and st["epoch"] == 1
    assert st["service"]["holder"] == mine.node_name
    assert r.status_code == 200
    assert (
        client.put(
            "/api/v1/ha/service",
            json={"name": "other", "address": "10.0.0.10", "prefix": 24, "interface": "eth0"},
        ).status_code
        == 409
    )

    tok = client.post("/api/v1/ha/join-tokens", json={"label": "dev2"}).json()
    assert tok["token"].startswith("vyj_") and "--join https://" in tok["command"]
    listed = client.get("/api/v1/ha/join-tokens").json()
    assert len(listed) == 1 and "hash" not in listed[0] and listed[0]["label"] == "dev2"

    # Node B joins: signed with its own key, authorised by the token.
    b_priv, b_pub = protocol.new_keypair()
    sealed = {"bundle": "v1:sealed", "node_id": "pending", "epoch": 1}

    def make_bundle(args):
        with session_scope() as db:
            service.action_register_peer(
                db,
                {
                    "node_name": args["node_name"],
                    "address": args["address"],
                    "public_key": args["public_key"],
                },
            )
        return sealed

    fake.hooks["make-bundle"] = make_bundle
    body = {
        "token": tok["token"],
        "node_name": "veyra-b",
        "address": "10.0.0.2",
        "public_key": b_pub,
        "version": __version__,
    }
    r, nonce = _signed(client, "join", body, node_id="joining", key=b_priv)
    assert r.status_code == 200, r.text
    assert _check_answer(r, nonce, pub) == sealed
    assert fake.calls[-1][0] == "make-bundle" and fake.calls[-1][1]["token"] == tok["token"]
    assert _local_row("veyra-b").role == "secondary"
    # Used once; a wrong version is refused before the token is consumed.
    r, _ = _signed(client, "join", body, node_id="joining", key=b_priv)
    assert r.status_code == 403 and r.json()["code"] == "bad_token"
    r, _ = _signed(client, "join", {**body, "version": "0.0.1"}, node_id="joining", key=b_priv)
    assert r.status_code in (403, 409)
    assert client.delete(f"/api/v1/ha/join-tokens/{tok['id']}").status_code == 204
    assert client.get("/api/v1/ha/join-tokens").json() == []
    events = client.get("/api/v1/ha/events").json()
    assert [e["event_type"] for e in events][-2:] == ["node_joined", "ha_enabled"]


# ------------------------------------------------------------------ peer endpoints


def test_peer_health_heartbeat_manifest_file_run(node):
    client, app, settings, fake, priv, pub = node  # noqa: RUF059
    b_priv, b_pub = protocol.new_keypair()
    mine, b = _make_primary(settings, pub, b_pub)  # noqa: RUF059
    b_id = str(b.id)
    fake.results["status"] = {
        "holds_address": True,
        "replication": {"db_role": "primary", "state": "streaming", "lag_bytes": 10},
    }
    r, nonce = _signed(client, "health", {}, node_id=b_id, key=b_priv)
    assert r.status_code == 200, r.text
    health = _check_answer(r, nonce, pub)
    assert health["role"] == "primary" and health["epoch"] == 1 and health["db_role"] == "primary"
    assert health["version"] == __version__ and health["holds_address"] is True

    r, nonce = _signed(
        client,
        "heartbeat",
        {
            "role": "secondary",
            "state": "online",
            "epoch": 1,
            "db_role": "standby",
            "replication": {"receiver": "streaming"},
            "software_version": __version__,
            "sync_at": utcnow().isoformat(),
        },
        node_id=b_id,
        key=b_priv,
    )
    assert r.status_code == 200 and _check_answer(r, nonce, pub)["epoch"] == 1
    row = _local_row("veyra-b")
    assert row.db_role == "standby" and row.replication == {"receiver": "streaming"}
    assert row.last_heartbeat_at is not None

    # Signature checks: wrong key, replayed nonce, unknown node, stale time.
    r, _ = _signed(client, "health", {}, node_id=b_id, key=priv)
    assert r.status_code == 401 and r.json()["code"] == "bad_signature"
    body = peer.encode({})
    ts, nonce = str(int(time.time())), protocol.new_nonce()
    headers = {
        protocol.H_INSTANCE: b_id,
        protocol.H_TIMESTAMP: ts,
        protocol.H_NONCE: nonce,
        protocol.H_SIGNATURE: protocol.sign(
            b_priv, protocol.request_string("POST", peer.path_for("health"), ts, nonce, body)
        ),
    }
    assert client.post(peer.path_for("health"), content=body, headers=headers).status_code == 200
    r = client.post(peer.path_for("health"), content=body, headers=headers)
    assert r.status_code == 401 and r.json()["code"] == "replayed"
    r, _ = _signed(client, "health", {}, node_id=str(uuid.uuid4()), key=b_priv)
    assert r.status_code == 401 and r.json()["code"] == "unknown_node"

    # Manifest and file.
    prompts = settings.data_dir / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "hello.wav").write_bytes(b"RIFF" * 10)
    (settings.config_dir / "secrets" / "x").write_text("s")
    r, nonce = _signed(client, "manifest", {}, node_id=b_id, key=b_priv)
    entries = _check_answer(r, nonce, pub)["entries"]
    paths = [e["path"] for e in entries]
    assert "data/prompts/hello.wav" in paths and "etc/secrets/x" in paths
    assert "etc/secrets/node.key" not in paths
    r, nonce = _signed(client, "file", {"path": "data/prompts/hello.wav"}, node_id=b_id, key=b_priv)
    assert r.status_code == 200 and r.content == b"RIFF" * 10
    _verify_answer(r, nonce, pub)  # the streamed body is covered by the signature
    r, _ = _signed(client, "file", {"path": "etc/secrets/node.key"}, node_id=b_id, key=b_priv)
    assert r.status_code == 404
    r, _ = _signed(client, "file", {"path": "data/prompts/../x"}, node_id=b_id, key=b_priv)
    assert r.status_code == 404

    # run: only the allowed verbs reach the agent.
    fake.results["freeze"] = {"frozen": True}
    r, nonce = _signed(client, "run", {"verb": "freeze", "args": {}}, node_id=b_id, key=b_priv)
    assert r.status_code == 200 and _check_answer(r, nonce, pub)["result"] == {"frozen": True}
    assert fake.calls[-1][0] == "freeze"
    r, _ = _signed(client, "run", {"verb": "fence", "args": {}}, node_id=b_id, key=b_priv)
    assert r.status_code == 403 and "fence" not in fake.verbs()
    fake.results["engine-stop"] = RuntimeError("engine is busy")
    r, _ = _signed(client, "run", {"verb": "engine-stop", "args": {}}, node_id=b_id, key=b_priv)
    assert r.status_code == 409 and r.json()["code"] == "refused"


# ------------------------------------------------------------------ switchover, failover, nodes


def test_switchover_preconditions_and_start(node):
    client, app, settings, fake, priv, pub = node  # noqa: RUF059
    b_priv, b_pub = protocol.new_keypair()  # noqa: RUF059
    mine, b = _make_primary(settings, pub, b_pub)
    fake.results["status"] = {"holds_address": True, "replication": {"db_role": "primary"}}
    chk = client.get("/api/v1/ha/switchover-check", params={"target": "veyra-b"}).json()
    assert not chk["ok"] and any("not streaming" in p for p in chk["problems"])
    r = client.post("/api/v1/ha/switchover", json={"target": "veyra-b"})
    assert r.status_code == 409 and r.json()["code"] == "preconditions"
    fake.results["status"] = {
        "holds_address": True,
        "replication": {"db_role": "primary", "state": "streaming", "lag_bytes": 100},
    }
    assert client.get("/api/v1/ha/switchover-check", params={"target": "veyra-b"}).json()["ok"]
    # The call goes to the peer's /ha/peer/run (here: the same app, which
    # treats the caller as its own peer row) and from there to its agent.
    with session_scope() as db:
        me = service.node_by_name(db, mine.node_name)
        me.public_key = pub  # the "peer" verifying our call is ourselves in this test
    _state(settings).save_node(
        NodeState(
            node_id=str(mine.id),
            node_name=mine.node_name,
            address="10.0.0.1",
            role="primary",
            epoch=1,
            peer=Peer(str(mine.id), "veyra-b", "10.0.0.2", "https://veyra-a", pub),
            service=ServiceAddress("veyra", "10.0.0.10", 24, "eth0"),
        )
    )
    # Our own row must look like the target to pass _calling_node: name differs.
    with session_scope() as db:
        me = service.node_by_name(db, mine.node_name)
        bb = service.node_by_name(db, "veyra-b")
        bb.public_key = pub
    _state(settings).save_node(
        NodeState(
            node_id=str(b.id),
            node_name=mine.node_name,
            address="10.0.0.1",
            role="primary",
            epoch=1,
            peer=Peer(str(b.id), "veyra-b", "10.0.0.2", "https://veyra-a", pub),
            service=ServiceAddress("veyra", "10.0.0.10", 24, "eth0"),
        )
    )
    r = client.post("/api/v1/ha/switchover", json={"target": "veyra-b"})
    assert r.status_code == 200, r.text
    assert r.json()["operation"]["kind"] == "switchover"
    assert fake.verbs()[-1] == "switchover" and fake.calls[-1][1]["actor"] == ADMIN_EMAIL
    events = client.get("/api/v1/ha/events").json()
    assert events[0]["event_type"] == "switchover_started"

    # Failover is refused on a primary; a secondary asks its agent.
    r = client.post("/api/v1/ha/failover", json={"confirm_fenced": True})
    assert r.status_code == 409
    n = _state(settings).node()
    n.role = "secondary"
    _state(settings).save_node(n)
    r = client.post("/api/v1/ha/failover", json={"confirm_fenced": True})
    assert r.status_code == 200 and fake.verbs()[-1] == "failover"
    assert fake.calls[-1][1]["confirm_fenced"] is True
    # Resume and rejoin reach the agent too.
    assert client.post("/api/v1/ha/resume").status_code == 200 and fake.verbs()[-1] == "resume"
    r = client.post(f"/api/v1/ha/nodes/{b.id}/rejoin")
    assert r.status_code == 200
    # Remove: only at the primary.
    assert client.delete(f"/api/v1/ha/nodes/{b.id}").status_code == 409
    n.role = "primary"
    _state(settings).save_node(n)
    fake.results["remove-peer"] = {"removed": True, "deployment_mode": "standalone"}
    r = client.delete(f"/api/v1/ha/nodes/{b.id}")
    assert r.status_code == 200 and fake.verbs()[-1] == "remove-peer"


def test_fencing_and_sync_settings(node):
    client, app, settings, fake, priv, pub = node  # noqa: RUF059
    r = client.put("/api/v1/ha/fencing", json={"enabled": True, "url": "https://pve:8006"})
    assert r.status_code == 400 and r.json()["code"] == "fencing_incomplete"
    r = client.put(
        "/api/v1/ha/fencing",
        json={
            "enabled": True,
            "url": "https://pve:8006/",
            "token_id": "root@pam!veyra",
            "token_secret": "s3cret",
            "pve_node": "pve1",
            "vms": {"veyra-a": {"vmid": 101}, "veyra-b": {"vmid": 102}},
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["has_secret"] and "secret" not in out and out["url"] == "https://pve:8006"
    assert fake.verbs()[-1] == "set-fencing"
    assert fake.calls[-1][1]["config"]["secret"] == "s3cret"  # the agent keeps the secret
    assert client.get("/api/v1/ha/fencing").json()["has_secret"]
    # Secret kept when omitted.
    r = client.put("/api/v1/ha/fencing", json={**out, "url": "https://pve2:8006"})
    assert r.json()["has_secret"] and r.json()["url"] == "https://pve2:8006"
    st = client.get("/api/v1/ha/status").json()
    assert st["fencing"]["configured"] is True
    r = client.put("/api/v1/ha/sync", json={"recordings": False})
    assert r.json() == {"recordings": False, "interval": 30} and fake.verbs()[-1] == "set-sync"


# ------------------------------------------------------------------ standby


def test_write_blocked_rules():
    assert write_blocked("/api/v1/extensions", Flags()) is None
    assert write_blocked("/api/v1/extensions", Flags(standby=True)) == "ha_standby"
    assert write_blocked("/api/v1/extensions", Flags(frozen=True)) == "ha_switchover"
    assert write_blocked("/api/v1/ha/failover", Flags(standby=True)) is None
    assert write_blocked("/api/v1/auth/login", Flags(standby=True)) is None
    s = StandbySessions(ttl=10)
    uid = uuid.uuid4()
    token, csrf = s.create(uid, now=100.0)
    assert s.resolve(token, now=105.0).user_id == uid and s.csrf_ok(s.resolve(token, 105.0), csrf)
    assert s.resolve(token, now=111.0) is None
    assert s.resolve("other", now=105.0) is None
    s.revoke(token)
    assert len(s) == 0 or s.resolve(token, now=105.0) is None


def test_standby_refuses_writes_and_signs_in_from_memory(node):
    client, app, settings, fake, priv, pub = node  # noqa: RUF059
    app.state.ha_guard.flags = lambda now=None: Flags(standby=True, checked_at=time.monotonic())
    assert client.get("/api/v1/extensions").status_code == 200
    r = client.post("/api/v1/organizations", json={"name": "X", "slug": "x"})
    assert r.status_code == 503 and r.json()["code"] == "ha_standby"
    # The HA routes still answer.
    assert client.post("/api/v1/ha/resume").status_code == 200
    # Sign-in: no session row is written; the session lives in the process.
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    r = client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    assert len(app.state.standby_sessions) == 1
    client.headers.update(csrf_headers(client))
    me = client.get("/api/v1/auth/session").json()
    assert me["user"]["email"] == ADMIN_EMAIL and me["is_platform_admin"]
    # Writes other than HA still refused; CSRF still checked.
    assert client.post("/api/v1/organizations", json={"name": "X", "slug": "x"}).status_code == 503
    assert client.post("/api/v1/ha/resume", headers={"X-CSRF-Token": "nope"}).status_code == 403
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/session").status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
    assert r.status_code == 401
    # A frozen primary says so.
    app.state.ha_guard.flags = lambda now=None: Flags(frozen=True, checked_at=time.monotonic())
    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    r = client.post("/api/v1/organizations", json={"name": "X", "slug": "x"})
    assert r.status_code == 503 and r.json()["code"] == "ha_switchover"


def test_standby_login_requires_platform_admin(node):
    client, app, settings, fake, priv, pub = node  # noqa: RUF059
    r = client.post(
        "/api/v1/users",
        json={
            "email": "ro@district.local",
            "display_name": "Read only",
            "password": "a long enough password 1",
        },
    )
    assert r.status_code in (200, 201), r.text
    app.state.ha_guard.flags = lambda now=None: Flags(standby=True, checked_at=time.monotonic())
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "ro@district.local", "password": "a long enough password 1"},
    )
    assert r.status_code == 403 and r.json()["code"] == "ha_standby"


# ------------------------------------------------------------------ alerts


def test_ha_alert_checks(node):
    from veyra.reporting import alerts

    client, app, settings, fake, priv, pub = node  # noqa: RUF059
    b_priv, b_pub = protocol.new_keypair()  # noqa: RUF059
    mine, b = _make_primary(settings, pub, b_pub)  # noqa: RUF059
    now = utcnow()
    with session_scope() as db:
        assert alerts.check_ha(db, settings, now, 64) == [] or all(
            f.rule != "node_offline" for f in alerts.check_ha(db, settings, now, 64)
        )
        row = service.node_by_name(db, "veyra-b")
        row.last_heartbeat_at = now - timedelta(minutes=5)
        me = service.node_by_name(db, mine.node_name)
        me.replication = {
            "db_role": "primary",
            "state": "streaming",
            "lag_bytes": 100 * 1024 * 1024,
        }
        db.flush()
        found = {f.rule for f in alerts.check_ha(db, settings, now, 64)}
        assert found == {"node_offline", "replication_lag"}
        row.last_heartbeat_at = now
        row.replication = {"receiver": "stopped"}
        row.sync_at = now - timedelta(minutes=10)
        me.replication = {"db_role": "primary", "state": None}
        db.flush()
        found = {f.rule for f in alerts.check_ha(db, settings, now, 64)}
        assert found == {"replication_broken", "ha_sync_failed"}
    n = _state(settings).node()
    n.state = "isolated"
    _state(settings).save_node(n)
    with session_scope() as db:
        assert "node_isolated" in {f.rule for f in alerts.check_ha(db, settings, now, 64)}
        inst = db.scalar(select(Installation))
        inst.deployment_mode = "standalone"
        db.flush()
        assert alerts.check_ha(db, settings, now, 64) == []
