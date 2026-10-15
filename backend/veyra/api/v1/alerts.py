# SPDX-License-Identifier: AGPL-3.0-or-later
"""Monitoring (docs/REPORTING.md §6): alerts, alert rules, and Prometheus
metrics for outside tools."""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import not_found
from veyra.core.models import Alert, AlertRule, FirewallBan
from veyra.core.models.base import utcnow
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.reporting.alerts import RULES, ensure_rules
from veyra.telephony.adapter import EngineUnavailable, NotSupported

router = APIRouter(tags=["monitoring"])
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AlertOut(BaseModel):
    id: str
    rule: str
    title: str
    subject: str
    state: str
    message: str
    first_seen_at: datetime
    raised_at: datetime | None
    cleared_at: datetime | None
    notify_error: str | None


@router.get("/alerts", response_model=Page[AlertOut], summary="Alerts, raised first")
def list_alerts(
    state: Literal["open", "raised", "cleared", "all"] = "open",
    page: PageParams = Depends(page_params),
    principal: Principal = Depends(require("alerts.read")),
    db: Session = Depends(get_db),
) -> Page[AlertOut]:
    stmt = select(Alert).order_by(Alert.state.desc(), Alert.first_seen_at.desc())
    if state == "open":
        stmt = stmt.where(Alert.state == "raised")
    elif state != "all":
        stmt = stmt.where(Alert.state == state)
    rows, total = paginate(db, stmt, page)
    return Page(
        items=[
            AlertOut(
                id=str(a.id),
                rule=a.rule,
                title=RULES[a.rule].title if a.rule in RULES else a.rule,
                subject=a.subject,
                state=a.state,
                message=a.message,
                first_seen_at=a.first_seen_at,
                raised_at=a.raised_at,
                cleared_at=a.cleared_at,
                notify_error=a.notify_error,
            )
            for a in rows
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


class RuleOut(BaseModel):
    key: str
    title: str
    is_enabled: bool
    delay_minutes: int
    threshold: int | None
    unit: str
    recipients: list[str]


class RulePatch(BaseModel):
    is_enabled: bool | None = None
    delay_minutes: int | None = Field(None, ge=0, le=1440)
    threshold: int | None = Field(None, ge=1, le=100000)
    recipients: list[str] | None = Field(None, max_length=20)

    @field_validator("recipients")
    @classmethod
    def _emails(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        out = []
        for a in v:
            a = a.strip()
            if not a:
                continue
            if not _EMAIL_RE.match(a):
                raise ValueError(f"{a!r} is not an email address")
            out.append(a)
        return sorted(set(out))


def _rule_out(r: AlertRule) -> RuleOut:
    d = RULES[r.key]
    return RuleOut(
        key=r.key,
        title=d.title,
        is_enabled=r.is_enabled,
        delay_minutes=r.delay_minutes,
        threshold=r.threshold if d.threshold is not None else None,
        unit=d.unit,
        recipients=list(r.recipients or []),
    )


@router.get("/alert-rules", response_model=list[RuleOut], summary="Alert rules")
def list_rules(
    principal: Principal = Depends(require("alerts.read")),
    db: Session = Depends(get_db),
) -> list[RuleOut]:
    rows = ensure_rules(db)
    db.commit()
    return [_rule_out(rows[k]) for k in RULES]


@router.patch("/alert-rules/{key}", response_model=RuleOut, summary="Change an alert rule")
def update_rule(
    key: str,
    body: RulePatch,
    principal: Principal = Depends(require("alerts.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RuleOut:
    rows = ensure_rules(db)
    rule = rows.get(key)
    if rule is None or key not in RULES:
        raise not_found("Alert rule")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if v is not None:
            setattr(rule, k, v)
    audit.record(
        db,
        action="alert_rule.update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="alert_rule",
        target_id=key,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=changes,
    )
    db.commit()
    return _rule_out(rule)


def _line(name: str, value: float, labels: dict[str, str] | None = None) -> str:
    if labels:
        inner = ",".join(
            f'{k}="{str(v).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
            for k, v in labels.items()
        )
        return f"{name}{{{inner}}} {value:g}"
    return f"{name} {value:g}"


@router.get("/metrics", response_class=PlainTextResponse, summary="Prometheus metrics")
def metrics(
    request: Request,
    since: datetime | None = Query(None, include_in_schema=False),
    principal: Principal = Depends(require("metrics.read")),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Text exposition format; scrape with an API token holding metrics.read."""
    from veyra.telephony import metrics as tm

    out = [
        "# HELP veyra_up 1 while the Veyra API answers.",
        "# TYPE veyra_up gauge",
        "veyra_up 1",
    ]
    reading = tm.read(request.app.state.telephony)
    out += [
        "# HELP veyra_engine_up 1 when the telephony engine answers.",
        "# TYPE veyra_engine_up gauge",
        _line("veyra_engine_up", 1 if reading is not None else 0),
    ]
    if reading is not None:
        out += [
            "# TYPE veyra_channels gauge",
            _line("veyra_channels", reading.channels),
            "# TYPE veyra_calls gauge",
            _line("veyra_calls", reading.calls_internal, {"direction": "internal"}),
            _line("veyra_calls", reading.calls_external, {"direction": "external"}),
            "# TYPE veyra_registered_phones gauge",
            _line("veyra_registered_phones", reading.registrations),
        ]
        try:
            statuses = request.app.state.telephony.endpoint_statuses()
        except (EngineUnavailable, NotSupported):
            statuses = []
        trunks = [s for s in statuses if s.endpoint.startswith("trunk-")]
        if trunks:
            out.append("# TYPE veyra_trunk_up gauge")
            out += [
                _line("veyra_trunk_up", 1 if s.registered else 0, {"trunk": s.endpoint[6:]})
                for s in trunks
            ]
    raised = db.scalars(select(Alert).where(Alert.state == "raised")).all()
    out += ["# HELP veyra_alert 1 per raised alert.", "# TYPE veyra_alert gauge"]
    out += [_line("veyra_alert", 1, {"rule": a.rule, "subject": a.subject}) for a in raised]
    out += ["# TYPE veyra_alerts_raised gauge", _line("veyra_alerts_raised", len(raised))]
    now = utcnow()
    active_bans = (
        db.scalar(
            select(func.count())
            .select_from(FirewallBan)
            .where(FirewallBan.lifted_at.is_(None), FirewallBan.expires_at > now)
        )
        or 0
    )
    out += [
        "# TYPE veyra_firewall_bans_active gauge",
        _line("veyra_firewall_bans_active", active_bans),
    ]
    settings = request.app.state.settings
    out.append("# TYPE veyra_disk_free_ratio gauge")
    for label, path in (("data", settings.data_dir), ("log", settings.log_dir)):
        try:
            u = shutil.disk_usage(path)
        except OSError:
            continue
        out.append(
            _line(
                "veyra_disk_free_ratio",
                round(u.free / u.total, 4) if u.total else 0,
                {"volume": label},
            )
        )
    return PlainTextResponse("\n".join(out) + "\n", media_type="text/plain; version=0.0.4")
