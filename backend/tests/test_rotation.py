# SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: SIM115
"""Installation key rotation (docs/PRODUCTION_HARDENING.md §3.1): the
registry covers every encrypted column, and a rotation re-encrypts
everything so the old key reads nothing and the new key reads all."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect

from veyra.core import models
from veyra.core.db import session_scope
from veyra.core.models import ConfigRevision, Extension, ModuleConfig, SystemSetting
from veyra.core.security import rotation
from veyra.core.security.crypto import DecryptionError, InstallationKey, load_installation_key

ENCRYPTED_COLUMN_SUFFIXES = ("_ciphertext", "_enc")


def test_registry_knows_every_encrypted_column():
    """A new ``*_ciphertext`` or ``*_enc`` column must be added to the registry."""
    import veyra.core.security.rotation as mod

    source = open(mod.__file__).read()
    missing = []
    for name in dir(models):
        cls = getattr(models, name)
        if not hasattr(cls, "__table__"):
            continue
        for col in inspect(cls).columns:
            if col.key.endswith(ENCRYPTED_COLUMN_SUFFIXES) and f'"{col.key}"' not in source:
                missing.append(f"{cls.__name__}.{col.key}")
    assert missing == []


def test_rotation_round_trip(admin, app):
    settings = app.state.settings
    old = load_installation_key(settings)
    # An extension with a SIP secret through the API, plus a revision artifact,
    # a module secret and a setting written directly.
    from veyra.core.models import Organization

    with session_scope() as db:
        org_id = str(db.query(Organization).first().id)
    r = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org_id, "number": "2201", "display_name": "Rotate Me"},
    )
    assert r.status_code == 201, r.text
    ext_id = r.json()["id"]
    with session_scope() as db:
        rev = ConfigRevision(
            id=uuid.uuid4(),
            engine="asterisk",
            state="deployed",
            created_by="test",
            artifacts={
                "files": [
                    {"path": "plain.conf", "content": "x", "sensitive": False},
                    {
                        "path": "pjsip.auth.conf",
                        "sensitive": True,
                        "ciphertext": old.encrypt(
                            "secret=abc", "revision-artifact:{rev}:pjsip.auth.conf"
                        ),
                    },
                ]
            },
        )
        # Use the real purpose function so the registry's purpose matches.
        from veyra.configmgmt.revisions import artifact_purpose

        rev.artifacts["files"][1]["ciphertext"] = old.encrypt(
            "secret=abc", artifact_purpose(rev.id, "pjsip.auth.conf")
        )
        db.add(rev)
        db.add(
            ModuleConfig(
                module_id="veyra.example-and",
                organization_id=None,
                config={"api_key": old.encrypt("k", "module:veyra.example-and"), "plain": 1},
            )
        )
        db.add(
            SystemSetting(
                key="notifications.smtp",
                value={"host": "h", "password_ciphertext": old.encrypt("pw", "smtp.password")},
            )
        )
        db.flush()
        report = rotation.check(db, old)
        assert report.ok and report.total >= 4
        new = InstallationKey.generate()
        n = rotation.rotate(db, old, new)
        assert n == report.total
        assert rotation.check(db, new).ok
        assert not rotation.check(db, old).ok
        ext = db.get(Extension, uuid.UUID(ext_id))
        from veyra.telephony.snapshot import secret_purpose

        new.decrypt(ext.sip_secret_ciphertext, secret_purpose(ext.id))
        with pytest.raises(DecryptionError):
            old.decrypt(ext.sip_secret_ciphertext, secret_purpose(ext.id))
        # A retry after a crash: everything already rotated is left alone.
        assert rotation.rotate(db, old, new) == 0
        db.rollback()
