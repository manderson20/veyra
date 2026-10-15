# SPDX-License-Identifier: AGPL-3.0-or-later
"""Firewall (docs/FIREWALL_TRUST.md §7): settings, allow and block rules,
bans, events and blocklist feeds. Platform administrators only. The API
never runs ``nft``; the ``veyra-firewall`` service applies what is stored."""

from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.api.v1.extensions import installation_key
from veyra.api.v1.schemas import ORM
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError
from veyra.core.models import FirewallBan, FirewallEvent, FirewallFeed, FirewallRule
from veyra.core.models.base import utcnow
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.firewall import service as fwservice
from veyra.firewall.detect import normalise_address
from veyra.firewall.settings import (
    CONFIRM_SECONDS,
    SERVICES,
    FirewallSettings,
    PendingConfirm,
    Policy,
    check_cidr,
    load_settings,
    load_status,
    save_settings,
)

router = APIRouter(prefix="/firewall", tags=["firewall"])

# The service writes a heartbeat every pass; older than this: not running.
HEARTBEAT_STALE_SECONDS = 30


def _record(
    db: Session,
    principal: Principal,
    ctx: RequestContext,
    action: str,
    target_id: str | uuid.UUID | None,
    details: dict[str, Any],
    target_type: str = "firewall",
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type=target_type,
        target_id=target_id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=details,
    )


def _self_block(address: str | None) -> ProblemError:
    return ProblemError(
        409,
        "That would block you",
        f"Your address ({address}) would lose access. Add it to the allow list first.",
        code="firewall_self_block",
    )


def _requester_allowed(db: Session, address: str | None) -> bool:
    if not address:
        return True  # not a network client (tests, the CLI)
    addr = normalise_address(address)
    return addr is None or fwservice.allowed(addr, fwservice.active_rules(db, utcnow())) is not None


def _covers(cidr: str, address: str | None) -> bool:
    addr = normalise_address(address or "")
    if addr is None:
        return False
    ip = ipaddress.ip_address(addr)
    net = ipaddress.ip_network(cidr, strict=False)
    return net.version == ip.version and ip in net


# ---------------------------------------------------------------- status


class TopAddress(BaseModel):
    address: str
    events: int


class StatusOut(BaseModel):
    enabled: bool
    service_running: bool
    applied: bool
    error: str | None
    sources: dict[str, str | None]
    active_bans: int
    events_24h: int
    bans_24h: int
    top_addresses: list[TopAddress]
    pending_confirm: PendingConfirm | None
    your_address: str | None
    your_address_allowed: bool


