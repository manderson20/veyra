# SPDX-License-Identifier: AGPL-3.0-or-later
"""Installation key rotation (docs/PRODUCTION_HARDENING.md §3.1): the
registry of every ciphertext bound to the installation key, a check that
all of them decrypt, and the re-encryption with a new key in one
transaction. A new purpose is added here, or ``test_rotation_registry``
fails when it finds an encrypted column the registry does not know.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from veyra.core.models import (
    Calendar,
    ConfigRevision,
    Device,
    Extension,
    FirewallFeed,
    IdentityProvider,
    MfaMethod,
    ModuleConfig,
    Organization,
    SipTrunk,
    SystemSetting,
    VoicemailBox,
    Webhook,
)
from veyra.core.security.crypto import DecryptionError, InstallationKey, is_encrypted_token


@dataclass
class Cipher:
    """One ciphertext: where it is, its purpose, how to replace it."""

    label: str
    purpose: str
    value: str
    replace: Callable[[str], None]


def _column(
    db: Session, model: Any, attr: str, purpose: Callable[[Any], str], label: str
) -> Iterator[Cipher]:
    row: Any
    for row in db.scalars(select(model)):
        value = getattr(row, attr)
        if not value:
            continue

        def put(new: str, row: Any = row) -> None:
            setattr(row, attr, new)

        yield Cipher(f"{label} {row.id}", purpose(row), value, put)


def _setting(db: Session, key: str, field: str, purpose: str) -> Iterator[Cipher]:
    row = db.get(SystemSetting, key)
    if row is None or not isinstance(row.value, dict) or not row.value.get(field):
        return

    def put(new: str, row: SystemSetting = row) -> None:
        value = dict(row.value)
        value[field] = new
        row.value = value
        flag_modified(row, "value")

    yield Cipher(f"setting {key}.{field}", purpose, str(row.value[field]), put)


def ciphers(db: Session) -> Iterator[Cipher]:
    """Every ciphertext bound to the installation key."""
    from veyra.api.v1.enrollment import device_purpose, enrollment_purpose
    from veyra.bells import calendars
    from veyra.central import protocol
    from veyra.configmgmt.revisions import artifact_purpose
    from veyra.core import mail
    from veyra.core.security import mfa
    from veyra.ha import service as ha_service
    from veyra.integrations import sso, webhooks
    from veyra.telephony.snapshot import pin_purpose, secret_purpose, trunk_secret_purpose
    from veyra.updates import manager as updates

    yield from _column(
        db, Extension, "sip_secret_ciphertext", lambda r: secret_purpose(r.id), "extension"
    )
    yield from _column(
        db, SipTrunk, "password_ciphertext", lambda r: trunk_secret_purpose(r.id), "trunk"
    )
    yield from _column(
        db, VoicemailBox, "pin_ciphertext", lambda r: pin_purpose(r.id), "voicemail box"
    )
    yield from _column(
        db, MfaMethod, "secret_ciphertext", lambda r: mfa.secret_purpose(r.user_id), "MFA method"
    )
    yield from _column(
        db,
        Organization,
        "provisioning_secret_ciphertext",
        lambda r: enrollment_purpose(r.id),
        "organization",
    )
    yield from _column(
        db, Device, "provisioning_secret_ciphertext", lambda r: device_purpose(r.id), "device"
    )
    yield from _column(
        db, Calendar, "url_ciphertext", lambda r: calendars.url_purpose(r.id), "calendar"
    )
    yield from _column(
        db, FirewallFeed, "key_ciphertext", lambda r: f"firewall.feed:{r.id}", "firewall feed"
    )
    yield from _column(
        db, IdentityProvider, "client_secret_enc", lambda r: sso.SECRET_PURPOSE, "identity provider"
    )
    yield from _column(db, Webhook, "secret_enc", lambda r: webhooks.SECRET_PURPOSE, "webhook")
    yield from _column(
        db, Webhook, "previous_secret_enc", lambda r: webhooks.SECRET_PURPOSE, "webhook previous"
    )
    # Revision artifacts: the sensitive files of every configuration revision.
    for rev in db.scalars(select(ConfigRevision)):
        files = (rev.artifacts or {}).get("files") or []
        for i, f in enumerate(files):
            if not isinstance(f, dict) or not f.get("ciphertext"):
                continue

            def put_artifact(new: str, rev: ConfigRevision = rev, i: int = i) -> None:
                doc = dict(rev.artifacts)
                items = [dict(x) for x in doc["files"]]
                items[i]["ciphertext"] = new
                doc["files"] = items
                rev.artifacts = doc
                flag_modified(rev, "artifacts")

            yield Cipher(
                f"revision {rev.sequence} {f.get('path')}",
                artifact_purpose(rev.id, str(f.get("path"))),
                str(f["ciphertext"]),
                put_artifact,
            )
    # Module configuration: secret fields are the encrypted strings.
    for mod in db.scalars(select(ModuleConfig)):
        for k, v in (mod.config or {}).items():
            if isinstance(v, str) and is_encrypted_token(v):

                def put_module(new: str, mod: ModuleConfig = mod, k: str = k) -> None:
                    cfg = dict(mod.config)
                    cfg[k] = new
                    mod.config = cfg
                    flag_modified(mod, "config")

                yield Cipher(
                    f"module {mod.module_id} {k}", f"module:{mod.module_id}", v, put_module
                )
    yield from _setting(db, "central.console", "private_key", protocol.KEY_PURPOSE)
    yield from _setting(db, "central.membership", "private_key", protocol.KEY_PURPOSE)
    yield from _setting(db, ha_service.FENCING_KEY, "secret", ha_service.FENCING_PURPOSE)
    yield from _setting(
        db, mail.SMTP_SETTINGS_KEY, "password_ciphertext", mail.SMTP_PASSWORD_PURPOSE
    )
    yield from _setting(db, updates.SOURCE_KEY, "token", updates.TOKEN_PURPOSE)


@dataclass
class Report:
    total: int = 0
    unreadable: list[str] | None = None

    @property
    def ok(self) -> bool:
        return not self.unreadable


def check(db: Session, key: InstallationKey) -> Report:
    """Every ciphertext decrypts with ``key``."""
    report = Report(0, [])
    for c in ciphers(db):
        report.total += 1
        try:
            key.decrypt(c.value, c.purpose)
        except DecryptionError:
            report.unreadable.append(c.label)  # type: ignore[union-attr]
    return report


def rotate(db: Session, old: InstallationKey, new: InstallationKey) -> int:
    """Re-encrypt everything from ``old`` to ``new`` (the caller commits).
    Raises DecryptionError on the first ciphertext ``old`` cannot read, so a
    half-rotated database never happens."""
    n = 0
    for c in ciphers(db):
        try:
            plain = old.decrypt(c.value, c.purpose)
        except DecryptionError:
            # Already rotated (a retry after a crash between the file swap
            # and the commit): the new key reads it.
            new.decrypt(c.value, c.purpose)
            continue
        c.replace(new.encrypt(plain, c.purpose))
        n += 1
    db.flush()
    return n
