# SPDX-License-Identifier: AGPL-3.0-or-later
"""Companion deployment metadata: info for the account page and the update
manifest that managed browsers poll (docs/COMPANION.md §5)."""

import json

from test_api_companion import _bearer, _companion_login, _make_user


def test_info_and_update_manifest(admin, app, tmp_path):
    app.state.settings.companion_dir = tmp_path
    # nothing packaged yet
    r = admin.get("/api/v1/companion/info")
    assert r.status_code == 200 and r.json()["available"] is False
    assert admin.get("/api/v1/companion/update.xml").status_code == 404
    # a zip without a signed package
    (tmp_path / "veyra-companion.zip").write_bytes(b"PK")
    info = admin.get("/api/v1/companion/info").json()
    assert info["available"] and info["zip_url"] == "/downloads/veyra-companion.zip"
    assert info["crx_url"] is None and info["extension_id"] is None
    # the installer's crx-info.json makes it a managed-deployable package
    (tmp_path / "crx-info.json").write_text(
        json.dumps({"id": "a" * 32, "version": "0.8.1", "name": "Veyra Companion"})
    )
    info = admin.get(
        "/api/v1/companion/info",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "pbx.example.org"},
    ).json()
    assert info["extension_id"] == "a" * 32 and info["version"] == "0.8.1"
    assert info["crx_url"] == "/downloads/veyra-companion.crx"
    assert info["update_url"] == "https://pbx.example.org/api/v1/companion/update.xml"
    assert info["install_sources_pattern"] == "https://pbx.example.org/*"
    # the update manifest is public and names the id, version and package URL
    anon = app  # not needed; use a fresh client without cookies
    from fastapi.testclient import TestClient

    c = TestClient(app, base_url="http://veyra.test")
    r = c.get(
        "/api/v1/companion/update.xml",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "pbx.example.org"},
    )
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert 'appid="' + "a" * 32 + '"' in r.text
    assert 'codebase="https://pbx.example.org/downloads/veyra-companion.crx"' in r.text
    assert 'version="0.8.1"' in r.text
    assert anon is app


def test_rollout_reports_certificate_trust_and_sign_ins(admin, app, tmp_path):
    app.state.settings.companion_dir = tmp_path
    app.state.acme_dir = tmp_path
    host = {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "pbx.example.org"}
    r = admin.get("/api/v1/companion/rollout", headers=host)
    assert r.status_code == 200, r.text
    body = r.json()
    # no public certificate: browsers need the Veyra CA pushed to them
    assert body["host"] == "pbx.example.org" and body["certificate"]["kind"] == "veyra"
    assert body["ca_url"] == "/downloads/veyra-ca.crt"
    assert body["adoption"] == {"users": 0, "active_7d": 0, "recent": []}
    # a Let's Encrypt certificate for another name does not count; a wildcard does
    (tmp_path / "certificate.json").write_text(
        json.dumps({"names": ["other.example.org"], "not_after": "2027-01-01T00:00:00+00:00"})
    )
    assert (
        admin.get("/api/v1/companion/rollout", headers=host).json()["certificate"]["kind"]
        == "veyra"
    )
    (tmp_path / "certificate.json").write_text(
        json.dumps({"names": ["*.example.org"], "issuer": "C=US, O=Let's Encrypt, CN=R11"})
    )
    cert = admin.get("/api/v1/companion/rollout", headers=host).json()["certificate"]
    assert cert["kind"] == "public" and "Let's Encrypt" in cert["issuer"]
    # a Companion sign-in shows up once it has been used
    _make_user(admin, "teacher@example.org")
    token = _companion_login(app, "teacher@example.org", device="Chromebook").json()["token"]
    assert _bearer(app, token).get("/api/v1/companion/info").status_code == 200
    adoption = admin.get("/api/v1/companion/rollout", headers=host).json()["adoption"]
    assert adoption["users"] == 1 and adoption["active_7d"] == 1
    assert adoption["recent"][0]["email"] == "teacher@example.org"
    assert adoption["recent"][0]["device"] == "Chromebook"
    # only platform administrators
    staff = _bearer(app, token)
    assert staff.get("/api/v1/companion/rollout").status_code == 403
