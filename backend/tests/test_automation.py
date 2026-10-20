# SPDX-License-Identifier: AGPL-3.0-or-later
"""Automation rules (issue #117): a missed call emails a group, a door
controller's request starts a page; conditions, cooldown, the loop guard,
the public hook address and the no-escalation check."""

import uuid

from fake_adapter import FakeAdapter
from test_api_ivr import _upload
from test_api_paging import _zone

from veyra.core import mail
from veyra.core.db import session_scope
from veyra.core.models import AutomationRun
from veyra.integrations import automation, webhooks

RULES = "/api/v1/automation/rules"


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _smtp_on():
    with session_scope() as db:
        mail.save_smtp_settings(
            db,
            mail.SmtpSettings(
                enabled=True, host="smtp.example.org", from_address="pbx@example.org"
            ),
        )


def _emit(org_id, event, data):
    with session_scope() as db:
        webhooks.emit(db, org_id, event, data)


def _process(app, adapter=None):
    with session_scope() as db:
        return automation.process(db, app.state.settings, adapter or FakeAdapter())


def test_missed_call_emails_a_group(admin, app):
    org = _org(admin)["id"]
    _smtp_on()
    r = admin.post(
        RULES,
        json={
            "organization_id": org,
            "name": "Missed calls to the office",
            "trigger": "call.ended",
            "conditions": [
                {"field": "outcome", "equals": "MISSED"},
                {"field": "did", "contains": "0100"},
            ],
            "actions": [{"type": "email", "to": ["office@example.org"]}],
            "cooldown_seconds": 0,
        },
    )
    assert r.status_code == 201, r.text
    rule = r.json()
    assert rule["hook_url"] is None
    _emit(org, "call.ended", {"outcome": "answered", "did": "+15550100"})
    _emit(org, "call.ended", {"outcome": "missed", "did": "+15550199"})
    assert _process(app) == 0  # neither matched
    _emit(
        org, "call.ended", {"outcome": "missed", "did": "+15550100", "from": {"number": "5551234"}}
    )
    q = app.state.settings.mailqueue_dir
    before = len(list(q.glob("*.eml"))) if q.is_dir() else 0
    assert _process(app) == 1
    files = sorted(q.glob("*.eml"))
    assert len(files) == before + 1
    body = files[-1].read_bytes().decode()
    assert "office@example.org" in body and "from.number: 5551234" in body
    runs = admin.get(f"{RULES}/{rule['id']}/runs").json()
    assert runs[0]["status"] == "done" and runs[0]["results"][0]["ok"]
    listed = admin.get(RULES, params={"organization_id": org}).json()
    assert listed[0]["fire_count"] == 1
    # Cooldown: a burst fires once.
    admin.patch(f"{RULES}/{rule['id']}", json={"cooldown_seconds": 600})
    _emit(org, "call.ended", {"outcome": "missed", "did": "+15550100"})
    assert _process(app) == 0  # it fired seconds ago
    from veyra.core.models import AutomationRule

    with session_scope() as db:
        db.get(AutomationRule, uuid.UUID(rule["id"])).last_fired_at = None
    for _ in range(3):
        _emit(org, "call.ended", {"outcome": "missed", "did": "+15550100"})
    assert _process(app) == 1


def test_door_controller_hook_starts_a_page(admin, app, tmp_path):
    org = _org(admin)
    adapter = FakeAdapter(prompts_dir=app.state.settings.prompts_dir)
    app.state.telephony = adapter
    zone = _zone(admin, org["id"], "Front", 3)
    bell = _upload(admin, org["id"], "Door alert")
    page = admin.post(
        "/api/v1/pages",
        json={
            "organization_id": org["id"],
            "name": "Door",
            "zones": [zone["id"]],
            "audio_id": bell["id"],
        },
    ).json()
    r = admin.post(
        RULES,
        json={
            "organization_id": org["id"],
            "name": "Front door held open",
            "trigger": "hook",
            "conditions": [{"field": "state", "equals": "held"}],
            "actions": [{"type": "page", "page_id": page["id"]}],
            "cooldown_seconds": 0,
        },
    )
    assert r.status_code == 201, r.text
    url = r.json()["hook_url"]
    assert url.startswith("https://") and "/api/v1/automation/hooks/" in url
    path = url[url.index("/api/v1/") :]
    # A rule paging on page.sent would loop: it does not fire from a rule's page.
    loop = admin.post(
        RULES,
        json={
            "organization_id": org["id"],
            "name": "Echo",
            "trigger": "page.sent",
            "actions": [{"type": "page", "page_id": page["id"]}],
            "cooldown_seconds": 0,
        },
    )
    assert loop.status_code == 201
    anon = app_client(app)
    assert anon.post(path, json={"state": "closed"}).json() == {"queued": 0}
    assert anon.post(path, json={"state": "held", "door": "Front"}).json() == {"queued": 1}
    assert anon.post("/api/v1/automation/hooks/wrong-token", json={}).status_code == 404
    assert _process(app, adapter) == 1
    assert adapter.originated[-1][0] == f"play-{page['slug']}@veyra-page-play"
    with session_scope() as db:
        assert db.query(AutomationRun).filter_by(event="page.sent").count() == 0
    log = admin.get("/api/v1/pages/log").json()["items"][0]
    assert log["trigger"] == "rule" and log["actor"] == "rule Front door held open"
    # A new address; the old one stops working.
    new = admin.post(f"{RULES}/{r.json()['id']}/rotate-hook").json()["hook_url"]
    assert anon.post(path, json={"state": "held"}).status_code == 404
    assert anon.post(new[new.index("/api/v1/") :], json={"state": "held"}).json()["queued"] == 1


def test_rules_cannot_page_without_the_right_to_page(admin):
    """A rule's page action needs paging.send of its author (no escalation)."""
    import uuid

    import pytest

    from veyra.api.v1 import automation as api
    from veyra.core.errors import ProblemError

    class Author:
        def has(self, perm, org_id=None):
            return perm != "paging.send"

    with session_scope() as db, pytest.raises(ProblemError) as e:
        api._check_actions(
            db, Author(), uuid.uuid4(), [api.ActionIn(type="page", page_id=uuid.uuid4())]
        )
    assert e.value.status == 403


def app_client(app):
    from fastapi.testclient import TestClient

    return TestClient(app, base_url="http://veyra.test")
