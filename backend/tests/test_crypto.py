# SPDX-License-Identifier: AGPL-3.0-or-later
"""Installation key: storage, encryption round trip, tamper and misuse detection."""

import os
import stat

import pytest

from veyra.core.config import Settings
from veyra.core.security import crypto
from veyra.core.security.crypto import (
    DecryptionError,
    InstallationKey,
    InstallationKeyError,
    load_installation_key,
)


def test_round_trip_is_bound_to_the_purpose():
    key = InstallationKey.generate()
    token = key.encrypt("s3cret", "extension.sip_secret:1")
    assert token.startswith("v1:") and "s3cret" not in token
    assert key.decrypt(token, "extension.sip_secret:1") == "s3cret"
    with pytest.raises(DecryptionError):
        key.decrypt(token, "extension.sip_secret:2")
    # every encryption uses a fresh nonce
    assert key.encrypt("s3cret", "p") != key.encrypt("s3cret", "p")
    assert crypto.is_encrypted_token(token) and not crypto.is_encrypted_token("plain")


def test_other_key_tampering_and_malformed_tokens_are_rejected():
    key, other = InstallationKey.generate(), InstallationKey.generate()
    token = key.encrypt("value", "p")
    with pytest.raises(DecryptionError):
        other.decrypt(token, "p")
    body = token[3:]
    flipped = body[:-6] + ("A" if body[-6] != "A" else "B") + body[-5:]
    with pytest.raises(DecryptionError):
        key.decrypt("v1:" + flipped, "p")
    for bad in ("", "v2:abc", "v1:", "v1:!!!", "v1:AAAA", token.replace("v1:", "")):
        with pytest.raises(DecryptionError):
            key.decrypt(bad, "p")


def test_key_file_format_mode_and_refusal_to_overwrite(tmp_path):
    path = tmp_path / "secrets" / "installation.key"
    key = InstallationKey.generate()
    key.write(path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o640
    text = path.read_text()
    assert len(text.strip()) == 64 and text.endswith("\n")
    assert InstallationKey.load(path).fingerprint == key.fingerprint
    with pytest.raises(InstallationKeyError, match="already exists"):
        InstallationKey.generate().write(path)
    InstallationKey.generate().write(path, overwrite=True)
    assert InstallationKey.load(path).fingerprint != key.fingerprint
    # upper-case hex and surrounding whitespace are accepted; anything else is not
    path.write_text("  " + key.hex.upper() + "\n\n")
    assert InstallationKey.load(path).fingerprint == key.fingerprint
    for bad in ("", "abc", "zz" * 32, key.hex[:-1]):
        path.write_text(bad)
        with pytest.raises(InstallationKeyError, match="64 hexadecimal"):
            InstallationKey.load(path)
    with pytest.raises(InstallationKeyError, match="does not exist"):
        InstallationKey.load(tmp_path / "nope")
    with pytest.raises(InstallationKeyError):
        InstallationKey(b"short")


def test_load_installation_key_follows_the_file(tmp_path):
    settings = Settings(
        database_url="postgresql+psycopg://x", config_dir=tmp_path, environment="test"
    )
    assert settings.installation_key_path == tmp_path / "secrets" / "installation.key"
    with pytest.raises(InstallationKeyError, match="does not exist"):
        load_installation_key(settings)
    assert crypto.try_load_installation_key(settings) is None
    first = InstallationKey.generate()
    first.write(settings.installation_key_path)
    assert load_installation_key(settings).fingerprint == first.fingerprint
    assert load_installation_key(settings) is load_installation_key(settings)  # cached
    second = InstallationKey.generate()
    second.write(settings.installation_key_path, overwrite=True)
    os.utime(settings.installation_key_path, ns=(1, 1))  # force a visible change
    assert load_installation_key(settings).fingerprint == second.fingerprint
    explicit = Settings(
        database_url="postgresql+psycopg://x",
        installation_key_file=tmp_path / "elsewhere.key",
        environment="test",
    )
    assert explicit.installation_key_path == tmp_path / "elsewhere.key"
