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


def _dir(**kw):
    """A Directory without the database."""
    from types import SimpleNamespace as NS

    numbers = [NS(**n) for n in kw.pop("numbers", [])]
    routes = [NS(**r) for r in kw.pop("routes", [])]
    return Directory({}, {}, routes, numbers, kw.pop("emergency", []))


def test_emergency_is_judged_by_the_callers_own_routes():
    """Another organization's emergency pattern does not make a call an
    emergency call (review of #440); disabled routes are not loaded."""
    a, b = uuid.uuid4(), uuid.uuid4()
    d = _dir(emergency=[(a, "", "933"), (None, "", "911")])
    assert d.is_emergency("933", a)
    assert not d.is_emergency("933", b)  # a normal, billable call for b
    assert d.is_emergency("911", b)  # a route for every organization


def test_emergency_routes_loaded_are_enabled_only(admin, app):
    from veyra.core.models import OutboundRoute

    with session_scope() as db:
        for slug, enabled in (("e-on", True), ("e-off", False)):
            db.add(
                OutboundRoute(
                    id=uuid.uuid4(),
                    name=slug,
                    slug=slug,
                    is_emergency=True,
                    is_enabled=enabled,
                    patterns=[{"prefix": "", "match": "9" + ("1" if enabled else "2") + "1"}],
                )
            )
    with session_scope() as db:
        d = Directory.load(db)
        assert d.is_emergency("911", None) and not d.is_emergency("921", None)


def test_inbound_route_follows_the_inventory_owner():
    """Two organizations kept routes for one DID (migration 0095): the
    inventory owner's is used (review of #440)."""
    a, b = uuid.uuid4(), uuid.uuid4()
    num = {"first": "5735550100", "last": "5735550199"}
    routes = [
        {"did": "5735550142", "organization_id": b},
        {"did": "5735550142", "organization_id": a},
    ]
    d = _dir(numbers=[{**num, "organization_id": a}], routes=routes)
    assert d.route_for("5735550142").organization_id == a
    # The owner has no route for it: none, and the owner is billed (owner_of).
    d = _dir(numbers=[{**num, "organization_id": a}], routes=routes[:1])
    assert d.route_for("5735550142") is None
    assert d.owner_of("5735550142") == a
