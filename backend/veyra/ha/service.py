# SPDX-License-Identifier: AGPL-3.0-or-later
"""The database side of HA (docs/HIGH_AVAILABILITY.md §9, §11): settings,
node rows, events, and the actions the root agent asks for through
``veyra ha db <action>`` (run as the service account, so the agent never
holds a database connection of its own).
"""

from __future__ import annotations

import socket
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra import __version__
from veyra.central import protocol
from veyra.core import audit
from veyra.core.models import ClusterEvent, ClusterNode, Installation, SystemSetting
from veyra.core.models.base import utcnow
from veyra.core.security.crypto import InstallationKey
from veyra.ha import rules
from veyra.ha.state import NodeState, Operation, StateDir

SERVICE_KEY = "ha.service"
FENCING_KEY = "ha.fencing"
SYNC_KEY = "ha.sync"
FENCING_PURPOSE = "ha:fencing-token"
HEARTBEAT_STALE_AFTER = timedelta(minutes=2)
EVENT_TYPES = (
    "ha_enabled",
    "node_joined",
    "node_removed",
    "switchover_started",
    "switchover_epoch",
    "switchover_completed",
    "switchover_aborted",
    "switchover_failed",
    "failover_started",
    "failover_epoch",
    "failover_completed",
    "fenced",
    "demoted",
    "rejoined",
    "isolated",
    "resumed",
    "ha_operation_failed",
)


class HAError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ------------------------------------------------------------------ settings


def setting(db: Session, key: str) -> dict[str, Any]:
    row = db.get(SystemSetting, key)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


def save_setting(db: Session, key: str, value: dict[str, Any], by: uuid.UUID | None = None) -> None:
    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=value, updated_by=by))
    else:
        row.value = value
        row.updated_by = by
    db.flush()


def service_settings(db: Session) -> dict[str, Any]:
    v = setting(db, SERVICE_KEY)
    return {
        "name": str(v.get("name") or ""),
        "address": str(v.get("address") or ""),
        "prefix": int(v.get("prefix") or 24),
        "interface": str(v.get("interface") or ""),
        "synchronous": bool(v.get("synchronous")),
    }


def sync_settings(db: Session) -> dict[str, Any]:
    v = setting(db, SYNC_KEY)
    return {"recordings": bool(v.get("recordings", True)), "interval": int(v.get("interval") or 30)}


def fencing_settings(db: Session, key: InstallationKey | None = None) -> dict[str, Any]:
    """The fencing settings without the secret (``has_secret`` says whether
    one is stored); ``key`` returns the decrypted secret under ``secret``."""
    v = setting(db, FENCING_KEY)
    out: dict[str, Any] = {
        "enabled": bool(v.get("enabled")),
        "method": "proxmox",
        "url": str(v.get("url") or ""),
        "token_id": str(v.get("token_id") or ""),
        "pve_node": str(v.get("pve_node") or ""),
        "vms": v.get("vms") if isinstance(v.get("vms"), dict) else {},
        "verify_tls": bool(v.get("verify_tls", True)),
        "ca_pem": str(v.get("ca_pem") or ""),
        "has_secret": bool(v.get("secret")),
    }
    if key is not None and v.get("secret"):
        out["secret"] = key.decrypt(str(v["secret"]), FENCING_PURPOSE)
    return out


def save_fencing(
    db: Session, body: dict[str, Any], key: InstallationKey, by: uuid.UUID | None
) -> dict[str, Any]:
    current = setting(db, FENCING_KEY)
    value: dict[str, Any] = {
        "enabled": bool(body.get("enabled")),
        "method": "proxmox",
        "url": str(body.get("url") or "").rstrip("/"),
        "token_id": str(body.get("token_id") or ""),
        "pve_node": str(body.get("pve_node") or ""),
        "vms": body.get("vms") if isinstance(body.get("vms"), dict) else {},
        "verify_tls": bool(body.get("verify_tls", True)),
        "ca_pem": str(body.get("ca_pem") or ""),
        "secret": current.get("secret"),
    }
    if body.get("token_secret"):
        value["secret"] = key.encrypt(str(body["token_secret"]), FENCING_PURPOSE)
    if value["enabled"] and not (value["url"] and value["token_id"] and value["secret"]):
        raise HAError(400, "fencing_incomplete", "Fencing needs the URL, token id and secret.")
    save_setting(db, FENCING_KEY, value, by)
    return fencing_settings(db)


