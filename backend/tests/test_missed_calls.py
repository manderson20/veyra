# SPDX-License-Identifier: AGPL-3.0-or-later
"""Missed-call email and preference merging (#136)."""

import uuid
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser

from veyra.core import mail
from veyra.core.db import session_scope
from veyra.core.models import CallRecord
from veyra.reporting import missed


def test_preferences_merge_sections_and_fields(admin):
    r = admin.put(
        "/api/v1/me/preferences",
        json={"portal": {"presence_rules": {"out": {"dnd": True}}, "missed_call_email": True}},
    )
    assert r.status_code == 200, r.text
    # The Companion saves only its section: the portal keeps its fields.
    r = admin.put("/api/v1/me/preferences", json={"companion": {"dial_prefix": "9"}})
    doc = r.json()
    assert doc["companion"]["dial_prefix"] == "9"
    assert doc["portal"]["missed_call_email"] is True
    assert doc["portal"]["presence_rules"]["out"]["dnd"] is True
    # A card that saves one portal field leaves the others.
    r = admin.put("/api/v1/me/preferences", json={"portal": {"missed_call_email": False}})
    doc = r.json()
    assert doc["portal"]["missed_call_email"] is False
    assert doc["portal"]["presence_rules"]["out"]["dnd"] is True
    assert doc["companion"]["dial_prefix"] == "9"


def test_missed_call_email(admin, app, settings):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    me = admin.get("/api/v1/auth/session").json()["user"]
    ext = admin.post(
        "/api/v1/extensions",
        json={
            "organization_id": org["id"],
            "number": "1001",
            "display_name": "Me",
            "user_id": me["id"],
        },
    ).json()
    with session_scope() as db:
        mail.save_smtp_settings(
            db,
            mail.SmtpSettings(enabled=True, host="smtp.example.org", from_address="v@example.org"),
        )

    def call(outcome: str) -> CallRecord:
        return CallRecord(
            id=uuid.uuid4(),
            linkedid=str(uuid.uuid4()),
            organization_id=uuid.UUID(org["id"]),
            direction="inbound",
            outcome=outcome,
            from_number="5735551234",
            from_name="Pat Parent",
            to_number="1001",
            to_extension_id=uuid.UUID(ext["id"]),
            started_at=datetime(2026, 10, 20, 14, 5, tzinfo=UTC),
            ring_seconds=20,
            talk_seconds=0,
            leg_count=1,
        )

    queue = settings.mailqueue_dir
    with session_scope() as db:
        assert missed.notify(db, [call("missed")], queue) == 0  # not turned on
    admin.put("/api/v1/me/preferences", json={"portal": {"missed_call_email": True}})
    with session_scope() as db:
        assert missed.notify(db, [call("missed"), call("answered"), call("voicemail")], queue) == 1
    (msg,) = [
        BytesParser(policy=policy.default).parsebytes(p.read_bytes()) for p in queue.glob("*.eml")
    ]
    assert msg["Subject"] == "Missed call from Pat Parent" and msg["To"] == me["email"]
    assert "(5735551234) called extension 1001" in msg.get_content()
