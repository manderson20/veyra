# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 9b: call samples for the dashboard graphs (docs/INTERFACE_REWORK.md §2)."""

from datetime import timedelta

from fake_adapter import FakeAdapter

from veyra.core.db import session_scope
from veyra.core.models import CallSample
from veyra.core.models.base import utcnow
from veyra.telephony import metrics
from veyra.telephony.adapter import ActiveCall, EndpointStatus


def _call(ch, endpoint):
    return ActiveCall(ch, "1001", "1002", "Up", 5, endpoint=endpoint)


def test_classify_counts_trunk_legs_as_external_and_pairs_the_rest():
    calls = [
        _call("a", "example-1001"),
        _call("b", "example-1002"),  # internal call: two phone legs
        _call("c", "example-1003"),
        _call("d", "trunk-carrier"),  # external call: phone leg + trunk leg
        _call("e", None),  # Local/ helper channel: ignored
    ]
    r = metrics.classify(calls, registrations=7)
    assert r.channels == 4 and r.calls_external == 1 and r.calls_internal == 1
    assert r.registrations == 7
    # A call being set up (one phone leg only) does not go negative.
    assert metrics.classify([_call("a", "example-1001")], 0).calls_internal == 0
    assert metrics.classify([_call("a", "trunk-x"), _call("b", "trunk-y")], 0).calls_internal == 0


def test_record_prune_and_series(app, admin):
    adapter = FakeAdapter()
    adapter.calls = [_call("a", "example-1001"), _call("b", "trunk-carrier")]
    adapter.endpoints = [
        EndpointStatus("example-1001", True, []),
        EndpointStatus("example-1002", False, []),
    ]
    app.state.telephony = adapter
    with session_scope() as db:
        reading = metrics.record_sample(db, adapter)
        assert reading is not None and reading.calls_external == 1 and reading.registrations == 1
        # Old rows are pruned, recent ones kept.
        db.add(
            CallSample(
                at=utcnow() - timedelta(days=15),
                channels=9,
                calls_internal=0,
                calls_external=0,
                registrations=0,
            )
        )
        for minutes, channels in ((50, 3), (49, 8), (10, 2)):
            db.add(
                CallSample(
                    at=utcnow() - timedelta(minutes=minutes),
                    channels=channels,
                    calls_internal=channels // 2,
                    calls_external=0,
                    registrations=1,
                )
            )
        db.commit()
        assert metrics.prune(db) == 1
        out = metrics.series(db, "1h")
        assert out["range"] == "1h" and out["step_seconds"] == 30
        # Buckets keep their maximum, so peaks survive downsampling.
        assert max(p["channels"] for p in out["points"]) == 8
        assert out["points"][-1]["channels"] == 2
        week = metrics.series(db, "7d")
        assert week["step_seconds"] == 2016 and len(week["points"]) <= 300
    r = admin.get("/api/v1/system/metrics/calls", params={"range": "6h"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True and body["current"]["calls_external"] == 1
    assert body["points"] and body["step_seconds"] == 72
    assert admin.get("/api/v1/system/metrics/calls", params={"range": "2y"}).status_code == 422
    # An engine that is not running reports no live reading, history stays.
    adapter.state = "not_configured"
    body = admin.get("/api/v1/system/metrics/calls").json()
    assert body["available"] is False and body["current"] is None and body["points"]
