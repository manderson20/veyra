# SPDX-License-Identifier: AGPL-3.0-or-later
"""The voicemail web inbox (docs/USER_PORTAL.md §2): a user's own boxes and
shared inboxes, playback, move, forward and delete through the store
helper, administrator parity, and the helper being down."""

import threading
import time

import pytest
from conftest import ADMIN_PASSWORD, login
from fastapi.testclient import TestClient

from veyra.core import tenancy
from veyra.core.db import session_scope
from veyra.core.models import Organization
from veyra.voicemail import store as vmstore

TXT = """[message]
origmailbox={box}
context={ctx}
callerid="Pat Lee" <1002>
origdate=Sat Oct 18 09:15:02 PM UTC 2026
origtime={origtime}
msg_id={origtime}-{n:08d}
flag={flag}
duration=5
"""


def _msg(folder, n, ctx, box, flag="", origtime=1760800000):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"msg{n:04d}.txt").write_text(
        TXT.format(box=box, ctx=ctx, origtime=origtime + n, n=n, flag=flag)
    )
    (folder / f"msg{n:04d}.wav").write_bytes(b"RIFF" + bytes([n]) * 8)


@pytest.fixture
def helper(app, tmp_path):
    """The real store on a temporary spool and socket, as the tests' user."""
    spool = tmp_path / "spool"
    spool.mkdir()
    sock = tmp_path / "vmstore.sock"
    st = vmstore.VoicemailStore(spool)
    threading.Thread(target=st.serve, args=(sock,), daemon=True).start()
    for _ in range(50):
        if sock.exists():
            break
        time.sleep(0.05)
    app.state.settings.vmstore_socket = sock
    return spool


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _user(admin, email):
    org = _org(admin)["id"]
    r = admin.post(
        "/api/v1/users",
        json={
            "email": email,
            "display_name": "Pat Lee",
            "password": ADMIN_PASSWORD,
            "home_organization_id": org,
            "require_password_change": False,
        },
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = admin.post(
        f"/api/v1/users/{uid}/roles",
        json={"role_key": "standard_user", "scope_type": "organization", "organization_id": org},
    )
    assert r.status_code in (200, 201), r.text
    return uid


def _ext(admin, number, user_id=None):
    body = {
        "organization_id": _org(admin)["id"],
        "number": number,
        "display_name": f"Desk {number}",
    }
    if user_id:
        body["user_id"] = user_id
    r = admin.post("/api/v1/extensions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _context(admin):
    with session_scope() as db:
        org = db.get(Organization, _org(admin)["id"])
        return tenancy.names_of(db, org.id).voicemail


def test_inbox_for_own_and_shared_boxes(admin, app, helper):
    uid = _user(admin, "pat@example.org")
    mine = _ext(admin, "1001", uid)
    other = _ext(admin, "1002")
    box = admin.post("/api/v1/voicemail", json={"extension_id": mine["id"]}).json()
    other_box = admin.post("/api/v1/voicemail", json={"extension_id": other["id"]}).json()
    shared = admin.post(
        "/api/v1/voicemail",
        json={
            "organization_id": _org(admin)["id"],
            "number": "1900",
            "name": "Front office",
            "members": [mine["id"]],
        },
    )
    assert shared.status_code == 201, shared.text
    shared = shared.json()
    ctx = _context(admin)
    inbox = helper / ctx / "1001" / "INBOX"
    for n in range(3):
        _msg(inbox, n, ctx, "1001", flag="Urgent" if n == 2 else "")
    _msg(helper / ctx / "1900" / "INBOX", 0, ctx, "1900")

    # A second client, without entering the lifespan again (that would reset
    # the app state the admin client depends on); the admin stays signed in.
    user = login(TestClient(app, base_url="http://veyra.test"), "pat@example.org", ADMIN_PASSWORD)
    boxes = user.get("/api/v1/me/voicemail").json()
    assert [(b["number"], b["shared"]) for b in boxes] == [("1001", False), ("1900", True)]
    # Nobody else's box, even in the same organization.
    assert user.get(f"/api/v1/me/voicemail/{other_box['id']}/messages").status_code == 404

    r = user.get(f"/api/v1/me/voicemail/{box['id']}/messages")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["counts"]["INBOX"] == 3 and out["folders"][0] == {"key": "INBOX", "label": "New"}
    assert [m["number"] for m in out["messages"]] == [2, 1, 0]  # newest first
    top = out["messages"][0]
    assert top["caller_number"] == "1002" and top["caller_name"] == "Pat Lee" and top["urgent"]
    assert top["duration_seconds"] == 5 and top["received_at"].startswith("2025-10-18T")
    assert (
        user.get(
            f"/api/v1/me/voicemail/{box['id']}/messages", params={"folder": "Trash"}
        ).status_code
        == 422
    )

    # Play (audited), download, move to Old, forward to the shared inbox, delete.
    r = user.get(f"/api/v1/me/voicemail/{box['id']}/messages/2/audio")
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/wav")
    assert r.content.startswith(b"RIFF\x02")
    r = user.get(f"/api/v1/me/voicemail/{box['id']}/messages/2/audio", params={"download": "true"})
    assert "attachment" in r.headers["content-disposition"]
    r = user.post(
        f"/api/v1/me/voicemail/{box['id']}/messages/2/move",
        json={"folder": "INBOX", "to": "Old", "msg_id": top["msg_id"]},
    )
    assert r.status_code == 200 and r.json()["moved"], r.text
    assert user.get(f"/api/v1/me/voicemail/{box['id']}/messages", params={"folder": "Old"}).json()[
        "counts"
    ] == {"INBOX": 2, "Old": 1, "Work": 0, "Family": 0, "Friends": 0, "Urgent": 0}
    # A stale msg_id is refused.
    r = user.post(
        f"/api/v1/me/voicemail/{box['id']}/messages/0/move",
        json={"folder": "INBOX", "to": "Work", "msg_id": "stale"},
    )
    assert r.status_code == 409 and r.json()["code"] == "message_moved"
    r = user.post(
        f"/api/v1/me/voicemail/{box['id']}/messages/0/forward",
        json={"folder": "INBOX", "box_id": shared["id"]},
    )
    assert r.status_code == 200 and r.json()["copied"], r.text
    copied = (helper / ctx / "1900" / "INBOX" / "msg0001.txt").read_text()
    assert copied.count("forwarded_by=") == 1
    # Forwarding to a box of another organization is not possible; a colleague's is.
    r = user.post(
        f"/api/v1/me/voicemail/{box['id']}/messages/0/forward",
        json={"folder": "INBOX", "box_id": other_box["id"]},
    )
    assert r.status_code == 200
    r = user.delete(f"/api/v1/me/voicemail/{box['id']}/messages/0", params={"folder": "INBOX"})
    assert r.status_code == 204
    assert user.get(f"/api/v1/me/voicemail/{box['id']}/messages").json()["counts"]["INBOX"] == 1
    # The shared inbox is readable by its member.
    r = user.get(f"/api/v1/me/voicemail/{shared['id']}/messages")
    assert r.status_code == 200 and r.json()["counts"]["INBOX"] == 2

    # Audit: every listening and change, flagged as self-service.
    r = admin.get("/api/v1/audit", params={"action": "voicemail.message_play"})
    assert r.status_code == 200, r.text
    events = r.json()["items"]
    assert events and events[0]["details"]["self_service"] is True

    # Administrator parity on the same routes under /voicemail.
    r = admin.get(f"/api/v1/voicemail/{box['id']}/messages")
    assert r.status_code == 200 and r.json()["counts"]["INBOX"] == 1
    assert admin.get(f"/api/v1/voicemail/{box['id']}/messages/0/audio").status_code == 200
    r = admin.post(f"/api/v1/voicemail/{box['id']}/messages/0/move", json={"to": "Family"})
    assert r.status_code == 200
    assert (
        admin.delete(
            f"/api/v1/voicemail/{box['id']}/messages/0", params={"folder": "Family"}
        ).status_code
        == 204
    )


def test_inbox_without_the_helper(admin, app, tmp_path):
    app.state.settings.vmstore_socket = tmp_path / "missing.sock"
    uid = _user(admin, "sam@example.org")
    ext = _ext(admin, "1003", uid)
    box = admin.post("/api/v1/voicemail", json={"extension_id": ext["id"]}).json()
    r = admin.get(f"/api/v1/voicemail/{box['id']}/messages")
    assert r.status_code == 503 and r.json()["code"] == "vmstore_unavailable"


def _wav(seconds: float, rate: int = 8000) -> bytes:
    import io
    import struct
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(seconds * rate)
        w.writeframes(struct.pack("<" + "h" * n, *([1000, -1000] * (n // 2) + [0] * (n % 2))))
    return buf.getvalue()


def test_greetings_upload_play_limit_and_delete(admin, app, helper):
    uid = _user(admin, "lee@example.org")
    ext = _ext(admin, "1004", uid)
    box = admin.post("/api/v1/voicemail", json={"extension_id": ext["id"]}).json()
    ctx = _context(admin)
    user = login(TestClient(app, base_url="http://veyra.test"), "lee@example.org", ADMIN_PASSWORD)
    base = f"/api/v1/me/voicemail/{box['id']}/greetings"

    r = user.get(base)
    assert r.status_code == 200, r.text
    assert [g["kind"] for g in r.json()] == ["unavail", "busy", "greet", "temp"]
    assert not any(g["recorded"] for g in r.json())
    # Upload a 16 kHz stereo-ish WAV: converted to the engine's 8 kHz mono WAV.
    r = user.put(base + "/unavail", files={"file": ("hello.wav", _wav(2.0, 16000), "audio/wav")})
    assert r.status_code == 200, r.text
    g = {x["kind"]: x for x in r.json()}
    assert (
        g["unavail"]["recorded"] and g["unavail"]["format"] == "wav" and not g["busy"]["recorded"]
    )
    stored = helper / ctx / "1004" / "unavail.wav"
    assert stored.exists() and stored.read_bytes()[:4] == b"RIFF"
    r = user.get(base + "/unavail/audio")
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/wav")
    assert user.get(base + "/busy/audio").status_code == 404
    # Longer than maxgreet (60 s) is refused; so is a non-audio file and a bad kind.
    r = user.put(base + "/busy", files={"file": ("long.wav", _wav(61.0), "audio/wav")})
    assert r.status_code == 422 and r.json()["code"] == "greeting_too_long"
    r = user.put(base + "/busy", files={"file": ("x.wav", b"not audio at all", "audio/wav")})
    assert r.status_code == 415
    assert (
        user.put(base + "/hello", files={"file": ("a.wav", _wav(1), "audio/wav")}).status_code
        == 422
    )
    # Delete; a second delete is a no-op.
    r = user.delete(base + "/unavail")
    assert r.status_code == 200 and not {x["kind"]: x for x in r.json()}["unavail"]["recorded"]
    assert not stored.exists()
    events = admin.get("/api/v1/audit", params={"action": "voicemail.greeting_set"}).json()["items"]
    assert (
        events
        and events[0]["details"]["kind"] == "unavail"
        and events[0]["details"]["self_service"]
    )
    # Administrator parity.
    r = admin.put(
        f"/api/v1/voicemail/{box['id']}/greetings/temp",
        files={"file": ("temp.wav", _wav(1.0), "audio/wav")},
    )
    assert r.status_code == 200 and {x["kind"]: x for x in r.json()}["temp"]["recorded"]
    assert admin.get(f"/api/v1/voicemail/{box['id']}/greetings/temp/audio").status_code == 200
    assert admin.delete(f"/api/v1/voicemail/{box['id']}/greetings/temp").status_code == 200
