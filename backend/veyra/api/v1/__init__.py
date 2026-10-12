# SPDX-License-Identifier: AGPL-3.0-or-later
"""Version 1 of the Veyra management API."""

from fastapi import APIRouter

from veyra.api.v1 import (
    audit,
    auth,
    auth_mfa,
    extensions,
    ha,
    modules,
    organizations,
    provisioning,
    search,
    setup,
    system,
    telephony,
    updates,
    users,
)

api_router = APIRouter(prefix="/api/v1")
for r in (
    auth,
    auth_mfa,
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
):
    api_router.include_router(r.router)
