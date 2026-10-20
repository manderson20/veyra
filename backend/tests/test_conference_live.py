# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live conference control (issue #96): the console tables Asterisk prints
(formats from app_confbridge: "%-32s %6u %6u %-6s %s" and "%-30s %-6s %-16s
%-16s %-16s %s"), the commands sent, and the API with its audit."""

# ruff: noqa: E501 (the console's own line widths)
import pytest
from fake_adapter import FakeAdapter

from veyra.core.db import session_scope
from veyra.core.models import AuditEvent
from veyra.telephony.asterisk import adapter as ast

LIST = """Conference Bridge Name           Users  Marked Locked Muted
================================ ====== ====== ====== =====
veyra-conf-staff                      2      0 No     No
veyra-ex1234-conf-a-room-with-a-long-slug      1      0 Yes    No
"""
USERS = """Channel                        Flags  User Profile     Bridge Profile   Menu             CallerID
============================== ====== ================ ================ ================ ================
PJSIP/example-1001-00000002    A      veyra-conf-staff-admin veyra-conf-staff-bridge veyra-conf-staff-menu 1001
PJSIP/trunk-example-carrier-0000001a m      veyra-conf-staff-user veyra-conf-staff-bridge veyra-conf-staff-menu "Parent" <5551234>
"""


def test_parse_confbridge_tables():
    rooms = ast.parse_confbridge_list(LIST)
    assert set(rooms) == {"veyra-conf-staff", "veyra-ex1234-conf-a-room-with-a-long-slug"}
    assert rooms["veyra-ex1234-conf-a-room-with-a-long-slug"]["locked"] == "Yes"
    users = ast.parse_confbridge_users(USERS)
    assert [u["channel"] for u in users] == [
        "PJSIP/example-1001-00000002",
        "PJSIP/trunk-example-carrier-0000001a",
    ]
    assert users[0]["flags"] == "A" and users[1]["flags"] == "m"
    assert users[1]["callerid"] == '"Parent" <5551234>'


def test_commands(monkeypatch):
    sent = []

    def run(cmd, timeout=10.0):
        sent.append(cmd)
        return True, LIST if cmd == "confbridge list" else USERS

    monkeypatch.setattr(ast.cli, "run", run)
    a = ast.AsteriskAdapter.__new__(ast.AsteriskAdapter)
    live = a.conference_live("veyra-conf-staff")
    assert live["locked"] is False and live["participants"][0]["admin"]
    assert live["participants"][1]["muted"]
    assert a.conference_live("veyra-conf-none") is None
    a.conference_action("veyra-conf-staff", "kick", "PJSIP/example-1001-00000002")
    a.conference_action("veyra-conf-staff", "mute_all")
    a.conference_action("veyra-conf-staff", "end")
    assert sent[-3:] == [
        "confbridge kick veyra-conf-staff PJSIP/example-1001-00000002",
        "confbridge mute veyra-conf-staff participants",
        "confbridge kick veyra-conf-staff all",
    ]
    with pytest.raises(ValueError):
        a.conference_action("veyra-conf-staff", "kick", "PJSIP/x; core stop now")
    with pytest.raises(ValueError):
        a.conference_action("other", "lock")


def test_live_api(admin, app):
    adapter = FakeAdapter()
    app.state.telephony = adapter
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    r = admin.post(
        "/api/v1/conferences", json={"organization_id": org, "name": "Staff", "number": "7100"}
    )
    assert r.status_code == 201, r.text
    room = r.json()
    base = f"/api/v1/conferences/{room['id']}/live"
    assert admin.get(base).json() == {"running": False, "locked": False, "participants": []}
    name = next(iter(k for k in [f"veyra-conf-{room['slug']}"]))
    adapter.conferences = {
        name: {
            "locked": False,
            "participants": [
                {
                    "channel": "PJSIP/a-1",
                    "caller_id": "1001",
                    "admin": True,
                    "marked": False,
                    "muted": False,
                },
                {
                    "channel": "PJSIP/b-2",
                    "caller_id": "1002",
                    "admin": False,
                    "marked": False,
                    "muted": False,
                },
            ],
        }
    }
    live = admin.get(base).json()
    assert live["running"] and len(live["participants"]) == 2
    out = admin.post(base, json={"action": "mute_all"}).json()
    assert [p["muted"] for p in out["participants"]] == [False, True]
    out = admin.post(base, json={"action": "kick", "channel": "PJSIP/b-2"}).json()
    assert [p["channel"] for p in out["participants"]] == ["PJSIP/a-1"]
    assert admin.post(base, json={"action": "kick", "channel": "PJSIP/zz"}).status_code == 404
    assert admin.post(base, json={"action": "lock"}).json()["locked"] is True
    assert admin.post(base, json={"action": "end"}).json()["running"] is False
    assert admin.post(base, json={"action": "reboot"}).status_code == 422
    with session_scope() as db:
        actions = {
            e.action
            for e in db.query(AuditEvent).filter(AuditEvent.action.like("conference.live_%"))
        }
    assert actions == {
        "conference.live_mute_all",
        "conference.live_kick",
        "conference.live_lock",
        "conference.live_end",
    }
