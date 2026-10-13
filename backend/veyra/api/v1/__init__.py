# SPDX-License-Identifier: AGPL-3.0-or-later
"""Version 1 of the Veyra management API."""

from fastapi import APIRouter

from veyra.api.v1 import (
    audit,
    auth,
    auth_companion,
    auth_mfa,
    calls,
    directory,
    events,
    extensions,
    ha,
    me,
    modules,
    organizations,
    provisioning,
    routing,
    search,
    setup,
    system,
    telephony,
    trunks,
    updates,
    users,
)

api_router = APIRouter(prefix="/api/v1")
for r in (
    auth,
    auth_mfa,
    auth_companion,
    setup,
    system,
    organizations,
    users,
    search,
    modules,
    updates,
    ha,
    audit,
    provisioning,
    telephony,
    extensions,
    calls,
    trunks,
    routing,
    me,
    directory,
    events,
):
    api_router.include_router(r.router)
