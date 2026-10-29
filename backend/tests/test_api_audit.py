# SPDX-License-Identifier: AGPL-3.0-or-later
"""Audit log search: date range and CSV export with the same filters."""

import csv
import io
from datetime import UTC, datetime, timedelta

from veyra.core.db import session_scope
from veyra.core.models import AuditEvent


def _event(action: str, at: datetime) -> None:
    with session_scope() as db:
        db.add(
            AuditEvent(
                occurred_at=at,
                actor_type="user",
                actor_label="tester@example.org",
                action=action,
                outcome="success",
                details={"n": 1},
            )
        )


def test_date_range_and_export(admin):
    now = datetime.now(UTC)
    _event("test.old", now - timedelta(days=10))
    _event("test.new", now - timedelta(hours=1))
    since = (now - timedelta(days=1)).isoformat()
    r = admin.get("/api/v1/audit", params={"q": "test.", "from": since})
    assert r.status_code == 200, r.text
    assert [e["action"] for e in r.json()["items"]] == ["test.new"]
    until = (now - timedelta(days=5)).isoformat()
    assert [
        e["action"]
        for e in admin.get("/api/v1/audit", params={"q": "test.", "to": until}).json()["items"]
    ] == ["test.old"]
    r = admin.get("/api/v1/audit/export.csv", params={"q": "test."})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [x["action"] for x in rows] == ["test.new", "test.old"]
    assert rows[0]["actor"] == "tester@example.org" and rows[0]["details"] == '{"n": 1}'