# ------------------------------------------------------------------ nodes


def local_name() -> str:
    return socket.gethostname()


def node_by_name(db: Session, name: str) -> ClusterNode | None:
    return db.scalar(select(ClusterNode).where(ClusterNode.node_name == name))


def installation(db: Session) -> Installation:
    inst = db.scalar(select(Installation))
    if inst is None:
        raise HAError(500, "no_installation", "The installation row is missing.")
    return inst


def db_role(db: Session) -> str:
    try:
        rec = db.scalar(select(func.pg_is_in_recovery()))
    except Exception:
        db.rollback()
        return "down"
    return "standby" if rec else "primary"


def record_event(
    db: Session, event_type: str, details: dict[str, Any], *, node_name: str | None, actor: str
) -> ClusterEvent:
    node = node_by_name(db, node_name) if node_name else None
    ev = ClusterEvent(
        event_type=event_type,
        node_id=node.id if node else None,
        actor_label=actor[:320],
        details=details,
    )
    db.add(ev)
    audit.record(
        db,
        action=f"ha.{event_type}",
        actor_type="system" if actor in ("agent", "peer") else "user",
        actor_label=actor,
        target_type="cluster_node" if node else None,
        target_id=node.id if node else None,
        details=details,
    )
    db.flush()
    return ev


def node_out(n: ClusterNode, now: datetime) -> dict[str, Any]:
    stale = rules.heartbeat_stale(n.last_heartbeat_at, now, HEARTBEAT_STALE_AFTER)
    return {
        "id": str(n.id),
        "node_name": n.node_name,
        "hostname": n.hostname,
        "address": n.address,
        "role": n.role,
        "state": "unknown" if stale and n.state == "online" else n.state,
        "last_heartbeat_at": n.last_heartbeat_at.isoformat() if n.last_heartbeat_at else None,
        "software_version": n.software_version,
        "fingerprint": n.fingerprint,
        "epoch": n.epoch,
        "db_role": n.db_role,
        "replication": dict(n.replication or {}),
        "sync_at": n.sync_at.isoformat() if n.sync_at else None,
        "holds_address": n.holds_address,
        "stale": stale,
    }


# ------------------------------------------------------------------ agent actions (``veyra ha db``)


def action_set_roles(db: Session, p: dict[str, Any]) -> dict[str, Any]:
    """After a promotion: who is primary, the epoch, the other's state."""
    inst = installation(db)
    epoch = int(p["epoch"])
    inst.ha_epoch = epoch
    inst.deployment_mode = "ha"
    for name, role, state in (
        (p["primary"], "primary", "online"),
        (p["secondary"], "secondary", str(p.get("secondary_state") or "unknown")),
    ):
        node = node_by_name(db, name)
        if node is None:
            continue
        node.role, node.state = role, state
        node.epoch = epoch
        if role == "primary":
            node.db_role = "primary"
    db.flush()
    return {"epoch": epoch}


def action_set_frozen(db: Session, p: dict[str, Any]) -> dict[str, Any]:
    inst = installation(db)
    inst.ha_frozen = bool(p.get("frozen"))
    db.flush()
    return {"frozen": inst.ha_frozen}


def action_event(db: Session, p: dict[str, Any]) -> dict[str, Any]:
    ev = record_event(
        db,
        str(p["event_type"]),
        dict(p.get("details") or {}),
        node_name=p.get("node_name"),
        actor=str(p.get("actor") or "agent"),
    )
    return {"id": ev.id}


