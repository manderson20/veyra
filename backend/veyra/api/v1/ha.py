# SPDX-License-Identifier: AGPL-3.0-or-later
"""High availability status (read-only in Milestone 0)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from veyra.core.db import get_db
from veyra.core.deps import require
from veyra.core.security.principal import Principal
from veyra.ha.status import cluster_status

router = APIRouter(prefix="/ha", tags=["high availability"])


@router.get("/status", summary="Cluster mode, nodes and roles")
def status(
    principal: Principal = Depends(require("ha.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return cluster_status(db)
