# SPDX-License-Identifier: AGPL-3.0-or-later
"""All core ORM models. Import this package so metadata is complete."""

from veyra.core.models.base import Base
from veyra.core.models.identity import (
    MfaMethod,
    MfaRecoveryCode,
    PasswordResetToken,
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
from veyra.core.models.routing import (
    InboundRoute,
    OutboundRoute,
    OutboundRouteTrunk,
    SipTrunk,
    TimeCondition,
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
    "InboundRoute",
    "Installation",
    "InstalledModule",
    "MfaMethod",
    "MfaRecoveryCode",
    "ModuleConfig",
    "Organization",
    "OutboundRoute",
    "OutboundRouteTrunk",
    "PasswordResetToken",
    "Permission",
    "ProvisioningTemplate",
    "Role",
    "RoleAssignment",
    "RolePermission",
    "SipTrunk",
    "Site",
    "SystemSetting",
    "TimeCondition",
    "UpdateCheck",
    "UpdateHistory",
    "UpdatePolicy",
    "User",
    "UserSession",
]
