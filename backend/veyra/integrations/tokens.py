# SPDX-License-Identifier: AGPL-3.0-or-later
"""Integration tokens (docs/INTEGRATIONS.md §2).

An integration is held by a service account (a ``users`` row that cannot sign
in) so the bearer-token path, permission checks and the audit log work as for
people. Its permissions come from the integration's scopes, granted in its
organization only; no role assignment is involved.
"""

from __future__ import annotations

import ipaddress
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.models import ApiToken, Integration, User
from veyra.core.models.base import utcnow
from veyra.core.security import api_tokens, tokens
from veyra.core.security.principal import Grant, Principal

SERVICE_AUTH_SOURCE = "integration"
SERVICE_DOMAIN = "integrations.invalid"
NO_EXPIRY = datetime(9999, 1, 1, tzinfo=UTC)

# What an integration may be allowed to do (§2.2). Administrative permissions
# are deliberately absent.
SCOPES: dict[str, str] = {
    "paging.send": "Start pages",
    "bells.write": "Ring bell schedules now",
    "calls.read": "See active calls",
    "calls.originate": "Place click-to-dial calls",
    "calls.hangup": "Hang up calls in progress",
    "calls.history.read": "Read the call history",
    "calls.history.export": "Export the call history as CSV",
    "directory.read": "Read the directory",
    "reports.read": "Run saved reports",
}


def check_networks(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        v = v.strip()
        if not v:
            continue
        try:
            net = ipaddress.ip_network(v, strict=False)
        except ValueError as e:
            raise ValueError(f"{v!r} is not an address or network") from e
        if str(net) not in out:
            out.append(str(net))
    return out


def address_allowed(integration: Integration, ip: str | None) -> bool:
    if not integration.allowed_networks:
        return True
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for n in integration.allowed_networks:
        try:
            if addr in ipaddress.ip_network(n, strict=False):
                return True
        except ValueError:
            continue
    return False


def _issue_token(db: Session, integration: Integration, ip: str | None) -> str:
    raw = api_tokens.new_token(api_tokens.INTEGRATION_PREFIX)
    row = ApiToken(
        id=uuid.uuid4(),
        user_id=integration.service_user_id,
        kind=api_tokens.KIND_INTEGRATION,
        label=integration.name[:120],
        token_hash=tokens.digest(raw),
        scopes=list(integration.scopes),
        created_at=utcnow(),
        created_ip=ip,
        expires_at=integration.expires_at or NO_EXPIRY,
        last_used_at=None,
        last_used_ip=None,
        revoked_at=None,
    )
    db.add(row)
    db.flush()
    integration.token_id = row.id
    return raw


def create(
    db: Session,
    *,
    organization_id: uuid.UUID,
    name: str,
    scopes: list[str],
    allowed_networks: list[str],
    expires_at: datetime | None,
    created_by: str,
    ip: str | None,
) -> tuple[Integration, str]:
    iid = uuid.uuid4()
    user = User(
        id=uuid.uuid4(),
        email=f"integration-{iid}@{SERVICE_DOMAIN}",
        display_name=f"Integration: {name}"[:200],
        password_hash=None,
        auth_source=SERVICE_AUTH_SOURCE,
        home_organization_id=organization_id,
    )
    db.add(user)
    db.flush()
    integration = Integration(
        id=iid,
        organization_id=organization_id,
        name=name,
        scopes=scopes,
        allowed_networks=allowed_networks,
        expires_at=expires_at,
        service_user_id=user.id,
        created_by=created_by,
    )
    db.add(integration)
    db.flush()
    raw = _issue_token(db, integration, ip)
    return integration, raw


def sync_token(db: Session, integration: Integration) -> None:
    """Carry scope, name and expiry changes over to the live token."""
    token = db.get(ApiToken, integration.token_id) if integration.token_id else None
    if token is not None:
        token.scopes = list(integration.scopes)
        token.label = integration.name[:120]
        token.expires_at = integration.expires_at or NO_EXPIRY
    user = db.get(User, integration.service_user_id)
    if user is not None:
        user.display_name = f"Integration: {integration.name}"[:200]


def rotate(db: Session, integration: Integration, ip: str | None) -> str:
    old = db.get(ApiToken, integration.token_id) if integration.token_id else None
    if old is not None:
        api_tokens.revoke(db, old)
    return _issue_token(db, integration, ip)


def delete(db: Session, integration: Integration) -> None:
    user = db.get(User, integration.service_user_id)
    db.delete(integration)
    db.flush()
    if user is not None:
        db.delete(user)  # cascades to its token


def by_token(db: Session, token: ApiToken) -> Integration | None:
    if token.kind != api_tokens.KIND_INTEGRATION:
        return None
    return db.scalar(select(Integration).where(Integration.token_id == token.id))


def principal_for(integration: Integration, token: ApiToken) -> Principal:
    scopes = frozenset(s for s in integration.scopes if s in SCOPES)
    return Principal(
        user_id=integration.service_user_id,
        email=f"Integration: {integration.name}",
        display_name=integration.name,
        grants=[
            Grant(
                scope_type="organization",
                organization_id=integration.organization_id,
                site_id=None,
                permissions=scopes,
            )
        ],
        token_scopes=scopes,
        token_id=token.id,
    )