def action_node_report(db: Session, p: dict[str, Any]) -> dict[str, Any]:
    """The agent's own figures (also used for the peer's heartbeat)."""
    node = node_by_name(db, str(p["node_name"]))
    if node is None:
        node = ClusterNode(
            id=uuid.uuid4(),
            node_name=str(p["node_name"]),
            hostname=str(p.get("hostname") or p["node_name"]),
            role=str(p.get("role") or "secondary"),
        )
        db.add(node)
    now = utcnow()
    node.last_heartbeat_at = now
    for field in ("address", "db_role", "software_version", "public_key", "fingerprint"):
        if p.get(field) is not None:
            setattr(node, field, p[field])
    if p.get("role"):
        node.role = str(p["role"])
    if p.get("state"):
        node.state = str(p["state"])
    if p.get("epoch") is not None:
        node.epoch = int(p["epoch"])
    if isinstance(p.get("replication"), dict):
        node.replication = p["replication"]
    if p.get("holds_address") is not None:
        node.holds_address = bool(p["holds_address"])
    if p.get("sync_at"):
        node.sync_at = datetime.fromisoformat(str(p["sync_at"]))
    db.flush()
    return {"id": str(node.id)}


def action_enable(db: Session, p: dict[str, Any]) -> dict[str, Any]:
    """Standalone becomes the primary of epoch 1 (§5)."""
    inst = installation(db)
    node = node_by_name(db, str(p["node_name"]))
    if node is None:
        node = ClusterNode(
            id=uuid.uuid4(), node_name=str(p["node_name"]), hostname=str(p["node_name"])
        )
        db.add(node)
    node.role, node.state, node.epoch = "primary", "online", 1
    node.db_role = "primary"
    node.address = str(p.get("address") or "") or node.address
    node.public_key = str(p["public_key"])
    node.fingerprint = protocol.fingerprint(node.public_key)
    node.software_version = __version__
    node.holds_address = True
    inst.deployment_mode = "ha"
    inst.ha_epoch = 1
    inst.ha_frozen = False
    if isinstance(p.get("service"), dict):
        save_setting(db, SERVICE_KEY, p["service"])
    record_event(
        db,
        "ha_enabled",
        {"node": node.node_name, "service": p.get("service")},
        node_name=node.node_name,
        actor=str(p.get("actor") or "agent"),
    )
    return {"node_id": str(node.id), "epoch": 1}


def action_register_peer(db: Session, p: dict[str, Any]) -> dict[str, Any]:
    node = node_by_name(db, str(p["node_name"]))
    if node is None:
        node = ClusterNode(
            id=uuid.uuid4(),
            node_name=str(p["node_name"]),
            hostname=str(p.get("hostname") or p["node_name"]),
        )
        db.add(node)
    node.role, node.state = "secondary", "joining"
    node.address = str(p.get("address") or "")
    node.public_key = str(p["public_key"])
    node.fingerprint = protocol.fingerprint(node.public_key)
    node.epoch = installation(db).ha_epoch
    node.db_role = "unknown"
    db.flush()
    record_event(
        db,
        "node_joined",
        {"node": node.node_name, "address": node.address},
        node_name=node.node_name,
        actor=str(p.get("actor") or "agent"),
    )
    return {"node_id": str(node.id)}


def action_remove_node(db: Session, p: dict[str, Any]) -> dict[str, Any]:
    node = node_by_name(db, str(p["node_name"]))
    if node is None:
        return {"removed": False}
    record_event(
        db,
        "node_removed",
        {"node": node.node_name},
        node_name=None,
        actor=str(p.get("actor") or "agent"),
    )
    # The history keeps its rows; they just no longer point at the node.
    from sqlalchemy import update

    db.execute(update(ClusterEvent).where(ClusterEvent.node_id == node.id).values(node_id=None))
    db.delete(node)
    inst = installation(db)
    remaining = db.scalar(select(func.count()).select_from(ClusterNode))
    if remaining is not None and remaining <= 1:
        inst.deployment_mode = "standalone"
    db.flush()
    return {"removed": True, "deployment_mode": inst.deployment_mode}


def action_standalone(db: Session, p: dict[str, Any]) -> dict[str, Any]:
    inst = installation(db)
    inst.deployment_mode = "standalone"
    inst.ha_frozen = False
    node = node_by_name(db, str(p["node_name"]))
    if node is not None:
        node.role, node.state = "standalone", "online"
    for other in db.scalars(
        select(ClusterNode).where(ClusterNode.node_name != str(p["node_name"]))
    ):
        db.delete(other)
    db.flush()
    return {"deployment_mode": "standalone"}


