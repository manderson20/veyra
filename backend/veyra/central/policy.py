# SPDX-License-Identifier: AGPL-3.0-or-later
"""Policies from the central console and how an instance applies them
(docs/CENTRAL_MANAGEMENT.md §4).

Every value goes through the same validation as if a local administrator had
typed it. A section the local administrator does not accept is reported as
``refused`` and leaves the instance as it is (central firewall entries and
the notice are removed, since they only ever come from the console).
"""

from __future__ import annotations

import ipaddress
import uuid
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from veyra.core.config import Settings
from veyra.core.models import FirewallRule, SystemSetting, UpdatePolicy
from veyra.telephony import routing
from veyra.updates.policy import Component, PolicyUpdate, availability_problem

SECTIONS = ("updates", "firewall_allow", "alert_recipients", "notice")
NOTICE_KEY = "central.notice"
FIREWALL_ORIGIN = "central"


def _emails(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        e = routing.check_email(v).lower()
        if e not in out:
            out.append(e)
    return out


class UpdatesSection(BaseModel):
    policy: PolicyUpdate
    # The update source's address and e-mail recipients; the token never
    # leaves the instance.
    source_url: str | None = Field(None, max_length=2000)
    recipients: list[str] | None = Field(None, max_length=20)

    @field_validator("recipients")
    @classmethod
    def _r(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _emails(v)


class AllowEntry(BaseModel):
    cidr: str = Field(max_length=64)
    comment: str | None = Field(None, max_length=150)

    @field_validator("cidr")
    @classmethod
    def _cidr(cls, v: str) -> str:
        try:
            return str(ipaddress.ip_network(v.strip(), strict=False))
        except ValueError as e:
            raise ValueError(f"{v!r} is not an address or network") from e


class PolicyDocument(BaseModel):
    updates: UpdatesSection | None = None
    firewall_allow: list[AllowEntry] | None = Field(None, max_length=100)
    alert_recipients: list[str] | None = Field(None, max_length=20)
    notice: str | None = Field(None, max_length=500)

    @field_validator("alert_recipients")
    @classmethod
    def _r(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _emails(v)

    @field_validator("notice")
    @classmethod
    def _n(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None


def validate_document(doc: dict[str, Any]) -> PolicyDocument:
    """Raises ValueError with a readable message."""
    try:
        parsed = PolicyDocument.model_validate(doc)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        raise ValueError(f"{where}: {first.get('msg')}") from e
    if parsed.updates is not None:
        problem = availability_problem(Component.VEYRA_CORE, parsed.updates.policy)
        if problem:
            raise ValueError(f"updates: {problem}")
    return parsed


# --------------------------------------------------------------------- apply


def _setting(db: Session, key: str, value: Any) -> None:
    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value


def notice(db: Session) -> str | None:
    row = db.get(SystemSetting, NOTICE_KEY)
    if row is None or not isinstance(row.value, dict):
        return None
    text = row.value.get("text")
    return str(text) if text else None


def _apply_updates(db: Session, settings: Settings, section: UpdatesSection) -> str:
    from veyra.updates import manager

    policy = db.get(UpdatePolicy, Component.VEYRA_CORE.value)
    if policy is None:
        return "error: no update policy on this installation"
    data = section.policy.model_dump(mode="json")
    changed = False
    for k, v in data.items():
        if getattr(policy, k) != v:
            setattr(policy, k, v)
            changed = True
    if section.source_url is not None or section.recipients is not None:
        current = manager.load_source(db)
        value = dict(current)
        if section.source_url is not None:
            url = section.source_url.strip()
            if url:
                manager.check_url(url, settings)
            value["url"] = url
        if section.recipients is not None:
            value["recipients"] = section.recipients
        if value != current:
            manager.save_source(db, value)
            changed = True
    return "applied" if changed else "unchanged"


def _apply_firewall(db: Session, entries: list[AllowEntry] | None) -> str:
    wanted = {e.cidr: (e.comment or "Central console")[:200] for e in entries or []}
    existing = {
        r.cidr: r
        for r in db.scalars(
            select(FirewallRule).where(
                FirewallRule.action == "allow", FirewallRule.origin == FIREWALL_ORIGIN
            )
        )
    }
    changed = False
    for cidr, row in existing.items():
        if cidr not in wanted:
            db.delete(row)
            changed = True
        elif row.comment != wanted[cidr]:
            row.comment = wanted[cidr]
            changed = True
    for cidr, comment in wanted.items():
        if cidr not in existing:
            db.add(
                FirewallRule(
                    id=uuid.uuid4(),
                    action="allow",
                    cidr=cidr,
                    services=[],
                    comment=comment,
                    origin=FIREWALL_ORIGIN,
                    created_by="Central console",
                )
            )
            changed = True
    db.flush()
    return "applied" if changed else "unchanged"


def _apply_recipients(db: Session, recipients: list[str]) -> str:
    from veyra.reporting.alerts import ensure_rules

    changed = False
    for rule in ensure_rules(db).values():
        if list(rule.recipients or []) != recipients:
            rule.recipients = list(recipients)
            changed = True
    return "applied" if changed else "unchanged"


def _apply_notice(db: Session, text: str | None) -> str:
    if (notice(db) or None) == (text or None):
        return "unchanged"
    _setting(db, NOTICE_KEY, {"text": text} if text else {})
    return "applied"


def apply(
    db: Session, settings: Settings, doc: dict[str, Any], accepted: dict[str, bool]
) -> dict[str, str]:
    """Apply what is accepted; returns a result per section:
    ``applied``, ``unchanged``, ``refused``, ``not set`` or ``error: …``."""
    results: dict[str, str] = {}
    try:
        parsed = validate_document(doc)
    except ValueError as e:
        return dict.fromkeys(SECTIONS, f"error: {e}")
    for section in SECTIONS:
        value = getattr(parsed, section)
        allowed = accepted.get(section, True)
        try:
            if section in ("firewall_allow", "notice"):
                # These exist only while the console sends them and this
                # installation accepts them: otherwise they are removed.
                effective = value if allowed else None
                outcome = (
                    _apply_firewall(db, effective)
                    if section == "firewall_allow"
                    else _apply_notice(db, effective)
                )
                if not allowed:
                    outcome = "refused" if value is not None else "not set"
                elif value is None:
                    outcome = "not set"
                results[section] = outcome
            elif value is None:
                results[section] = "not set"
            elif not allowed:
                results[section] = "refused"
            elif section == "updates":
                results[section] = _apply_updates(db, settings, value)
            else:
                results[section] = _apply_recipients(db, value)
        except Exception as e:  # one bad section never blocks the others
            results[section] = f"error: {e}"[:300]
    return results


def clear(db: Session) -> None:
    """What only the console put here goes when the installation leaves."""
    db.execute(
        delete(FirewallRule).where(
            FirewallRule.action == "allow", FirewallRule.origin == FIREWALL_ORIGIN
        )
    )
    _setting(db, NOTICE_KEY, {})
