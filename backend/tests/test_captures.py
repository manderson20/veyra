# SPDX-License-Identifier: AGPL-3.0-or-later
"""Packet captures (docs/CALL_FEATURES.md §2.2): filter validation and the
expression, the pcap reader and SIP summary, the root runner against a fake
tcpdump, the database side, the API and retention."""

from __future__ import annotations

import json
import os
import stat
import struct
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fake_adapter import FakeAdapter

from veyra.core import retention
from veyra.core.db import session_scope
from veyra.core.models import Capture
from veyra.diagnostics import captures, filters, pcap, runner
from veyra.telephony.adapter import Registration

# ------------------------------------------------------------------ filters


def test_filter_normalises_and_builds_the_expression():
    spec = filters.normalize(
        {
            "hosts": ["192.168.1.20", " sip.carrier.example ", "fd00::20"],
            "nets": ["10.0.0.0/255.255.0.0"],
            "ports": ["5060", 5061, 5060],
            "portranges": [[10000, 20000]],
            "rtp": 1,
        }
    )
    assert spec["hosts"] == ["192.168.1.20", "fd00::20", "sip.carrier.example"]
    assert spec["nets"] == ["10.0.0.0/16"] and spec["ports"] == [5060, 5061]
    assert spec["portranges"] == [[10000, 20000]] and spec["rtp"] is True
    assert filters.expression(spec) == (
        "(host 192.168.1.20 or host fd00::20 or host sip.carrier.example or net 10.0.0.0/16) "
        "and (port 5060 or port 5061 or portrange 10000-20000)"
    )
    assert filters.expression({"ports": [5060]}) == "(port 5060)"
    assert (
        filters.describe({"ports": [5060], "portranges": [[1, 2]]}) == "all SIP (ports 5060 + RTP)"
    )


@pytest.mark.parametrize(
    "spec",
    [
        {"ports": []},
        {"hosts": ["1.2.3.4; rm -rf /"], "ports": [5060]},
        {"hosts": ["not a host name"], "ports": [5060]},
        {"hosts": ["1.2.3"], "ports": [5060]},
        {"nets": ["10.0.0.0/33"], "ports": [5060]},
        {"ports": [0]},
        {"ports": ["x"]},
        {"portranges": [[20000, 10000]], "ports": [5060]},
        {"portranges": [[1]], "ports": [5060]},
        {"ports": [5060], "expression": "anything"},
        {"hosts": [f"10.0.0.{i}" for i in range(17)], "ports": [5060]},
    ],
)
def test_filter_refuses_bad_input(spec):
    with pytest.raises(filters.FilterError):
        filters.normalize(spec)


# ------------------------------------------------------------------ pcap


def _udp4(src: str, sport: int, dst: str, dport: int, payload: bytes) -> bytes:
    udp = struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload
    total = 20 + len(udp)
    ip = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        total,
        1,
        0,
        64,
        17,
        0,
        bytes(int(x) for x in src.split(".")),
        bytes(int(x) for x in dst.split(".")),
    )
    return ip + udp


def _sll2(ip_packet: bytes) -> bytes:
    # protocol, reserved, ifindex, hatype, pkttype, halen, addr[8]
    return struct.pack("!HHiHBB8s", 0x0800, 0, 2, 1, 0, 6, b"\0" * 8) + ip_packet


def _pcap(records: list[tuple[float, bytes]], linktype: int = pcap.LINKTYPE_LINUX_SLL2) -> bytes:
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 262144, linktype)
    for ts, frame in records:
        sec, usec = int(ts), int((ts - int(ts)) * 1_000_000)
        out += struct.pack("<IIII", sec, usec, len(frame), len(frame)) + frame
    return out


