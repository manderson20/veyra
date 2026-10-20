# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public SDK surface for Veyra modules (module API v1).

Modules should import only from here. Anything else under ``veyra.`` is an
internal implementation detail and may change without notice.
"""

from veyra.core.db import get_db
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.events import Event
from veyra.core.models.base import utcnow
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.modules.context import HealthResult, ModuleContext
from veyra.modules.core_data import (
    DeviceInfo,
    ExtensionInfo,
    OrganizationInfo,
    SiteInfo,
    UserInfo,
)
from veyra.version import MODULE_API_VERSION

__all__ = [
    "MODULE_API_VERSION",
    "DeviceInfo",
    "Event",
    "ExtensionInfo",
    "HealthResult",
    "ModuleContext",
    "OrganizationInfo",
    "Page",
    "PageParams",
    "Principal",
    "ProblemError",
    "SiteInfo",
    "UserInfo",
    "conflict",
    "forbidden",
    "get_db",
    "not_found",
    "page_params",
    "paginate",
    "utcnow",
]
