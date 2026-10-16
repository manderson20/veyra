# SPDX-License-Identifier: AGPL-3.0-or-later
"""High availability (docs/HIGH_AVAILABILITY.md §9): status, enrollment,
switchover, failover, recovery, fencing, events, and the signed node
endpoints ``/ha/peer/*`` the other node calls."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from veyra import __version__
from veyra.api.v1.extensions import installation_key
from veyra.central import protocol
from veyra.core import audit
from veyra.core.config import Settings, get_settings
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, not_found
from veyra.core.models import ClusterNode
from veyra.core.security.principal import Principal
from veyra.core.security.ratelimit import SlidingWindowLimiter
from veyra.ha import join, peer, rules, service, sync
from veyra.ha.client import AgentClient, AgentError, AgentUnavailable
from veyra.ha.state import StateDir

router = APIRouter(prefix="/ha", tags=["high availability"])
READ = "ha.read"
MANAGE = "ha.manage"
_limiter = SlidingWindowLimiter(600, 60)
_digest_cache: dict[str, tuple[float, int, str]] = {}


# ----------------------------------------------------------------- helpers


def _state_dir(settings: Settings) -> StateDir:
    return StateDir(settings.data_dir / "ha")


def _agent(settings: Settings) -> AgentClient:
    return AgentClient(settings.ha_socket_path)


def _agent_status(settings: Settings) -> dict[str, Any] | None:
    try:
        out = _agent(settings).call("status")
    except AgentError:
        return None
    return out if isinstance(out, dict) else None


def _agent_call(settings: Settings, verb: str, **args: Any) -> Any:
    try:
        return _agent(settings).call(verb, **args)
    except AgentUnavailable as e:
        raise ProblemError(503, "HA agent unavailable", e.message, code="agent_unavailable") from e
    except AgentError as e:
        raise ProblemError(409, "HA agent refused", e.message, code=e.code) from e


def _problem(e: service.HAError | peer.PeerError | join.JoinError) -> JSONResponse:
    return JSONResponse(
        status_code=e.status,
        content={
            "title": "High availability",
            "status": e.status,
            "code": e.code,
            "detail": e.message,
        },
        media_type="application/problem+json",
    )


def _headers(request: Request) -> dict[str, str]:
    return {k.lower(): v for k, v in request.headers.items()}


def _node_key(settings: Settings) -> str:
    try:
        return (settings.config_dir / "secrets" / "node.key").read_text().strip()
    except OSError as e:
        raise ProblemError(
            503, "Node key unavailable", "This node has no node key yet.", code="no_node_key"
        ) from e


def _ca_pem(settings: Settings) -> str | None:
    try:
        return (settings.config_dir / "tls" / "ca.crt").read_text()
    except OSError:
        return None


def _local(db: Session, settings: Settings) -> dict[str, Any]:
    return service.status(db, _state_dir(settings), _agent_status(settings))["local"]


def _peer_node(db: Session) -> ClusterNode | None:
    me = service.local_name()
    for n in db.query(ClusterNode).all():
        if n.node_name != me and n.role in ("primary", "secondary"):
            return n
    return None


def _peer_call(
    db: Session, settings: Settings, verb: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """A signed call to the peer from the API (it can read the node key)."""
    node = _state_dir(settings).node()
    if node is None or node.peer is None:
        raise ProblemError(409, "No peer", "This node has no peer.", code="no_peer")
    try:
        return peer.call(
            node.peer.url,
            verb,
            payload,
            node_id=node.node_id,
            private_key=_node_key(settings),
            peer_public_key=node.peer.public_key,
            ca_pem=_ca_pem(settings),
        )
    except peer.PeerError as e:
        raise ProblemError(
            e.status if e.status < 500 else 502, "Peer call failed", e.message, code=e.code
        ) from e


def _audit(
    db: Session, principal: Principal, ctx: RequestContext, action: str, **details: Any
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="cluster",
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=details,
    )


# ----------------------------------------------------------------- status


@router.get("/status", summary="Cluster mode, nodes, roles, replication and the running operation")
def status(
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return service.status(db, _state_dir(settings), _agent_status(settings))


@router.get("/events", summary="Cluster events")
def events(
    limit: int = Query(100, ge=1, le=500),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return service.events(db, limit)


# ----------------------------------------------------------------- service, enable


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=253)
    address: str = Field(min_length=7, max_length=45)
    prefix: int = Field(24, ge=8, le=32)
    interface: str = Field(min_length=1, max_length=32)
    synchronous: bool = False


@router.put("/service", summary="Service name and address (before enabling)")
def put_service(
    body: ServiceIn,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    import ipaddress

    try:
        ipaddress.ip_address(body.address)
    except ValueError as e:
        raise ProblemError(400, "Invalid address", str(e), code="bad_address") from e
    inst = service.installation(db)
    current = service.service_settings(db)
    if inst.deployment_mode == "ha" and (
        body.name != current["name"]
        or body.address != current["address"]
        or body.interface != current["interface"]
    ):
        raise ProblemError(
            409,
            "Service address fixed",
            "The service name and address cannot change while HA is enabled.",
            code="ha_enabled",
        )
    value = body.model_dump()
    service.save_setting(db, service.SERVICE_KEY, value, principal.user_id)
    if inst.deployment_mode == "ha" and body.synchronous != current["synchronous"]:
        _agent_call(settings, "set-synchronous", synchronous=body.synchronous)
    _audit(db, principal, ctx, "ha.service_update", **value)
    db.commit()
    return service.service_settings(db)


@router.post("/enable", summary="Enable high availability: this node becomes the primary")
def enable(
    body: ServiceIn,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    inst = service.installation(db)
    if inst.deployment_mode == "ha":
        raise ProblemError(409, "Already enabled", "HA is already enabled.", code="ha_enabled")
    node = service.node_by_name(db, service.local_name())
    out = _agent_call(
        settings,
        "enable",
        service=body.model_dump(exclude={"synchronous"}),
        synchronous=body.synchronous,
        address=node.address if node and node.address else _node_address(settings),
        actor=principal.label,
    )
    _audit(db, principal, ctx, "ha.enable", service=body.model_dump())
    db.commit()
    return {"operation": out}


def _node_address(settings: Settings) -> str:
    """This node's own address: the first non-loopback address that resolves
    for its name."""
    import socket

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = str(info[4][0])
            if not addr.startswith("127."):
                return addr
    except OSError:
        pass
    return ""


# ----------------------------------------------------------------- join tokens


class TokenIn(BaseModel):
    label: str | None = Field(None, max_length=120)


@router.get("/join-tokens", summary="Join tokens (hashes only)")
def list_tokens(
    principal: Principal = Depends(require(MANAGE)), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    return join.list_tokens(db)


@router.post("/join-tokens", status_code=201, summary="Create a single-use join token")
def create_token(
    body: TokenIn,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    inst = service.installation(db)
    if inst.deployment_mode != "ha":
        raise ProblemError(409, "Not enabled", "Enable HA first.", code="ha_disabled")
    node = _state_dir(settings).node()
    if node is None or node.role != "primary":
        raise ProblemError(409, "Not the primary", "Nodes join at the primary.", code="not_primary")
    raw, item = join.create_token(db, label=body.label, created_by=principal.label)
    _audit(db, principal, ctx, "ha.join_token_create", id=item["id"], label=body.label)
    db.commit()
    me = service.node_by_name(db, service.local_name())
    return {
        **item,
        "token": raw,
        "primary_url": f"https://{service.local_name()}",
        "fingerprint": me.fingerprint if me else None,
        "command": (
            f"sudo installer/install.sh --role secondary --join https://{service.local_name()} "
            f"--token {raw}"
        ),
    }


@router.delete("/join-tokens/{token_id}", status_code=204, summary="Delete a join token")
def delete_token(
    token_id: str,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    if not join.delete_token(db, token_id):
        raise not_found("Join token")
    _audit(db, principal, ctx, "ha.join_token_delete", id=token_id)
    db.commit()
    return Response(status_code=204)


# ----------------------------------------------------------------- switchover, failover


class SwitchoverIn(BaseModel):
    target: str = Field(min_length=1, max_length=128)


def _target(db: Session, name: str) -> ClusterNode:
    node = service.node_by_name(db, name)
    if node is None:
        raise not_found("Node")
    return node


@router.get("/switchover-check", summary="Switchover preconditions for a target")
def switchover_check(
    target: str = Query(..., max_length=128),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    node = _target(db, target)
    facts = service.switchover_facts(db, _state_dir(settings), node, _agent_status(settings))
    problems = rules.switchover_problems(facts)
    return {"target": node.node_name, "ok": not problems, "problems": problems}


@router.post("/switchover", summary="Planned switchover to the other node")
def switchover(
    body: SwitchoverIn,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    node = _target(db, body.target)
    local = _state_dir(settings).node()
    if local is None or not local.ha_enabled:
        raise ProblemError(409, "Not enabled", "HA is not enabled.", code="ha_disabled")
    if node.node_name == local.node_name:
        # Asked on the standby itself: the standby takes over.
        if local.role != "secondary":
            raise ProblemError(
                409, "Already primary", "This node is the primary.", code="not_secondary"
            )
        _audit(db, principal, ctx, "ha.switchover", target=node.node_name)
        db.commit()
        return {"operation": _agent_call(settings, "switchover", actor=principal.label)}
    facts = service.switchover_facts(db, _state_dir(settings), node, _agent_status(settings))
    problems = rules.switchover_problems(facts)
    if problems:
        raise ProblemError(
            409,
            "Switchover not possible",
            " ".join(problems),
            code="preconditions",
            errors=[{"detail": p} for p in problems],
        )
    service.record_event(
        db,
        "switchover_started",
        {"target": node.node_name},
        node_name=node.node_name,
        actor=principal.label,
    )
    _audit(db, principal, ctx, "ha.switchover", target=node.node_name)
    db.commit()
    out = _peer_call(
        db, settings, "run", {"verb": "switchover", "args": {"actor": principal.label}}
    )
    return {"operation": out.get("result")}


class FailoverIn(BaseModel):
    confirm_fenced: bool = False


@router.post("/failover", summary="Fail over to this standby (the primary is down)")
def failover(
    body: FailoverIn,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    local = _state_dir(settings).node()
    if local is None or local.role != "secondary":
        raise ProblemError(
            409, "Not the standby", "A failover runs on the standby.", code="not_secondary"
        )
    out = _agent_call(
        settings, "failover", confirm_fenced=body.confirm_fenced, actor=principal.label
    )
    # The standby cannot write the audit log yet; the agent records the
    # events after the promotion.
    return {"operation": out}


@router.post("/resume", summary="Resume primary duties on an isolated primary")
def resume(
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    out = _agent_call(settings, "resume", actor=principal.label)
    try:
        _audit(db, principal, ctx, "ha.resume")
        db.commit()
    except Exception:
        db.rollback()
    return {"operation": out}


@router.post("/nodes/{node_id}/rejoin", summary="Rejoin a node as the standby")
def rejoin(
    node_id: uuid.UUID,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    node = db.get(ClusterNode, node_id)
    if node is None:
        raise not_found("Node")
    local = _state_dir(settings).node()
    _audit(db, principal, ctx, "ha.rejoin", node=node.node_name)
    db.commit()
    if local and node.node_name == local.node_name:
        return {"operation": _agent_call(settings, "rejoin", actor=principal.label)}
    out = _peer_call(
        db, settings, "run", {"verb": "rejoin", "args": {"epoch": local.epoch if local else 0}}
    )
    return {"operation": out.get("result")}


@router.delete("/nodes/{node_id}", summary="Remove the secondary from the cluster")
def remove_node(
    node_id: uuid.UUID,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    node = db.get(ClusterNode, node_id)
    if node is None:
        raise not_found("Node")
    local = _state_dir(settings).node()
    if local is None or local.role != "primary":
        raise ProblemError(
            409, "Not the primary", "Nodes are removed at the primary.", code="not_primary"
        )
    if node.role != "secondary":
        raise ProblemError(
            409, "Not a secondary", "Only a secondary can be removed.", code="not_secondary"
        )
    # Best effort: tell the node it is on its own, so it never starts the engine.
    with contextlib.suppress(ProblemError):
        _peer_call(db, settings, "run", {"verb": "standalone", "args": {}})
    _audit(db, principal, ctx, "ha.node_remove", node=node.node_name)
    db.commit()
    return _agent_call(settings, "remove-peer", actor=principal.label)


class StandbyUpgradeIn(BaseModel):
    version: str = Field(min_length=1, max_length=64)


@router.post("/standby-upgrade", summary="Install a release on the standby first (§12)")
def standby_upgrade(
    body: StandbyUpgradeIn,
    principal: Principal = Depends(require("updates.manage")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    """docs/HIGH_AVAILABILITY.md §12: the standby starts its own upgrade unit
    with the artifact the file sync already brought it."""
    local = _state_dir(settings).node()
    if local is None or local.role != "primary":
        raise ProblemError(
            409, "Not the primary", "Start standby upgrades at the primary.", code="not_primary"
        )
    op = _state_dir(settings).operation()
    if op is not None and op.running:
        raise ProblemError(409, "Busy", "An HA operation is running.", code="busy")
    out = _peer_call(db, settings, "run", {"verb": "upgrade", "args": {"version": body.version}})
    _audit(db, principal, ctx, "ha.standby_upgrade", version=body.version)
    db.commit()
    return {"started": out.get("result", {}).get("started", body.version)}


# ----------------------------------------------------------------- fencing, sync


class FencingIn(BaseModel):
    enabled: bool = False
    url: str = ""
    token_id: str = ""
    token_secret: str | None = None
    pve_node: str = ""
    vms: dict[str, dict[str, Any]] = Field(default_factory=dict)
    verify_tls: bool = True
    ca_pem: str = ""


@router.get("/fencing", summary="Fencing settings (secret never returned)")
def get_fencing(
    principal: Principal = Depends(require(MANAGE)), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return service.fencing_settings(db)


@router.put("/fencing", summary="Fencing settings (Proxmox)")
def put_fencing(
    body: FencingIn,
    request: Request,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    key = installation_key(request)
    try:
        out = service.save_fencing(db, body.model_dump(), key, principal.user_id)
    except service.HAError as e:
        raise ProblemError(e.status, "Fencing", e.message, code=e.code) from e
    _audit(db, principal, ctx, "ha.fencing_update", enabled=out["enabled"], url=out["url"])
    db.commit()
    _push_fencing(db, settings, key)
    return out


def _push_fencing(db: Session, settings: Settings, key: Any) -> None:
    """The agent keeps a copy with the secret so it can fence without the
    database (which is what a failover is about)."""
    with contextlib.suppress(AgentError):
        _agent(settings).call("set-fencing", config=service.fencing_settings(db, key))


@router.post("/fencing/test", summary="Reach Proxmox and read the peer VM's state")
def test_fencing(
    request: Request,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from veyra.ha import fencing

    cfg = service.fencing_settings(db, installation_key(request))
    peer_row = _peer_node(db)
    name = peer_row.node_name if peer_row else service.local_name()
    target = fencing.settings_to_target(cfg, name, str(cfg.get("secret") or ""))
    if target is None:
        return {"ok": False, "error": "Fencing is not configured for the peer node."}
    return {"node": name, **fencing.check(target)}


class SyncIn(BaseModel):
    recordings: bool = True


@router.put("/sync", summary="File sync options")
def put_sync(
    body: SyncIn,
    principal: Principal = Depends(require(MANAGE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    service.save_setting(db, service.SYNC_KEY, {"recordings": body.recordings}, principal.user_id)
    _audit(db, principal, ctx, "ha.sync_update", recordings=body.recordings)
    db.commit()
    with contextlib.suppress(AgentError):
        _agent(settings).call("set-sync", recordings=body.recordings)
    return service.sync_settings(db)


# ----------------------------------------------------------------- peer endpoints


PeerVerb = Literal["join", "health", "heartbeat", "manifest", "file", "run", "epoch"]


def _calling_node(db: Session, headers: dict[str, str]) -> ClusterNode:
    raw = headers.get(protocol.H_INSTANCE.lower(), "")
    try:
        node_id = uuid.UUID(raw)
    except ValueError as e:
        raise peer.PeerError(401, "unknown_node", "The calling node is not known.") from e
    node = db.get(ClusterNode, node_id)
    if node is None or not node.public_key or node.node_name == service.local_name():
        raise peer.PeerError(401, "unknown_node", "The calling node is not known.")
    return node


def _roots(db: Session, settings: Settings) -> dict[str, Path]:
    return sync.roots_for(
        settings.data_dir, settings.config_dir, recordings=service.sync_settings(db)["recordings"]
    )


@router.post("/peer/{verb}", include_in_schema=False)
async def peer_endpoint(
    verb: PeerVerb,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    if not _limiter.hit(f"peer:{ctx.ip}"):
        return _problem(peer.PeerError(429, "rate_limited", "Too many requests."))
    body = await request.body()
    headers = _headers(request)
    try:
        if verb == "join":
            return _peer_join(db, settings, body, headers, ctx)
        node = _calling_node(db, headers)
        nonce = peer.verify_request(db, node.public_key or "", verb, body, headers)
        data = peer.parse_body(body)
        key = _node_key(settings)
        if verb == "file":
            return _peer_file(db, settings, data, key, nonce)
        payload = _peer_dispatch(verb, db, settings, node, data, ctx)
        db.commit()
        out, sig = peer.answer(key, nonce, payload)
    except (peer.PeerError, service.HAError, join.JoinError) as e:
        db.rollback()
        return _problem(e)
    except ProblemError as e:
        db.rollback()
        return _problem(peer.PeerError(e.status, e.code or "error", str(e)))
    return Response(content=out, media_type="application/json", headers=sig)


def _peer_dispatch(
    verb: str,
    db: Session,
    settings: Settings,
    node: ClusterNode,
    data: dict[str, Any],
    ctx: RequestContext,
) -> dict[str, Any]:
    state_dir = _state_dir(settings)
    if verb == "health":
        return service.health_payload(db, state_dir, _agent_status(settings))
    if verb == "heartbeat":
        if service.db_role(db) != "primary":
            raise peer.PeerError(503, "ha_standby", "This node is a standby.")
        data["node_name"] = node.node_name
        service.action_node_report(db, data)
        return {"ok": True, "epoch": service.installation(db).ha_epoch}
    if verb == "manifest":
        # Data roots are readable by the service account; the root-only
        # roots (secrets, TLS, trust) come from the agent (§4.2).
        readable, _privileged = sync.split_roots(_roots(db, settings))
        entries = [e.to_dict() for e in sync.manifest(readable, digest_cache=_digest_cache)]
        covered = list(readable)
        with contextlib.suppress(AgentError):
            etc = _agent(settings).call("manifest-etc")
            if isinstance(etc, dict):
                entries += list(etc.get("entries") or [])
                covered += list(etc.get("roots") or [])
        return {"entries": entries, "roots": covered}
    if verb == "run":
        inner = str(data.get("verb") or "")
        args: dict[str, Any] = data["args"] if isinstance(data.get("args"), dict) else {}
        if inner not in peer.RUNNABLE and inner not in (
            "switchover",
            "engine-start",
            "hold-address",
            "event",
        ):
            raise peer.PeerError(403, "verb_not_allowed", f"A peer may not ask for {inner!r}.")
        if inner == "event":
            service.record_event(
                db,
                str(args.get("event_type") or "ha_event"),
                dict(args.get("details") or {}),
                node_name=node.node_name,
                actor="peer",
            )
            return {"result": {}}
        try:
            result = _agent(settings).call(inner, **args)
        except AgentUnavailable as e:
            raise peer.PeerError(503, "agent_unavailable", e.message) from e
        except AgentError as e:
            raise peer.PeerError(409, e.code, e.message) from e
        return {"result": result}
    if verb == "epoch":
        _agent_call(settings, "set-peer-epoch", epoch=int(data.get("epoch") or 0))
        return {"ok": True}
    raise peer.PeerError(404, "unknown_verb", "Unknown verb.")


def _peer_join(
    db: Session, settings: Settings, body: bytes, headers: dict[str, str], ctx: RequestContext
) -> Response:
    data = peer.parse_body(body)
    public = str(data.get("public_key") or "")
    name = str(data.get("node_name") or "")[:128]
    address = str(data.get("address") or "")[:64]
    try:
        protocol.fingerprint(public)
    except (ValueError, TypeError) as e:
        raise peer.PeerError(400, "bad_request", "The node identity is not valid.") from e
    if not name or not address:
        raise peer.PeerError(400, "bad_request", "The node name and address are required.")
    if name == service.local_name():
        raise peer.PeerError(400, "bad_request", "A node cannot join itself.")
    nonce = peer.verify_request(db, public, "join", body, headers)
    local = _state_dir(settings).node()
    if local is None or local.role != "primary":
        raise peer.PeerError(409, "not_primary", "Nodes join at the primary.")
    if str(data.get("version") or "") != __version__:
        raise peer.PeerError(
            409, "version_mismatch", f"The primary runs {__version__}; install that version first."
        )
    token = str(data.get("token") or "")
    join.consume_token(db, token, name)
    db.commit()
    try:
        out = _agent(settings).call(
            "make-bundle",
            token=token,
            node_name=name,
            address=address,
            public_key=public,
            actor="join",
        )
    except AgentUnavailable as e:
        raise peer.PeerError(503, "agent_unavailable", e.message) from e
    except AgentError as e:
        raise peer.PeerError(409, e.code, e.message) from e
    audit.record(
        db,
        action="ha.node_join",
        actor_type="system",
        actor_label=f"node {name}",
        ip_address=ctx.ip,
        details={"address": address, "fingerprint": protocol.fingerprint(public)},
    )
    db.commit()
    body_out, sig = peer.answer(_node_key(settings), nonce, out if isinstance(out, dict) else {})
    return Response(content=body_out, media_type="application/json", headers=sig)


def _peer_file(
    db: Session, settings: Settings, data: dict[str, Any], key: str, nonce: str
) -> Response:
    logical = str(data.get("path") or "")
    readable, privileged = sync.split_roots(_roots(db, settings))
    if sync.excluded(logical):
        raise peer.PeerError(404, "no_file", "No such file.")
    if sync.resolve(privileged, logical) is not None:
        # Root-only file: the agent reads it (small files, base64 over the socket).
        try:
            out = _agent(settings).call("read-file", path=logical)
        except AgentError as e:
            raise peer.PeerError(404 if e.code == "no_file" else 503, e.code, e.message) from e
        content = base64.b64decode(str(out.get("content") or ""))
        headers = peer.answer_headers(key, nonce, hashlib.sha256(content).hexdigest())
        return Response(content=content, media_type="application/octet-stream", headers=headers)
    path = sync.resolve(readable, logical)
    if path is None or not path.is_file() or sync.excluded(logical):
        raise peer.PeerError(404, "no_file", "No such file.")
    digest = hashlib.sha256()
    for chunk in sync.read_chunks(path):
        digest.update(chunk)
    headers = peer.answer_headers(key, nonce, digest.hexdigest())
    headers["Content-Length"] = str(path.stat().st_size)

    def body() -> Iterator[bytes]:
        yield from sync.read_chunks(path)

    return StreamingResponse(body(), media_type="application/octet-stream", headers=headers)
