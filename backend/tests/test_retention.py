# SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: E501
"""Retention (docs/PRODUCTION_HARDENING.md §4): settings with their
minimums, the daily job per class including the append-only audit log,
the inventory and the API."""

from __future__ import annotations

import uuid
from datetime import timedelta

from veyra.core import retention
from veyra.core.db import session_scope
from veyra.core.models import (
    Alert,
    AuditEvent,
    CallSample,
    ClusterEvent,
    FirewallEvent,
    SystemSetting,
)
from veyra.core.models.base import utcnow


def test_settings_minimums_and_calls_link(admin):
    with session_scope() as db:
        s = retention.settings(db)
        assert s["audit_log"] == 730 and s["calls"] == 400 and s["metrics"] == 14
        out = retention.save_settings(db, {"alerts": 100, "calls": 200}, None)
        assert out["alerts"] == 100 and out["calls"] == 200
        # The Milestone 10 call-history setting follows.
        assert db.get(SystemSetting, retention.CALLS_KEY).value["days"] == 200
        try:
            retention.save_settings(db, {"audit_log": 100}, None)
        except ValueError as e:
            assert "365" in str(e)
        else:
            raise AssertionError("audit log below a year was accepted")
        db.rollback()


def test_job_prunes_each_class_and_audits(admin):
    now = utcnow()
    with session_scope() as db:
        old = now - timedelta(days=800)
        db.add(
            AuditEvent(
                occurred_at=old,
                actor_type="system",
                actor_label="t",
                action="x",
                outcome="success",
                details={},
            )
        )
        db.add(
            AuditEvent(
                occurred_at=now - timedelta(days=10),
                actor_type="system",
                actor_label="t",
                action="y",
                outcome="success",
                details={},
            )
        )
        db.add(
            Alert(
                id=uuid.uuid4(),
                rule="engine_down",
                subject="s",
                message="m",
                state="cleared",
                first_seen_at=old,
                cleared_at=old,
                details={},
            )
        )
        db.add(
            Alert(
                id=uuid.uuid4(),
                rule="engine_down",
                subject="open",
                message="m",
                state="raised",
                first_seen_at=old,
                details={},
            )
        )
        db.add(
            ClusterEvent(occurred_at=old, event_type="isolated", actor_label="agent", details={})
        )
        db.add(
            FirewallEvent(
                id=uuid.uuid4(),
                at=old,
                address="192.0.2.1",
                source="asterisk",
                kind="x",
                detail=None,
            )
        )
        db.add(
            CallSample(
                id=uuid.uuid4(),
                at=now - timedelta(days=20),
                channels=0,
                calls_internal=0,
                calls_external=0,
                registrations=0,
            )
        )
        db.add(
            CallSample(
                id=uuid.uuid4(),
                at=now,
                channels=0,
                calls_internal=0,
                calls_external=0,
                registrations=0,
            )
        )
        db.flush()
        assert retention.due(db) is True
        removed = retention.run(db, now)
        db.commit()
        assert (
            removed["audit_log"] == 1 and removed["alerts"] == 1 and removed["cluster_events"] == 1
        )
        assert removed["firewall"] == 1 and removed["metrics"] == 1
        assert db.query(Alert).count() == 1  # the open one stays
        assert db.query(AuditEvent).filter_by(action="y").count() == 1
        # The job's own trail: one entry per class that lost rows.
        trail = db.query(AuditEvent).filter_by(action="retention.pruned").all()
        assert {e.target_id for e in trail} >= {
            "audit_log",
            "alerts",
            "cluster_events",
            "firewall",
            "metrics",
        }
        assert retention.due(db, now + timedelta(hours=1)) is False
        assert retention.due(db, now + timedelta(hours=25)) is True


def test_retention_api(admin, app):
    r = admin.get("/api/v1/retention")
    assert r.status_code == 200
    rules = {x["key"]: x for x in r.json()["rules"]}
    assert rules["audit_log"]["minimum_days"] == 365 and r.json()["last_run"] is None
    r = admin.put("/api/v1/retention", json={"days": {"page_log": 10}})
    assert r.status_code == 400 and r.json()["code"] == "confirm_short"
    r = admin.put("/api/v1/retention", json={"days": {"page_log": 10}, "confirm_short": True})
    assert (
        r.status_code == 200 and {x["key"]: x["days"] for x in r.json()["rules"]}["page_log"] == 10
    )
    r = admin.put("/api/v1/retention", json={"days": {"audit_log": 10}, "confirm_short": True})
    assert r.status_code == 400 and r.json()["code"] == "bad_retention"
    r = admin.put("/api/v1/retention", json={"days": {"nope": 10}})
    assert r.status_code == 400
    inv = admin.get("/api/v1/retention/inventory").json()
    keys = {x["key"] for x in inv}
    assert {"audit_log", "calls", "recordings", "backups", "sessions", "voicemail"} <= keys
    audit_row = next(x for x in inv if x["key"] == "audit_log")
    assert audit_row["rows"] >= 1 and audit_row["bytes"] > 0 and audit_row["oldest"]
    r = admin.post("/api/v1/retention/run")
    assert r.status_code == 200 and "audit_log" in r.json()["removed"]
    assert admin.get("/api/v1/retention").json()["last_run"]["at"]
