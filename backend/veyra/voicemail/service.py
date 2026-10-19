# SPDX-License-Identifier: AGPL-3.0-or-later
"""Voicemail messages for the API (docs/USER_PORTAL.md §2): where a box lives
in the spool, the message index as the interface shows it, and the store
helper's errors as API problems. Used by the ``me`` routes and the
administrator's routes alike."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from veyra.core import tenancy
from veyra.core.config import Settings
from veyra.core.errors import ProblemError
from veyra.core.models import Extension, VoicemailBox
from veyra.voicemail.client import StoreClient, StoreClientError, StoreUnavailable
from veyra.voicemail.store import FOLDERS, GREETINGS

FOLDER_LABELS = {
    "INBOX": "New",
    "Old": "Old",
    "Work": "Work",
    "Family": "Family",
    "Friends": "Friends",
    "Urgent": "Urgent",
}
GREETING_LABELS = {
    "unavail": "Unavailable",
    "busy": "Busy",
    "greet": "Name",
    "temp": "Temporary",
}
MEDIA_TYPES = {"wav": "audio/wav", "WAV": "audio/wav", "gsm": "audio/gsm"}

_CALLERID_RE = re.compile(r'^\s*"?(?P<name>[^"<]*?)"?\s*<?(?P<number>[+0-9*#A-Za-z._-]*)>?\s*$')


class MessageOut(BaseModel):
    number: int
    folder: str
    msg_id: str
    caller_number: str
    caller_name: str
    received_at: datetime | None
    duration_seconds: int
    urgent: bool
    format: str | None
    size_bytes: int


class MessagesOut(BaseModel):
    folder: str
    messages: list[MessageOut]
    counts: dict[str, int]
    folders: list[dict[str, str]]


class MoveIn(BaseModel):
    folder: str = "INBOX"
    to: str
    msg_id: str | None = None


class ForwardIn(BaseModel):
    folder: str = "INBOX"
    box_id: uuid.UUID
    msg_id: str | None = None


def check_folder(folder: str) -> str:
    if folder not in FOLDERS:
        raise ProblemError(422, "Unknown folder", f"{folder!r} is not a folder.", code="bad_folder")
    return folder


def check_greeting(kind: str) -> str:
    if kind not in GREETINGS:
        raise ProblemError(
            422, "Unknown greeting", f"{kind!r} is not a greeting kind.", code="bad_greeting"
        )
    return kind


def parse_callerid(value: str) -> tuple[str, str]:
    """``"Pat Lee" <1002>`` → (number, name); bare numbers and names too."""
    m = _CALLERID_RE.match(value or "")
    if not m:
        return value.strip(), ""
    name, number = m.group("name").strip(), m.group("number").strip()
    if not number and name and re.fullmatch(r"[+0-9*#]+", name):
        number, name = name, ""
    return number, name


def location(db: Session, box: VoicemailBox) -> tuple[str, str]:
    """(context, mailbox) of a box in the spool: the organization's voicemail
    context and the extension's number (or the shared box's own number)."""
    context = tenancy.names_of(db, box.organization_id).voicemail
    mailbox = box.number or ""
    if box.extension_id is not None:
        ext = db.get(Extension, box.extension_id)
        mailbox = ext.number if ext else mailbox
    if not mailbox:
        raise ProblemError(409, "No mailbox", "The box has no number.", code="no_mailbox")
    return context, mailbox


def client(settings: Settings) -> StoreClient:
    return StoreClient(settings.vmstore_socket)


def problem(e: StoreClientError) -> ProblemError:
    """The helper's error as the API's."""
    if isinstance(e, StoreUnavailable):
        return ProblemError(
            503,
            "Voicemail store unavailable",
            "The voicemail store helper is not running on this server (veyra-vmstore).",
            code="vmstore_unavailable",
        )
    status = {
        "not_found": 404,
        "message_moved": 409,
        "busy": 409,
        "full": 409,
        "bad_argument": 422,
        "too_large": 413,
    }.get(e.code, 502)
    title = {
        "not_found": "Not found",
        "message_moved": "Message list changed",
        "busy": "Mailbox busy",
        "full": "Folder full",
        "bad_argument": "Invalid request",
        "too_large": "Too large",
    }.get(e.code, "Voicemail store error")
    return ProblemError(status, title, e.message, code=e.code)


def _message_out(folder: str, m: dict[str, Any]) -> MessageOut:
    number, name = parse_callerid(str(m.get("callerid") or ""))
    origtime = int(m.get("origtime") or 0)
    return MessageOut(
        number=int(m["number"]),
        folder=folder,
        msg_id=str(m.get("msg_id") or ""),
        caller_number=number,
        caller_name=name,
        received_at=datetime.fromtimestamp(origtime, UTC) if origtime else None,
        duration_seconds=int(m.get("duration") or 0),
        urgent=bool(m.get("urgent")),
        format=m.get("format"),
        size_bytes=int(m.get("size") or 0),
    )


def list_messages(db: Session, settings: Settings, box: VoicemailBox, folder: str) -> MessagesOut:
    check_folder(folder)
    context, mailbox = location(db, box)
    try:
        out = client(settings).list(context, mailbox, folder)
    except StoreClientError as e:
        raise problem(e) from e
    messages = [_message_out(folder, m) for m in out.get("messages", [])]
    messages.sort(key=lambda m: m.received_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    return MessagesOut(
        folder=folder,
        messages=messages,
        counts={f: int(out.get("counts", {}).get(f, 0)) for f in FOLDERS},
        folders=[{"key": f, "label": FOLDER_LABELS[f]} for f in FOLDERS],
    )


def audio(
    db: Session, settings: Settings, box: VoicemailBox, folder: str, number: int
) -> tuple[str, bytes]:
    """(media type, bytes) of one message."""
    check_folder(folder)
    context, mailbox = location(db, box)
    try:
        fmt, data = client(settings).read(context, mailbox, folder, number)
    except StoreClientError as e:
        raise problem(e) from e
    return MEDIA_TYPES.get(fmt, "application/octet-stream"), data


def move(
    db: Session, settings: Settings, box: VoicemailBox, number: int, body: MoveIn
) -> dict[str, Any]:
    check_folder(body.folder)
    check_folder(body.to)
    context, mailbox = location(db, box)
    try:
        return client(settings).move(context, mailbox, body.folder, number, body.to, body.msg_id)
    except StoreClientError as e:
        raise problem(e) from e


def delete(
    db: Session,
    settings: Settings,
    box: VoicemailBox,
    folder: str,
    number: int,
    msg_id: str | None,
) -> None:
    check_folder(folder)
    context, mailbox = location(db, box)
    try:
        client(settings).delete(context, mailbox, folder, number, msg_id)
    except StoreClientError as e:
        raise problem(e) from e


def forward(
    db: Session,
    settings: Settings,
    box: VoicemailBox,
    number: int,
    body: ForwardIn,
    target: VoicemailBox,
    note: str,
) -> dict[str, Any]:
    check_folder(body.folder)
    context, mailbox = location(db, box)
    to_context, to_mailbox = location(db, target)
    try:
        c = client(settings)
        if body.msg_id:
            # The copy has no msg_id guard of its own: check the index first.
            listed = c.list(context, mailbox, body.folder).get("messages", [])
            current = next((m for m in listed if int(m["number"]) == number), None)
            if current is None or str(current.get("msg_id")) != body.msg_id:
                raise StoreClientError("message_moved", "the message list changed; reload it")
        return c.copy(context, mailbox, body.folder, number, to_context, to_mailbox, note)
    except StoreClientError as e:
        raise problem(e) from e


def greetings(db: Session, settings: Settings, box: VoicemailBox) -> list[dict[str, Any]]:
    context, mailbox = location(db, box)
    try:
        found = client(settings).greetings(context, mailbox)
    except StoreClientError as e:
        raise problem(e) from e
    return [
        {
            "kind": k,
            "label": GREETING_LABELS[k],
            "recorded": found.get(k) is not None,
            "format": (found.get(k) or {}).get("format"),
            "size_bytes": int((found.get(k) or {}).get("size") or 0),
        }
        for k in GREETINGS
    ]
