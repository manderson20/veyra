# SPDX-License-Identifier: AGPL-3.0-or-later
"""VM Notify (FreePBX, issue #392): a new message in a box with notify
numbers starts a job; the worker calls the numbers one at a time until
someone presses 1, then repeats the list after a wait, a set number of
rounds. The called person then hears the box's own menu and must enter the
PIN. Listening to the new messages (the count drops to 0) cancels the job.

The call is placed like a fax: a Local channel through the organization's
internal context (an extension) or its outbound routes (any other number),
answered into ``veyra-vmnotify``, which reports ``UserEvent(VeyraVmNotify)``
when 1 is pressed.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.models import Extension, Organization, VoicemailBox, VoicemailNotifyJob
from veyra.core.models.base import utcnow

log = logging.getLogger("veyra.vmnotify")

EVENT = "VeyraVmNotify"
MAX_NUMBERS = 5
# Time given to one call (ringing, the prompt and the key) before the next number.
CALL_SECONDS = 90
RING_SECONDS = 40
_NUMBER_RE = re.compile(r"^\+?[0-9]{2,20}$")


def start(db: Session, box: VoicemailBox, now: datetime | None = None) -> VoicemailNotifyJob | None:
    """A new message arrived: start calling, unless a job is already running."""
    numbers = [n for n in box.notify_numbers or [] if _NUMBER_RE.match(n)][:MAX_NUMBERS]
    if not numbers or not box.is_enabled:
        return None
    running = db.scalar(
        select(VoicemailNotifyJob).where(
            VoicemailNotifyJob.box_id == box.id, VoicemailNotifyJob.state == "pending"
        )
    )
    if running is not None:
        return None
    now = now or utcnow()
    job = VoicemailNotifyJob(
        id=uuid.uuid4(),
        box_id=box.id,
        numbers=numbers,
        next_index=0,
        round=0,
        next_at=now,
        state="pending",
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.flush()
    return job


def cancel(db: Session, box_id: uuid.UUID, now: datetime | None = None) -> int:
    """The messages were listened to: stop calling."""
    n = 0
    for job in db.scalars(
        select(VoicemailNotifyJob).where(
            VoicemailNotifyJob.box_id == box_id, VoicemailNotifyJob.state == "pending"
        )
    ):
        job.state, job.updated_at = "cancelled", now or utcnow()
        n += 1
    return n


def accept(db: Session, job_id: str, now: datetime | None = None) -> bool:
    try:
        job = db.get(VoicemailNotifyJob, uuid.UUID(job_id))
    except ValueError:
        return False
    if job is None or job.state != "pending":
        return False
    job.state, job.updated_at = "accepted", now or utcnow()
    return True


def _call(
    db: Session, adapter: Any, box: VoicemailBox, job: VoicemailNotifyJob, number: str
) -> None:
    from veyra.core import tenancy

    org = db.get(Organization, box.organization_id)
    names = tenancy.names_of(db, box.organization_id)
    ext = db.get(Extension, box.extension_id) if box.extension_id else None
    mailbox = ext.number if ext is not None else (box.number or "")
    local = db.scalar(
        select(Extension.id).where(
            Extension.organization_id == box.organization_id, Extension.number == number
        )
    )
    label = re.sub(r'["<>\\]', "", (box.name or (ext.display_name if ext else "") or "Voicemail"))
    variables = {
        "VEYRA_VMN_JOB": str(job.id),
        "VEYRA_VMN_BOX": mailbox,
        "VEYRA_VMN_CONTEXT": names.voicemail,
        "__VEYRA_ORG": org.slug if org is not None else "",
    }
    adapter.originate_channel(
        f"Local/{number}@{names.internal if local else names.outbound}/n",
        "s",
        context=names.vm_notify,
        caller_id=f'"{label[:30]}" <{mailbox}>',
        timeout=RING_SECONDS,
        variables=variables,
    )


def tick(db: Session, adapter: Any, now: datetime | None = None) -> int:
    """Place the calls that are due. Returns how many were placed."""
    now = now or utcnow()
    placed = 0
    due = db.scalars(
        select(VoicemailNotifyJob).where(
            VoicemailNotifyJob.state == "pending", VoicemailNotifyJob.next_at <= now
        )
    ).all()
    for job in due:
        box = db.get(VoicemailBox, job.box_id)
        if box is None or not box.is_enabled:
            job.state, job.updated_at = "cancelled", now
            continue
        numbers = list(job.numbers or [])
        if job.next_index >= len(numbers):
            job.round += 1
            job.next_index = 0
            if job.round >= max(1, box.notify_rounds):
                job.state, job.updated_at = "exhausted", now
                continue
            job.next_at = now + timedelta(minutes=max(1, box.notify_retry_minutes))
            job.updated_at = now
            continue
        number = numbers[job.next_index]
        job.next_index += 1
        job.last_number = number
        job.next_at = now + timedelta(seconds=CALL_SECONDS)
        job.updated_at = now
        try:
            _call(db, adapter, box, job, number)
            placed += 1
        except Exception as e:  # the engine is down: the next number or round tries again
            log.warning("VM Notify call to %s failed: %s", number, e)
    return placed