def action_deploy(db: Session, p: dict[str, Any]) -> dict[str, Any]:
    """A revision from the database, queued for the deployer; the agent waits
    for the deployer separately (``wait-deploy``)."""
    from veyra.configmgmt import service as cfg
    from veyra.core.config import get_settings
    from veyra.core.security.crypto import try_load_installation_key
    from veyra.telephony import get_adapter

    settings = get_settings()
    generated = cfg.create_revision(
        db, get_adapter(settings), created_by="ha-agent", key=try_load_installation_key(settings)
    )
    rev = generated.revision
    if rev.state == "validated":
        cfg.request_deploy(db, rev)
    return {"sequence": rev.sequence, "state": rev.state, "errors": list(rev.validation_errors)}


def action_deploy_state(db: Session, p: dict[str, Any]) -> dict[str, Any]:
    from veyra.core.models import ConfigRevision

    rev = db.scalar(select(ConfigRevision).where(ConfigRevision.sequence == int(p["sequence"])))
    return {"state": rev.state if rev else "missing"}


ACTIONS = {
    "set-roles": action_set_roles,
    "set-frozen": action_set_frozen,
    "event": action_event,
    "node-report": action_node_report,
    "enable": action_enable,
    "register-peer": action_register_peer,
    "remove-node": action_remove_node,
    "standalone": action_standalone,
    "deploy": action_deploy,
    "deploy-state": action_deploy_state,
}


# ------------------------------------------------------------------ status


