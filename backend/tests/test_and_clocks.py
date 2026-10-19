# SPDX-License-Identifier: AGPL-3.0-or-later
"""The AND clock messages module (docs/PAGING_RECORDINGS.md §6) and the
module API 1.1 pieces it uses: periodic tasks, secrets, bell events."""

from __future__ import annotations

import importlib.util
import sys
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from veyra.core.events import Event, bus
from veyra.core.models.base import utcnow

MOD = "veyra.and-clocks"
BASE = "/api/v1/ext/and-clocks"
MODULE_DIR = Path(__file__).resolve().parents[2] / "modules" / "veyra-and-clocks"


def _delivery_module():  # the pure helpers, imported without the framework
    spec = importlib.util.spec_from_file_location(
        "and_clocks_delivery", MODULE_DIR / "backend" / "delivery.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["and_clocks_delivery"] = mod
    spec.loader.exec_module(mod)
    return mod


dl = _delivery_module()


class _Clock(BaseHTTPRequestHandler):
    received: list[dict] = []
    status = 200

    def _record(self, body: bytes) -> None:
        _Clock.received.append(
            {
                "method": self.command,
                "path": self.path,
                "body": body.decode(),
                "auth": self.headers.get("Authorization"),
                "type": self.headers.get("Content-Type"),
            }
        )
        self.send_response(_Clock.status)
        self.end_headers()

    def do_POST(self) -> None:
        self._record(self.rfile.read(int(self.headers.get("Content-Length") or 0)))

    def do_GET(self) -> None:
        self._record(b"")

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def clock_server():
    _Clock.received = []
    _Clock.status = 200
    server = HTTPServer(("127.0.0.1", 0), _Clock)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def clocks_admin(admin):
    assert admin.post(f"/api/v1/modules/{MOD}/install").status_code == 200
    assert admin.post(f"/api/v1/modules/{MOD}/enable").status_code == 200
    return admin


def ctx_of(admin):
    return admin.app.state.modules.loaded[MOD].ctx


# -- formatting -----------------------------------------------------------------


def test_inline_markup_and_xml():
    m = dl.Message("Lockdown <now> & stay", "red", 120, "emergency", "fast")
    assert dl.marked_up(m) == "{color=red;flashers=FFF}Lockdown <now> & stay"
    assert dl.marked_up(dl.Message("Hi")) == "Hi"
    xml = dl.ip_speaker_message(m)
    assert xml.startswith("<IPSpeakerMessage><Message ")
    assert 'text="Lockdown &lt;now&gt; &amp; stay"' in xml
    assert 'prio="1"' in xml and 'maxseconds="120"' in xml and 'setflashers_val="FFF"' in xml


def test_request_templates_escape_per_body_type():
    m = dl.Message("Bus 5 & 7 late", "green")
    d = dl.Delivery(
        "POST", "http", "/msg", "form", "t={text}&p={password}&s={seconds}", "none", "", "p w"
    )
    method, url, body, headers = dl.build_request("10.0.0.5", m, d)
    assert (method, url) == ("POST", "http://10.0.0.5/msg")
    assert parse_qs(body.decode()) == {
        "t": ["{color=green}Bus 5 & 7 late"],
        "p": ["p w"],
        "s": ["60"],
    }
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"

    d = dl.Delivery("GET", "https", "/send?m={plain_text}", "none", "", "none", "", "")
    _, url, body, _ = dl.build_request("clock.example", m, d)
    assert url == "https://clock.example/send?m=Bus%205%20%26%207%20late" and body == b""

    d = dl.Delivery("POST", "http", "/x", "xml", "<Wrap>{xml}</Wrap>", "none", "", "")
    _, _, body, _ = dl.build_request("h", m, d)
    assert body.decode().startswith("<Wrap><IPSpeakerMessage>")

    d = dl.Delivery("POST", "http", "/x", "json", '{"m": "{plain_text}"}', "none", "", "")
    _, _, body, _ = dl.build_request("h", dl.Message('say "hi"'), d)
    assert body.decode() == '{"m": "say \\"hi\\""}'


def test_split_address():
    assert dl.split_address("10.0.0.5", 80) == ("10.0.0.5", 80)
    assert dl.split_address("10.0.0.5:8080", 80) == ("10.0.0.5", 8080)
    assert dl.split_address("clock.example", 443) == ("clock.example", 443)


# -- module end to end ---------------------------------------------------------------


def _setup(admin, server, **delivery):
    r = admin.post(
        f"{BASE}/clocks", json={"name": "Office", "address": server, "group_name": "Main"}
    )
    assert r.status_code == 201, r.text
    body = {
        "method": "POST",
        "scheme": "http",
        "path": "/message",
        "content_type": "form",
        "body": "text={text}&prio={priority}",
        "auth": "basic",
        "username": "admin",
        "password": "clock-pass",
        **delivery,
    }
    r = admin.post(f"{BASE}/delivery", json=body)
    assert r.status_code == 201, r.text
    assert "password" not in r.json() and r.json()["has_password"] is True


def test_send_now_reaches_the_clock(clocks_admin, clock_server):
    admin = clocks_admin
    # nothing to send to yet
    r = admin.post(f"{BASE}/messages", json={"text": "Hello"})
    assert r.status_code == 422
    _setup(admin, clock_server)
    r = admin.post(
        f"{BASE}/messages",
        json={
            "text": "Fire drill at 10",
            "color": "red",
            "priority": "high",
            "flashers": "",
            "seconds": "",
            "send_at": "",
            "send_to": "main",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "sent" and r.json()["result"].startswith("1 of 1")
    got = _Clock.received[0]
    assert got["path"] == "/message" and got["auth"].startswith("Basic ")
    assert parse_qs(got["body"]) == {"text": ["{color=red}Fire drill at 10"], "prio": ["20"]}

    log = admin.get(f"{BASE}/messages").json()
    assert log["items"][0]["status"] == "sent" and log["items"][0]["send_to_label"] == "main"

    # a refusing clock is reported, the log keeps the reason
    _Clock.status = 403
    r = admin.post(f"{BASE}/messages", json={"text": "again"})
    assert r.json()["status"] == "failed" and "HTTP 403" in r.json()["result"]

    # unknown target
    r = admin.post(f"{BASE}/messages", json={"text": "x", "send_to": "Gym"})
    assert r.status_code == 422 and "Gym" in r.json()["detail"]

    # the password is kept when the setup is saved again without one
    r = admin.post(f"{BASE}/delivery", json={"method": "POST", "path": "/m2", "password": ""})
    assert r.json()["has_password"] is True and r.json()["url_label"] == "http://<clock>/m2"
    preview = admin.post(f"{BASE}/delivery/preview", json={"text": "hi"}).json()
    assert preview["url"] == "http://<clock>/m2"


def test_scheduled_message_sent_by_worker_task(clocks_admin, clock_server):
    admin = clocks_admin
    _setup(admin, clock_server)
    soon = (utcnow() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M")  # org time zone is UTC
    r = admin.post(f"{BASE}/messages", json={"text": "Assembly", "send_at": soon})
    assert r.status_code == 201 and r.json()["status"] == "scheduled"
    assert (
        admin.post(
            f"{BASE}/messages", json={"text": "x", "send_at": "2001-01-01 00:00"}
        ).status_code
        == 422
    )
    assert (
        admin.post(f"{BASE}/messages", json={"text": "x", "send_at": "tomorrow"}).status_code == 422
    )

    from sqlalchemy import update

    from veyra.core.db import session_scope

    ctx = ctx_of(admin)
    tasks = {t.name: t for t in ctx.periodic_tasks}
    assert set(tasks) == {"send-due-messages", "check-clocks"}
    tasks["send-due-messages"].fn()
    assert _Clock.received == []  # not due yet
    with session_scope() as db:
        from sqlalchemy import Table

        table: Table = ctx.metadata.tables["mod_and_clocks_message"]
        db.execute(update(table).values(send_at=utcnow() - timedelta(seconds=5)))
    tasks["send-due-messages"].fn()
    assert len(_Clock.received) == 1
    assert admin.get(f"{BASE}/messages").json()["items"][0]["status"] == "sent"

    # reachability: the test server answers
    tasks["check-clocks"].fn()
    assert admin.get(f"{BASE}/clocks").json()["items"][0]["reachability"] == "reachable"


def test_bell_rang_queues_bell_messages(clocks_admin, clock_server):
    admin = clocks_admin
    _setup(admin, clock_server)
    r = admin.post(
        f"{BASE}/bell-messages",
        json={"bell_schedule": "Main bells", "send_to": "", "text": "", "color": "", "seconds": ""},
    )
    assert r.status_code == 201, r.text
    assert r.json()["text"] == "{summary}"
    org = r.json()["organization_id"]
    bus.publish(
        Event("bell.rang", {"organization_id": org, "schedule_name": "Other", "summary": "x"})
    )
    bus.publish(
        Event(
            "bell.rang",
            {"organization_id": org, "schedule_name": "MAIN BELLS", "summary": "Period 2"},
        )
    )
    items = admin.get(f"{BASE}/messages").json()["items"]
    assert [(i["text"], i["status"], i["source"]) for i in items] == [
        ("Period 2", "scheduled", "bell")
    ]
    {t.name: t for t in ctx_of(admin).periodic_tasks}["send-due-messages"].fn()
    assert parse_qs(_Clock.received[0]["body"])["text"] == ["Period 2"]


def test_missing_delivery_is_reported(clocks_admin):
    admin = clocks_admin
    admin.post(f"{BASE}/clocks", json={"name": "Hall", "address": "192.0.2.10"})
    r = admin.post(f"{BASE}/messages", json={"text": "Hello"})
    assert r.json()["status"] == "not_sent" and "not set up" in r.json()["result"]
    health = admin.get(f"/api/v1/modules/{MOD}").json()["health"]
    assert health["status"] == "degraded"


def test_permissions_and_validation(clocks_admin):
    admin = clocks_admin
    assert (
        admin.post(f"{BASE}/clocks", json={"name": "A", "address": "bad address!"}).status_code
        == 422
    )
    assert (
        admin.post(f"{BASE}/clocks", json={"name": "A", "address": "192.0.2.1"}).status_code == 201
    )
    assert (
        admin.post(f"{BASE}/clocks", json={"name": "a", "address": "192.0.2.2"}).status_code == 409
    )
    r = admin.post(f"{BASE}/delivery", json={"method": "POST", "path": "http://evil/x"})
    assert r.status_code == 422


def test_worker_loads_enabled_modules_and_runs_tasks(clocks_admin, settings):
    from veyra.core.db import session_scope
    from veyra.core.events import EventBus
    from veyra.modules.manager import ModuleManager

    worker = ModuleManager(settings, EventBus())
    with session_scope() as db:
        worker.sync_worker(db)
    assert worker.is_enabled(MOD)
    assert worker.run_periodic(now=1000.0) == 2
    assert worker.run_periodic(now=1001.0) == 0  # not due again yet
    assert worker.run_periodic(now=1006.0) == 1  # the 5 s task
    clocks_admin.post(f"/api/v1/modules/{MOD}/disable")
    with session_scope() as db:
        worker.sync_worker(db)
    assert not worker.is_enabled(MOD) and MOD not in worker.loaded


def test_clocks_can_be_edited(clocks_admin):
    """Editing rows of a resource table (#115, module API 1.2)."""
    admin = clocks_admin
    a = admin.post(f"{BASE}/clocks", json={"name": "Gym", "address": "192.0.2.10"}).json()
    admin.post(f"{BASE}/clocks", json={"name": "Office", "address": "192.0.2.11"})
    r = admin.patch(
        f"{BASE}/clocks/{a['id']}", json={"address": "192.0.2.20", "group_name": "East wing"}
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["address"] == "192.0.2.20" and out["group_name"] == "East wing"
    assert out["reachability"] == "unknown"
    assert admin.patch(f"{BASE}/clocks/{a['id']}", json={"name": "office"}).status_code == 409
    assert admin.patch(f"{BASE}/clocks/{a['id']}", json={"address": "bad one"}).status_code == 422
    view = next(
        v
        for e in admin.get("/api/v1/modules/ui-extensions").json()
        if e["module_id"] == "veyra.and-clocks"
        for v in e["views"]
        if v["id"] == "clocks"
    )
    assert [f["key"] for f in view["edit_form"]] == ["name", "address", "group_name", "model"]
