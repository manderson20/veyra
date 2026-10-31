# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recording after an attended transfer (issue #123). The dialplan evaluates
recording policies before Dial, and nothing runs when a consult call becomes
the real call. So when the caller lands on a phone whose policy records, the
recording starts here, in the same file form the worker already files.

A caller who was promised an announcement has not heard it, so a policy with
an announcement does not start recording mid-call."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.models import Extension, RecordingPolicy
from veyra.telephony.asterisk import cli
from veyra.telephony.asterisk.ari import AriClient

log = logging.getLogger("veyra.events")

_CHANNEL_RE = re.compile(r"^[A-Za-z0-9/_.@;:\-]{1,120}$")
_REF_RE = re.compile(r"^[0-9A-Za-z._-]{1,64}$")


def is_attended_transfer(event: dict[str, Any]) -> bool:
    return event.get("type") == "BridgeAttendedTransfer" and event.get("result") == "Success"


def _endpoint(channel: dict[str, Any]) -> str | None:
    from veyra.telephony.asterisk.events import endpoint_of

    return endpoint_of(str(channel.get("name") or ""))


def policy_for(db: Session, extension: Extension, direction: str) -> RecordingPolicy | None:
    """The first enabled policy that records this extension in this direction
    and asks for no announcement; a policy that does ask is reported."""
    found = None
    for policy in db.scalars(
        select(RecordingPolicy)
        .where(
            RecordingPolicy.organization_id == extension.organization_id,
            RecordingPolicy.is_enabled.is_(True),
        )
        .order_by(RecordingPolicy.name)
    ):
        if not getattr(policy, direction):
            continue
        if policy.scope != "all" and extension.id not in (policy.extension_ids or []):
            continue
        if policy.announcement_prompt_id is not None:
            log.warning(
                "Not recording a transfer to %s: policy %s has an announcement the caller "
                "did not hear",
                extension.number,
                policy.name,
            )
            continue
        found = policy
        break
    return found


def handle(
    event: dict[str, Any],
    ari: AriClient,
    db: Session,
    recordings_dir: str,
    run: Callable[[str], tuple[bool, str]] = cli.run,
) -> str | None:
    """Start recording the transferred caller if a policy says so; returns the
    recording's reference. Reads the channels first, so a call that is already
    recorded stays in its one file."""
    caller = event.get("transferee") or {}
    target = event.get("transfer_target") or {}
    caller_id, caller_name = str(caller.get("id") or ""), str(caller.get("name") or "")
    endpoint = _endpoint(target)
    if not caller_id or not endpoint:
        return None
    if not _CHANNEL_RE.match(caller_name) or not _REF_RE.match(caller_id):
        return None
    extension = db.scalar(select(Extension).where(Extension.endpoint_name == endpoint))
    if extension is None:
        return None
    if ari.get_variable(caller_id, "VEYRA_CALLREC"):
        return None
    if ari.get_variable(caller_id, "VEYRA_DID"):
        direction = "inbound"
    else:
        caller_endpoint = _endpoint(caller)
        known = caller_endpoint and db.scalar(
            select(Extension.id).where(Extension.endpoint_name == caller_endpoint)
        )
        direction = "internal" if known else "outbound"
    policy = policy_for(db, extension, direction)
    if policy is None:
        return None
    path = f"{recordings_dir}/incoming/{caller_id}--{policy.id}.wav"
    ok, out = run(f"mixmonitor start {caller_name} {path},b")
    if not ok:
        log.warning("Could not record the transfer to %s: %s", extension.number, out[:200])
        return None
    # Children of the caller's channel and the call's history find the recording.
    ari.set_variable(caller_id, "__VEYRA_CALLREC", caller_id)
    ari.set_variable(caller_id, "CDR(veyra_rec)", caller_id)
    log.info("Recording transfer to %s under policy %s", extension.number, policy.name)
    return caller_id
