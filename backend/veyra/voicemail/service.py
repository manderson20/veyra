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
from veyra.telephony import audio as audio_tools
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


class EmailIn(BaseModel):
    """Email one message now (issue #148); ``delete`` removes it from the
    box only once the SMTP server has accepted the email."""

    folder: str = "INBOX"
    msg_id: str | None = None
    delete: bool = False


class AdminEmailIn(EmailIn):
    # Default: the box's address.
    to: str | None = None


class EmailOut(BaseModel):
    sent_to: list[str]
    deleted: bool
    # Sent, but the delete failed: the message is still in the box.
    delete_error: str | None = None


class CallIn(BaseModel):
    """Call-me-to-play (issue #136): ring ``extension_id`` (default: the box's
    own extension) and play the message when it answers."""

    folder: str = "INBOX"
    msg_id: str | None = None
    extension_id: uuid.UUID | None = None


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


def list_messages(
    db: Session,
    settings: Settings,
    box: VoicemailBox,
    folder: str,
    names: dict[str, str] | None = None,
) -> MessagesOut:
    """The folder's messages, newest first; ``names`` (number → name, from
    the user's contacts) fills in a caller name the carrier did not send."""
    check_folder(folder)
    context, mailbox = location(db, box)
    try:
        out = client(settings).list(context, mailbox, folder)
    except StoreClientError as e:
        raise problem(e) from e
    messages = [_message_out(folder, m) for m in out.get("messages", [])]
    if names:
        from veyra.portal.contacts import resolve

        for m in messages:
            if not m.caller_name:
                m.caller_name = resolve(names, m.caller_number) or ""
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


# ------------------------------------------------------------ greetings (§3)

# Asterisk's maxgreet in the generated voicemail.conf (generator._voicemail).
MAX_GREETING_SECONDS = 60


class GreetingOut(BaseModel):
    kind: str
    label: str
    recorded: bool
    format: str | None
    size_bytes: int


def greeting_list(db: Session, settings: Settings, box: VoicemailBox) -> list[GreetingOut]:
    return [GreetingOut(**g) for g in greetings(db, settings, box)]


def greeting_audio(
    db: Session, settings: Settings, box: VoicemailBox, kind: str
) -> tuple[str, bytes]:
    check_greeting(kind)
    context, mailbox = location(db, box)
    try:
        fmt, data = client(settings).greeting_get(context, mailbox, kind)
    except StoreClientError as e:
        raise problem(e) from e
    return MEDIA_TYPES.get(fmt, "application/octet-stream"), data


def greeting_save(
    db: Session,
    settings: Settings,
    box: VoicemailBox,
    kind: str,
    data: bytes,
    filename: str | None,
) -> float:
    """Convert an upload or a browser recording to the engine's WAV (8 kHz
    mono) and store it as the greeting; returns the duration."""
    check_greeting(kind)
    if not data:
        raise ProblemError(415, "Empty file", "The audio file is empty.", code="unsupported_audio")
    try:
        wav, duration = audio_tools.convert_any(data, filename)
    except audio_tools.AudioError as e:
        raise ProblemError(415, "Unsupported audio", str(e), code="unsupported_audio") from e
    if duration > MAX_GREETING_SECONDS:
        raise ProblemError(
            422,
            "Greeting too long",
            f"The greeting is {duration:.0f} s long; the limit is {MAX_GREETING_SECONDS} s.",
            code="greeting_too_long",
        )
    context, mailbox = location(db, box)
    try:
        client(settings).greeting_put(context, mailbox, kind, wav, "wav")
    except StoreClientError as e:
        raise problem(e) from e
    return duration


def greeting_remove(db: Session, settings: Settings, box: VoicemailBox, kind: str) -> bool:
    check_greeting(kind)
    context, mailbox = location(db, box)
    try:
        return client(settings).greeting_delete(context, mailbox, kind)
    except StoreClientError as e:
        raise problem(e) from e


def delete_delivered(db: Session, settings: Settings, ref: dict[str, str]) -> VoicemailBox | None:
    """After the SMTP server accepted a notification (issue #148): delete
    the message it is about when its box asks for that and the email
    carried the recording. Returns the box when a message was deleted."""
    context, mailbox, msg_id = ref.get("context"), ref.get("mailbox"), ref.get("msg_id")
    if not (context and mailbox and msg_id):
        return None
    boxes = db.query(VoicemailBox).filter(
        VoicemailBox.delete_after_email.is_(True), VoicemailBox.attach_audio.is_(True)
    )
    for box in boxes:
        if not box.email:
            continue
        try:
            if location(db, box) != (context, mailbox):
                continue
        except ProblemError:
            continue
        return box if client(settings).delete_id(context, mailbox, msg_id) else None
    return None


