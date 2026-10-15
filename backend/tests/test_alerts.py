# SPDX-License-Identifier: AGPL-3.0-or-later
"""Monitoring (docs/REPORTING.md §6): alert life cycle, the checks, email
through the mail queue, the rules API and the Prometheus text."""

from datetime import UTC, datetime, timedelta

from fake_adapter import FakeAdapter
from sqlalchemy import select

from veyra.core.db import session_scope
from veyra.core.models import Alert, AlertRule, FirewallBan
from veyra.reporting import alerts
from veyra.telephony.adapter import EndpointStatus

T0 = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


class Notes:
    def __init__(self):
        self.sent = []

    def __call__(self, rule, alert, what):
        self.sent.append((rule.key, alert.subject, what))


def test_life_cycle_pending_raised_reminded_cleared(db_ready):
    notes = Notes()
    down = [alerts.Finding("trunk_down", "carrier", "Trunk Carrier is not reachable.")]
    with session_scope() as db:
        alerts.evaluate(db, down, notes, T0)  # pending, delay 5 minutes
        assert db.scalar(select(Alert)).state == "pending" and notes.sent == []
        alerts.evaluate(db, down, notes, T0 + timedelta(minutes=5))
        assert db.scalar(select(Alert)).state == "raised"
        alerts.evaluate(db, down, notes, T0 + timedelta(hours=12))
        alerts.evaluate(db, down, notes, T0 + timedelta(hours=24, minutes=6))
        alerts.evaluate(db, [], notes, T0 + timedelta(hours=25))
        a = db.scalar(select(Alert))
        assert a.state == "cleared" and a.cleared_at is not None
    assert notes.sent == [
        ("trunk_down", "carrier", "raised"),
        ("trunk_down", "carrier", "reminder"),
        ("trunk_down", "carrier", "cleared"),
    ]
    # A blip shorter than the delay never raises and leaves nothing behind.
    with session_scope() as db:
        alerts.evaluate(db, down, notes, T0 + timedelta(days=2))
        alerts.evaluate(db, [], notes, T0 + timedelta(days=2, minutes=1))
        assert db.query(Alert).filter(Alert.state != "cleared").count() == 0
        # A disabled rule raises nothing.
        db.get(AlertRule, "engine_down").is_enabled = False
        alerts.evaluate(db, [alerts.Finding("engine_down", "", "x")], notes, T0 + timedelta(days=3))
        assert db.query(Alert).filter(Alert.rule == "engine_down").count() == 0


def test_checks(db_ready, tmp_path):
    assert alerts.check_disk([tmp_path], 101)[0].rule == "disk_space"
    assert alerts.check_disk([tmp_path], 0) == []
    assert (
        alerts.check_services(("veyra-api", "veyra-pager"), lambda u: u != "veyra-pager")[0].subject
        == "veyra-pager"
    )
    assert (
        alerts.check_certificate(5.2, 21)[0].message == "The HTTPS certificate expires in 5 days."
    )
    assert alerts.check_certificate(400, 21) == alerts.check_certificate(None, 21) == []
    adapter = FakeAdapter()
    assert alerts.check_engine(adapter) == []
    with session_scope() as db:
        for i in range(3):
            db.add(
                FirewallBan(
                    address=f"198.51.100.{i}",
                    reason="x",
                    source="asterisk",
                    banned_at=T0 - timedelta(minutes=10),
                    expires_at=T0 + timedelta(hours=1),
                )
            )
        db.flush()
        assert alerts.check_firewall(db, T0, 2)[0].rule == "firewall_bans"
        assert alerts.check_firewall(db, T0, 3) == []


def test_api_rules_alerts_and_metrics(admin, app):
    app.state.telephony = FakeAdapter()
    app.state.settings.data_dir.mkdir(parents=True, exist_ok=True)  # exists on a real server
    rules = admin.get("/api/v1/alert-rules").json()
    assert [r["key"] for r in rules][:2] == ["engine_down", "trunk_down"]
    r = admin.patch(
        "/api/v1/alert-rules/disk_space",
        json={"threshold": 15, "recipients": ["it@example.org", "it@example.org"]},
    )
    assert (
        r.status_code == 200
        and r.json()["recipients"] == ["it@example.org"]
        and r.json()["threshold"] == 15
    )
    assert (
        admin.patch("/api/v1/alert-rules/disk_space", json={"recipients": ["nope"]}).status_code
        == 422
    )
    assert admin.patch("/api/v1/alert-rules/nonsense", json={}).status_code == 404
    with session_scope() as db:
        alerts.evaluate(db, [alerts.Finding("certificate", "", "expires soon")], Notes(), T0)
    listed = admin.get("/api/v1/alerts").json()
    assert listed["total"] == 1 and listed["items"][0]["title"] == "HTTPS certificate expiring"
    text = admin.get("/api/v1/metrics")
    assert text.status_code == 200 and text.headers["content-type"].startswith("text/plain")
    assert "veyra_up 1" in text.text and 'veyra_alert{rule="certificate",subject=""} 1' in text.text
    assert "veyra_engine_up" in text.text and 'veyra_disk_free_ratio{volume="data"}' in text.text


def test_phones_check_counts_provisioned_extensions(admin):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    exts = []
    for n in ("1001", "1002"):
        exts.append(
            admin.post(
                "/api/v1/extensions",
                json={"organization_id": org["id"], "number": n, "display_name": n},
            ).json()
        )
    for i, e in enumerate(exts):
        r = admin.post(
            "/api/v1/devices",
            json={
                "organization_id": org["id"],
                "mac_address": f"0004f2aabb0{i}",
                "model": "VVX 450",
                "manufacturer": "Poly",
                "primary_extension_id": e["id"],
            },
        )
        assert r.status_code == 201, r.text
    adapter = FakeAdapter()
    with session_scope() as db:
        from veyra.core.models import Extension

        names = [db.get(Extension, e["id"]).endpoint_name for e in exts]
    adapter.endpoint_statuses = lambda: [
        EndpointStatus(names[0], True),
        EndpointStatus(names[1], False),
    ]
    with session_scope() as db:
        found = alerts.check_phones(db, adapter, 20)
        assert found and found[0].details["numbers"] == ["1002"]
        assert alerts.check_phones(db, adapter, 50) == []
