# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from datetime import UTC, datetime, timedelta

import pytest

from veyra.core.signing import (
    Keyring,
    TrustedKey,
    TrustLevel,
    generate_keypair,
    load_public_key,
    sign,
)
from veyra.updates.metadata import MetadataError, verify_metadata
from veyra.updates.policy import Component, Mode, PolicyUpdate, availability_problem

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def metadata(**overrides) -> bytes:
    doc = {
        "schema_version": 1,
        "sequence": 5,
        "generated_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=7)).isoformat(),
        "releases": [
            {
                "component": "veyra_core",
                "target": "veyra",
                "version": "0.2.0",
                "channel": "stable",
                "category": "feature",
            }
        ],
    }
    doc.update(overrides)
    return json.dumps(doc).encode()


def keyring(level=TrustLevel.OFFICIAL):
    priv, pub = generate_keypair()
    return Keyring([TrustedKey("release-key", level, load_public_key(pub))]), priv


def test_valid_metadata():
    kr, priv = keyring()
    body = metadata()
    meta = verify_metadata(body, sign(body, priv, "release-key"), kr, now=NOW)
    assert meta.releases[0].version == "0.2.0"


def test_tampered_metadata_rejected():
    kr, priv = keyring()
    sig = sign(metadata(), priv, "release-key")
    with pytest.raises(MetadataError, match="signature"):
        verify_metadata(metadata(sequence=6), sig, kr, now=NOW)


def test_expired_metadata_rejected():
    kr, priv = keyring()
    body = metadata(expires_at=(NOW - timedelta(seconds=1)).isoformat())
    with pytest.raises(MetadataError, match="expired"):
        verify_metadata(body, sign(body, priv, "release-key"), kr, now=NOW)


def test_rollback_rejected():
    kr, priv = keyring()
    body = metadata()
    with pytest.raises(MetadataError, match="older"):
        verify_metadata(body, sign(body, priv, "release-key"), kr, last_sequence=6, now=NOW)


def test_non_official_key_rejected():
    kr, priv = keyring(TrustLevel.COMMUNITY)
    body = metadata()
    with pytest.raises(MetadataError, match="official"):
        verify_metadata(body, sign(body, priv, "release-key"), kr, now=NOW)


def test_policy_rules():
    with pytest.raises(ValueError):
        PolicyUpdate(mode=Mode.AUTO_INSTALL_WINDOW)  # needs a maintenance window
    with pytest.raises(ValueError):
        PolicyUpdate(mode=Mode.NOTIFY, auto_install_categories=["security"])
    ok = PolicyUpdate(mode=Mode.NOTIFY)
    assert availability_problem(Component.VEYRA_CORE, ok) is None
    auto = PolicyUpdate(
        mode=Mode.AUTO_INSTALL_WINDOW,
        auto_install_categories=["security"],
        maintenance_window={
            "days": ["sun"],
            "start": "02:00",
            "duration_minutes": 120,
            "timezone": "America/Chicago",
        },
    )
    assert availability_problem(Component.VEYRA_CORE, auto) is not None
    assert availability_problem(Component.OPERATING_SYSTEM, ok) is not None