REGISTER = (
    b"REGISTER sip:veyra.example SIP/2.0\r\n"
    b"Via: SIP/2.0/UDP 192.168.1.20:5060;branch=z9hG4bKabc;rport\r\n"
    b"From: <sip:1001@veyra.example>;tag=1\r\n"
    b"To: <sip:1001@veyra.example>\r\n"
    b"i: reg-1@192.168.1.20\r\n"
    b"CSeq: 1 REGISTER\r\n"
    b"Contact: <sip:1001@192.168.1.20:5060>\r\n"
    b"User-Agent: PolycomVVX-VVX_411-UA/6.4.3\r\n"
    b"Content-Length: 0\r\n\r\n"
)
UNAUTHORIZED = (
    b"SIP/2.0 401 Unauthorized\r\n"
    b"Via: SIP/2.0/UDP 192.168.1.20:5060;branch=z9hG4bKabc;rport=5060\r\n"
    b"From: <sip:1001@veyra.example>;tag=1\r\n"
    b"To: <sip:1001@veyra.example>;tag=z\r\n"
    b"Call-ID: reg-1@192.168.1.20\r\n"
    b"CSeq: 1 REGISTER\r\n"
    b'WWW-Authenticate: Digest realm="asterisk",nonce="x"\r\n'
    b"Server: Asterisk PBX 22\r\n"
    b"Content-Length: 0\r\n\r\n"
)


def test_pcap_reader_and_sip_summary(tmp_path):
    t0 = 1792278500.25
    frames = [
        (t0, _sll2(_udp4("192.168.1.20", 5060, "192.168.1.1", 5060, REGISTER))),
        (t0 + 0.01, _sll2(_udp4("192.168.1.1", 5060, "192.168.1.20", 5060, UNAUTHORIZED))),
        (t0 + 0.02, _sll2(_udp4("192.168.1.20", 12000, "192.168.1.1", 12000, b"\x80\x00rtp"))),
        (t0 + 0.03, b"\x00\x00short"),
    ]
    path = tmp_path / "c.pcap"
    path.write_bytes(_pcap(frames))
    out = pcap.summary(path)
    assert out["packets_read"] == 4 and out["truncated"] is False
    assert len(out["messages"]) == 2
    req, resp = out["messages"]
    assert req["kind"] == "request" and req["method"] == "REGISTER"
    assert (req["src"], req["sport"], req["dst"], req["dport"]) == (
        "192.168.1.20",
        5060,
        "192.168.1.1",
        5060,
    )
    assert req["call_id"] == "reg-1@192.168.1.20"  # compact header form
    assert req["user_agent"].startswith("PolycomVVX") and req["at"] == "2026-10-17T23:08:20.250Z"
    assert resp["kind"] == "response" and resp["status"] == 401 and resp["method"] == "REGISTER"
    assert resp["user_agent"] == "Asterisk PBX 22"
    assert len(out["dialogs"]) == 1
    d = out["dialogs"][0]
    assert d["messages"] == 2 and d["method"] == "REGISTER" and d["last_status"] == 401
    assert d["parties"] == ["192.168.1.20", "192.168.1.1"]
    # Ethernet with a VLAN tag, and a message cap.
    eth = (
        b"\xff" * 6
        + b"\x00" * 6
        + b"\x81\x00\x00\x05\x08\x00"
        + _udp4("10.0.0.2", 5060, "10.0.0.1", 5060, REGISTER)
    )
    path.write_bytes(_pcap([(t0, eth), (t0 + 1, eth)], pcap.LINKTYPE_ETHERNET))
    out = pcap.summary(path, max_messages=1)
    assert len(out["messages"]) == 1 and out["truncated"] is True
    with pytest.raises(pcap.PcapError):
        pcap.summary(Path(path).write_bytes(b"junk" * 10) and path)
    path.write_bytes(b"\x0a\x0d\x0d\x0a" + b"\0" * 40)
    with pytest.raises(pcap.PcapError, match="pcapng"):
        pcap.summary(path)


# ------------------------------------------------------------------ runner