def status(
    db: Session,
    state_dir: StateDir,
    agent_status: dict[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """``GET /ha/status`` (§9): Milestone 0's fields plus local, peer,
    replication, sync, service, operation and fencing."""
    now = now or utcnow()
    inst = db.scalar(select(Installation))
    mode = inst.deployment_mode if inst else "standalone"
    nodes = list(db.scalars(select(ClusterNode).order_by(ClusterNode.node_name)))
    local = state_dir.node()
    op = state_dir.operation()
    sync = state_dir.sync()
    me = local_name()
    local_row = next((n for n in nodes if n.node_name == me), None)
    peer_row = next((n for n in nodes if n.node_name != me), None) if mode == "ha" else None
    role_db = db_role(db)
    service = service_settings(db)
    holder = next((n.node_name for n in nodes if n.holds_address), None)
    replication: dict[str, Any] | None = None
    if agent_status and isinstance(agent_status.get("replication"), dict):
        replication = agent_status["replication"]
    elif local_row is not None and local_row.replication:
        replication = dict(local_row.replication)
    return {
        "deployment_mode": mode,
        "ha_enabled": mode == "ha",
        "automatic_failover": False,
        "automatic_failover_reason": (
            "Automatic failover is disabled: without a witness, a node cannot tell a dead peer "
            "from a broken link. Failover is the operator's decision "
            "(docs/HIGH_AVAILABILITY.md §7)."
        ),
        "database_role": role_db,
        "version": __version__,
        "nodes": [node_out(n, now) for n in nodes],
        "local": {
            "node_name": me,
            "role": local.role if local else (local_row.role if local_row else "standalone"),
            "epoch": local.epoch if local else (local_row.epoch if local_row else 0),
            "state": local.state if local else "online",
            "db_role": role_db,
            "holds_address": bool(agent_status.get("holds_address"))
            if agent_status
            else bool(local_row.holds_address if local_row else False),
            "agent": agent_status is not None,
            "peer_reachable": agent_status.get("peer_reachable") if agent_status else None,
            "frozen": bool(inst.ha_frozen) if inst else False,
        },
        "peer": node_out(peer_row, now) if peer_row else None,
        "replication": replication if mode == "ha" else None,
        "sync": {
            "last_success_at": sync.last_success_at,
            "last_attempt_at": sync.last_attempt_at,
            "last_error": sync.last_error,
            "backlog": sync.backlog,
            "running": bool(agent_status.get("sync_running")) if agent_status else False,
            "recordings": sync_settings(db)["recordings"],
        }
        if mode == "ha"
        else None,
        "service": {**service, "holder": holder},
        "operation": op.to_dict() if op else None,
        "fencing": {
            "configured": bool(setting(db, FENCING_KEY).get("enabled")),
            "method": "proxmox",
        },
        "epoch": inst.ha_epoch if inst else 0,
    }


def health_payload(
    db: Session, state_dir: StateDir, agent_status: dict[str, Any] | None
) -> dict[str, Any]:
    """What this node answers to the peer's ``health`` (§3.2)."""
    local = state_dir.node()
    role_db = db_role(db)
    me = local_name()
    row: ClusterNode | None = None
    frozen = False
    if role_db != "down":
        # Node calls must be answered while the database is stopped
        # (switchover step 4); the state files carry what is needed.
        try:
            row = node_by_name(db, me)
            frozen = bool(installation(db).ha_frozen) if row else False
        except Exception:
            db.rollback()
            row = None
    if row is None and local is not None:
        frozen = local.state == "frozen"
    sync = state_dir.sync()
    op = state_dir.operation()
    return {
        "node_id": local.node_id if local else (str(row.id) if row else ""),
        "node_name": me,
        "role": local.role if local else (row.role if row else "standalone"),
        "epoch": local.epoch if local else (row.epoch if row else 0),
        "state": local.state if local else "online",
        "db_role": role_db,
        "version": __version__,
        "holds_address": bool(agent_status.get("holds_address")) if agent_status else False,
        "replication": agent_status.get("replication") if agent_status else None,
        "sync_at": sync.last_success_at,
        "operation": op.to_dict() if op else None,
        "frozen": frozen,
    }


def switchover_facts(
    db: Session,
    state_dir: StateDir,
    target: ClusterNode,
    agent_status: dict[str, Any] | None,
    now: datetime | None = None,
) -> rules.SwitchoverFacts:
    now = now or utcnow()
    local = state_dir.node()
    inst = installation(db)
    rep = (agent_status or {}).get("replication") or {}
    sync = state_dir.sync()
    sync_age = None
    if target.sync_at is not None:
        sync_age = now - target.sync_at
    elif sync.last_success_at:
        sync_age = now - datetime.fromisoformat(sync.last_success_at)
    op = state_dir.operation()
    from veyra.configmgmt import service as cfg
    from veyra.core.models import AvailableUpdate

    deploying = any(cfg.pending(db, engine) is not None for engine in ("asterisk",))
    upgrading = (
        db.scalar(
            select(func.count())
            .select_from(AvailableUpdate)
            .where(AvailableUpdate.state.in_(("installing", "scheduled")))
        )
        or 0
    ) > 0
    return rules.SwitchoverFacts(
        local_role=local.role if local else "standalone",
        target_role=target.role,
        target_online=not rules.heartbeat_stale(
            target.last_heartbeat_at, now, HEARTBEAT_STALE_AFTER
        )
        and target.state in ("online", "unknown"),
        local_version=__version__,
        target_version=target.software_version,
        replication_state=rep.get("state"),
        lag_bytes=rep.get("lag_bytes"),
        sync_age=sync_age,
        operation_running=bool(op and op.running),
        deployment_running=deploying,
        upgrade_running=bool(upgrading),
        frozen=bool(inst.ha_frozen),
    )


def events(db: Session, limit: int = 100) -> list[dict[str, Any]]:
    rows = db.execute(
        select(ClusterEvent, ClusterNode.node_name)
        .outerjoin(ClusterNode, ClusterNode.id == ClusterEvent.node_id)
        .order_by(ClusterEvent.occurred_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": ev.id,
            "occurred_at": ev.occurred_at.isoformat(),
            "event_type": ev.event_type,
            "node_name": name,
            "actor_label": ev.actor_label,
            "details": ev.details,
        }
        for ev, name in rows
    ]


def new_operation_view(op: Operation | None) -> dict[str, Any] | None:
    return op.to_dict() if op else None


def node_state_or_default(state_dir: StateDir) -> NodeState:
    return state_dir.node() or NodeState(node_name=local_name())
