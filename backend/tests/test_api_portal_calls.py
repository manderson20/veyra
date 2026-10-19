# SPDX-License-Identifier: AGPL-3.0-or-later
"""My Phone call history (docs/USER_PORTAL.md §4, §5): contact names, own
export, recordings behind the organization setting, class-of-service limits
on self-service forwards."""

import uuid
from datetime import UTC, datetime, timedelta

from conftest import ADMIN_PASSWORD, login
from fastapi.testclient import TestClient

from veyra.core.db import session_scope
from veyra.core.models import CallRecord, CallRecording


def _user(admin, email):
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
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
        json={"role_key": "standard_user", "scope_type": "organization", "organization_id": org},
    )
    assert r.status_code in (200, 201), r.text
    return uid, org


def _ext(admin, org, number, user_id=None, **extra):
    body = {"organization_id": org, "number": number, "display_name": f"Desk {number}", **extra}
    if user_id:
        body["user_id"] = user_id
    r = admin.post("/api/v1/extensions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _call(
    org, linkedid, *, from_ext=None, to_ext=None, from_number, to_number, direction, rec=None
):
    now = datetime.now(UTC)
    with session_scope() as db:
        call = CallRecord(
            id=uuid.uuid4(),
            linkedid=linkedid,
            organization_id=uuid.UUID(org),
            direction=direction,
            outcome="answered",
            from_number=from_number,
            to_number=to_number,
            from_extension_id=uuid.UUID(from_ext) if from_ext else None,
            to_extension_id=uuid.UUID(to_ext) if to_ext else None,
            answered_extension_id=uuid.UUID(to_ext) if to_ext else None,
            started_at=now - timedelta(minutes=5),
            answered_at=now - timedelta(minutes=5),
            ended_at=now - timedelta(minutes=4),
            ring_seconds=3,
            talk_seconds=60,
            leg_count=1,
            recording_ref=rec,
        )
        db.add(call)
        db.flush()
        if rec:
            db.add(
                CallRecording(
                    id=uuid.uuid4(),
                    ref=rec,
                    organization_id=uuid.UUID(org),
                    call_id=call.id,
                    path=f"example/2026/10/{rec}.ogg",
                    format="ogg",
                    size_bytes=10,
                    duration_seconds=60,
                )
            )
        return str(call.id)


def test_own_calls_contacts_export_and_recordings(admin, app, tmp_path):
    uid, org = _user(admin, "pat@example.org")
    mine = _ext(admin, org, "1001", uid)
    other = _ext(admin, org, "1002")
    pat = login(TestClient(app, base_url="http://veyra.test"), "pat@example.org", ADMIN_PASSWORD)
    pat.post(
        "/api/v1/me/contacts",
        json={"name": "Bus Garage", "numbers": [{"label": "work", "number": "+1 573 555 0199"}]},
    )
    inbound = _call(
        org,
        "l1",
        to_ext=mine["id"],
        from_number="5735550199",
        to_number="1001",
        direction="inbound",
    )
    internal = _call(
        org,
        "l2",
        from_ext=mine["id"],
        to_ext=other["id"],
        from_number="1001",
        to_number="1002",
        direction="internal",
        rec="l2",
    )
    _call(
        org,
        "l3",
        to_ext=other["id"],
        from_number="5735550100",
        to_number="1002",
        direction="inbound",
    )

    items = pat.get("/api/v1/me/calls").json()["items"]
    assert {c["id"] for c in items} == {inbound, internal}  # not the colleague's call
    by_id = {c["id"]: c for c in items}
    assert by_id[inbound]["contact_name"] == "Bus Garage"  # national form matched +1
    assert by_id[internal]["contact_name"] is None and by_id[internal]["recorded"]
    r = pat.get("/api/v1/me/calls/export.csv")
    assert r.status_code == 200 and "5735550199" in r.text and "5735550100" not in r.text

    # Recordings: off by default → 403; the admin turns it on → the file streams; audited.
    r = pat.get(f"/api/v1/me/calls/{internal}/recording")
    assert r.status_code == 403 and r.json()["code"] == "recordings_not_allowed"
    r = admin.patch(f"/api/v1/organizations/{org}", json={"users_play_own_recordings": True})
    assert r.status_code == 200 and r.json()["users_play_own_recordings"] is True, r.text
    rec_dir = app.state.settings.recordings_dir
    (rec_dir / "example" / "2026" / "10").mkdir(parents=True, exist_ok=True)
    (rec_dir / "example" / "2026" / "10" / "l2.ogg").write_bytes(b"OggS" + b"\0" * 6)
    r = pat.get(f"/api/v1/me/calls/{internal}/recording")
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/ogg")
    assert pat.get(f"/api/v1/me/calls/{inbound}/recording").status_code == 404  # no recording
    events = admin.get("/api/v1/audit", params={"action": "recording.play"}).json()["items"]
    assert events and events[0]["details"]["self_service"] is True
    # Another user's call is not reachable even with the setting on.
    _user(admin, "sam@example.org")
    sam = login(TestClient(app, base_url="http://veyra.test"), "sam@example.org", ADMIN_PASSWORD)
    assert sam.get(f"/api/v1/me/calls/{internal}/recording").status_code == 404


def test_self_service_forwards_respect_class_of_service(admin, app):
    uid, org = _user(admin, "lee@example.org")
    r = admin.post(
        "/api/v1/classes-of-service",
        json={"organization_id": org, "name": "Classroom", "allow_external_forwards": False},
    )
    assert r.status_code == 201, r.text
    ext = _ext(admin, org, "1005", uid, class_of_service_id=r.json()["id"])
    lee = login(TestClient(app, base_url="http://veyra.test"), "lee@example.org", ADMIN_PASSWORD)
    base = f"/api/v1/me/extensions/{ext['id']}/state"
    r = lee.put(base, json={"cf_always": "5735550100"})
    assert r.status_code == 422 and r.json()["code"] == "cos_denied", r.text
    r = lee.put(base, json={"cf_always": "1002"})
    assert r.status_code == 200 and r.json()["cf_always"] == "1002", r.text
    # Without the class, outside forwards are fine.
    admin.patch(f"/api/v1/extensions/{ext['id']}", json={"class_of_service_id": None})
    assert lee.put(base, json={"cf_busy": "5735550100"}).status_code == 200
