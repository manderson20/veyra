# SPDX-License-Identifier: AGPL-3.0-or-later
"""Platform tables: audit log, settings, modules, updates, HA, configuration revisions,
provisioning templates."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from veyra.core.models.base import Base, Timestamps, UUIDPrimaryKey, utcnow

# --------------------------------------------------------------------------- audit


class AuditEvent(Base):
    """Append-only administrative audit log. Rows are never updated or deleted by
    the application; retention is enforced by a separate, audited job."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_occurred_at", "occurred_at"),
        Index("ix_audit_log_org_occurred", "organization_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow
    )
    actor_type: Mapped[str] = mapped_column(String(16))  # user | system | module
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_label: Mapped[str] = mapped_column(String(320))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(128))
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(16))  # success | failure | denied
    ip_address: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


# --------------------------------------------------------------------------- settings


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


# --------------------------------------------------------------------------- modules


class InstalledModule(Timestamps, Base):
    __tablename__ = "installed_modules"

    module_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[str] = mapped_column(String(64))
    # installed | enabled | disabled | failed | removed (data retained)
    state: Mapped[str] = mapped_column(String(16))
    trust_level: Mapped[str] = mapped_column(String(16))  # official | community | third_party
    signature_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    source_path: Mapped[str] = mapped_column(Text)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    last_error: Mapped[str | None] = mapped_column(Text)


class ModuleConfig(Timestamps, Base):
    __tablename__ = "module_configs"
    __table_args__ = (UniqueConstraint("module_id", "organization_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    module_id: Mapped[str] = mapped_column(String(128))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


# --------------------------------------------------------------------------- updates


class UpdatePolicy(Timestamps, Base):
    """Update behaviour for one component class. See docs/UPDATE_MANAGEMENT.md."""

    __tablename__ = "update_policies"

    # veyra_core | modules | provisioning_templates | telephony_engine | operating_system
    component: Mapped[str] = mapped_column(String(32), primary_key=True)
    # manual | notify | download_approve | auto_install_window
    mode: Mapped[str] = mapped_column(String(32), default="notify")
    channel: Mapped[str] = mapped_column(String(16), default="stable")
    check_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    check_interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    auto_download: Mapped[bool] = mapped_column(Boolean, default=False)
    # Categories that may be installed unattended in auto_install_window mode.
    auto_install_categories: Mapped[list[str]] = mapped_column(JSONB, default=list)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_admins: Mapped[bool] = mapped_column(Boolean, default=True)
    # {"days": ["sun"], "start": "02:00", "duration_minutes": 120, "timezone": "UTC"}
    maintenance_window: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class AvailableUpdate(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "available_updates"
    __table_args__ = (UniqueConstraint("component", "target", "version"),)

    component: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(128))  # "veyra" or a module/template id
    version: Mapped[str] = mapped_column(String(64))
    current_version: Mapped[str | None] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(16))  # security | bugfix | feature
    release_notes: Mapped[str | None] = mapped_column(Text)
    # available | downloaded | approved | installing | installed | failed | dismissed
    state: Mapped[str] = mapped_column(String(16), default="available")
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    # Download, approval and installation (docs/SOFTWARE_UPDATES.md §2-3).
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(320))
    install_when: Mapped[str | None] = mapped_column(String(16))  # now | window
    install_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    install_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class UpdateHistory(UUIDPrimaryKey, Base):
    __tablename__ = "update_history"

    component: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(128))
    from_version: Mapped[str | None] = mapped_column(String(64))
    to_version: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(16), default="running")
    initiated_by: Mapped[str] = mapped_column(String(320))
    node_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    backup_ref: Mapped[str | None] = mapped_column(Text)
    log: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class Backup(UUIDPrimaryKey, Base):
    """A backup taken by the root runner (docs/PRODUCTION_HARDENING.md §2);
    the runner records it through ``veyra backup record``."""

    __tablename__ = "backups"

    kind: Mapped[str] = mapped_column(String(16))  # scheduled | manual | upgrade
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # running | verified | failed | deleted
    state: Mapped[str] = mapped_column(String(16), default="running")
    path: Mapped[str] = mapped_column(Text)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    recipients: Mapped[list[str]] = mapped_column(JSONB, default=list)
    bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    parts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    copies: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    verify: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(320), default="scheduler")


class UpdateCheck(Base):
    __tablename__ = "update_checks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(16))  # ok | not_configured | failed | rejected
    message: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------- HA


class ClusterNode(UUIDPrimaryKey, Timestamps, Base):
    """A Veyra node. Roles are data, never derived from hostnames."""

    __tablename__ = "cluster_nodes"

    node_name: Mapped[str] = mapped_column(String(128), unique=True)
    hostname: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(255))
    # standalone | primary | secondary | witness
    role: Mapped[str] = mapped_column(String(16), default="standalone")
    # online | offline | degraded | maintenance | unknown
    state: Mapped[str] = mapped_column(String(16), default="unknown")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    software_version: Mapped[str | None] = mapped_column(String(64))
    # Milestone 16 (docs/HIGH_AVAILABILITY.md §11): the node's Ed25519 public
    # key for the peer channel, the cluster epoch it last acted in, what its
    # database is doing, the replication figures it last reported, the last
    # successful file sync, and whether it holds the service address.
    public_key: Mapped[str | None] = mapped_column(String(100))
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    epoch: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # primary | standby | down | unknown
    db_role: Mapped[str] = mapped_column(String(16), default="unknown", server_default="unknown")
    replication: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    holds_address: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class ClusterEvent(Base):
    __tablename__ = "cluster_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_type: Mapped[str] = mapped_column(String(64))  # switchover_requested, role_changed, ...
    node_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cluster_nodes.id"))
    actor_label: Mapped[str] = mapped_column(String(320))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


# --------------------------------------------------------------------------- configuration


class ConfigRevision(UUIDPrimaryKey, Base):
    """A generated engine configuration. See docs/ARCHITECTURE.md §Configuration management."""

    __tablename__ = "config_revisions"

    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    engine: Mapped[str] = mapped_column(String(32))
    # draft | validated | deploying | deployed | failed | superseded | rolled_back
    state: Mapped[str] = mapped_column(String(16), default="draft")
    summary: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str | None] = mapped_column(String(64))
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    validation_errors: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("config_revisions.id"))
    created_by: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # now | when_idle: the deployer waits for the engine to have no active
    # calls (up to a timeout) before applying a when_idle revision.
    deploy_mode: Mapped[str] = mapped_column(String(16), default="now")
    deploy_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------------------------- provisioning


class ProvisioningTemplate(UUIDPrimaryKey, Timestamps, Base):
    """Locally created or imported templates. Official templates ship on disk and
    are never modified; local templates override them by inheritance."""

    __tablename__ = "provisioning_templates"
    __table_args__ = (UniqueConstraint("template_key", "version"),)

    template_key: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16))  # local | community
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    files: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
