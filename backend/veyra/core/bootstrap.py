# SPDX-License-Identifier: AGPL-3.0-or-later
"""Idempotent bootstrap: installation identity, permissions, system roles,
default update policies and the first-run setup token."""

from __future__ import annotations

import socket
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from veyra.core.models import (
    ClusterNode,
    Installation,
    Permission,
    Role,
    RolePermission,
    SystemSetting,
    UpdatePolicy,
    User,
)
from veyra.core.models.base import utcnow
from veyra.core.security import tokens
from veyra.core.security.permissions import SYSTEM_ROLE_DEFS, PermissionRegistry, registry
from veyra.version import __version__

SETUP_TOKEN_KEY = "setup.token"  # noqa: S105 (settings key, not a secret)
SETUP_TOKEN_TTL = timedelta(hours=24)

UPDATE_COMPONENTS = (
    "veyra_core",
    "modules",
    "provisioning_templates",
    "telephony_engine",
    "operating_system",
)


def ensure_installation(db: Session) -> Installation:
    inst = db.scalar(select(Installation))
    if inst is None:
        inst = Installation(id=uuid.uuid4(), instance_id=uuid.uuid4())
        db.add(inst)
        db.flush()
    return inst


def sync_permissions(db: Session, reg: PermissionRegistry = registry) -> None:
    """Make the permissions table and system-role grants match the registry.

    Custom roles are never touched. Permissions of modules that are no longer
    registered are kept in the table (so custom roles referencing them survive
    a module being disabled) but removed from system roles.
    """
    existing = {p.key: p for p in db.scalars(select(Permission))}
    for definition in reg.all():
        row = existing.get(definition.key)
        if row is None:
            db.add(
                Permission(
                    key=definition.key,
                    description=definition.description,
                    module_id=definition.module_id,
                )
            )
        else:
            row.description = definition.description
            row.module_id = definition.module_id
    db.flush()

    wanted = reg.role_permissions()
    names = {key: (name, desc) for key, name, desc in SYSTEM_ROLE_DEFS}
    roles = {
        r.key: r
        for r in db.scalars(
            select(Role).where(Role.is_system.is_(True), Role.organization_id.is_(None))
        )
    }
    for key, (name, desc) in names.items():
        role = roles.get(key)
        if role is None:
            role = Role(id=uuid.uuid4(), key=key, name=name, description=desc, is_system=True)
            db.add(role)
            db.flush()
            roles[key] = role
        else:
            role.name, role.description = name, desc
        db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        for perm in sorted(wanted.get(key, set())):
            db.add(RolePermission(role_id=role.id, permission_key=perm))
    db.flush()


def ensure_update_policies(db: Session) -> None:
    existing = {p.component for p in db.scalars(select(UpdatePolicy))}
    for component in UPDATE_COMPONENTS:
        if component in existing:
            continue
        # Safe defaults: check and notify; never install unattended.
        # OS and telephony engine updates are managed outside Veyra by default.
        managed_externally = component in ("operating_system", "telephony_engine")
        db.add(
            UpdatePolicy(
                component=component,
                mode="manual" if managed_externally else "notify",
                channel="stable",
                check_enabled=not managed_externally,
                check_interval_hours=24,
                auto_download=False,
                auto_install_categories=[],
                require_approval=True,
                notify_admins=True,
                maintenance_window=None,
            )
        )
    db.flush()


def ensure_local_node(db: Session) -> ClusterNode:
    hostname = socket.gethostname()
    node = db.scalar(select(ClusterNode).where(ClusterNode.node_name == hostname))
    if node is None:
        node = ClusterNode(
            id=uuid.uuid4(),
            node_name=hostname,
            hostname=hostname,
            role="standalone",
            state="online",
        )
        db.add(node)
    node.software_version = __version__
    node.last_heartbeat_at = utcnow()
    node.state = "online"
    db.flush()
    return node


def bootstrap(db: Session) -> Installation:
    inst = ensure_installation(db)
    sync_permissions(db)
    ensure_update_policies(db)
    return inst


# ----------------------------------------------------------------- setup token


def setup_required(db: Session) -> bool:
    return db.scalar(select(User.id).limit(1)) is None


def create_setup_token(db: Session) -> str:
    """Create (or replace) the one-time first-run setup token.

    Only its hash is stored. The installer prints the token on the server
    console so that only someone with shell access can complete setup.
    """
    token = tokens.new_token(24)
    value: dict[str, Any] = {
        "hash": tokens.digest(token),
        "expires_at": (utcnow() + SETUP_TOKEN_TTL).isoformat(),
    }
    row = db.get(SystemSetting, SETUP_TOKEN_KEY)
    if row is None:
        db.add(SystemSetting(key=SETUP_TOKEN_KEY, value=value))
    else:
        row.value = value
    db.flush()
    return token


def check_setup_token(db: Session, token: str) -> bool:
    from datetime import datetime

    row = db.get(SystemSetting, SETUP_TOKEN_KEY)
    if row is None or not token:
        return False
    if datetime.fromisoformat(row.value["expires_at"]) <= utcnow():
        return False
    return tokens.matches(token, row.value["hash"])


def consume_setup_token(db: Session) -> None:
    row = db.get(SystemSetting, SETUP_TOKEN_KEY)
    if row is not None:
        db.delete(row)
