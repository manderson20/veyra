# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outgoing email: SMTP settings, message composition and the file queue
between Asterisk (voicemail notifications) and the worker that sends them
(docs/VOICEMAIL_IVR.md §2).

Veyra has no mail transport of its own. Messages are RFC 5322 files in the
queue directory; ``veyra worker`` takes each one, delivers it with
``smtplib`` through the configured server, deletes it on success and
otherwise retries with growing delays until it gives up after a day and
moves the file to ``failed/``. Nothing here runs inside an API request
except the explicit "send a test message" action.
"""

from __future__ import annotations

import email.utils
import ipaddress
import json
import logging
import os
import smtplib
import socket
import ssl
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from veyra.core.models import SystemSetting
from veyra.core.models.base import utcnow
from veyra.core.security.crypto import DecryptionError, InstallationKey
from veyra.telephony.routing import check_email

log = logging.getLogger("veyra.mail")

SMTP_SETTINGS_KEY = "notifications.smtp"
SMTP_PASSWORD_PURPOSE = "smtp.password"  # noqa: S105 (a purpose label, not a secret)
SECURITY_MODES = ("starttls", "tls", "none")
SEND_TIMEOUT = 20
# Minutes between delivery attempts of one message, then the last value repeats.
RETRY_MINUTES = (1, 5, 15, 60)
GIVE_UP_AFTER = timedelta(hours=24)
QUEUE_SUFFIX = ".eml"
STATE_SUFFIX = ".json"
FAILED_DIR = "failed"


class MailError(RuntimeError):
    pass


# ----------------------------------------------------------------- settings


class SmtpSettings(BaseModel):
    """The stored document (``system_settings`` key ``notifications.smtp``).
    The password is kept encrypted with the installation key and never
    leaves the server."""

    enabled: bool = False
    host: str = ""
    port: int = Field(587, ge=1, le=65535)
    security: Literal["starttls", "tls", "none"] = "starttls"
    username: str | None = None
    password_ciphertext: str | None = None
    from_address: str | None = None
    from_name: str | None = None

    @field_validator("host")
    @classmethod
    def _host(cls, v: str) -> str:
        v = v.strip()
        if v and not all(c.isalnum() or c in ".-:[]" for c in v):
            raise ValueError("enter a host name or address")
        return v

    @field_validator("username", "from_name", mode="before")
    @classmethod
    def _blank(cls, v: Any) -> str | None:
        if v is None:
            return None
        v = str(v).strip()
        return v or None

    @field_validator("from_address", mode="before")
    @classmethod
    def _from(cls, v: Any) -> str | None:
        if v is None or not str(v).strip():
            return None
        return check_email(str(v))

    @property
    def has_password(self) -> bool:
        return bool(self.password_ciphertext)

    def problems(self) -> list[str]:
        out = []
        if self.enabled and not self.host:
            out.append("Enter the SMTP server host name.")
        if self.security == "none" and self.host and not _is_loopback(self.host):
            out.append(
                "Unencrypted delivery (security 'none') is only allowed to a loopback relay."
            )
        if self.username and not self.password_ciphertext:
            out.append("Enter the password for the SMTP user name.")
        return out


def _is_loopback(host: str) -> bool:
    h = host.strip("[]")
    if h.lower() in ("localhost", "localhost.localdomain"):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def load_smtp_settings(db: Session) -> SmtpSettings:
    row = db.get(SystemSetting, SMTP_SETTINGS_KEY)
    if row is None or not isinstance(row.value, dict):
        return SmtpSettings()
    return SmtpSettings.model_validate(row.value)


def save_smtp_settings(db: Session, settings: SmtpSettings, updated_by: Any = None) -> None:
    row = db.get(SystemSetting, SMTP_SETTINGS_KEY)
    value = settings.model_dump(mode="json")
    if row is None:
        db.add(SystemSetting(key=SMTP_SETTINGS_KEY, value=value, updated_by=updated_by))
    else:
        row.value = value
        row.updated_by = updated_by
    db.flush()


def default_from_address() -> str:
    return f"veyra@{socket.getfqdn() or 'localhost'}"


def sender(settings: SmtpSettings, installation_name: str) -> tuple[str, str]:
    """Effective (address, display name) of outgoing messages."""
    return settings.from_address or default_from_address(), settings.from_name or installation_name


# ----------------------------------------------------------------- sending


def compose(
    *,
    from_address: str,
    from_name: str,
    to: str,
    subject: str,
    text: str,
    attachments: list[tuple[str, str, bytes]] | None = None,
) -> EmailMessage:
    """``attachments``: (filename, MIME type, content), e.g. a report's CSV."""
    msg = EmailMessage(policy=policy.SMTP)
    msg["From"] = email.utils.formataddr((from_name, from_address))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=from_address.rpartition("@")[2] or None)
    msg.set_content(text)
    for filename, mime, content in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(
            content, maintype=maintype, subtype=subtype or "octet-stream", filename=filename
        )
    return msg


