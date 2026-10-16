# SPDX-License-Identifier: AGPL-3.0-or-later
"""Security review (docs/PRODUCTION_HARDENING.md §5): generated secrets never
reach the logs or the audit log's details."""

from __future__ import annotations

import logging

from sqlalchemy import select

from veyra.core.db import session_scope
from veyra.core.models import AuditEvent, Organization


def test_sip_secret_and_tokens_stay_out_of_logs_and_audit(admin, caplog):
    caplog.set_level(logging.DEBUG)
    with session_scope() as db:
        org_id = str(db.query(Organization).first().id)
    ext = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org_id, "number": "2301", "display_name": "Secret Test"},
    ).json()
    creds = admin.get(f"/api/v1/extensions/{ext['id']}/sip-credentials").json()
    secret = creds["secret"]
    assert secret and len(secret) >= 16
    token = admin.post("/api/v1/ha/join-tokens", json={"label": "x"})  # 409 (HA off) is fine
    assert token.status_code in (201, 409)
    text = caplog.text
    assert secret not in text
    with session_scope() as db:
        for ev in db.scalars(select(AuditEvent)):
            blob = str(ev.details)
            assert secret not in blob, f"secret in audit details of {ev.action}"