def _fake_tcpdump(tmp_path: Path, behaviour: str) -> str:
    """A stand-in for tcpdump: writes a pcap header to the -w file, then
    ``sleeps`` until terminated (printing the capture count), ``grows`` the
    file quickly, or ``fails`` at once."""
    script = tmp_path / "tcpdump"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import signal, struct, sys, time\n"
        "args = sys.argv[1:]\n"
        "assert args[:9] == ['-i', 'any', '-nn', '-s', '0', '-Z', 'root', '-U', '-w'], args\n"
        "path, expr = args[9], args[10]\n"
        f"mode = {behaviour!r}\n"
        "if mode == 'fails':\n"
        '    sys.stderr.write("tcpdump: can\'t parse filter expression\\n"); sys.exit(1)\n'
        "n = 0\n"
        "def done(*_):\n"
        "    sys.stderr.write(f'{n} packets captured\\n{n} packets received by filter\\n')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, done)\n"
        "f = open(path, 'wb')\n"
        "f.write(struct.pack('<IHHiIII', 0xA1B2C3D4, 2, 4, 0, 0, 262144, 276)); f.flush()\n"
        "sys.stderr.write('tcpdump: listening on any, link-type LINUX_SLL2\\n')\n"
        "sys.stderr.flush()\n"
        "while True:\n"
        "    time.sleep(0.05)\n"
        "    if mode == 'grows':\n"
        "        f.write(b'x' * 65536); f.flush(); n += 1\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


class _Recorder:
    def __init__(self, capture: dict) -> None:
        self.capture = capture
        self.records: list[dict] = []

    def __call__(self, argv):
        argv = list(argv)
        assert argv[:4] == ["runuser", "-u", "veyra", "--"]
        if argv[5:7] == ["capture", "show"]:
            return runner.Result(0, json.dumps(self.capture))
        if argv[5:7] == ["capture", "record"]:
            self.records.append(json.loads(argv[8]))
            return runner.Result(0, "{}")
        raise AssertionError(argv)


def _definition(**kw) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "filter": {"hosts": ["192.168.1.20"], "ports": [5060]},
        "duration_seconds": 10,
        "size_limit_mb": 1,
        **kw,
    }


def test_runner_enforces_duration_and_records(tmp_path):
    d = _definition()
    rec = _Recorder(d)
    clock = {"t": 0.0}

    def tick(_s: float) -> None:
        time.sleep(0.1)  # let the fake start, as a real capture would run for seconds
        clock["t"] += 4.0  # three polls cover the ten seconds

    payload = runner.run_capture(
        d["id"],
        run=rec,
        binary=_fake_tcpdump(tmp_path, "sleeps"),
        directory=tmp_path / "captures",
        sleep=tick,
        clock=lambda: clock["t"],
        handle_signals=False,
    )
    assert payload["state"] == "finished" and payload["packets"] == 0 and payload["error"] is None
    assert payload["bytes"] == 24 and Path(payload["path"]).is_file()
    assert oct(os.stat(payload["path"]).st_mode & 0o777) == "0o640"
    assert [r["state"] for r in rec.records] == ["running", "finished"]
    assert rec.records[0]["path"] == payload["path"]


def test_runner_enforces_size_limit(tmp_path):
    d = _definition(duration_seconds=600, size_limit_mb=1)
    rec = _Recorder(d)
    payload = runner.run_capture(
        d["id"],
        run=rec,
        binary=_fake_tcpdump(tmp_path, "grows"),
        directory=tmp_path / "captures",
        sleep=time.sleep,
        handle_signals=False,
    )
    assert payload["state"] == "finished" and payload["error"] == "size limit reached"
    assert payload["bytes"] >= 1024 * 1024 and payload["packets"] >= 16


def test_runner_reports_tcpdump_failure_and_bad_rows(tmp_path):
    d = _definition()
    rec = _Recorder(d)
    payload = runner.run_capture(
        d["id"],
        run=rec,
        binary=_fake_tcpdump(tmp_path, "fails"),
        directory=tmp_path / "captures",
        sleep=lambda s: None,
        handle_signals=False,
    )
    assert payload["state"] == "failed" and "parse filter" in payload["error"]
    assert rec.records[-1]["state"] == "failed"
    # The expression is rebuilt from the fields: a bad stored filter never reaches tcpdump.
    bad = _definition(filter={"hosts": ["1.2.3.4 or 1"], "ports": [5060]})
    rec = _Recorder(bad)
    payload = runner.run_capture(
        bad["id"], run=rec, binary="/nonexistent", directory=tmp_path, handle_signals=False
    )
    assert payload["state"] == "failed" and "host name" in payload["error"]
    assert rec.records == [payload]
    assert runner.tcpdump_argv(Path("/x.pcap"), "(port 5060)")[-3:] == [
        "-w",
        "/x.pcap",
        "(port 5060)",
    ]


