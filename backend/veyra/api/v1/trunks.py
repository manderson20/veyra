# SPDX-License-Identifier: AGPL-3.0-or-later
"""SIP trunks: connections to carriers (docs/TRUNKS_ROUTING.md §2).

Installation-wide: platform administrators create and edit them; organization
administrators and technicians may list them (to restrict an inbound route to
a trunk). The password is write-only and encrypted at rest; the status comes
from the engine's endpoint state (qualify ping).
"""

from __future__ import annotations

import ipaddress
import re
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1.extensions import installation_key
from veyra.configmgmt import service as configmgmt
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, not_found
from veyra.core.events import Event, bus
from veyra.core.models import InboundRoute, OutboundRoute, OutboundRouteTrunk, SipTrunk
from veyra.core.security.principal import Principal
from veyra.telephony import routing
from veyra.telephony.adapter import Capability, EngineUnavailable, NotSupported
from veyra.telephony.settings import CODECS, _address_or_host
from veyra.telephony.snapshot import trunk_secret_purpose

router = APIRouter(prefix="/trunks", tags=["trunks"])

_USER_RE = re.compile(r"^[A-Za-z0-9._+@-]{1,80}$")
_PASSWORD_RE = re.compile(r"^[^\r\n\[\];\s]{1,128}$")
_NUMBER_RE = re.compile(r"^\+?[0-9]{1,32}$")
_HOSTPORT_RE = re.compile(r"^([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(:[0-9]{1,5})?$")

AuthMode = Literal["registration", "ip"]
Transport = Literal["udp", "tcp", "tls"]
CallerIdHeader = Literal["pai", "rpid", "none"]
DtmfMode = Literal["rfc4733", "inband", "info", "auto"]


# ----------------------------------------------------------------- schemas


def _match_address(v: str) -> str:
    v = v.strip()
    try:
        ipaddress.ip_network(v, strict=False)
        return v
    except ValueError:
        pass
    return _address_or_host(v)


def _optional_text(v: str | None, pattern: re.Pattern[str], message: str) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if not pattern.match(v):
        raise ValueError(message)
    return v


class TrunkBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    is_enabled: bool = True
    auth_mode: AuthMode = "registration"
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(5060, ge=1, le=65535)
    transport: Transport = "udp"
    username: str | None = Field(None, max_length=80)
    auth_username: str | None = Field(None, max_length=80)
    from_user: str | None = Field(None, max_length=80)
    from_domain: str | None = Field(None, max_length=253)
    outbound_proxy: str | None = Field(None, max_length=260)
    match_addresses: list[str] = Field(default_factory=list, max_length=32)
    codecs: list[str] | None = None
    max_channels: int | None = Field(None, ge=1, le=10000)
    default_caller_id: str | None = Field(None, max_length=32)
    caller_id_header: CallerIdHeader = "pai"
    dtmf_mode: DtmfMode = "rfc4733"
    fax_t38: bool = False
    qualify_frequency: int = Field(60, ge=0, le=3600)
    register_expiry: int = Field(3600, ge=60, le=86400)
    register_retry_interval: int = Field(60, ge=10, le=3600)
    register_forbidden_retry: int = Field(600, ge=30, le=86400)
    # None: keep trying for as long as the carrier refuses (the default).
    register_max_retries: int | None = Field(None, ge=1, le=100000)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        routing.slugify(v)
        return v

    @field_validator("host")
    @classmethod
    def _host(cls, v: str) -> str:
        return _address_or_host(v)

    @field_validator("from_domain")
    @classmethod
    def _from_domain(cls, v: str | None) -> str | None:
        return _address_or_host(v) if v and v.strip() else None

    @field_validator("outbound_proxy")
    @classmethod
    def _proxy(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not _HOSTPORT_RE.match(v):
            raise ValueError("host name or address, optionally with :port")
        return v

    @field_validator("username", "auth_username", "from_user")
    @classmethod
    def _user(cls, v: str | None) -> str | None:
        return _optional_text(v, _USER_RE, "letters, digits and . _ + @ - only")

    @field_validator("default_caller_id")
    @classmethod
    def _cid(cls, v: str | None) -> str | None:
        return _optional_text(v, _NUMBER_RE, "digits (and a leading +) only")

    @field_validator("match_addresses")
    @classmethod
    def _matches(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for item in v:
            m = _match_address(item)
            if m not in out:
                out.append(m)
        return out

    @field_validator("codecs")
    @classmethod
    def _codecs(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        v = [c.strip().lower() for c in v if c.strip()]
        if not v:
            return None
        bad = [c for c in v if c not in CODECS]
        if bad:
            raise ValueError(f"unknown codec(s): {', '.join(bad)}")
        return list(dict.fromkeys(v))

    @field_validator("description")
    @classmethod
    def _desc(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None


class TrunkIn(TrunkBase):
    password: str | None = Field(None, max_length=128)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str | None) -> str | None:
        return _optional_text(v, _PASSWORD_RE, "no spaces, brackets or semicolons; at most 128")

    @model_validator(mode="after")
    def _mode_rules(self) -> TrunkIn:
        if self.auth_mode == "registration":
            if not self.username:
                raise ValueError("a registration trunk needs a user name")
            if not self.password:
                raise ValueError("a registration trunk needs a password")
        return self


class TrunkPatch(BaseModel):
    """Every field optional; ``password: null`` clears the password."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    is_enabled: bool | None = None
    auth_mode: AuthMode | None = None
    host: str | None = Field(None, min_length=1, max_length=253)
    port: int | None = Field(None, ge=1, le=65535)
    transport: Transport | None = None
    username: str | None = Field(None, max_length=80)
    auth_username: str | None = Field(None, max_length=80)
    password: str | None = Field(None, max_length=128)
    from_user: str | None = Field(None, max_length=80)
    from_domain: str | None = Field(None, max_length=253)
    outbound_proxy: str | None = Field(None, max_length=260)
    match_addresses: list[str] | None = Field(None, max_length=32)
    codecs: list[str] | None = None
    max_channels: int | None = Field(None, ge=1, le=10000)
    default_caller_id: str | None = Field(None, max_length=32)
    caller_id_header: CallerIdHeader | None = None
    dtmf_mode: DtmfMode | None = None
    fax_t38: bool | None = None
    qualify_frequency: int | None = Field(None, ge=0, le=3600)
    register_expiry: int | None = Field(None, ge=60, le=86400)
    register_retry_interval: int | None = Field(None, ge=10, le=3600)
    register_forbidden_retry: int | None = Field(None, ge=30, le=86400)
    register_max_retries: int | None = Field(None, ge=1, le=100000)


class TrunkStatusOut(BaseModel):
    # online/offline: reachability (qualify); rejected/registering/unregistered: the
    # registration state when the engine reports one (issue #45).
    state: Literal["online", "offline", "unknown", "rejected", "registering", "unregistered"]
    reachable: bool | None
    # The engine's own word for the outbound registration (Registered, Rejected, …).
    registration: str | None = None


class TrunkOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    is_enabled: bool
    auth_mode: str
    host: str
    port: int
    transport: str
    username: str | None
    auth_username: str | None
    has_password: bool
    from_user: str | None
    from_domain: str | None
    outbound_proxy: str | None
    match_addresses: list[str]
    codecs: list[str] | None
    max_channels: int | None
    default_caller_id: str | None
    caller_id_header: str
    dtmf_mode: str
    fax_t38: bool
    qualify_frequency: int
    register_expiry: int
    register_retry_interval: int = 60
    register_forbidden_retry: int = 600
    register_max_retries: int | None = None
    status: TrunkStatusOut | None
    created_at: datetime
    updated_at: datetime


class TrunkPage(BaseModel):
    items: list[TrunkOut]
    total: int


# ----------------------------------------------------------------- helpers


class Live:
    """What the engine says about trunks: reachability per endpoint and the
    outbound registration state per section (issue #45)."""

    def __init__(self, reachable: dict[str, bool], registrations: dict[str, str]) -> None:
        self.reachable = reachable
        self.registrations = registrations


def _statuses(request: Request | None) -> Live | None:
    if request is None:
        return None
    adapter = request.app.state.telephony
    caps = adapter.capabilities()
    if Capability.ENDPOINT_STATUS not in caps and Capability.TRUNK_STATUS not in caps:
        return None
    try:
        reachable = {s.endpoint: s.registered for s in adapter.endpoint_statuses()}
    except (EngineUnavailable, NotSupported):
        return None
    registrations: dict[str, str] = {}
    if Capability.TRUNK_REGISTRATIONS in caps:
        try:
            registrations = {r.section: r.status for r in adapter.trunk_registrations()}
        except (EngineUnavailable, NotSupported):
            registrations = {}
    return Live(reachable, registrations)


def registration_state(word: str | None) -> str | None:
    """The engine's registration word -> our state, None for 'registered'."""
    if not word:
        return None
    w = word.lower()
    if w.startswith("registered"):
        return None
    if w.startswith("rejected"):
        return "rejected"
    if w.startswith("unregistered") or w.startswith("stopped"):
        return "unregistered"
    return "registering"


def _status(trunk: SipTrunk, live: Live | None) -> TrunkStatusOut | None:
    if live is None:
        return None
    name = routing_name(trunk)
    registration = live.registrations.get(name) if trunk.auth_mode == "registration" else None
    if name not in live.reachable or trunk.qualify_frequency == 0:
        state = registration_state(registration) or "unknown"
        return TrunkStatusOut(state=state, reachable=None, registration=registration)
    reachable = live.reachable[name]
    # A rejected or pending registration matters more than a qualify answer.
    state = registration_state(registration) or ("online" if reachable else "offline")
    return TrunkStatusOut(state=state, reachable=reachable, registration=registration)


def routing_name(trunk: SipTrunk) -> str:
    return f"trunk-{trunk.slug}"


def _out(trunk: SipTrunk, live: Live | None) -> TrunkOut:
    return TrunkOut(
        id=trunk.id,
        name=trunk.name,
        slug=trunk.slug,
        description=trunk.description,
        is_enabled=trunk.is_enabled,
        auth_mode=trunk.auth_mode,
        host=trunk.host,
        port=trunk.port,
        transport=trunk.transport,
        username=trunk.username,
        auth_username=trunk.auth_username,
        has_password=bool(trunk.password_ciphertext),
        from_user=trunk.from_user,
        from_domain=trunk.from_domain,
        outbound_proxy=trunk.outbound_proxy,
        match_addresses=list(trunk.match_addresses or []),
        codecs=list(trunk.codecs) if trunk.codecs else None,
        max_channels=trunk.max_channels,
        default_caller_id=trunk.default_caller_id,
        caller_id_header=trunk.caller_id_header,
        dtmf_mode=trunk.dtmf_mode,
        fax_t38=trunk.fax_t38,
        qualify_frequency=trunk.qualify_frequency,
        register_expiry=trunk.register_expiry,
        register_retry_interval=trunk.register_retry_interval,
        register_forbidden_retry=trunk.register_forbidden_retry,
        register_max_retries=trunk.register_max_retries,
        status=_status(trunk, live),
        created_at=trunk.created_at,
        updated_at=trunk.updated_at,
    )


def _get(db: Session, trunk_id: uuid.UUID) -> SipTrunk:
    trunk = db.get(SipTrunk, trunk_id)
    if trunk is None:
        raise not_found("Trunk")
    return trunk


def _unique_slug(db: Session, name: str) -> str:
    base = routing.slugify(name)
    slug = base
    n = 2
    while db.scalar(select(SipTrunk.id).where(SipTrunk.slug == slug)) is not None:
        slug = f"{base[: 40 - len(str(n)) - 1]}-{n}"
        n += 1
    return slug


def _validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


def _record(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    trunk: SipTrunk,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=None,
        target_type="trunk",
        target_id=trunk.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": trunk.name, **details},
    )
    configmgmt.mark_changed(db, by=principal.label, what=f"{action} {trunk.name}")


def _in_use(db: Session, trunk: SipTrunk) -> list[str]:
    routes = db.scalars(
        select(OutboundRoute.name)
        .join(OutboundRouteTrunk, OutboundRouteTrunk.route_id == OutboundRoute.id)
        .where(OutboundRouteTrunk.trunk_id == trunk.id)
        .order_by(OutboundRoute.name)
    ).all()
    dids = db.scalars(
        select(InboundRoute.did).where(InboundRoute.trunk_id == trunk.id).order_by(InboundRoute.did)
    ).all()
    return [f"outbound route {r}" for r in routes] + [f"inbound route {d}" for d in dids]


# ----------------------------------------------------------------- routes


@router.get("", response_model=TrunkPage, summary="List SIP trunks with their status")
def list_trunks(
    request: Request,
    q: str | None = Query(None, max_length=100),
    principal: Principal = Depends(require("trunks.read")),
    db: Session = Depends(get_db),
) -> TrunkPage:
    stmt: Select[SipTrunk] = select(SipTrunk).order_by(SipTrunk.name)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(SipTrunk.name.ilike(like), SipTrunk.host.ilike(like)))
    rows = db.scalars(stmt).all()
    live = _statuses(request)
    return TrunkPage(items=[_out(t, live) for t in rows], total=len(rows))


@router.post("", response_model=TrunkOut, status_code=201, summary="Create a SIP trunk")
def create_trunk(
    body: TrunkIn,
    request: Request,
    principal: Principal = Depends(require("trunks.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> TrunkOut:
    if db.scalar(select(func.count()).select_from(SipTrunk).where(SipTrunk.name == body.name)):
        raise conflict(f"A trunk named {body.name!r} already exists.", "name_in_use")
    trunk = SipTrunk(
        id=uuid.uuid4(),
        slug=_unique_slug(db, body.name),
        **body.model_dump(exclude={"password"}),
    )
    if body.password:
        key = installation_key(request)
        trunk.password_ciphertext = key.encrypt(body.password, trunk_secret_purpose(trunk.id))
    db.add(trunk)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(f"A trunk named {body.name!r} already exists.", "name_in_use") from e
    _record(
        db,
        ctx,
        principal,
        "trunk.create",
        trunk,
        {"auth_mode": trunk.auth_mode, "host": trunk.host, "transport": trunk.transport},
    )
    db.commit()
    bus.publish(Event("trunk.created", {"id": str(trunk.id), "name": trunk.name}))
    return _out(trunk, _statuses(request))


@router.get("/{trunk_id}", response_model=TrunkOut, summary="Get a SIP trunk")
def get_trunk(
    trunk_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("trunks.read")),
    db: Session = Depends(get_db),
) -> TrunkOut:
    return _out(_get(db, trunk_id), _statuses(request))


@router.patch("/{trunk_id}", response_model=TrunkOut, summary="Edit a SIP trunk")
def update_trunk(
    trunk_id: uuid.UUID,
    body: TrunkPatch,
    request: Request,
    principal: Principal = Depends(require("trunks.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> TrunkOut:
    trunk = _get(db, trunk_id)
    changes = body.model_dump(exclude_unset=True)
    password_change = "password" in changes
    new_password = changes.pop("password", None)
    # Validate the merged document with the create schema so every rule applies.
    merged = {
        **{k: getattr(trunk, k) for k in TrunkBase.model_fields},
        **changes,
        "password": (
            new_password if password_change else ("x" if trunk.password_ciphertext else None)
        ),
    }
    try:
        validated = TrunkIn.model_validate(merged)
    except ValueError as e:
        raise _validation("trunk", _first_error(e)) from e
    details: dict[str, Any] = {}
    for field in TrunkBase.model_fields:
        if field not in changes:
            continue
        new = getattr(validated, field)
        old = getattr(trunk, field)
        if new != old:
            setattr(trunk, field, new)
            details[field] = new if field != "name" else {"from": old, "to": new}
    if password_change:
        if new_password:
            key = installation_key(request)
            trunk.password_ciphertext = key.encrypt(new_password, trunk_secret_purpose(trunk.id))
            details["password_changed"] = True
        else:
            trunk.password_ciphertext = None
            details["password_cleared"] = True
    if not details:
        return _out(trunk, _statuses(request))
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("A trunk with that name already exists.", "name_in_use") from e
    _record(db, ctx, principal, "trunk.update", trunk, details)
    db.commit()
    bus.publish(Event("trunk.updated", {"id": str(trunk.id), "fields": sorted(details)}))
    return _out(trunk, _statuses(request))


def _first_error(e: ValueError) -> str:
    errors = getattr(e, "errors", None)
    if callable(errors):
        try:
            first = errors()[0]
            loc = ".".join(str(p) for p in first.get("loc", ()))
            msg = str(first.get("msg", "")).removeprefix("Value error, ")
            return f"{loc}: {msg}" if loc else msg
        except (IndexError, KeyError, TypeError):
            pass
    return str(e)


@router.delete("/{trunk_id}", status_code=204, summary="Delete a SIP trunk")
def delete_trunk(
    trunk_id: uuid.UUID,
    principal: Principal = Depends(require("trunks.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    trunk = _get(db, trunk_id)
    used = _in_use(db, trunk)
    if used:
        raise ProblemError(
            409,
            "Trunk in use",
            f"Remove the trunk from these routes first: {', '.join(used)}.",
            code="trunk_in_use",
            errors=[{"field": "routes", "message": u} for u in used],
        )
    _record(db, ctx, principal, "trunk.delete", trunk, {"host": trunk.host})
    payload = {"id": str(trunk.id), "name": trunk.name}
    db.delete(trunk)
    db.commit()
    bus.publish(Event("trunk.deleted", payload))
    return Response(status_code=204)
