# SPDX-License-Identifier: AGPL-3.0-or-later
"""Single sign-on, integration tokens and outgoing webhooks (docs/INTEGRATIONS.md)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, Timestamps, UUIDPrimaryKey


class IdentityProvider(UUIDPrimaryKey, Timestamps, Base):
    """An OpenID Connect provider people sign in with (§1.1)."""

    __tablename__ = "identity_providers"

    kind: Mapped[str] = mapped_column(String(16))  # google | microsoft | oidc
    name: Mapped[str] = mapped_column(String(120))
    issuer: Mapped[str] = mapped_column(String(500))
    client_id: Mapped[str] = mapped_column(String(500))
    # Encrypted with the installation key, purpose ``sso:client-secret``.
    client_secret_enc: Mapped[str] = mapped_column(Text)
    allowed_domains: Mapped[list[str]] = mapped_column(JSONB, default=list)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    create_accounts: Mapped[bool] = mapped_column(Boolean, default=False)
    default_role_key: Mapped[str] = mapped_column(String(64), default="standard_user")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Cached discovery document and JWKS (refetched when stale or on an unknown kid).
    discovery: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    jwks: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    metadata_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserIdentity(UUIDPrimaryKey, Base):
    """The link between a Veyra account and a provider subject (§1.3)."""

    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("provider_id", "subject"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identity_providers.id", ondelete="CASCADE")
    )
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SsoRequest(UUIDPrimaryKey, Base):
    """One sign-in attempt between the start and the callback (§1.2), and for
    the Companion the one-time code handed back to the extension (§1.6)."""

    __tablename__ = "sso_requests"

    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identity_providers.id", ondelete="CASCADE")
    )
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Digest of the cookie value that binds a web attempt to its browser.
    browser_hash: Mapped[str | None] = mapped_column(String(64))
    nonce: Mapped[str] = mapped_column(String(100))
    code_verifier: Mapped[str] = mapped_column(String(128))
    client: Mapped[str] = mapped_column(String(16))  # web | companion | test
    next_path: Mapped[str | None] = mapped_column(String(500))
    # Companion: where to send the one-time code and the extension's PKCE challenge.
    redirect_uri: Mapped[str | None] = mapped_column(String(500))
    client_challenge: Mapped[str | None] = mapped_column(String(128))
    result_code_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    result_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    result_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    # A test sign-in from the setup wizard (§1.8): what would have happened.
    test_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Integration(UUIDPrimaryKey, Timestamps, Base):
    """An organization's API token for another system (§2). The token itself is
    an ``api_tokens`` row of kind ``integration`` held by a service account."""

    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    allowed_networks: Mapped[list[str]] = mapped_column(JSONB, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    service_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("api_tokens.id", ondelete="SET NULL")
    )
    created_by: Mapped[str] = mapped_column(String(320))


class Webhook(UUIDPrimaryKey, Timestamps, Base):
    """An outgoing webhook (§3)."""

    __tablename__ = "webhooks"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(Text)
    allow_http: Mapped[bool] = mapped_column(Boolean, default=False)
    events: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # Encrypted, purpose ``webhooks:secret``; the previous one is kept for a
    # day after a rotation so receivers can switch over.
    secret_enc: Mapped[str] = mapped_column(Text)
    previous_secret_enc: Mapped[str | None] = mapped_column(Text)
    previous_secret_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    disabled_reason: Mapped[str | None] = mapped_column(String(200))
    failing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(16))  # delivered | failed
    created_by: Mapped[str] = mapped_column(String(320))


class WebhookDelivery(UUIDPrimaryKey, Base):
    """One event for one webhook: the outbox row the worker sends (§3.5)."""

    __tablename__ = "webhook_deliveries"

    webhook_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("webhooks.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # pending | delivered | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=6)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(500))
    response_excerpt: Mapped[str | None] = mapped_column(Text)


class AutomationRule(UUIDPrimaryKey, Timestamps, Base):
    """ "When X happens, do Y" (issue #117; docs/INTEGRATIONS.md §3.8): an
    event of the webhook catalogue, or a request to the rule's own secret
    address (``hook``), with field conditions and actions."""

    __tablename__ = "automation_rules"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # An event name (``call.ended``) or ``hook`` (incoming web request).
    trigger: Mapped[str] = mapped_column(String(64))
    # [{"field": "outcome", "equals": "missed"}]: all must hold (dotted paths).
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # [{"type": "email", "to": [...]}, {"type": "page", "page_id": ..., "audio_id": ...}]
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=60)
    # SHA-256 of the hook token (``hook`` rules); the token is shown once.
    hook_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fire_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(320))


class AutomationRun(UUIDPrimaryKey, Base):
    """One firing of a rule, queued where the event is emitted and run by
    the worker (pages need the engine; the emitter's transaction stays short)."""

    __tablename__ = "automation_runs"

    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|done|failed
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
