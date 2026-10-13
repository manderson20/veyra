# SPDX-License-Identifier: AGPL-3.0-or-later
"""Permission catalog and built-in system roles.

Permissions are plain strings ``<area>.<action>``. Core registers the ones
below; modules register theirs from their manifest. The ``*`` permission is
held only by the Platform Administrator role and implies every permission.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ALL = "*"


@dataclass(frozen=True)
class PermissionDef:
    key: str
    description: str
    module_id: str = "core"
    # Platform permissions only take effect when granted at platform scope.
    platform_only: bool = False
    default_roles: tuple[str, ...] = ()


CORE_PERMISSIONS: tuple[PermissionDef, ...] = (
    PermissionDef(ALL, "All permissions (Platform Administrator)", platform_only=True),
    PermissionDef(
        "system.health.read",
        "View system health",
        default_roles=("org_admin", "site_admin", "technician", "read_only"),
    ),
    PermissionDef("system.settings.read", "View system settings", platform_only=True),
    PermissionDef("system.settings.write", "Change system settings", platform_only=True),
    PermissionDef(
        "organizations.read",
        "View organizations",
        default_roles=("org_admin", "site_admin", "technician", "read_only"),
    ),
    PermissionDef("organizations.write", "Create and edit organizations", platform_only=True),
    PermissionDef(
        "users.read", "View users", default_roles=("org_admin", "site_admin", "read_only")
    ),
    PermissionDef("users.write", "Create, edit and disable users", default_roles=("org_admin",)),
    PermissionDef(
        "roles.read", "View roles and assignments", default_roles=("org_admin", "read_only")
    ),
    PermissionDef("roles.write", "Assign roles", default_roles=("org_admin",)),
    PermissionDef("audit.read", "View the audit log", default_roles=("org_admin",)),
    PermissionDef(
        "modules.read", "View installed modules", default_roles=("org_admin", "read_only")
    ),
    PermissionDef(
        "modules.manage", "Install, enable, disable and remove modules", platform_only=True
    ),
    PermissionDef(
        "updates.read",
        "View available updates and history",
        default_roles=("org_admin", "read_only"),
    ),
    PermissionDef("updates.manage", "Change update policies", platform_only=True),
    PermissionDef("updates.approve", "Approve and apply updates", platform_only=True),
    PermissionDef(
        "ha.read", "View high availability status", default_roles=("org_admin", "read_only")
    ),
    PermissionDef("ha.manage", "Change HA roles and perform switchover", platform_only=True),
    PermissionDef("config.read", "View configuration revisions", default_roles=("org_admin",)),
    PermissionDef("config.deploy", "Deploy telephony configuration", platform_only=True),
    PermissionDef(
        "provisioning.read",
        "View provisioning templates",
        default_roles=("org_admin", "site_admin", "technician", "read_only"),
    ),
    PermissionDef(
        "provisioning.write",
        "Create and edit local provisioning templates",
        default_roles=("org_admin",),
    ),
    PermissionDef(
        "extensions.read",
        "View extensions",
        default_roles=("org_admin", "site_admin", "technician", "read_only"),
    ),
    PermissionDef(
        "extensions.write", "Create and edit extensions", default_roles=("org_admin", "site_admin")
    ),
    PermissionDef(
        "calls.read",
        "View active calls",
        default_roles=("org_admin", "site_admin", "technician", "read_only"),
    ),
    PermissionDef(
        "calls.originate",
        "Place calls from your own extensions (click-to-dial)",
        default_roles=("org_admin", "site_admin", "technician", "standard_user", "read_only"),
    ),
    PermissionDef(
        "trunks.read",
        "View SIP trunks and their status",
        default_roles=("org_admin", "technician"),
    ),
    PermissionDef(
        "trunks.write", "Create and edit SIP trunks and outbound routes", platform_only=True
    ),
    PermissionDef(
        "routing.read",
        "View inbound routes, outbound routes and time conditions",
        default_roles=("org_admin", "site_admin", "technician", "read_only"),
    ),
    PermissionDef(
        "routing.write",
        "Create and edit inbound routes and time conditions",
        default_roles=("org_admin", "site_admin"),
    ),
    PermissionDef(
        "voicemail.read",
        "View voicemail boxes",
        default_roles=("org_admin", "site_admin", "technician", "read_only"),
    ),
    PermissionDef(
        "voicemail.write",
        "Create and edit voicemail boxes and reset PINs",
        default_roles=("org_admin", "site_admin"),
    ),
    PermissionDef(
        "ivr.read",
        "View IVR menus and prompts",
        default_roles=("org_admin", "site_admin", "technician", "read_only"),
    ),
    PermissionDef(
        "ivr.write",
        "Create and edit IVR menus and prompts",
        default_roles=("org_admin", "site_admin"),
    ),
    PermissionDef(
        "directory.read",
        "Look up extensions and people in your organizations (directory)",
        default_roles=("org_admin", "site_admin", "technician", "standard_user", "read_only"),
    ),
    PermissionDef(
        "devices.read",
        "View devices",
        default_roles=("org_admin", "site_admin", "technician", "read_only"),
    ),
    PermissionDef(
        "devices.write",
        "Create and edit devices",
        default_roles=("org_admin", "site_admin", "technician"),
    ),
)


@dataclass(frozen=True)
class RoleDef:
    key: str
    name: str
    description: str
    permissions: frozenset[str] = field(default_factory=frozenset)


SYSTEM_ROLE_DEFS: tuple[tuple[str, str, str], ...] = (
    (
        "platform_admin",
        "Platform Administrator",
        "Full control of this Veyra installation and every organization on it.",
    ),
    (
        "org_admin",
        "Organization Administrator",
        "Manages users, telephony and devices within an organization.",
    ),
    ("site_admin", "Site Administrator", "Manages extensions and devices at a site."),
    ("technician", "Technician", "Maintains devices and views telephony configuration."),
    ("standard_user", "Standard User", "Self-service access to their own phone and voicemail."),
    ("read_only", "Read-Only User", "Can view, but not change, configuration."),
)


class PermissionRegistry:
    """In-memory view of every known permission (core + enabled modules)."""

    def __init__(self) -> None:
        self._defs: dict[str, PermissionDef] = {}
        for p in CORE_PERMISSIONS:
            self.register(p)

    def register(self, perm: PermissionDef) -> None:
        existing = self._defs.get(perm.key)
        if existing and existing.module_id != perm.module_id:
            raise ValueError(
                f"Permission {perm.key!r} is already registered by {existing.module_id!r}"
            )
        self._defs[perm.key] = perm

    def unregister_module(self, module_id: str) -> None:
        for key in [k for k, v in self._defs.items() if v.module_id == module_id]:
            del self._defs[key]

    def get(self, key: str) -> PermissionDef | None:
        return self._defs.get(key)

    def all(self) -> list[PermissionDef]:
        return sorted(self._defs.values(), key=lambda p: p.key)

    def role_permissions(self) -> dict[str, set[str]]:
        mapping: dict[str, set[str]] = {key: set() for key, _, _ in SYSTEM_ROLE_DEFS}
        mapping["platform_admin"].add(ALL)
        for p in self._defs.values():
            for role in p.default_roles:
                mapping.setdefault(role, set()).add(p.key)
        return mapping


registry = PermissionRegistry()