def email_message(
    db: Session,
    settings: Settings,
    box: VoicemailBox,
    number: int,
    body: EmailIn,
    to: str,
) -> EmailOut:
    """Send one message with its recording to ``to`` through the configured
    server, then delete it if asked: a failed send keeps it (issue #148)."""
    from sqlalchemy import select

    from veyra.core import mail
    from veyra.core.models import Installation
    from veyra.core.security.crypto import try_load_installation_key
    from veyra.telephony.routing import check_email

    check_folder(body.folder)
    try:
        to = check_email(to)
    except ValueError as e:
        raise ProblemError(422, "Invalid address", str(e), code="bad_email") from e
    smtp = mail.load_smtp_settings(db)
    if not smtp.enabled:
        raise ProblemError(
            409,
            "Email delivery is off",
            "Set up Settings → Email delivery first.",
            code="smtp_disabled",
        )
    context, mailbox = location(db, box)
    c = client(settings)
    try:
        listed = c.list(context, mailbox, body.folder).get("messages", [])
        current = next((m for m in listed if int(m["number"]) == number), None)
        if current is None:
            raise StoreClientError("not_found", "no such message")
        msg_id = str(current.get("msg_id") or "")
        if body.msg_id and msg_id != body.msg_id:
            raise StoreClientError("message_moved", "the message list changed; reload it")
        fmt, data = c.read(context, mailbox, body.folder, number)
    except StoreClientError as e:
        raise problem(e) from e
    m = _message_out(body.folder, current)
    caller = " ".join(x for x in (m.caller_name, m.caller_number) if x) or "an unknown caller"
    when = f"{m.received_at:%Y-%m-%d %H:%M} UTC" if m.received_at else "at an unknown time"
    inst = db.scalar(select(Installation))
    address, name = mail.sender(smtp, inst.name if inst else "Veyra")
    stamp = f"{m.received_at:%Y%m%d-%H%M%S}" if m.received_at else f"{number:04d}"
    message = mail.compose(
        from_address=address,
        from_name=name,
        to=to,
        subject=f"Voicemail from {caller} (mailbox {mailbox})",
        text=(
            f"A voicemail for mailbox {mailbox} ({box.name or mailbox}): from {caller}, "
            f"received {when}, {m.duration_seconds} seconds long.\n\n"
            "The recording is attached."
            + ("\nIt has been deleted from the voicemail box." if body.delete else "")
            + "\n\nThis message was sent by Veyra.\n"
        ),
        attachments=[(f"voicemail-{stamp}.wav", MEDIA_TYPES.get(fmt, "audio/wav"), data)],
    )
    try:
        sent_to = mail.send(smtp, try_load_installation_key(settings), message)
    except mail.MailError as e:
        raise ProblemError(
            502, "Email not sent", f"The message was kept: {e}", code="mail_failed"
        ) from e
    out = EmailOut(sent_to=sent_to, deleted=False)
    if body.delete:
        try:
            out.deleted = c.delete_id(context, mailbox, msg_id, [body.folder])
        except StoreClientError as e:
            out.delete_error = e.message
        else:
            if not out.deleted:
                out.delete_error = "the message was no longer in the folder"
    return out


def call_to_play(
    db: Session,
    settings: Settings,
    adapter: Any,
    box: VoicemailBox,
    number: int,
    body: CallIn,
    ext: Extension,
) -> str:
    """Ring ``ext`` and play the message to it (issue #136). Returns the
    engine's channel id."""
    from veyra.telephony.adapter import Capability, EngineUnavailable, NotSupported

    check_folder(body.folder)
    context, mailbox = location(db, box)
    try:
        listed = client(settings).list(context, mailbox, body.folder).get("messages", [])
    except StoreClientError as e:
        raise problem(e) from e
    current = next((m for m in listed if int(m["number"]) == number), None)
    if current is None:
        raise problem(StoreClientError("not_found", "no such message"))
    msg_id = str(current.get("msg_id") or "")
    if body.msg_id and msg_id != body.msg_id:
        raise problem(StoreClientError("message_moved", "the message list changed; reload it"))
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", msg_id):
        raise ProblemError(409, "Cannot play", "The message has no id.", code="no_msg_id")
    if Capability.CLICK_TO_DIAL not in adapter.capabilities():
        raise ProblemError(
            409, "Not available", "The engine cannot place calls.", code="not_available"
        )
    if not ext.is_enabled:
        raise ProblemError(
            409, "Extension disabled", "This extension is disabled.", code="extension_disabled"
        )
    names = tenancy.names_of(db, box.organization_id)
    try:
        return adapter.originate_channel(
            f"PJSIP/{ext.endpoint_name}",
            "s",
            context=names.voicemail_play,
            caller_id=f"Voicemail <{mailbox}>",
            timeout=30,
            variables={"VEYRA_VM_BOX": mailbox, "VEYRA_VM_MSG": msg_id},
        )
    except (EngineUnavailable, NotSupported) as e:
        raise ProblemError(
            409, "Call not placed", f"The engine refused the call: {e}", code="originate_failed"
        ) from e


PRUNE_KEY = "voicemail.pruned_at"


def prune_boxes(db: Session, settings: Settings, now: datetime | None = None) -> int:
    """Once a day: delete messages older than each box's ``keep_days``
    (issue #142). Returns how many messages went; a box whose store call
    fails is skipped until the next day."""
    from datetime import timedelta

    from veyra.core.models import SystemSetting
    from veyra.core.models.base import utcnow

    now = now or utcnow()
    row = db.get(SystemSetting, PRUNE_KEY)
    last = (row.value or {}).get("at") if row is not None and isinstance(row.value, dict) else None
    if last and now - datetime.fromisoformat(last) < timedelta(hours=23):
        return 0
    removed = 0
    c = client(settings)
    for box in db.query(VoicemailBox).filter(VoicemailBox.keep_days.is_not(None)):
        try:
            context, mailbox = location(db, box)
            removed += c.prune(
                context, mailbox, int((now - timedelta(days=int(box.keep_days or 0))).timestamp())
            )
        except (ProblemError, StoreClientError):
            continue
    if row is None:
        db.add(SystemSetting(key=PRUNE_KEY, value={"at": now.isoformat(), "removed": removed}))
    else:
        row.value = {"at": now.isoformat(), "removed": removed}
    db.commit()
    return removed
