# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 6b: Companion sign-in and bearer tokens, scope intersection,
own extensions and preferences, directory, call-event tickets and stream,
ARI event translation."""

import time
from datetime import timedelta

import pytest
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, login
from fake_adapter import FakeAdapter
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from veyra.api.v1 import auth as auth_mod
from veyra.core.callevents import CallEvent, CallEventHub
from veyra.core.db import session_scope
from veyra.core.models import ApiToken
from veyra.core.models.base import utcnow
from veyra.core.security import totp
from veyra.core.security.ratelimit import SlidingWindowLimiter
from veyra.telephony.adapter import EndpointStatus
from veyra.telephony.asterisk.events import AriEventTranslator, endpoint_of

AUTH = "/api/v1/auth"
MFA = f"{AUTH}/mfa"


def _client(app) -> TestClient:
    return TestClient(app, base_url="http://veyra.test")


def _bearer(app, token) -> TestClient:
    c = _client(app)
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _make_user(admin, email, role="standard_user"):
    org = _org(admin)["id"]
    r = admin.post(
        "/api/v1/users",
        json={
            "email": email,
            "display_name": email.split("@")[0].title(),
            "password": ADMIN_PASSWORD,
            "home_organization_id": org,
            "require_password_change": False,
        },
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = admin.post(
        f"/api/v1/users/{uid}/roles",
        json={"role_key": role, "scope_type": "organization", "organization_id": org},
    )
    assert r.status_code == 201, r.text
    return uid


def _ext(admin, number, name, user_id=None):
    org = _org(admin)["id"]
    body = {"organization_id": org, "number": number, "display_name": name}
    if user_id:
        body["user_id"] = user_id
    r = admin.post("/api/v1/extensions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _companion_login(app, email, device="Chrome on Windows"):
    c = _client(app)
    return c.post(
        f"{AUTH}/companion/login",
        json={"email": email, "password": ADMIN_PASSWORD, "device": device},
    )


def test_companion_login_without_mfa_issues_a_scoped_token(admin, app):
    adapter = FakeAdapter()
    app.state.telephony = adapter
    uid = _make_user(admin, "pat@district.local")
    ext = _ext(admin, "1001", "Pat's desk", uid)
    _ext(admin, "1002", "Hallway")
    adapter.endpoints = [EndpointStatus(ext["endpoint_name"], True)]

    r = _companion_login(app, "pat@district.local")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["token"].startswith("vyc_") and out["user"]["email"] == "pat@district.local"
    assert [e["number"] for e in out["extensions"]] == ["1001"]
    assert out["extensions"][0]["registration"]["registered"] is True
    assert set(out["permissions"]) == {"calls.originate", "directory.read"}  # intersection
    token = out["token"]

    c = _bearer(app, token)
    # scoped routes work without cookies or CSRF, even with hostile fetch metadata
    assert c.get("/api/v1/me/extensions").json()[0]["number"] == "1001"
    r = c.post(
        "/api/v1/calls/originate",
        json={"extension_id": ext["id"], "number": "1002"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert r.status_code == 202, r.text
    assert adapter.originated[-1][0] == ext["endpoint_name"]
    # out of scope: 403 even though the route exists
    assert c.get("/api/v1/extensions").status_code == 403
    assert c.get("/api/v1/calls").status_code == 403  # standard users lack calls.read
    # tokens are listed and the current one is marked
    toks = c.get(f"{AUTH}/tokens").json()
    assert len(toks) == 1 and toks[0]["is_current"] and toks[0]["label"] == "Chrome on Windows"
    assert toks[0]["last_used_at"] is not None and "token" not in toks[0]
    # audit does not leak the token
    events = admin.get("/api/v1/audit").json()["items"]
    assert any(e["action"] == "auth.token_issue" for e in events)
    assert token not in str(events)
    # logout revokes the token
    assert c.post(f"{AUTH}/companion/logout").status_code == 204
    assert c.get("/api/v1/me/extensions").status_code == 401


def test_companion_login_errors_mirror_the_web_flow(admin, app):
    c = _client(app)
    r = c.post(f"{AUTH}/companion/login", json={"email": "nobody@x.local", "password": "x" * 12})
    assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"
    uid = _make_user(admin, "lock@district.local")
    for _ in range(3):
        r = c.post(
            f"{AUTH}/companion/login",
            json={"email": "lock@district.local", "password": "wrong-password"},
        )
        assert r.status_code == 401
    u = admin.get(f"/api/v1/users/{uid}").json()
    assert u["locked_until"] is None  # below the threshold (10)
    # a bad bearer token is rejected cleanly
    assert _bearer(app, "vyc_" + "a" * 43).get("/api/v1/me/extensions").status_code == 401
    assert _bearer(app, "nonsense").get("/api/v1/me/extensions").status_code == 401
    # must_change_password blocks tokens
    r = admin.post(
        "/api/v1/users",
        json={
            "email": "temp@district.local",
            "display_name": "Temp",
            "password": ADMIN_PASSWORD,
            "home_organization_id": _org(admin)["id"],
            "require_password_change": True,
        },
    )
    assert r.status_code == 201
    r = _companion_login(app, "temp@district.local")
    assert r.status_code == 403 and r.json()["code"] == "password_change_required"


def test_companion_login_with_second_factor(admin, app, monkeypatch):
    monkeypatch.setattr(auth_mod, "_limiter", lambda _settings: SlidingWindowLimiter(1000, 60))
    _make_user(admin, "mfa@district.local")
    web = login(_client(app), "mfa@district.local", ADMIN_PASSWORD)
    begin = web.post(f"{MFA}/totp/begin", json={"label": "Phone"}).json()
    r = web.post(
        f"{MFA}/totp/confirm",
        json={"method_id": begin["method_id"], "code": totp.totp(begin["secret"], time.time())},
    )
    assert r.status_code == 200, r.text
    secret, codes = begin["secret"], r.json()["recovery_codes"]

    r = _companion_login(app, "mfa@district.local")
    assert r.status_code == 202, r.text
    ch = r.json()
    assert ch["methods"] == 1 and not ch["enrol"] and len(ch["challenge"]) > 20
    c = _client(app)
    # wrong code
    r = c.post(f"{AUTH}/companion/verify", json={"challenge": ch["challenge"], "code": "000000"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_code"
    # a recovery code works and the challenge is then spent
    r = c.post(f"{AUTH}/companion/verify", json={"challenge": ch["challenge"], "code": codes[0]})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    r = c.post(f"{AUTH}/companion/verify", json={"challenge": ch["challenge"], "code": codes[1]})
    assert r.status_code == 410 and r.json()["code"] == "challenge_expired"
    # the pre-auth session did not survive as a web session
    assert c.get(f"{AUTH}/session").status_code == 401
    assert _bearer(app, token).get("/api/v1/me/preferences").status_code == 200
    # a TOTP code also works (the next step: the enrolment used the current one)
    ch2 = _companion_login(app, "mfa@district.local").json()
    r = c.post(
        f"{AUTH}/companion/verify",
        json={"challenge": ch2["challenge"], "code": totp.hotp(secret, totp.step(time.time()) + 1)},
    )
    assert r.status_code == 200, r.text
    # five bad codes lock the challenge
    ch3 = _companion_login(app, "mfa@district.local").json()
    for _i in range(5):
        r = c.post(
            f"{AUTH}/companion/verify", json={"challenge": ch3["challenge"], "code": "111111"}
        )
    assert r.status_code == 401 and r.json()["code"] == "mfa_locked"
    # enrolment required but nothing enrolled: sent to the web interface
    admin.put(f"{MFA}/policy", json={"required_for": ["standard_user"], "grace_days": 0})
    _make_user(admin, "new@district.local")
    r = _companion_login(app, "new@district.local")
    assert r.status_code == 403 and r.json()["code"] == "mfa_enrolment_required"


def test_token_expiry_revocation_and_admin_view(admin, app, monkeypatch):
    uid = _make_user(admin, "exp@district.local")
    token = _companion_login(app, "exp@district.local").json()["token"]
    c = _bearer(app, token)
    assert c.get("/api/v1/me/extensions").status_code == 200
    # admin sees and revokes
    listing = admin.get(f"/api/v1/users/{uid}/tokens").json()
    assert len(listing) == 1 and listing[0]["kind"] == "companion"
    # a second token, then revoke one from the account
    token2 = _companion_login(app, "exp@district.local", device="Edge on Mac").json()["token"]
    c2 = _bearer(app, token2)
    mine = c2.get(f"{AUTH}/tokens").json()
    other = next(t for t in mine if not t["is_current"])
    assert c2.delete(f"{AUTH}/tokens/{other['id']}").status_code == 204
    assert c.get("/api/v1/me/extensions").status_code == 401
    assert c2.get("/api/v1/me/extensions").status_code == 200
    r = admin.delete(f"/api/v1/users/{uid}/tokens")
    assert r.status_code == 200 and "1 token" in r.json()["message"]
    assert c2.get("/api/v1/me/extensions").status_code == 401
    # idle expiry
    token3 = _companion_login(app, "exp@district.local").json()["token"]
    with session_scope() as db:
        tok = db.query(ApiToken).filter(ApiToken.revoked_at.is_(None)).one()
        tok.expires_at = utcnow() - timedelta(minutes=1)
    assert _bearer(app, token3).get("/api/v1/me/extensions").status_code == 401
    # a disabled user's tokens die with the account
    token4 = _companion_login(app, "exp@district.local").json()["token"]
    admin.patch(f"/api/v1/users/{uid}", json={"is_active": False})
    assert _bearer(app, token4).get("/api/v1/me/extensions").status_code == 401
    # web sessions keep full power and the token routes work for them too
    assert admin.get(f"{AUTH}/tokens").status_code == 200
    assert admin.post(f"{AUTH}/tokens/revoke-all").json()["revoked"] == 0


def test_admin_token_is_scoped_too(admin, app):
    _ext(admin, "1001", "Admin desk")
    r = _companion_login(app, ADMIN_EMAIL)
    assert r.status_code == 200, r.text
    out = r.json()
    assert "trunks.write" not in out["permissions"] and "calls.originate" in out["permissions"]
    c = _bearer(app, out["token"])
    assert c.get("/api/v1/trunks").status_code == 403
    assert c.get("/api/v1/calls").status_code == 200  # calls.read is in scope and held
    assert c.get("/api/v1/directory").json()["total"] == 1
    # a platform administrator token may not administer: no special treatment
    assert c.post("/api/v1/extensions", json={}).status_code == 403


def test_preferences_and_directory(admin, app):
    adapter = FakeAdapter()
    app.state.telephony = adapter
    uid = _make_user(admin, "pref@district.local")
    mine = _ext(admin, "1001", "Pref desk", uid)
    other = _ext(admin, "1002", "Office", _make_user(admin, "other@district.local"))
    _ext(admin, "1003", "Disabled", None)
    admin.patch(
        f"/api/v1/extensions/{_ext(admin, '1004', 'Off')['id']}", json={"is_enabled": False}
    )
    adapter.endpoints = [EndpointStatus(mine["endpoint_name"], True)]
    token = _companion_login(app, "pref@district.local").json()["token"]
    c = _bearer(app, token)

    assert c.get("/api/v1/me/preferences").json()["companion"]["speed_dials"] == []
    doc = {
        "companion": {
            "speed_dials": [{"label": "Front office", "number": "(573) 555-0100"}],
            "dial_prefix": "9",
            "default_extension_id": other["id"],  # not mine: dropped
            "notify_missed": False,
        }
    }
    r = c.put("/api/v1/me/preferences", json=doc)
    assert r.status_code == 200, r.text
    got = r.json()["companion"]
    assert got["speed_dials"] == [{"label": "Front office", "number": "5735550100"}]
    assert got["dial_prefix"] == "9" and got["default_extension_id"] is None
    assert got["notify_missed"] is False and got["notify_incoming"] is True
    assert (
        c.put("/api/v1/me/preferences", json={"companion": {"dial_prefix": "abc"}}).status_code
        == 422
    )
    assert c.put("/api/v1/me/preferences", json={"other": {}}).status_code == 422
    assert (
        c.put(
            "/api/v1/me/preferences",
            json={"companion": {"speed_dials": [{"label": "", "number": "1"}]}},
        ).status_code
        == 422
    )

    d = c.get("/api/v1/directory").json()
    assert [e["number"] for e in d["results"]] == ["1001", "1002", "1003"]
    assert d["results"][0]["registered"] is True and d["results"][1]["registered"] is False
    assert d["results"][1]["user_display_name"] == "Other"
    assert [
        e["number"] for e in c.get("/api/v1/directory", params={"q": "office"}).json()["results"]
    ] == ["1002"]
    assert [
        e["number"] for e in c.get("/api/v1/directory", params={"q": "other@"}).json()["results"]
    ] == ["1002"]
    # the web session of the standard user can use it too; a user without the permission cannot
    web = login(_client(app), "pref@district.local", ADMIN_PASSWORD)
    assert web.get("/api/v1/directory").json()["total"] == 3


def test_event_ticket_and_stream(admin, app):
    hub: CallEventHub = app.state.callevents
    uid = _make_user(admin, "ws@district.local")
    ext = _ext(admin, "1001", "WS desk", uid)
    token = _companion_login(app, "ws@district.local").json()["token"]
    c = _bearer(app, token)
    r = c.post("/api/v1/events/ticket")
    assert r.status_code == 200, r.text
    tk = r.json()
    assert tk["expires_in"] == 60 and tk["url"] == "/api/v1/events/calls"
    with c.websocket_connect(f"/api/v1/events/calls?ticket={tk['ticket']}") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["extensions"][0]["number"] == "1001"
        assert hello["listener"] == "disabled"  # no engine in tests
        now = utcnow().isoformat()
        delivered = hub.publish(
            CallEvent("call.ringing", "ch1", ext["endpoint_name"], "in", "5735551234", "Jane", now)
        )
        assert delivered == 1
        # events for somebody else's phone are not delivered
        assert (
            hub.publish(CallEvent("call.ringing", "ch2", "brookfield-9999", "in", "1", None, now))
            == 0
        )
        msg = ws.receive_json()
        assert msg["type"] == "call.ringing" and msg["extension_number"] == "1001"
        assert msg["remote_number"] == "5735551234" and msg["extension_id"] == ext["id"]
        assert "endpoint" not in msg
        ws.send_text("pong")
    # the ticket is single-use, and no ticket is refused before the handshake
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        c.websocket_connect(f"/api/v1/events/calls?ticket={tk['ticket']}"),
    ):
        pass
    assert exc.value.code == 4401
    with pytest.raises(WebSocketDisconnect), c.websocket_connect("/api/v1/events/calls"):
        pass
    # a web session may use the stream too
    assert admin.post("/api/v1/events/ticket").status_code == 200
    engine = admin.get("/api/v1/telephony/engine").json()
    assert engine["events"]["state"] == "disabled" and engine["events"]["events_seen"] == 2


def test_ari_event_translation():
    assert endpoint_of("PJSIP/brookfield-1001-00000003") == "brookfield-1001"
    assert endpoint_of("PJSIP/trunk-carrier-0000000a") == "trunk-carrier"
    assert endpoint_of("Local/1001@veyra-internal-0000;1") is None
    t = AriEventTranslator()
    ch = {
        "id": "c1",
        "name": "PJSIP/brookfield-1001-00000001",
        "state": "Down",
        "caller": {"name": "", "number": ""},
        "connected": {"name": "Jane Doe", "number": "5735551234"},
        "dialplan": {"context": "veyra-internal", "exten": "s"},
    }
    assert (
        t.translate(
            {"type": "ChannelCreated", "channel": ch, "timestamp": "2026-10-13T12:00:00+0000"}
        )
        == []
    )
    ringing = t.translate(
        {
            "type": "ChannelStateChange",
            "channel": {**ch, "state": "Ringing"},
            "timestamp": "2026-10-13T12:00:01+0000",
        }
    )
    assert [e.type for e in ringing] == ["call.ringing"]
    assert ringing[0].remote_number == "5735551234" and ringing[0].direction == "in"
    assert ringing[0].endpoint == "brookfield-1001" and ringing[0].at == "2026-10-13T12:00:01+0000"
    # no duplicate ringing
    assert t.translate({"type": "ChannelStateChange", "channel": {**ch, "state": "Ringing"}}) == []
    up = t.translate({"type": "ChannelStateChange", "channel": {**ch, "state": "Up"}})
    assert [e.type for e in up] == ["call.answered"] and up[0].answered
    ended = t.translate(
        {"type": "ChannelDestroyed", "channel": ch, "cause": 16, "cause_txt": "Normal Clearing"}
    )
    assert (
        [e.type for e in ended] == ["call.ended"]
        and ended[0].answered
        and ended[0].cause == "Normal Clearing"
    )
    assert t.channels == {}
    # an outgoing call from the phone
    out = {
        "id": "c2",
        "name": "PJSIP/brookfield-1001-00000002",
        "state": "Ring",
        "caller": {"name": "Pat", "number": "1001"},
        "connected": {"name": "", "number": ""},
        "dialplan": {"context": "veyra-internal", "exten": "95735550100"},
    }
    dialing = t.translate({"type": "ChannelCreated", "channel": out})
    assert [e.type for e in dialing] == ["call.dialing"]
    assert dialing[0].remote_number == "95735550100" and dialing[0].direction == "out"
    # the state change that follows does not announce it twice
    assert t.translate({"type": "ChannelStateChange", "channel": {**out, "state": "Ring"}}) == []
    # a missed call: destroyed before answer, still announced
    missed = t.translate(
        {"type": "ChannelDestroyed", "channel": out, "cause": 19, "cause_txt": "No Answer"}
    )
    assert missed[0].type == "call.ended" and not missed[0].answered
    # channels that were never announced do not produce an ended event
    assert t.translate({"type": "ChannelCreated", "channel": {**ch, "id": "c3"}}) == []
    assert t.translate({"type": "ChannelDestroyed", "channel": {**ch, "id": "c3"}}) == []
    # trunks and unknown technologies are ignored
    assert (
        t.translate(
            {"type": "ChannelCreated", "channel": {**ch, "id": "c4", "name": "Local/x@y-0001;2"}}
        )
        == []
    )
