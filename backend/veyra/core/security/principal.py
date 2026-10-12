"""The authenticated caller and its effective, scoped permissions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from veyra.core.security.permissions import ALL, registry


@dataclass(frozen=True)
class Grant:
    scope_type: str  # platform | organization | site
    organization_id: uuid.UUID | None
    site_id: uuid.UUID | None
    permissions: frozenset[str]


@dataclass
class Principal:
    user_id: uuid.UUID
    email: str
    display_name: str
    grants: list[Grant] = field(default_factory=list)
    session_id: uuid.UUID | None = None

    @property
    def label(self) -> str:
        return self.email

    @property
    def is_platform_admin(self) -> bool:
        return any(g.scope_type == "platform" and ALL in g.permissions for g in self.grants)

    def has(
        self,
        permission: str,
        organization_id: uuid.UUID | None = None,
        site_id: uuid.UUID | None = None,
    ) -> bool:
        """True when ``permission`` is granted for the given scope.

        * Platform grants apply everywhere.
        * Organization grants apply to that organization (and its sites).
        * Site grants apply only to that site.
        * Permissions marked ``platform_only`` require a platform grant.
        * With no organization given, only platform grants count, unless
          ``organization_id`` is irrelevant for the permission, in which case
          callers should use :meth:`has_any_scope`.
        """
        definition = registry.get(permission)
        platform_only = definition.platform_only if definition else True
        for g in self.grants:
            if not (permission in g.permissions or ALL in g.permissions):
                continue
            if g.scope_type == "platform":
                return True
            if platform_only or organization_id is None:
                continue
            if g.organization_id != organization_id:
                continue
            if g.scope_type == "organization":
                return True
            if g.scope_type == "site" and site_id is not None and g.site_id == site_id:
                return True
        return False

    def has_any_scope(self, permission: str) -> bool:
        """True when the permission is granted in at least one scope (used for
        navigation and for list endpoints that then filter by scope)."""
        definition = registry.get(permission)
        platform_only = definition.platform_only if definition else True
        for g in self.grants:
            granted = permission in g.permissions or ALL in g.permissions
            if granted and (g.scope_type == "platform" or not platform_only):
                return True
        return False

    def organization_ids_with(self, permission: str) -> set[uuid.UUID] | None:
        """Organizations in which ``permission`` is held at organization scope.

        Returns ``None`` when the permission is held at platform scope
        (meaning: every organization).
        """
        result: set[uuid.UUID] = set()
        for g in self.grants:
            if permission in g.permissions or ALL in g.permissions:
                if g.scope_type == "platform":
                    return None
                if g.scope_type == "organization" and g.organization_id:
                    result.add(g.organization_id)
        return result

    def effective_permissions(self) -> list[str]:
        """Flattened list used by the UI to show/hide navigation. Advisory only:
        every API endpoint enforces permissions itself."""
        if self.is_platform_admin:
            return sorted(p.key for p in registry.all())
        keys: set[str] = set()
        for g in self.grants:
            keys |= set(g.permissions)
        return sorted(keys)
