# SPDX-License-Identifier: AGPL-3.0-or-later
"""Email delivery: SMTP settings, sending through a fake smtplib, and the
file queue with retries and give-up."""

from datetime import timedelta

import pytest

from veyra.core import mail
from veyra.core.models.base import utcnow
from veyra.core.security.crypto import InstallationKey


class FakeSmtp:
    """Stands in for smtplib.SMTP / SMTP_SSL; records what was done."""

    instances: list["FakeSmtp"] = []
    fail_login = False
    fail_connect = False

    def __init__(self, host, port, timeout=None, context=None):
        if FakeSmtp.fail_connect:
            raise OSError("connection refused")
        self.host, self.port, self.ssl = host, port, context is not None
        self.started_tls = False
        self.login_args = None
        self.sent: list[tuple[str, list[str]]] = []
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo_or_helo_if_needed(self):
        pass

    def ehlo(self):
        pass

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, password):
        import smtplib

        if FakeSmtp.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.login_args = (user, password)

    def send_message(self, msg, from_addr=None, to_addrs=None):
        self.sent.append((from_addr, list(to_addrs or [])))


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSmtp.instances = []
    FakeSmtp.fail_login = False
    FakeSmtp.fail_connect = False
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSmtp)
    return FakeSmtp


def _settings(**over):
    values = {
        "enabled": True,
        "host": "smtp.example.org",
        "port": 587,
        "security": "starttls",
        "username": None,
        "from_address": "pbx@example.org",
        "from_name": "Test PBX",
    }
    values.update(over)
    return mail.SmtpSettings(**values)


def _msg(to="user@example.org"):
    return mail.compose(
        from_address="pbx@example.org", from_name="Test PBX", to=to, subject="Hi", text="Body"
    )


def test_settings_validation_and_problems():
    s = _settings(security="none", host="relay.example.org")
    assert s.problems() == [
        "Unencrypted delivery (security 'none') is only allowed to a loopback relay."
    ]
    assert _settings(security="none", host="127.0.0.1").problems() == []
    assert _settings(security="none", host="localhost").problems() == []
    assert _settings(enabled=True, host="").problems() == ["Enter the SMTP server host name."]
    assert _settings(username="u").problems() == ["Enter the password for the SMTP user name."]
    with pytest.raises(ValueError):
        _settings(from_address="not an address")
    with pytest.raises(ValueError):
        _settings(host="bad host name")
    assert mail.sender(mail.SmtpSettings(), "District")[1] == "District"
    assert mail.sender(mail.SmtpSettings(), "District")[0].startswith("veyra@")


def test_send_uses_starttls_login_and_password_from_the_key(fake_smtp):
    key = InstallationKey.generate()
    s = _settings(
        username="mailer", password_ciphertext=key.encrypt("pa55", mail.SMTP_PASSWORD_PURPOSE)
    )
    msg = _msg()
    msg["Cc"] = "second@example.org"
    msg["Bcc"] = "hidden@example.org"
    recipients = mail.send(s, key, msg)
    assert recipients == ["user@example.org", "second@example.org", "hidden@example.org"]
    conn = fake_smtp.instances[-1]
    assert conn.started_tls and not conn.ssl and conn.login_args == ("mailer", "pa55")
    assert conn.sent == [("pbx@example.org", recipients)]
    assert "Bcc" not in msg
    # implicit TLS uses SMTP_SSL and no STARTTLS
    mail.send(_settings(security="tls", port=465), None, _msg())
    assert fake_smtp.instances[-1].ssl and not fake_smtp.instances[-1].started_tls


def test_send_errors_are_reported_as_mail_errors(fake_smtp):
    with pytest.raises(mail.MailError, match="not enabled"):
        mail.send(_settings(enabled=False), None, _msg())
    with pytest.raises(mail.MailError, match="host name"):
        mail.send(_settings(host=""), None, _msg())
    with pytest.raises(mail.MailError, match="no recipient"):
        msg = _msg()
        del msg["To"]
        mail.send(_settings(), None, msg)
    with pytest.raises(mail.MailError, match="installation key is missing"):
        mail.send(_settings(password_ciphertext="x"), None, _msg())
    key = InstallationKey.generate()
    with pytest.raises(mail.MailError, match="cannot be read"):
        mail.send(_settings(password_ciphertext="garbage"), key, _msg())
    fake_smtp.fail_login = True
    s = _settings(
        username="mailer", password_ciphertext=key.encrypt("p", mail.SMTP_PASSWORD_PURPOSE)
    )
    with pytest.raises(mail.MailError, match="rejected the user name or password"):
        mail.send(s, key, _msg())
    fake_smtp.fail_login = False
    fake_smtp.fail_connect = True
    with pytest.raises(mail.MailError, match=r"could not send through smtp\.example\.org:587"):
        mail.send(_settings(), None, _msg())


