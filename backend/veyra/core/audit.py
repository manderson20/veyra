# SPDX-License-Identifier: AGPL-3.0-or-later
"""Administrative audit logging.

Every state-changing API operation records an audit event, including denied
and failed attempts. Details are sanitized so that secrets never reach the
audit log.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from veyra.core.models import AuditEvent

log = logging.getLogger("veyra.audit")

_SENSITIVE_MARKERS = ("password", "secret", "token", "key", "credential")
REDACTED = "[REDACTED]"


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (REDACTED if any(m in str(k).lower() for m in _SENSITIVE_MARKERS) else sanitize(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [sanitize(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def record(
    db: Session,
    *,
    action: str,
    outcome: str = "success",
    actor_type: str = "user",
    actor_user_id: uuid.UUID | None = None,
    actor_label: str = "system",
    organization_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    ip_address: str | None = None,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        actor_label=actor_label,
        organization_id=organization_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        outcome=outcome,
        ip_address=ip_address,
        request_id=request_id,
        details=sanitize(details or {}),
    )
    db.add(event)
    log.info("audit %s %s by %s (%s)", action, outcome, actor_label, target_id or "-")
    return event