@router.get("/status", response_model=StatusOut, summary="Firewall state and activity")
def get_status(
    principal: Principal = Depends(require("firewall.read")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> StatusOut:
    now = utcnow()
    fw = load_settings(db)
    st = load_status(db)
    beat = st.get("heartbeat")
    running = False
    if beat:
        try:
            running = (now - datetime.fromisoformat(beat)).total_seconds() < HEARTBEAT_STALE_SECONDS
        except ValueError:
            running = False
    since = now - timedelta(hours=24)
    top = db.execute(
        select(FirewallEvent.address, func.sum(FirewallEvent.count).label("n"))
        .where(FirewallEvent.at > since)
        .group_by(FirewallEvent.address)
        .order_by(func.sum(FirewallEvent.count).desc())
        .limit(10)
    ).all()
    return StatusOut(
        enabled=fw.enabled,
        service_running=running,
        applied=bool(st.get("applied")) and running,
        error=st.get("error"),
        sources=st.get("sources") or {},
        active_bans=len(fwservice.active_bans(db, now)),
        events_24h=int(
            db.scalar(
                select(func.coalesce(func.sum(FirewallEvent.count), 0)).where(
                    FirewallEvent.at > since
                )
            )
            or 0
        ),
        bans_24h=int(
            db.scalar(
                select(func.count()).select_from(FirewallBan).where(FirewallBan.banned_at > since)
            )
            or 0
        ),
        top_addresses=[TopAddress(address=a, events=int(n)) for a, n in top],
        pending_confirm=fw.pending_confirm,
        your_address=ctx.ip,
        your_address_allowed=_requester_allowed(db, ctx.ip),
    )


# -------------------------------------------------------------- settings


class SettingsIn(BaseModel):
    enabled: bool = False
    policy: dict[str, Policy] = Field(default_factory=dict)
    ban_score: int = Field(10, ge=2, le=1000)
    window_minutes: int = Field(10, ge=1, le=1440)
    ban_minutes: int = Field(60, ge=1, le=10080)
    max_ban_days: int = Field(7, ge=1, le=365)
    weights: dict[str, int] = Field(default_factory=dict)
    ssh_ports: list[int] = Field(default_factory=lambda: [22])
    bootstrap_networks: list[str] = Field(default_factory=list)


@router.get("/settings", response_model=FirewallSettings, summary="Firewall settings")
def get_settings_(
    principal: Principal = Depends(require("firewall.read")),
    db: Session = Depends(get_db),
) -> FirewallSettings:
    return load_settings(db)


@router.put("/settings", response_model=FirewallSettings, summary="Change firewall settings")
def put_settings(
    body: SettingsIn,
    principal: Principal = Depends(require("firewall.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> FirewallSettings:
    current = load_settings(db)
    try:
        new = FirewallSettings.model_validate(
            {**body.model_dump(), "pending_confirm": current.pending_confirm}
        )
    except ValueError as e:
        raise ProblemError(
            422, "Validation failed", str(e).splitlines()[0], code="validation_failed"
        ) from e
    requester_ok = _requester_allowed(db, ctx.ip)
    newly_restricted = [s for s in new.restricted() if s not in current.restricted()]
    if new.enabled and "web" in new.restricted() and not requester_ok:
        raise _self_block(ctx.ip)
    if new.enabled and ctx.ip:
        addr = normalise_address(ctx.ip)
        rules = fwservice.active_rules(db, utcnow())
        if addr and not requester_ok and fwservice.blocked_by(addr, rules):
            raise _self_block(ctx.ip)
    if new.enabled and newly_restricted:
        # Confirm or revert (§3.4): the service restores the previous policy
        # unless POST /firewall/confirm arrives in time.
        new.pending_confirm = PendingConfirm(
            previous_policy=(
                current.pending_confirm.previous_policy
                if current.pending_confirm
                else current.policy
            ),
            deadline=utcnow() + timedelta(seconds=CONFIRM_SECONDS),
            by=ctx.ip or principal.label,
        )
    before = current.model_dump(mode="json")
    after = new.model_dump(mode="json")
    changed = {k: after[k] for k in after if before.get(k) != after[k] and k != "pending_confirm"}
    save_settings(db, new, updated_by=principal.user_id)
    _record(db, principal, ctx, "firewall.settings_update", "settings", {"changed": changed})
    db.commit()
    return new


@router.post("/confirm", response_model=FirewallSettings, summary="Keep a policy change")
def confirm(
    principal: Principal = Depends(require("firewall.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> FirewallSettings:
    fw = load_settings(db)
    if fw.pending_confirm is None:
        raise ProblemError(
            409, "Nothing to confirm", "No policy change is waiting.", code="nothing_pending"
        )
    fw.pending_confirm = None
    save_settings(db, fw, updated_by=principal.user_id)
    _record(db, principal, ctx, "firewall.policy_confirm", "settings", {"policy": fw.policy})
    db.commit()
    return fw


# ----------------------------------------------------------------- rules


class RuleIn(BaseModel):
    action: Literal["allow", "block"]
    cidr: str = Field(..., max_length=64)
    services: list[str] = Field(default_factory=list)
    comment: str | None = Field(None, max_length=200)
    expires_at: datetime | None = None

    @field_validator("cidr")
    @classmethod
    def _cidr(cls, v: str) -> str:
        return check_cidr(v)

    @field_validator("services")
    @classmethod
    def _services(cls, v: list[str]) -> list[str]:
        for s in v:
            if s not in SERVICES:
                raise ValueError(f"unknown service {s!r}; choose from {', '.join(SERVICES)}")
        return sorted(set(v))


class RulePatch(BaseModel):
    services: list[str] | None = None
    comment: str | None = Field(None, max_length=200)
    expires_at: datetime | None = None

    @field_validator("services")
    @classmethod
    def _services(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else RuleIn._services(v)


class RuleOut(ORM):
    id: uuid.UUID
    action: str
    cidr: str
    services: list[str]
    comment: str | None
    expires_at: datetime | None
    origin: str
    created_by: str | None
    created_at: datetime


@router.get("/rules", response_model=list[RuleOut], summary="Allow and block rules")
def list_rules(
    action: str | None = Query(None, pattern="^(allow|block)$"),
    principal: Principal = Depends(require("firewall.read")),
    db: Session = Depends(get_db),
) -> list[RuleOut]:
    stmt = select(FirewallRule).order_by(
        FirewallRule.action, FirewallRule.origin, FirewallRule.cidr
    )
    if action:
        stmt = stmt.where(FirewallRule.action == action)
    return [RuleOut.model_validate(r) for r in db.scalars(stmt)]


def _manual_rule(db: Session, rule_id: uuid.UUID) -> FirewallRule:
    rule = db.get(FirewallRule, rule_id)
    if rule is None:
        raise ProblemError(404, "Not found", "No such rule.", code="not_found")
    if rule.origin != "manual":
        raise ProblemError(
            409,
            "Maintained by Veyra",
            "This entry follows the server, SIP or trunk configuration; change it there.",
            code="automatic_rule",
        )
    return rule


@router.post("/rules", response_model=RuleOut, status_code=201, summary="Add a rule")
def create_rule(
    body: RuleIn,
    principal: Principal = Depends(require("firewall.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RuleOut:
    if body.action == "block" and _covers(body.cidr, ctx.ip) and not _requester_allowed(db, ctx.ip):
        raise _self_block(ctx.ip)
    if body.expires_at is not None and body.expires_at <= utcnow():
        raise ProblemError(
            422, "Validation failed", "The expiry must be in the future.", code="validation_failed"
        )
    exists = db.scalar(
        select(FirewallRule).where(
            FirewallRule.action == body.action,
            FirewallRule.cidr == body.cidr,
            FirewallRule.origin == "manual",
        )
    )
    if exists:
        raise ProblemError(
            409, "Already listed", f"{body.cidr} is already on that list.", code="duplicate"
        )
    rule = FirewallRule(
        id=uuid.uuid4(),
        action=body.action,
        cidr=body.cidr,
        services=body.services,
        comment=body.comment,
        expires_at=body.expires_at,
        origin="manual",
        created_by=principal.label,
    )
    db.add(rule)
    db.flush()
    _record(db, principal, ctx, f"firewall.{body.action}", rule.id, body.model_dump(mode="json"))
    db.commit()
    return RuleOut.model_validate(rule)


@router.patch("/rules/{rule_id}", response_model=RuleOut, summary="Change a rule")
def update_rule(
    rule_id: uuid.UUID,
    body: RulePatch,
    principal: Principal = Depends(require("firewall.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RuleOut:
    rule = _manual_rule(db, rule_id)
    fields = body.model_fields_set
    if "services" in fields and body.services is not None:
        rule.services = body.services
    if "comment" in fields:
        rule.comment = body.comment
    if "expires_at" in fields:
        rule.expires_at = body.expires_at
    _record(
        db,
        principal,
        ctx,
        "firewall.rule_update",
        rule.id,
        body.model_dump(mode="json", exclude_unset=True),
    )
    db.commit()
    return RuleOut.model_validate(rule)


@router.delete("/rules/{rule_id}", status_code=204, summary="Remove a rule")
def delete_rule(
    rule_id: uuid.UUID,
    principal: Principal = Depends(require("firewall.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    rule = _manual_rule(db, rule_id)
    if rule.action == "allow" and _covers(rule.cidr, ctx.ip):
        fw = load_settings(db)
        others = [r for r in fwservice.active_rules(db, utcnow()) if r.id != rule.id]
        addr = normalise_address(ctx.ip or "")
        if fw.enabled and "web" in fw.restricted() and addr and not fwservice.allowed(addr, others):
            raise _self_block(ctx.ip)
    _record(
        db,
        principal,
        ctx,
        "firewall.rule_delete",
        rule.id,
        {"action": rule.action, "cidr": rule.cidr},
    )
    db.delete(rule)
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ bans


class BanOut(ORM):
    id: uuid.UUID
    address: str
    reason: str
    source: str
    event_count: int
    offence: int
    banned_at: datetime
    expires_at: datetime
    lifted_at: datetime | None
    lifted_by: str | None


@router.get("/bans", response_model=Page[BanOut], summary="Bans, newest first")
def list_bans(
    active: bool | None = Query(None),
    address: str | None = Query(None, max_length=45),
    page: PageParams = Depends(page_params),
    principal: Principal = Depends(require("firewall.read")),
    db: Session = Depends(get_db),
) -> Page[BanOut]:
    now = utcnow()
    stmt = select(FirewallBan).order_by(FirewallBan.banned_at.desc())
    if active is True:
        stmt = stmt.where(FirewallBan.lifted_at.is_(None), FirewallBan.expires_at > now)
    elif active is False:
        stmt = stmt.where((FirewallBan.lifted_at.is_not(None)) | (FirewallBan.expires_at <= now))
    if address:
        stmt = stmt.where(FirewallBan.address == address.strip())
    rows, total = paginate(db, stmt, page)
    return Page(
        items=[BanOut.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


def _ban(db: Session, ban_id: uuid.UUID) -> FirewallBan:
    ban = db.get(FirewallBan, ban_id)
    if ban is None:
        raise ProblemError(404, "Not found", "No such ban.", code="not_found")
    return ban


@router.post("/bans/{ban_id}/lift", response_model=BanOut, summary="Lift a ban now")
def lift_ban(
    ban_id: uuid.UUID,
    principal: Principal = Depends(require("firewall.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> BanOut:
    ban = _ban(db, ban_id)
    if ban.lifted_at is None:
        ban.lifted_at = utcnow()
        ban.lifted_by = principal.label
        _record(db, principal, ctx, "firewall.ban_lift", ban.id, {"address": ban.address})
        db.commit()
    return BanOut.model_validate(ban)


@router.post(
    "/bans/{ban_id}/block", response_model=RuleOut, status_code=201, summary="Block permanently"
)
def block_banned(
    ban_id: uuid.UUID,
    principal: Principal = Depends(require("firewall.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RuleOut:
    ban = _ban(db, ban_id)
    cidr = check_cidr(ban.address)
    rule = db.scalar(
        select(FirewallRule).where(
            FirewallRule.action == "block",
            FirewallRule.cidr == cidr,
            FirewallRule.origin == "manual",
        )
    )
    if rule is None:
        rule = FirewallRule(
            id=uuid.uuid4(),
            action="block",
            cidr=cidr,
            services=[],
            comment=f"From ban: {ban.reason}"[:200],
            origin="manual",
            created_by=principal.label,
        )
        db.add(rule)
    if ban.lifted_at is None:
        ban.lifted_at = utcnow()
        ban.lifted_by = principal.label
    db.flush()
    _record(db, principal, ctx, "firewall.block", rule.id, {"cidr": cidr, "from_ban": str(ban.id)})
    db.commit()
    return RuleOut.model_validate(rule)


# ---------------------------------------------------------------- events


class EventOut(ORM):
    id: uuid.UUID
    at: datetime
    address: str
    source: str
    kind: str
    detail: str | None
    count: int
    would_ban: bool


@router.get("/events", response_model=Page[EventOut], summary="Suspicious events, newest first")
def list_events(
    address: str | None = Query(None, max_length=45),
    source: str | None = Query(None, pattern="^(asterisk|auth|provisioning|nginx)$"),
    since: datetime | None = Query(None),
    would_ban: bool | None = Query(None),
    page: PageParams = Depends(page_params),
    principal: Principal = Depends(require("firewall.read")),
    db: Session = Depends(get_db),
) -> Page[EventOut]:
    stmt = select(FirewallEvent).order_by(FirewallEvent.at.desc())
    if address:
        stmt = stmt.where(FirewallEvent.address == address.strip())
    if source:
        stmt = stmt.where(FirewallEvent.source == source)
    if since:
        stmt = stmt.where(FirewallEvent.at >= since)
    if would_ban is not None:
        stmt = stmt.where(FirewallEvent.would_ban.is_(would_ban))
    rows, total = paginate(db, stmt, page)
    return Page(
        items=[EventOut.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


# ----------------------------------------------------------------- feeds


class FeedIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    kind: Literal["crowdsec", "list"]
    url: str = Field(..., max_length=500, pattern=r"^https?://")
    # CrowdSec bouncer key. Omitted on update: unchanged.
    key: str | None = Field(None, max_length=200)
    is_enabled: bool = True


class FeedOut(ORM):
    id: uuid.UUID
    name: str
    kind: str
    url: str
    has_key: bool
    is_enabled: bool
    last_fetched_at: datetime | None
    last_status: str | None
    last_error: str | None
    entry_count: int


def _feed_out(f: FirewallFeed) -> FeedOut:
    return FeedOut(
        id=f.id,
        name=f.name,
        kind=f.kind,
        url=f.url,
        has_key=bool(f.key_ciphertext),
        is_enabled=f.is_enabled,
        last_fetched_at=f.last_fetched_at,
        last_status=f.last_status,
        last_error=f.last_error,
        entry_count=f.entry_count,
    )


def _check_feed(body: FeedIn) -> None:
    if body.kind == "list" and not body.url.startswith("https://"):
        raise ProblemError(
            422, "Validation failed", "List feeds must use HTTPS.", code="validation_failed"
        )


@router.get("/feeds", response_model=list[FeedOut], summary="Blocklist feeds")
def list_feeds(
    principal: Principal = Depends(require("firewall.read")),
    db: Session = Depends(get_db),
) -> list[FeedOut]:
    return [_feed_out(f) for f in db.scalars(select(FirewallFeed).order_by(FirewallFeed.name))]


@router.post("/feeds", response_model=FeedOut, status_code=201, summary="Add a feed")
def create_feed(
    body: FeedIn,
    request: Request,
    principal: Principal = Depends(require("firewall.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> FeedOut:
    _check_feed(body)
    if db.scalar(select(FirewallFeed).where(FirewallFeed.name == body.name)):
        raise ProblemError(409, "Name in use", "Another feed has that name.", code="duplicate")
    feed = FirewallFeed(
        id=uuid.uuid4(),
        name=body.name,
        kind=body.kind,
        url=body.url,
        is_enabled=body.is_enabled,
        last_status="pending",
        entry_count=0,
    )
    if body.key:
        feed.key_ciphertext = installation_key(request).encrypt(
            body.key, f"firewall.feed:{feed.id}"
        )
    db.add(feed)
    db.flush()
    _record(
        db, principal, ctx, "firewall.feed_create", feed.id, {"name": feed.name, "kind": feed.kind}
    )
    db.commit()
    return _feed_out(feed)


def _feed(db: Session, feed_id: uuid.UUID) -> FirewallFeed:
    feed = db.get(FirewallFeed, feed_id)
    if feed is None:
        raise ProblemError(404, "Not found", "No such feed.", code="not_found")
    return feed


@router.put("/feeds/{feed_id}", response_model=FeedOut, summary="Change a feed")
def update_feed(
    feed_id: uuid.UUID,
    body: FeedIn,
    request: Request,
    principal: Principal = Depends(require("firewall.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> FeedOut:
    _check_feed(body)
    feed = _feed(db, feed_id)
    other = db.scalar(
        select(FirewallFeed).where(FirewallFeed.name == body.name, FirewallFeed.id != feed.id)
    )
    if other:
        raise ProblemError(409, "Name in use", "Another feed has that name.", code="duplicate")
    feed.name, feed.kind, feed.url, feed.is_enabled = (
        body.name,
        body.kind,
        body.url,
        body.is_enabled,
    )
    if "key" in body.model_fields_set:
        feed.key_ciphertext = (
            installation_key(request).encrypt(body.key, f"firewall.feed:{feed.id}")
            if body.key
            else None
        )
    feed.last_status = "pending"
    _record(db, principal, ctx, "firewall.feed_update", feed.id, {"name": feed.name})
    db.commit()
    return _feed_out(feed)


@router.post("/feeds/{feed_id}/refresh", response_model=FeedOut, summary="Fetch a feed now")
def refresh_feed(
    feed_id: uuid.UUID,
    principal: Principal = Depends(require("firewall.write")),
    db: Session = Depends(get_db),
) -> FeedOut:
    feed = _feed(db, feed_id)
    # The firewall service fetches pending feeds on its next pass.
    feed.last_status = "pending"
    db.commit()
    return _feed_out(feed)


@router.delete("/feeds/{feed_id}", status_code=204, summary="Remove a feed")
def delete_feed(
    feed_id: uuid.UUID,
    principal: Principal = Depends(require("firewall.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    feed = _feed(db, feed_id)
    _record(db, principal, ctx, "firewall.feed_delete", feed.id, {"name": feed.name})
    db.delete(feed)
    db.commit()
    return Response(status_code=204)
