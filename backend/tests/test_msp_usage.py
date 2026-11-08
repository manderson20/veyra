# SPDX-License-Identifier: AGPL-3.0-or-later
"""Usage by organization for billing (docs/MULTI_TENANCY_MSP.md §9)."""

import uuid
from datetime import UTC, datetime, timedelta

from conftest import org_user, two_organizations
from test_api_routing import _trunk

from veyra.core.db import session_scope
from veyra.core.models import CallRecord, OrganizationNumber
from veyra.reporting.cdr import Directory

MONTH = "2026-10"
T0 = datetime(2026, 10, 5, 14, 0, tzinfo=UTC)


def _call(org, direction, minute, talk, trunk=None, emergency=False):
    start = T0 + timedelta(minutes=minute)
    return CallRecord(
        linkedid=f"l-{uuid.uuid4().hex[:12]}",
        organization_id=org,
        direction=direction,
        outcome="answered",
        started_at=start,
        ended_at=start + timedelta(seconds=talk + 5),
        talk_seconds=talk,
        trunk_id=trunk,
        is_emergency=emergency,
        to_number="911" if emergency else "5551234567",
    )


def _calls(a, b, trunk):
    with session_scope() as db:
        db.add_all(
            [
                _call(a.id, "outbound", 0, 61, trunk),  # 2 billable minutes
                _call(a.id, "outbound", 0, 30, trunk),  # at the same time: peak 2
                _call(a.id, "inbound", 10, 120, trunk),  # 2 minutes
                _call(a.id, "outbound", 0, 300, trunk, emergency=True),  # never billable
                _call(a.id, "internal", 20, 600),
                _call(b.id, "outbound", 0, 59, trunk),
                # Another month.
                CallRecord(
                    linkedid="l-sept",
                    organization_id=a.id,
                    direction="outbound",
                    outcome="answered",
                    started_at=datetime(2026, 9, 30, 23, 0, tzinfo=UTC),
                    talk_seconds=60,
                ),
            ]
        )


def test_usage_per_organization_and_trunk(admin, app):
    a, b = two_organizations(admin)
    trunk = _trunk(admin)
    _calls(a, b, uuid.UUID(trunk["id"]))
    rows = admin.get("/api/v1/reports/usage", params={"month": MONTH}).json()["rows"]
    by = {(r["organization_id"], r["trunk"]): r for r in rows}
    ra = by[(a.id, trunk["name"])]
    assert (ra["outbound_calls"], ra["inbound_calls"]) == (2, 1)
    assert ra["billable_minutes"] == 2 + 1 + 2
    assert ra["emergency_calls"] == 1 and ra["peak_concurrent"] == 2
    assert by[(a.id, "")]["internal_calls"] == 1
    assert by[(b.id, trunk["name"])]["billable_minutes"] == 1
    # Each organization's administrators see their own.
    alice = org_user(admin, app, "admin@a.local", "org_admin", a.id)
    mine = alice.get("/api/v1/reports/usage", params={"month": MONTH}).json()["rows"]
    assert {r["organization_id"] for r in mine} == {a.id}
    csv = admin.get("/api/v1/reports/usage.csv", params={"month": MONTH})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert csv.text.splitlines()[0].startswith("Month,Organization,Trunk,Inbound calls")
    assert admin.get("/api/v1/reports/usage", params={"month": "2026-13"}).status_code == 422


def test_report_builder_groups_by_organization(admin, app):
    a, b = two_organizations(admin)
    trunk = _trunk(admin)
    _calls(a, b, uuid.UUID(trunk["id"]))
    r = admin.post(
        "/api/v1/reports/run",
        json={
            "group_by": ["organization"],
            "measures": ["calls"],
            "period": {"kind": "custom", "from_date": "2026-10-01", "to_date": "2026-10-31"},
        },
    )
    assert r.status_code == 200, r.text
    labels = {row["group"][0]["label"] for row in r.json()["rows"]}
    assert {"Beta"} <= labels


def test_billing_owner_of_a_number_is_exact(admin, app):
    a, _ = two_organizations(admin)
    with session_scope() as db:
        db.add(
            OrganizationNumber(
                organization_id=a.id,
                first="5735550100",
                last="5735550199",
                source="manual",
                created_at=T0,
            )
        )
    with session_scope() as db:
        d = Directory.load(db)
        assert str(d.owner_of("+15735550142")) == a.id
        assert d.owner_of("5550142") is None  # no suffix guessing
        assert d.route_for("9995735550142") is None
