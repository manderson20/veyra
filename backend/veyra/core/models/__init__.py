"""All core ORM models. Import this package so metadata is complete."""

from veyra.core.models.base import Base
from veyra.core.models.identity import (
    Permission,
    Role,
    RoleAssignment,
    RolePermission,
    User,
    UserSession,
)
from veyra.core.models.platform import (
    AuditEvent,
    AvailableUpdate,
    ClusterEvent,
    ClusterNode,
    ConfigRevision,
    InstalledModule,
    ModuleConfig,
    ProvisioningTemplate,
    SystemSetting,
    UpdateCheck,
    UpdateHistory,
    UpdatePolicy,
)
from veyra.core.models.telephony import Device, Extension
from veyra.core.models.tenancy import Building, Department, Installation, Organization, Site

__all__ = [
    "AuditEvent",
    "AvailableUpdate",
    "Base",
    "Building",
    "ClusterEvent",
    "ClusterNode",
    "ConfigRevision",
    "Department",
    "Device",
    "Extension",
    "Installation",
    "InstalledModule",
    "ModuleConfig",
    "Organization",
    "Permission",
    "ProvisioningTemplate",
    "Role",
    "RoleAssignment",
    "RolePermission",
    "Site",
    "SystemSetting",
    "UpdateCheck",
    "UpdateHistory",
    "UpdatePolicy",
    "User",
    "UserSession",
]
