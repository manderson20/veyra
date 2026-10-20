# SPDX-License-Identifier: AGPL-3.0-or-later
"""Automation rules, "when X happens, do Y" (issue #117; docs/INTEGRATIONS.md §3.8).

A rule listens to an event of the webhook catalogue (``call.ended``,
``voicemail.message``, ``alert.raised``…) or to a request to its own secret
address (``hook``: a door controller, a fire panel, a script). When the
event's fields match the rule's conditions, a run is queued in the same
transaction (:func:`enqueue`, called from ``webhooks.emit``); the worker
runs it within seconds (:func:`process`): it sends emails and starts
recorded pages. Events caused by a rule's own actions do not trigger rules
again, and a cooldown keeps a burst of events from paging twenty times.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.models import AutomationRule, AutomationRun, Organization
from veyra.core.models.base import utcnow

log = logging.getLogger("veyra.automation")

HOOK = "hook"
ACTION_TYPES = ("email", "page")
MAX_ACTIONS = 5
MAX_CONDITIONS = 10
MAX_HOOK_BYTES = 16 * 1024
RUNS_PER_PASS = 50
KEEP_RUNS = timedelta(days=30)

# Set while a rule's actions run: the events they cause do not fire rules.
_running: ContextVar[bool] = ContextVar("veyra_automation_running", default=False)


@contextmanager
def _in_rule() -> Any:
    token = _running.set(True)
    try:
        yield
    finally:
        _running.reset(token)


def new_hook_token() -> tuple[str, str]:
    """(token shown once, its SHA-256 stored)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ----------------------------------------------------------------- matching


def field(data: Any, path: str) -> Any:
    """``from.number`` in the event data; None when absent."""
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def matches(conditions: list[dict[str, Any]], data: dict[str, Any]) -> bool:
    """Every condition holds: ``equals`` (case-insensitive text) or
    ``contains`` (substring)."""
    for c in conditions:
        value = field(data, str(c.get("field") or ""))
        text = "" if value is None else str(value).lower()
        if "equals" in c and text != str(c["equals"]).lower():
            return False
        if "contains" in c and str(c["contains"]).lower() not in text:
            return False
    return True


def enqueue(
    db: Session,
    organization_id: uuid.UUID,
    event: str,
    data: dict[str, Any],
    rule_id: uuid.UUID | None = None,
) -> int:
    """Queue a run for every enabled rule of the organization (or only
    ``rule_id``) that listens to ``event`` and whose conditions hold, outside
    its cooldown. The caller commits."""
    if _running.get():
        return 0
    stmt = select(AutomationRule).where(
        AutomationRule.organization_id == organization_id,
        AutomationRule.enabled.is_(True),
        AutomationRule.trigger == event,
    )
    if rule_id is not None:  # a hook address belongs to one rule
        stmt = stmt.where(AutomationRule.id == rule_id)
    rules = db.scalars(stmt).all()
    queued = 0
    now = utcnow()
    for rule in rules:
        if not matches(rule.conditions or [], data):
            continue
        if rule.last_fired_at and now - rule.last_fired_at < timedelta(
            seconds=rule.cooldown_seconds or 0
        ):
            continue
        rule.last_fired_at = now
        rule.fire_count = (rule.fire_count or 0) + 1
        db.add(
            AutomationRun(
                id=uuid.uuid4(),
                rule_id=rule.id,
                event=event,
                data=data,
                status="pending",
                results=[],
                created_at=now,
            )
        )
        queued += 1
    if queued:
        db.flush()
    return queued


# ----------------------------------------------------------------- actions


def summary(event: str, data: dict[str, Any], prefix: str = "") -> list[str]:
    """The event's fields as "key: value" lines for an email body."""
    lines: list[str] = []
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            lines += summary(event, value, f"{name}.")
        elif value not in (None, "", [], {}):
            lines.append(f"{name}: {value}")
    return lines