# ------------------------------------------------------------------ database side and API


@pytest.fixture
def unit(monkeypatch):
    calls: list[list[str]] = []

    class R:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(captures, "systemctl", lambda cmd: calls.append(cmd) or R())
    return calls


def _register(app, endpoint: str, host: str) -> None:
    adapter = FakeAdapter()
    adapter.contacts = [
        Registration(
            endpoint=endpoint,
            uri=f"sip:{endpoint}@{host}:5060",
            contact_host=host,
            contact_port=5060,
            source_host="203.0.113.7",
            source_port=41234,
        )
    ]
    app.state.telephony = adapter


def test_capture_api_flow(admin, app, client, unit, tmp_path):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    ext = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1001", "display_name": "Front Office"},
    ).json()
    # No phone registered: an extension target is refused with a reason.
    r = admin.post(
        "/api/v1/diagnostics/captures", json={"target": "extension", "extension_id": ext["id"]}
    )
    assert r.status_code == 409 and r.json()["code"] == "not_registered"
    _register(app, ext["endpoint_name"], "192.168.1.20")
    t = admin.get("/api/v1/diagnostics/captures/targets").json()
    assert t["sip_ports"] == [5060] and t["rtp_range"] == [10000, 20000]
    assert t["extensions"][0]["hosts"] == ["203.0.113.7"]  # the source address, not the contact
    r = admin.post(
        "/api/v1/diagnostics/captures",
        json={
            "target": "extension",
            "extension_id": ext["id"],
            "rtp": True,
            "duration_seconds": 60,
        },
    )
    assert r.status_code == 202, r.text
    row = r.json()
    assert row["state"] == "starting" and row["label"] == "Extension 1001 Front Office"
    assert row["expression"] == "(host 203.0.113.7) and (port 5060 or portrange 10000-20000)"
    assert row["rtp"] is True and row["downloadable"] is False
    assert unit[-1] == ["systemctl", "start", "--no-block", f"veyra-capture@{row['id']}.service"]
    # Validation at the edge.
    assert admin.post("/api/v1/diagnostics/captures", json={"target": "address"}).status_code == 400
    assert (
        admin.post(
            "/api/v1/diagnostics/captures", json={"target": "address", "address": "10.0.0.0/8; x"}
        ).json()["code"]
        == "bad_filter"
    )
    assert (
        admin.post(
            "/api/v1/diagnostics/captures", json={"target": "all_sip", "duration_seconds": 5}
        ).status_code
        == 422
    )
    # A second one may run; a third is refused.
    second = admin.post(
        "/api/v1/diagnostics/captures", json={"target": "address", "address": "10.0.0.0/8"}
    ).json()
    assert second["expression"] == "(net 10.0.0.0/8) and (port 5060)"
    r = admin.post("/api/v1/diagnostics/captures", json={"target": "all_sip"})
    assert r.status_code == 409 and r.json()["code"] == "too_many"
    # Nothing to download while it runs.
    assert admin.get(f"/api/v1/diagnostics/captures/{row['id']}/download").status_code == 409
    # The runner reports.
    pcap_path = Path(row["id"] + ".pcap")
    pcap_path = app.state.settings.captures_dir / pcap_path
    pcap_path.parent.mkdir(parents=True, exist_ok=True)
    pcap_path.write_bytes(
        _pcap([(1792278500.0, _sll2(_udp4("192.168.1.20", 5060, "192.168.1.1", 5060, REGISTER)))])
    )
    with session_scope() as db:
        captures.record(db, {"id": row["id"], "state": "running", "path": str(pcap_path)})
        captures.record(
            db,
            {
                "id": row["id"],
                "state": "finished",
                "bytes": pcap_path.stat().st_size,
                "packets": 1,
                "finished_at": "2026-10-17T22:30:00+00:00",
            },
        )
    lst = admin.get("/api/v1/diagnostics/captures").json()
    assert lst["running"] == 1 and lst["max_running"] == 2
    done = next(c for c in lst["captures"] if c["id"] == row["id"])
    assert done["state"] == "finished" and done["packets"] == 1 and done["downloadable"] is True
    # Download is audited and served as pcap.
    r = admin.get(f"/api/v1/diagnostics/captures/{row['id']}/download")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.tcpdump")
    assert (
        "veyra-capture-" in r.headers["content-disposition"]
        and r.content[:4] == b"\xd4\xc3\xb2\xa1"
    )
    # The SIP summary reads the file.
    sip = admin.get(f"/api/v1/diagnostics/captures/{row['id']}/sip").json()
    assert sip["messages"][0]["method"] == "REGISTER" and len(sip["dialogs"]) == 1
    actions = [
        e["action"] for e in admin.get("/api/v1/audit", params={"limit": 50}).json()["items"]
    ]
    for a in ("capture.start", "capture.download", "capture.view", "capture.run"):
        assert a in actions, actions
    # Stop goes through the unit; delete removes the file.
    r = admin.post(f"/api/v1/diagnostics/captures/{second['id']}/stop")
    assert r.status_code == 202
    assert unit[-1] == ["systemctl", "stop", "--no-block", f"veyra-capture@{second['id']}.service"]
    assert admin.delete(f"/api/v1/diagnostics/captures/{second['id']}").status_code == 409
    assert admin.delete(f"/api/v1/diagnostics/captures/{row['id']}").status_code == 200
    assert not pcap_path.exists()
    assert admin.get(f"/api/v1/diagnostics/captures/{row['id']}").status_code == 404
    assert all(
        c["id"] != row["id"] for c in admin.get("/api/v1/diagnostics/captures").json()["captures"]
    )
    # A record for a deleted capture changes nothing.
    with session_scope() as db:
        assert captures.record(db, {"id": row["id"], "state": "finished"}).state == "deleted"


