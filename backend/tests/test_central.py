# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 15 (docs/CENTRAL_MANAGEMENT.md): enrollment, signed check-ins,
policies, commands, revocation and leaving. The test installation is both
the console and its own instance; the instance's HTTP client is routed into
the same app."""

from __future__ import annotations

import json
import time
import uuid

import httpx
import pytest

from veyra.central import console, member, protocol
from veyra.central import policy as central_policy
from veyra.core.db import session_scope
from veyra.core.models import (
    AlertRule,
    CentralCommand,
    CentralInstance,
    FirewallRule,
    UpdatePolicy,
)
from veyra.core.security.crypto import load_installation_key

BASE = "http://127.0.0.1"


@pytest.fixture
def routed(admin, monkeypatch):
    """The instance's requests go to the test app (the console)."""
    monkeypatch.setattr(protocol, "transport", admin._transport)
    return admin


def _console(admin) -> dict:
    r = admin.put("/api/v1/central/console", json={"enabled": True})
    assert r.status_code == 200, r.text
    return r.json()


def _token(admin, **body) -> dict:
    r = admin.post("/api/v1/central/tokens", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _enroll(admin, tok: dict, **over) -> httpx.Response:
    body = {"url": BASE, "token": tok["token"], "fingerprint": tok["fingerprint"], **over}
    return admin.post("/api/v1/central/membership/enroll", json=body)


def _check_in(app):
    with session_scope() as db:
        return member.check_in(
            db, app.state.settings, load_installation_key(app.state.settings), None
        )


def test_protocol_signatures():
    priv, pub = protocol.new_keypair()
    data = protocol.request_string("POST", "/x", "1", "n", b"{}")
    sig = protocol.sign(priv, data)
    assert protocol.verify(pub, data, sig)
    assert not protocol.verify(pub, data + b"x", sig)
    _, other = protocol.new_keypair()
    assert not protocol.verify(other, data, sig)
    fp = protocol.fingerprint(pub)
    assert len(fp) == 39 and fp.count("-") == 7
    assert protocol.normalize_fingerprint(fp.upper()) == protocol.normalize_fingerprint(fp)
    assert protocol.fresh(str(int(time.time()))) and not protocol.fresh("1")
    assert protocol.check_console_url("https://c.example.org/") == "https://c.example.org"
    assert protocol.check_console_url("http://127.0.0.1:8100") == "http://127.0.0.1:8100"
    for bad in ("http://c.example.org", "ftp://x", "https://c.example.org/path"):
        with pytest.raises(protocol.ProtocolError):
            protocol.check_console_url(bad)


def test_policy_validation():
    ok = central_policy.validate_document(
        {
            "updates": {"policy": {"mode": "notify"}, "recipients": ["Ops@Example.org"]},
            "firewall_allow": [{"cidr": "10.1.2.3"}],
            "alert_recipients": ["noc@example.org"],
            "notice": "  Maintenance Saturday  ",
        }
    )
    assert ok.firewall_allow and ok.firewall_allow[0].cidr == "10.1.2.3/32"
    assert ok.notice == "Maintenance Saturday"
    assert ok.updates and ok.updates.recipients == ["ops@example.org"]
    for bad in (
        {"firewall_allow": [{"cidr": "not-an-address"}]},
        {"alert_recipients": ["nobody"]},
        {"updates": {"policy": {"mode": "auto_install_window"}}},
    ):
        with pytest.raises(ValueError):
            central_policy.validate_document(bad)


def test_enroll_check_in_policy_commands_revoke_leave(routed, app):
    admin = routed
    assert admin.post("/api/v1/central/tokens", json={}).status_code == 409  # console off
    con = _console(admin)
    assert con["enabled"] and con["fingerprint"]
    policy = admin.post(
        "/api/v1/central/policies",
        json={
            "name": "Districts",
            "is_default": True,
            "document": {
                "firewall_allow": [{"cidr": "10.20.0.0/16", "comment": "Management"}],
                "alert_recipients": ["noc@example.org"],
                "notice": "Maintenance Saturday 6-8",
                "updates": {
                    "policy": {
                        "mode": "download_approve",
                        "maintenance_window": {
                            "days": ["sun"],
                            "start": "02:00",
                            "duration_minutes": 120,
                        },
                    }
                },
            },
        },
    )
    assert policy.status_code == 201, policy.text
    tok = _token(admin, label="North")
    # Wrong fingerprint: refused before anything is saved.
    r = _enroll(admin, tok, fingerprint="0000-0000-0000-0000-0000-0000-0000-0000")
    assert r.status_code == 409 and "fingerprint" in r.json()["detail"]
    # The token was spent by that attempt; a fresh one enrolls.
    r = _enroll(admin, tok)
    assert r.status_code == 409 and "token" in r.json()["detail"]
    tok = _token(admin, label="North")
    r = _enroll(admin, tok)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["enrolled"] and m["console_fingerprint"] == con["fingerprint"]
    assert _enroll(admin, _token(admin)).json()["detail"].startswith("This installation is already")

    # First check-in: the report arrives, the policy comes back and is applied.
    state = _check_in(app)
    assert state["last_error"] is None, state
    results = state["policy"]["results"]
    assert results == {
        "updates": "applied",
        "firewall_allow": "applied",
        "alert_recipients": "applied",
        "notice": "applied",
    }
    with session_scope() as db:
        assert db.query(FirewallRule).filter_by(origin="central", cidr="10.20.0.0/16").count() == 1
        assert all(r.recipients == ["noc@example.org"] for r in db.query(AlertRule))
        assert db.get(UpdatePolicy, "veyra_core").mode == "download_approve"
    notice = admin.get("/api/v1/central/notice").json()
    assert notice["text"] == "Maintenance Saturday 6-8" and notice["managed"]["updates"]
    rows = admin.get("/api/v1/central/instances").json()
    assert len(rows) == 1 and rows[0]["label"] == "North"
    assert (
        rows[0]["status"] in ("ok", "degraded", "online") and rows[0]["policy_state"] == "pending"
    )
    # The next check-in reports the applied version: nothing is resent.
    state = _check_in(app)
    rows = admin.get("/api/v1/central/instances").json()
    assert rows[0]["policy_state"] == "applied"

    # Refusing a section withdraws it at once and is reported.
    r = admin.put("/api/v1/central/membership/accepted", json={"firewall_allow": False})
    assert r.json()["policy"]["results"]["firewall_allow"] == "refused"
    with session_scope() as db:
        assert db.query(FirewallRule).filter_by(origin="central").count() == 0
    _check_in(app)
    assert admin.get("/api/v1/central/instances").json()[0]["policy_state"] == "partly refused"

    # Commands: delivered once, results come back with the next check-in.
    iid = rows[0]["instance_id"]
    r = admin.post(f"/api/v1/central/instances/{iid}/commands", json={"kind": "check_updates"})
    assert r.status_code == 201
    r = admin.post(
        f"/api/v1/central/instances/{iid}/commands",
        json={"kind": "approve_update", "arguments": {"version": "9.9.9", "when": "soon"}},
    )
    assert r.status_code == 422
    r = admin.post(
        f"/api/v1/central/instances/{iid}/commands",
        json={"kind": "approve_update", "arguments": {"version": "9.9.9", "when": "now"}},
    )
    state = _check_in(app)
    assert [p["outcome"] for p in state["pending_results"]] == ["failed", "failed"]
    _check_in(app)
    detail = admin.get(f"/api/v1/central/instances/{iid}").json()
    outcomes = {c["kind"]: c["outcome"] for c in detail["commands"]}
    assert outcomes == {"check_updates": "failed", "approve_update": "failed"}
    assert "not among the available" in next(
        c["message"] for c in detail["commands"] if c["kind"] == "approve_update"
    )
    assert detail["report"]["telephony"]["extensions"] == 0 and detail["samples"]
    # Commands refused locally.
    admin.put("/api/v1/central/membership/accepted", json={"commands": False})
    admin.post(f"/api/v1/central/instances/{iid}/commands", json={"kind": "refresh_catalogs"})
    state = _check_in(app)
    assert state["pending_results"][0]["outcome"] == "refused"

    # Revoke: the instance learns it at the next check-in and drops central settings.
    assert admin.delete(f"/api/v1/central/instances/{iid}").status_code == 409
    assert admin.post(f"/api/v1/central/instances/{iid}/revoke").json()["status"] == "revoked"
    state = _check_in(app)
    assert state["revoked"] and "Revoked" in state["last_error"]
    assert admin.get("/api/v1/central/notice").json()["text"] is None
    with session_scope() as db:
        assert not member.due(db)
    # Leave, then re-enroll with a new token.
    assert admin.post("/api/v1/central/membership/leave").json() == {"enrolled": False}
    r = _enroll(admin, _token(admin))
    assert r.status_code == 200 and not r.json()["revoked"]
    with session_scope() as db:
        assert db.get(CentralInstance, uuid.UUID(iid)).revoked_at is None


def test_check_in_security(routed, app):
    admin = routed
    _console(admin)
    assert _enroll(admin, _token(admin)).status_code == 200
    with session_scope() as db:
        m = member.membership(db)
        inst = db.query(CentralInstance).one()
    priv = load_installation_key(app.state.settings).decrypt(m["private_key"], protocol.KEY_PURPOSE)
    body = json.dumps({"identity": {"name": "x"}}).encode()

    def post(headers: dict, content: bytes = body) -> httpx.Response:
        return admin.post(protocol.CHECK_IN_PATH, content=content, headers=headers)

    ts, nonce = str(int(time.time())), protocol.new_nonce()
    good = {
        protocol.H_INSTANCE: str(inst.instance_id),
        protocol.H_TIMESTAMP: ts,
        protocol.H_NONCE: nonce,
        protocol.H_SIGNATURE: protocol.sign(
            priv, protocol.request_string("POST", protocol.CHECK_IN_PATH, ts, nonce, body)
        ),
    }
    r = post(good)
    assert r.status_code == 200 and r.headers.get(protocol.H_CONSOLE_SIGNATURE)
    answer = protocol.check_answer(r, console_key := m["console_public_key"], nonce)
    assert "commands" in answer
    # The same request again is a replay.
    assert post(good).json()["code"] == "replayed"
    # A changed body no longer matches the signature.
    assert post({**good, protocol.H_NONCE: "other"}, body + b" ").json()["code"] == "bad_signature"
    # An old timestamp is refused.
    old = str(int(time.time()) - 3600)
    stale = {**good, protocol.H_TIMESTAMP: old, protocol.H_NONCE: "n2"}
    assert post(stale).json()["code"] == "stale"
    # Unknown instance.
    assert (
        post({**good, protocol.H_INSTANCE: str(uuid.uuid4())}).json()["code"] == "unknown_instance"
    )
    # The answer cannot be replayed against another request's nonce.
    with pytest.raises(protocol.ProtocolError):
        protocol.check_answer(r, console_key, "another-nonce")


def test_console_offline_keeps_settings_and_alerts(routed, app, monkeypatch):
    admin = routed
    _console(admin)
    admin.post(
        "/api/v1/central/policies",
        json={"name": "P", "is_default": True, "document": {"notice": "Hello"}},
    )
    assert _enroll(admin, _token(admin)).status_code == 200
    _check_in(app)
    # The console goes away: the instance records the error and keeps its settings.
    monkeypatch.setattr(
        protocol,
        "transport",
        httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("down"))),
    )
    state = _check_in(app)
    assert "not reachable" in state["last_error"]
    assert admin.get("/api/v1/central/notice").json()["text"] == "Hello"
    # The console raises "instance not checking in" once the threshold passes.
    from datetime import timedelta

    from veyra.core.models.base import utcnow
    from veyra.reporting import alerts

    with session_scope() as db:
        inst = db.query(CentralInstance).one()
        inst.last_seen_at = utcnow() - timedelta(minutes=30)
    with session_scope() as db:
        findings = alerts.check_central(db, utcnow())
        assert [f.rule for f in findings] == ["instance_offline"]
    rows = admin.get("/api/v1/central/instances").json()
    assert rows[0]["status"] == "offline"


def test_permissions_and_bulk(routed, app):
    admin = routed
    _console(admin)
    assert _enroll(admin, _token(admin)).status_code == 200
    iid = admin.get("/api/v1/central/instances").json()[0]["instance_id"]
    r = admin.post(
        "/api/v1/central/commands",
        json={"instance_ids": [iid, str(uuid.uuid4())], "kind": "check_updates"},
    )
    assert r.json() == {"queued": 1, "skipped": [r.json()["skipped"][0]]}
    with session_scope() as db:
        assert db.query(CentralCommand).count() == 1
        console.expire_and_prune(db)
    r = admin.post("/api/v1/central/policies", json={"name": "Bad", "document": {"notice": 5}})
    assert r.status_code == 422
    sections = admin.get("/api/v1/central/policy-sections").json()
    assert sections["sections"] == list(central_policy.SECTIONS)