def _email(
    db: Session, settings: Any, rule: AutomationRule, run: AutomationRun, action: dict[str, Any]
) -> str:
    from veyra.core import mail
    from veyra.core.models import Installation

    smtp = mail.load_smtp_settings(db)
    if not smtp.enabled:
        raise RuntimeError("email delivery is off (Settings → Email delivery)")
    to = [a for a in action.get("to") or [] if parseaddr(str(a))[1]]
    if not to:
        raise RuntimeError("no recipient")
    inst = db.scalar(select(Installation))
    address, name = mail.sender(smtp, inst.name if inst else "Veyra")
    what = "a request to its address" if run.event == HOOK else f"the event {run.event}"
    text = (
        f"The rule “{rule.name}” was triggered by {what}.\n\n"
        + "\n".join(summary(run.event, run.data or {}))
        + "\n\nThis message was sent by Veyra (Integrations → Automation).\n"
    )
    msg = mail.compose(
        from_address=address,
        from_name=name,
        to=", ".join(to),
        subject=str(action.get("subject") or f"Veyra: {rule.name}")[:200],
        text=text,
    )
    queue_dir = Path(settings.mailqueue_dir)
    queue_dir.mkdir(parents=True, exist_ok=True)
    mail.enqueue(queue_dir, msg.as_bytes())
    return f"email queued for {', '.join(to)}"


def _page(db: Session, adapter: Any, rule: AutomationRule, action: dict[str, Any]) -> str:
    from veyra.api.v1.pages import start_page
    from veyra.core.models import Page, Prompt

    page = db.get(Page, uuid.UUID(str(action.get("page_id"))))
    if page is None or page.organization_id != rule.organization_id:
        raise RuntimeError("the page no longer exists")
    audio = None
    if action.get("audio_id"):
        audio = db.get(Prompt, uuid.UUID(str(action["audio_id"])))
        if audio is None or audio.organization_id != rule.organization_id:
            raise RuntimeError("the recording no longer exists")
    started, message, _channel = start_page(
        db, adapter, page, trigger="rule", actor=f"rule {rule.name}", audio=audio
    )
    if not started:
        raise RuntimeError(message)
    return message


def run_one(db: Session, settings: Any, adapter: Any, run: AutomationRun) -> None:
    rule = db.get(AutomationRule, run.rule_id)
    if rule is None:
        db.delete(run)
        return
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    with _in_rule():
        for action in rule.actions or []:
            kind = str(action.get("type") or "")
            try:
                if kind == "email":
                    detail = _email(db, settings, rule, run, action)
                elif kind == "page":
                    detail = _page(db, adapter, rule, action)
                else:
                    raise RuntimeError(f"unknown action {kind!r}")
                results.append({"type": kind, "ok": True, "detail": detail})
            except Exception as e:  # one failing action never stops the others
                log.warning("Rule %s: %s action failed: %s", rule.name, kind, e)
                errors.append(f"{kind}: {e}")
                results.append({"type": kind, "ok": False, "detail": str(e)[:500]})
    # start_page commits; reload the rows it may have expired.
    run = db.get(AutomationRun, run.id) or run
    rule = db.get(AutomationRule, rule.id) or rule
    run.results = results
    run.status = "failed" if errors else "done"
    run.finished_at = utcnow()
    rule.last_error = "; ".join(errors)[:2000] if errors else None


def process(db: Session, settings: Any, adapter: Any) -> int:
    """Run the pending runs (oldest first) and prune old ones."""
    done = 0
    for run in db.scalars(
        select(AutomationRun)
        .where(AutomationRun.status == "pending")
        .order_by(AutomationRun.created_at)
        .limit(RUNS_PER_PASS)
    ).all():
        run_one(db, settings, adapter, run)
        db.commit()
        done += 1
    cutoff = utcnow() - KEEP_RUNS
    old = db.scalars(select(AutomationRun).where(AutomationRun.created_at < cutoff)).all()
    for r in old:
        db.delete(r)
    if old:
        db.commit()
    return done


def organization_of(db: Session, rule: AutomationRule) -> Organization | None:
    return db.get(Organization, rule.organization_id)
