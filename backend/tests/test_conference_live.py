# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live conference control (issue #96): the console tables Asterisk prints
(formats from app_confbridge: "%-32s %6u %6u %-6s %s" and "%-30s %-6s %-16s
%-16s %-16s %s"), the commands sent, and the API with its audit."""

# ruff: noqa: E501 (the console's own line widths)
import uuid

import pytest
from fake_adapter import FakeAdapter
from sqlalchemy import select

from veyra.core.db import session_scope
from veyra.core.models import AuditEvent, OutboundRoute, User
from veyra.telephony import routing
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
    assert admin.get(base).json() == {
        "running": False,
        "locked": False,
        "recording": False,
        "always_recorded": False,
        "participants": [],
    }
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


def _room(admin, app, **extra):
    adapter = FakeAdapter()
    app.state.telephony = adapter
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    r = admin.post(
        "/api/v1/conferences",
        json={"organization_id": org, "name": "Board", "number": "7200", **extra},
    )
    assert r.status_code == 201, r.text
    return adapter, org, r.json()


def test_pattern_matches():
    assert routing.pattern_matches("", "911", "911")
    assert routing.pattern_matches("9", "911", "9911")
    assert routing.pattern_matches("", "[23]XX", "311")
    assert routing.pattern_matches("", "NXX.", "2125")
    assert not routing.pattern_matches("", "911", "9110")
    assert not routing.pattern_matches("", "NXX", "111")


def test_record_commands(monkeypatch):
    sent = []

    def run(cmd, timeout=10.0):
        sent.append(cmd)
        if cmd == "confbridge list":
            return True, LIST
        if cmd == "core show channels concise":
            return True, "CBRec/veyra-conf-staff-0000abcd!Bridge!!1!Up\nPJSIP/a!x!!1!Up\n"
        return True, USERS

    monkeypatch.setattr(ast.cli, "run", run)
    a = ast.AsteriskAdapter.__new__(ast.AsteriskAdapter)
    assert a.conference_live("veyra-conf-staff")["recording"] is True
    a.conference_action("veyra-conf-staff", "record_start")
    a.conference_action("veyra-conf-staff", "record_stop")
    assert sent[-2:] == [
        "confbridge record start veyra-conf-staff",
        "confbridge record stop veyra-conf-staff",
    ]
    monkeypatch.setattr(
        ast.cli, "run", lambda c, timeout=10.0: (True, "Conference is already being recorded.")
    )
    with pytest.raises(ast.EngineUnavailable):
        a.conference_action("veyra-conf-staff", "record_start")


def test_record_api_and_always_recorded(admin, app):
    adapter, _org, room = _room(admin, app)
    base = f"/api/v1/conferences/{room['id']}/live"
    adapter.conferences = {f"veyra-conf-{room['slug']}": {"locked": False, "participants": []}}
    assert admin.post(base, json={"action": "record_start"}).json()["recording"] is True
    assert admin.post(base, json={"action": "record_stop"}).json()["recording"] is False
    admin.patch(f"/api/v1/conferences/{room['id']}", json={"record": True})
    r = admin.post(base, json={"action": "record_stop"})
    assert r.status_code == 409 and r.json()["code"] == "always_recorded"
    assert admin.get(base).json()["always_recorded"] is True


def test_invite(admin, app):
    adapter, _org, room = _room(admin, app)
    base = f"/api/v1/conferences/{room['id']}/live"
    assert (
        admin.post(base, json={"action": "invite", "number": "(555) 123-4567"}).status_code == 200
    )
    endpoint, exten, context, variables = adapter.originated_channels[-1]
    assert endpoint == "Local/5551234567@veyra-outbound/n"
    assert (exten, context) == ("s", f"veyra-conf-{room['slug']}")
    assert variables["VEYRA_CONF_INVITED"] == "1"
    with session_scope() as db:
        ev = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "conference.live_invite")
        ).one()
        assert ev.details["number"] == "(555) 123-4567"
    assert admin.post(base, json={"action": "invite", "number": "abc"}).status_code == 422
    # Emergency numbers are refused, whatever the route's prefix.
    with session_scope() as db:
        db.add(
            OutboundRoute(
                id=uuid.uuid4(),
                name="E",
                slug="e",
                is_emergency=True,
                is_enabled=True,
                position=0,
                patterns=[
                    {"prefix": "9", "match": "911", "prepend": ""},
                    {"prefix": "", "match": "911", "prepend": ""},
                ],
            )
        )
    n = len(adapter.originated_channels)
    r = admin.post(base, json={"action": "invite", "number": "9911"})
    assert r.status_code == 422 and r.json()["code"] == "emergency_number"
    assert len(adapter.originated_channels) == n
    admin.patch(f"/api/v1/conferences/{room['id']}", json={"is_enabled": False})
    assert admin.post(base, json={"action": "invite", "number": "5551234"}).status_code == 409


def test_owner_on_my_phone(admin, app):
    adapter, org, room = _room(admin, app)
    with session_scope() as db:
        user_id = str(db.scalars(select(User)).first().id)
    ext = admin.post(
        "/api/v1/extensions",
        json={
            "organization_id": org,
            "number": "1050",
            "display_name": "Owner",
            "user_id": user_id,
        },
    )
    assert ext.status_code == 201, ext.text
    ext_id = ext.json()["id"]
    base = f"/api/v1/me/conferences/{room['id']}/live"
    assert admin.get("/api/v1/me/conferences").json() == []
    assert admin.get(base).status_code == 404
    assert admin.post(base, json={"action": "lock"}).status_code == 404
    r = admin.put(f"/api/v1/conferences/{room['id']}/owners", json={"extension_ids": [ext_id]})
    assert r.status_code == 200 and r.json()["owners"] == [ext_id]
    assert [x["number"] for x in admin.get("/api/v1/me/conferences").json()] == ["7200"]
    adapter.conferences = {f"veyra-conf-{room['slug']}": {"locked": False, "participants": []}}
    assert admin.post(base, json={"action": "lock"}).json()["locked"] is True
    assert admin.post(base, json={"action": "invite", "number": "5551234"}).status_code == 200
    assert (
        admin.put(
            f"/api/v1/conferences/{room['id']}/owners",
            json={"extension_ids": [str(uuid.uuid4())]},
        ).status_code
        == 422
    )
    assert (
        admin.put(f"/api/v1/conferences/{room['id']}/owners", json={"extension_ids": []}).json()[
            "owners"
        ]
        == []
    )
    assert admin.get(base).status_code == 404
