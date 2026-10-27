# SPDX-License-Identifier: AGPL-3.0-or-later
"""Presence from the calendar (issue #136): in a meeting while a timed event
is on, back to available after it only if the calendar set it; addresses
must be public https; the address is stored encrypted."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import ADMIN_PASSWORD, login
from fastapi.testclient import TestClient
from test_api_mfa import _make_user

from veyra.core.db import session_scope
from veyra.core.models import SystemSetting
from veyra.core.security.crypto import load_installation_key
from veyra.portal import presence_calendar as pc


def _ics(start: datetime, minutes: int) -> bytes:
    fmt = "%Y%m%dT%H%M%SZ"
    end = start + timedelta(minutes=minutes)
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:test\r\n"
        "BEGIN:VEVENT\r\nUID:a@example.org\r\n"
        f"DTSTART:{start.strftime(fmt)}\r\nDTEND:{end.strftime(fmt)}\r\n"
        "SUMMARY:Budget review\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:b@example.org\r\nDTSTART;VALUE=DATE:20261020\r\n"
        "SUMMARY:All day\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    ).encode()


def test_public_https_only(monkeypatch):
    with pytest.raises(pc.CalendarAddressError):
        pc.check_public_url("http://calendar.example.org/x.ics")
    monkeypatch.setattr(
        pc.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("10.0.0.5", 443))]
    )
    with pytest.raises(pc.CalendarAddressError, match="internet"):
        pc.check_public_url("https://intranet.example.org/x.ics")
    monkeypatch.setattr(
        pc.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 443))]
    )
    assert pc.check_public_url("webcal://calendar.example.org/x.ics").startswith("https://")


def test_meeting_on_and_off(admin, app, monkeypatch):
    monkeypatch.setattr(
        pc.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 443))]
    )
    now = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
    feed = {"data": _ics(now - timedelta(minutes=10), 30)}
    monkeypatch.setattr(pc.calendars, "fetch", lambda url, **_: feed["data"])
    org = admin.get("/api/v1/organizations").json()["items"][0]
    uid = _make_user(admin, "pat@example.org")
    ext = admin.post(
        "/api/v1/extensions",
        json={
            "organization_id": org["id"],
            "number": "1001",
            "display_name": "Pat",
            "user_id": uid,
        },
    ).json()
    user = login(TestClient(app, base_url="http://veyra.test"), "pat@example.org", ADMIN_PASSWORD)
    r = user.put(
        "/api/v1/me/presence-calendar", json={"url": "https://calendar.example.org/s/x.ics"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["configured"] and r.json()["address"] == "https://calendar.example.org/…"
    with session_scope() as db:
        stored = db.get(SystemSetting, pc.setting_key(uuid.UUID(uid))).value
        assert "x.ics" not in str(stored)
    key = load_installation_key(app.state.settings)

    def presence():
        return user.get(f"/api/v1/me/extensions/{ext['id']}/presence").json()["state"]

    with session_scope() as db:
        assert pc.process(db, key, now=now, fetch=lambda url: feed["data"]) == 1
    assert presence() == "meeting"
    # Within the interval: nothing is read again.
    with session_scope() as db:
        assert pc.process(db, key, now=now + timedelta(minutes=1)) == 0
    # The meeting ends: back to available.
    feed["data"] = _ics(now - timedelta(hours=3), 30)
    with session_scope() as db:
        assert (
            pc.process(db, key, now=now + timedelta(minutes=30), fetch=lambda url: feed["data"])
            == 1
        )
    assert presence() == "available"
    # A state the user chose by hand stays.
    user.put(f"/api/v1/me/extensions/{ext['id']}/presence", json={"state": "lunch"})
    feed["data"] = _ics(now + timedelta(minutes=55), 30)
    with session_scope() as db:
        pc.process(db, key, now=now + timedelta(minutes=60), fetch=lambda url: feed["data"])
    assert presence() == "lunch"
    assert user.delete("/api/v1/me/presence-calendar").status_code == 204
    assert user.get("/api/v1/me/presence-calendar").json()["configured"] is False


def test_user_calendars_connect_only_to_public_addresses(monkeypatch):
    """Checked at connect time (no DNS rebinding) and for every redirect."""
    import socket

    from veyra.bells import calendars

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(calendars.CalendarError, match="on the internet"):
        pc.fetch_public("https://calendar.example.com/x.ics")
    # A redirect (or any address) without https is refused before connecting.
    with pytest.raises(calendars.CalendarError, match="without https"):
        pc.fetch_public("http://calendar.example.com/x.ics")