def test_queue_sends_retries_and_gives_up(fake_smtp, tmp_path):
    q = tmp_path / "mailqueue"
    s = _settings()
    path = mail.enqueue(q, _msg().as_bytes())
    assert path.suffix == ".eml" and not list(q.glob(".*tmp"))
    assert mail.queue_summary(q) == {"waiting": 1, "failed": 0}
    # a file that is not a message is retried, not fatal
    bad = q / "20260101T000000-bad.eml"
    bad.write_bytes(b"")
    now = utcnow()
    fake_smtp.fail_connect = True
    r = mail.process_queue(q, s, None, now=now)
    assert r.sent == [] and sorted(r.retried) == sorted([path.name, bad.name])
    state = mail._read_state(path)
    assert state.attempts == 1 and "connection refused" in (state.last_error or "")
    assert state.next_attempt_at is not None and state.recipients == ["user@example.org"]
    # not due yet: skipped
    fake_smtp.fail_connect = False
    r = mail.process_queue(q, s, None, now=now + timedelta(seconds=30))
    assert r.sent == [] and r.retried == []
    # due: sent and removed, with its state file
    r = mail.process_queue(q, s, None, now=now + timedelta(minutes=2))
    assert path.name in r.sent and not path.exists() and not mail._state_path(path).exists()
    assert fake_smtp.instances[-1].sent[0][1] == ["user@example.org"]
    # the empty file keeps failing: retry delays grow and it is given up after a day
    assert mail.retry_delay(1) == timedelta(minutes=1)
    assert mail.retry_delay(2) == timedelta(minutes=5)
    assert mail.retry_delay(9) == timedelta(minutes=60)
    r = mail.process_queue(q, s, None, now=now + timedelta(hours=25))
    assert r.failed and r.failed[0][0] == bad.name
    assert (q / mail.FAILED_DIR / bad.name).exists() and not bad.exists()
    assert mail.queue_summary(q) == {"waiting": 0, "failed": 1}
    # a missing queue directory is fine
    assert mail.process_queue(tmp_path / "nope", s, None).sent == []


def test_voicemail_reference_is_stripped_and_returned(fake_smtp, tmp_path, monkeypatch):
    """Issue #148: the body's marker and the queue's header never leave the
    server; a sent notification returns its message reference."""
    sent: list[bytes] = []
    monkeypatch.setattr(FakeSmtp, "send_message", lambda self, m, **kw: sent.append(m.as_bytes()))
    q = tmp_path / "mailqueue"
    raw = (
        b"X-Veyra-Voicemail: context=veyra; mailbox=1001; msg_id=1760800000-00000001\n"
        + _msg().as_bytes()
        + b"\n\n[veyra-vm:/var/spool/asterisk/voicemail/veyra/1001/INBOX/msg0000]\n"
    )
    mail.enqueue(q, raw)
    plain = mail.enqueue(q, _msg().as_bytes())
    r = mail.process_queue(q, _settings(), None)
    assert len(r.sent) == 2 and len(r.voicemail) == 1 and r.voicemail[0][0] != plain.name
    assert mail.parse_voicemail_ref(r.voicemail[0][1]) == {
        "context": "veyra",
        "mailbox": "1001",
        "msg_id": "1760800000-00000001",
    }
    assert all(b"veyra-vm" not in m and b"X-Veyra-Voicemail" not in m for m in sent)
    # a failed send returns no reference: the message stays in the box
    mail.enqueue(q, raw)
    fake_smtp.fail_connect = True
    r = mail.process_queue(q, _settings(), None)
    assert r.voicemail == [] and len(r.retried) == 1
