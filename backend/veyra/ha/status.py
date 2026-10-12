"""Cluster status reporting (read-only in Milestone 0)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.core.models import ClusterNode, Installation
from veyra.core.models.base import utcnow

HEARTBEAT_STALE_AFTER = timedelta(minutes=2)


def _db_role(db: Session) -> str | None:
    """'primary' when this database accepts writes, 'standby' when it is a replica."""
    try:
        in_recovery = db.scalar(select(func.pg_is_in_recovery()))
    except Exception:
        db.rollback()
        return None
    return "standby" if in_recovery else "primary"


def cluster_status(db: Session) -> dict[str, Any]:
    inst = db.scalar(select(Installation))
    nodes = list(db.scalars(select(ClusterNode).order_by(ClusterNode.node_name)))
    now = utcnow()
    node_rows = []
    for n in nodes:
        stale = n.last_heartbeat_at is None or now - n.last_heartbeat_at > HEARTBEAT_STALE_AFTER
        node_rows.append(
            {
                "id": str(n.id),
                "node_name": n.node_name,
                "hostname": n.hostname,
                "address": n.address,
                "role": n.role,
                "state": "unknown" if stale else n.state,
                "last_heartbeat_at": n.last_heartbeat_at.isoformat()
                if n.last_heartbeat_at
                else None,
                "software_version": n.software_version,
            }
        )
    mode = inst.deployment_mode if inst else "standalone"
    return {
        "deployment_mode": mode,
        "ha_enabled": mode == "ha",
        "automatic_failover": False,
        "automatic_failover_reason": (
            "Automatic failover is disabled until fencing and quorum have been implemented "
            "and tested (Milestone 16)."
        ),
        "database_role": _db_role(db),
        "replication": None if mode != "ha" else {"state": "unknown"},
        "nodes": node_rows,
    }