def test_capture_stale_and_unit_failure(admin, app, monkeypatch):
    class Bad:
        returncode = 1
        stderr = "Failed to start veyra-capture@x.service: Access denied"

    monkeypatch.setattr(captures, "systemctl", lambda cmd: Bad())
    r = admin.post("/api/v1/diagnostics/captures", json={"target": "all_sip"})
    assert r.status_code == 503 and "Access denied" in r.json()["detail"]
    lst = admin.get("/api/v1/diagnostics/captures").json()["captures"]
    assert lst[0]["state"] == "failed" and "Access denied" in lst[0]["error"]
    # A unit that never reports back is marked failed after its duration and a grace period.
    with session_scope() as db:
        old = Capture(
            id=uuid.uuid4(),
            state="running",
            label="old",
            filter={"ports": [5060]},
            expression="(port 5060)",
            duration_seconds=60,
            size_limit_mb=1,
            path="",
            created_by="x",
            started_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        db.add(old)
        db.commit()
        assert captures.mark_stale(db) == 1
        assert db.get(Capture, old.id).error == "the capture unit did not report back"


def test_capture_permissions(admin, client):
    from conftest import ADMIN_PASSWORD, login
    from test_api_rbac import make_org, make_user

    org = make_org(admin, "other")
    make_user(admin, "orgadmin@other.local", org, "org_admin")
    oa = login(client, "orgadmin@other.local", ADMIN_PASSWORD)
    assert oa.get("/api/v1/diagnostics/captures").status_code == 403
    assert oa.post("/api/v1/diagnostics/captures", json={"target": "all_sip"}).status_code == 403


def test_retention_prunes_captures_with_files(admin, tmp_path):
    f = tmp_path / "old.pcap"
    f.write_bytes(b"x")
    with session_scope() as db:
        for state, path, days in (
            ("finished", str(f), 10),
            ("running", "", 10),
            ("finished", "", 1),
        ):
            db.add(
                Capture(
                    id=uuid.uuid4(),
                    state=state,
                    label=state,
                    filter={"ports": [5060]},
                    expression="(port 5060)",
                    duration_seconds=1800 if state == "running" else 60,
                    size_limit_mb=1,
                    path=path,
                    bytes=1,
                    created_by="x",
                    started_at=datetime.now(UTC) - timedelta(days=days),
                )
            )
        db.commit()
        assert retention.settings(db)["captures"] == 7
        removed = retention.run(db)
        db.commit()
        assert removed["captures"] == 1 and not f.exists()
        assert db.query(Capture).count() == 2
        inv = {i["key"]: i for i in retention.inventory(db)}
        assert inv["captures"]["rows"] == 2 and inv["captures"]["bytes"] == 2


# ------------------------------------------------------------------ logs and engine queries (§2.3)


def test_log_tail_and_engine_queries(admin, tmp_path, monkeypatch):
    from veyra.api.v1 import diagnostics
    from veyra.telephony.asterisk import cli

    monkeypatch.setattr(diagnostics, "LOG_DIR", tmp_path)
    (tmp_path / "messages.log").write_text(
        "".join(f"[2026-10-18 00:00:{i:02d}] NOTICE line {i} ext 1001\n" for i in range(300))
    )
    files = admin.get("/api/v1/diagnostics/logs").json()
    by = {f["key"]: f for f in files["files"]}
    assert by["messages"]["present"] is True and by["security"]["present"] is False
    r = admin.get("/api/v1/diagnostics/logs/messages", params={"lines": 50})
    assert r.status_code == 200 and len(r.json()["lines"]) == 50
    assert r.json()["lines"][-1].endswith("line 299 ext 1001")
    r = admin.get("/api/v1/diagnostics/logs/messages", params={"lines": 2000, "q": "LINE 29"})
    assert [ln.split("line ")[1].split(" ")[0] for ln in r.json()["lines"]] == [
        "29",
        *[str(n) for n in range(290, 300)],
    ]
    r = admin.get("/api/v1/diagnostics/logs/security")
    assert r.status_code == 200 and r.json()["lines"] == [] and r.json()["present"] is False
    assert admin.get("/api/v1/diagnostics/logs/other").status_code == 404
    assert admin.get("/api/v1/diagnostics/logs/messages", params={"lines": 5}).status_code == 422
    # Queries: fixed commands, one validated argument, audited.
    ran: list[str] = []
    monkeypatch.setattr(
        cli, "run", lambda command, timeout=10.0: ran.append(command) or (True, f"out of {command}")
    )
    keys = {q["key"]: q for q in admin.get("/api/v1/diagnostics/queries").json()["queries"]}
    assert (
        keys["endpoint"]["takes_argument"] is True and keys["channels"]["takes_argument"] is False
    )
    r = admin.post(
        "/api/v1/diagnostics/query", json={"key": "endpoint", "argument": "example-1001"}
    )
    assert r.status_code == 200 and r.json()["output"] == "out of pjsip show endpoint example-1001"
    r = admin.post("/api/v1/diagnostics/query", json={"key": "endpoint", "argument": "x; reload"})
    assert r.status_code == 422
    r = admin.post("/api/v1/diagnostics/query", json={"key": "channels", "argument": "x"})
    assert r.status_code == 422
    assert admin.post("/api/v1/diagnostics/query", json={"key": "reload"}).status_code == 404
    assert admin.post("/api/v1/diagnostics/query", json={"key": "channels"}).status_code == 200
    assert ran == ["pjsip show endpoint example-1001", "core show channels verbose"]
    actions = [
        e["action"] for e in admin.get("/api/v1/audit", params={"limit": 50}).json()["items"]
    ]
    assert "diagnostics.log_read" in actions and "diagnostics.query" in actions