def _recipients(msg: EmailMessage) -> list[str]:
    out: list[str] = []
    for header in ("To", "Cc", "Bcc"):
        for _name, addr in email.utils.getaddresses(msg.get_all(header, [])):
            if addr and addr not in out:
                out.append(addr)
    return out


def _password(settings: SmtpSettings, key: InstallationKey | None) -> str | None:
    if not settings.password_ciphertext:
        return None
    if key is None:
        raise MailError("the SMTP password cannot be read: the installation key is missing")
    try:
        return key.decrypt(settings.password_ciphertext, SMTP_PASSWORD_PURPOSE)
    except DecryptionError as e:
        raise MailError(f"the SMTP password cannot be read: {e}") from e


def send(
    settings: SmtpSettings,
    key: InstallationKey | None,
    msg: EmailMessage,
    *,
    timeout: float = SEND_TIMEOUT,
) -> list[str]:
    """Deliver one message through the configured server. Returns the
    recipients; raises :class:`MailError` with a message fit for the audit
    log and the interface."""
    if not settings.enabled:
        raise MailError("email delivery is not enabled (Settings → Email delivery)")
    problems = settings.problems()
    if problems:
        raise MailError(" ".join(problems))
    recipients = _recipients(msg)
    if not recipients:
        raise MailError("the message has no recipient")
    if "Bcc" in msg:
        del msg["Bcc"]
    envelope_from = settings.from_address or default_from_address()
    password = _password(settings, key)
    context = ssl.create_default_context()
    try:
        if settings.security == "tls":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.host, settings.port, timeout=timeout, context=context
            )
        else:
            client = smtplib.SMTP(settings.host, settings.port, timeout=timeout)
        with client:
            client.ehlo_or_helo_if_needed()
            if settings.security == "starttls":
                client.starttls(context=context)
                client.ehlo()
            if settings.username:
                client.login(settings.username, password or "")
            client.send_message(msg, from_addr=envelope_from, to_addrs=recipients)
    except smtplib.SMTPAuthenticationError as e:
        raise MailError(
            f"the SMTP server rejected the user name or password ({e.smtp_code})"
        ) from e
    except smtplib.SMTPRecipientsRefused as e:
        raise MailError(
            "the SMTP server refused the recipient: "
            + "; ".join(f"{a} ({c} {m!r})" for a, (c, m) in e.recipients.items())
        ) from e
    except (smtplib.SMTPException, OSError, ssl.SSLError) as e:
        raise MailError(f"could not send through {settings.host}:{settings.port}: {e}") from e
    return recipients


# ----------------------------------------------------------------- queue


def enqueue(queue_dir: Path, raw: bytes) -> Path:
    """Add a complete RFC 5322 message to the queue (atomic)."""
    queue_dir.mkdir(parents=True, exist_ok=True)
    name = f"{utcnow():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:12]}{QUEUE_SUFFIX}"
    tmp = queue_dir / f".{name}.tmp"
    tmp.write_bytes(raw)
    final = queue_dir / name
    os.replace(tmp, final)
    return final


