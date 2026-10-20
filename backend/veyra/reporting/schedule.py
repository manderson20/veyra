# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scheduled report emails (docs/REPORT_BUILDER.md §3): when a saved report
is due, and sending it as CSV through the mail queue."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core import mail
from veyra.core.models import Installation, Organization, SavedReport
from veyra.core.models.base import utcnow
from veyra.reporting import builder

log = logging.getLogger("veyra.reports")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SUMMARY_ROWS = 15


class Schedule(BaseModel):
    frequency: Literal["daily", "weekly", "monthly"]
    hour: int = Field(7, ge=0, le=23)
    weekday: int = Field(0, ge=0, le=6)  # Monday = 0, for weekly
    # For monthly: 1-31; a month without that day sends on its last day.
    day: int = Field(1, ge=1, le=31)
    recipients: list[str] = Field(min_length=1, max_length=20)

    @field_validator("recipients")
    @classmethod
    def _emails(cls, v: list[str]) -> list[str]:
        out = []
        for a in v:
            a = a.strip()
            if a and not _EMAIL_RE.match(a):
                raise ValueError(f"{a!r} is not an email address")
            if a:
                out.append(a)
        if not out:
            raise ValueError("add at least one address")
        return sorted(set(out))


def _month_days(d: date) -> int:
    import calendar

    return calendar.monthrange(d.year, d.month)[1]


def next_run(s: Schedule, tz: str, after: datetime) -> datetime:
    """The first send time strictly after ``after``, in UTC; the hour is the
    organization's local hour (so it follows daylight saving)."""
    zone = ZoneInfo(tz)
    local = after.astimezone(zone)
    d: date = local.date()
    for _ in range(400):
        due = (
            s.frequency == "daily"
            or (s.frequency == "weekly" and d.weekday() == s.weekday)
            or (s.frequency == "monthly" and d.day == min(s.day, _month_days(d)))
        )
        if due:
            at = datetime.combine(d, time(s.hour), zone)
            if at > local:
                return at.astimezone(ZoneInfo("UTC"))
        d += timedelta(days=1)
    raise ValueError("no next run within a year")


def org_tz(db: Session, org_id: Any) -> str:
    org = db.get(Organization, org_id)
    return org.timezone if org is not None and org.timezone else "UTC"


def send(db: Session, report: SavedReport, queue_dir: Path, now: datetime | None = None) -> None:
    """Run the report and queue it as an email to its recipients; raises on
    failure (the caller records the error)."""
    if not report.schedule:
        raise ValueError("the report has no recipients")
    sched = Schedule.model_validate(report.schedule)
    smtp = mail.load_smtp_settings(db)
    if not smtp.enabled:
        raise ValueError("email delivery is off (System → Settings → Email)")
    definition = builder.Definition.model_validate(
        {**report.definition, "organization_id": str(report.organization_id)}
    )
    result = builder.run(db, definition, {report.organization_id}, now)
    csv_text = builder.to_csv(result)
    inst = db.scalar(select(Installation))
    name = inst.name if inst else "Veyra"
    address, from_name = mail.sender(smtp, name)
    period = result["period"]["label"]
    lines = [f"{report.name}: {period} ({result['period']['timezone']})", ""]
    head = csv_text.splitlines()
    lines += head[: SUMMARY_ROWS + 1]
    if len(head) > SUMMARY_ROWS + 1:
        lines.append(f"... {len(head) - SUMMARY_ROWS - 1} more rows in the attachment")
    lines += [
        "",
        "The full report is attached as CSV. Change or stop this email under",
        "Telephony → Reports → Saved in Veyra.",
    ]
    stamp = (now or utcnow()).strftime("%Y%m%d")
    slug = re.sub(r"[^a-z0-9]+", "-", report.name.lower()).strip("-")[:40] or "report"
    for to in sched.recipients:
        msg = mail.compose(
            from_address=address,
            from_name=from_name,
            to=to,
            subject=f"[{name}] {report.name}: {period}",
            text="\n".join(lines) + "\n",
            attachments=[(f"{slug}-{stamp}.csv", "text/csv", csv_text.encode())],
        )
        mail.enqueue(queue_dir, msg.as_bytes())


def process(db: Session, queue_dir: Path, now: datetime | None = None) -> int:
    """Send every due scheduled report once; returns how many were sent."""
    now = now or utcnow()
    due = db.scalars(
        select(SavedReport).where(
            SavedReport.next_run_at.is_not(None), SavedReport.next_run_at <= now
        )
    ).all()
    sent = 0
    for r in due:
        try:
            send(db, r, queue_dir, now)
        except Exception as e:  # one failing report must not stop the others
            r.last_error = str(e)[:500]
            log.warning("Scheduled report %s not sent: %s", r.name, e)
        else:
            r.last_error = None
            r.last_sent_at = now
            sent += 1
        try:
            r.next_run_at = next_run(
                Schedule.model_validate(r.schedule), org_tz(db, r.organization_id), now
            )
        except Exception:
            r.next_run_at = None
    return sent