@dataclass
class QueueState:
    attempts: int = 0
    first_attempt_at: str | None = None
    next_attempt_at: str | None = None
    last_error: str | None = None
    recipients: list[str] = field(default_factory=list)


def _state_path(message: Path) -> Path:
    return message.with_name(message.name + STATE_SUFFIX)


def _read_state(message: Path) -> QueueState:
    try:
        data = json.loads(_state_path(message).read_text(encoding="utf-8"))
        return QueueState(**{k: v for k, v in data.items() if k in QueueState.__dataclass_fields__})
    except (OSError, ValueError, TypeError):
        return QueueState()


def _write_state(message: Path, state: QueueState) -> None:
    _state_path(message).write_text(json.dumps(state.__dict__), encoding="utf-8")


def retry_delay(attempts: int) -> timedelta:
    minutes = RETRY_MINUTES[min(attempts, len(RETRY_MINUTES)) - 1] if attempts else RETRY_MINUTES[0]
    return timedelta(minutes=minutes)


@dataclass
class QueueResult:
    sent: list[str] = field(default_factory=list)  # file names
    retried: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (file name, error)


def queue_summary(queue_dir: Path) -> dict[str, Any]:
    """Counts for the settings card: waiting and failed messages."""
    waiting = len(list(queue_dir.glob(f"*{QUEUE_SUFFIX}"))) if queue_dir.is_dir() else 0
    failed_dir = queue_dir / FAILED_DIR
    failed = len(list(failed_dir.glob(f"*{QUEUE_SUFFIX}"))) if failed_dir.is_dir() else 0
    return {"waiting": waiting, "failed": failed}


def process_queue(
    queue_dir: Path,
    settings: SmtpSettings,
    key: InstallationKey | None,
    *,
    now: datetime | None = None,
    limit: int = 50,
) -> QueueResult:
    """One pass over the queue: send what is due, schedule retries, give up
    on messages older than a day. Safe to call every minute."""
    result = QueueResult()
    if not queue_dir.is_dir():
        return result
    now = now or utcnow()
    for message in sorted(queue_dir.glob(f"*{QUEUE_SUFFIX}"))[:limit]:
        state = _read_state(message)
        if state.next_attempt_at and datetime.fromisoformat(state.next_attempt_at) > now:
            continue
        try:
            raw = message.read_bytes()
        except OSError as e:
            log.warning("Mail queue: cannot read %s: %s", message.name, e)
            continue
        try:
            msg = BytesParser(policy=policy.SMTP).parsebytes(raw)
            assert isinstance(msg, EmailMessage)
            state.recipients = _recipients(msg)
            send(settings, key, msg)
        except MailError as e:
            error = str(e)
        except Exception as e:  # a malformed file must not stop the queue
            error = f"could not parse the message: {e}"
        else:
            message.unlink(missing_ok=True)
            _state_path(message).unlink(missing_ok=True)
            result.sent.append(message.name)
            log.info("Mail queue: sent %s to %s", message.name, ", ".join(state.recipients))
            continue
        state.attempts += 1
        state.last_error = error
        first = datetime.fromisoformat(state.first_attempt_at) if state.first_attempt_at else now
        state.first_attempt_at = first.isoformat()
        if now - first >= GIVE_UP_AFTER:
            failed_dir = queue_dir / FAILED_DIR
            failed_dir.mkdir(exist_ok=True)
            _write_state(message, state)
            os.replace(message, failed_dir / message.name)
            os.replace(_state_path(message), failed_dir / _state_path(message).name)
            result.failed.append((message.name, error))
            log.error(
                "Mail queue: giving up on %s after %d attempts: %s",
                message.name,
                state.attempts,
                error,
            )
            continue
        state.next_attempt_at = (now + retry_delay(state.attempts)).isoformat()
        _write_state(message, state)
        result.retried.append(message.name)
        log.warning(
            "Mail queue: %s not sent (attempt %d): %s; next try at %s",
            message.name,
            state.attempts,
            error,
            state.next_attempt_at,
        )
    return result
