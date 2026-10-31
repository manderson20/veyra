# SPDX-License-Identifier: AGPL-3.0-or-later
"""SRTP per device profile (issue #49)."""

from __future__ import annotations

from types import SimpleNamespace

from veyra.provisioning import srtp
from veyra.telephony.asterisk import generator

TLS = SimpleNamespace(tls_enabled=True)
NO_TLS = SimpleNamespace(tls_enabled=False)
ON = {"sip_transport": "TLS", "srtp": "required"}


def test_srtp_counts_only_on_tls():
    assert srtp.effective(ON, TLS) == "required" and srtp.problem(ON, TLS) is None
    assert srtp.effective(ON, NO_TLS) == "off" and "off in Telephony" in srtp.problem(ON, NO_TLS)
    plain = {"sip_transport": "UDPOnly", "srtp": "optional"}
    assert srtp.effective(plain, TLS) == "off" and "needs the TLS" in srtp.problem(plain, TLS)
    assert srtp.effective({}, TLS) == "off" and srtp.problem({}, TLS) is None
    assert srtp.requested({"srtp": "nonsense"}) == "off"


def test_a_shared_extension_never_loses_a_phone():
    assert srtp.for_extension([]) == "off"
    assert srtp.for_extension(["off", "off"]) == "off"
    assert srtp.for_extension(["required", "required"]) == "required"
    assert srtp.for_extension(["required", "off"]) == "optional"
    assert srtp.for_extension(["optional", "required"]) == "optional"


def _endpoint(mode):
    from veyra.telephony.settings import SipSettings

    ext = {"endpoint_name": "x1001", "number": "1001", "secret": "s", "organization": "main"}
    if mode:
        ext["srtp"] = mode
    return generator._endpoints(SipSettings(), [ext]).content


def test_endpoint_settings():
    assert "media_encryption" not in _endpoint(None)
    assert "media_encryption" not in _endpoint("off")
    assert "media_encryption=sdes\nmedia_encryption_optimistic=no" in _endpoint("required")
    assert "media_encryption=sdes\nmedia_encryption_optimistic=yes" in _endpoint("optional")


def _tls(admin, on):
    s = admin.get("/api/v1/telephony/settings").json()["settings"]
    return admin.put("/api/v1/telephony/settings", json={**s, "tls_enabled": on})


def _profile(admin, org, name, template, **values):
    return admin.post(
        "/api/v1/device-profiles",
        json={"organization_id": org, "name": name, "template_key": template, "values": values},
    )


def _phone(admin, org, mac, model, maker, profile, ext):
    r = admin.post(
        "/api/v1/devices",
        json={
            "organization_id": org,
            "mac_address": mac,
            "manufacturer": maker,
            "model": model,
            "profile_id": profile,
            "primary_extension_id": ext,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _files(admin, device):
    r = admin.get(f"/api/v1/devices/{device['id']}/preview")
    assert r.status_code == 200, r.text
    return "\n".join(f["content"] for f in r.json()["files"])


def test_profiles_devices_files_and_engine(admin, app):
    from veyra.core.db import session_scope
    from veyra.core.security.crypto import load_installation_key
    from veyra.telephony.snapshot import build_snapshot

    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    ext = {}
    for number in ("1001", "1002", "1003"):
        r = admin.post(
            "/api/v1/extensions",
            json={"organization_id": org, "number": number, "display_name": number},
        )
        assert r.status_code == 201, r.text
        ext[number] = r.json()["id"]
    wanted = {"sip_transport": "TLS", "srtp": "required"}
    # TLS off, or another transport: refused rather than quietly unencrypted.
    r = _profile(admin, org, "A", "poly.vvx.base", **wanted)
    assert r.status_code == 422 and "off in Telephony" in r.text
    assert _tls(admin, True).status_code == 200
    r = _profile(admin, org, "A", "poly.vvx.base", sip_transport="UDPOnly", srtp="required")
    assert r.status_code == 422 and "needs the TLS" in r.text
    poly = _profile(admin, org, "Poly", "poly.vvx.base", **wanted)
    assert poly.status_code == 201, poly.text
    yea = _profile(admin, org, "Yealink", "yealink.base", **wanted)
    assert yea.status_code == 201, yea.text
    plain = _profile(admin, org, "Plain", "yealink.base")
    assert plain.status_code == 201, plain.text
    a = _phone(admin, org, "00:04:F2:00:00:01", "VVX 411", "Poly", poly.json()["id"], ext["1001"])
    text = _files(admin, a)
    assert 'sec.srtp.require="1"' in text and 'transport="TLS"' in text
    b = _phone(admin, org, "80:5E:C0:00:00:02", "T46U", "Yealink", yea.json()["id"], ext["1002"])
    assert "srtp_encryption = 2" in _files(admin, b)
    # One phone that does not encrypt keeps a shared extension reachable.
    _phone(admin, org, "80:5E:C0:00:00:03", "T46U", "Yealink", yea.json()["id"], ext["1003"])
    c = _phone(admin, org, "80:5E:C0:00:00:04", "T46U", "Yealink", plain.json()["id"], ext["1003"])
    assert "srtp_encryption = 0" in _files(admin, c)
    with session_scope() as db:
        snap = build_snapshot(db, load_installation_key(app.state.settings))
    modes = {e["number"]: e["srtp"] for e in snap["extensions"]}
    assert modes == {"1001": "required", "1002": "required", "1003": "optional"}
    # TLS cannot be turned off under them.
    r = _tls(admin, False)
    assert r.status_code == 422 and "Poly" in r.text
    # A device's own override is checked with its profile's values.
    r = admin.patch(f"/api/v1/devices/{c['id']}", json={"values": {"srtp": "required"}})
    assert r.status_code == 422 and "needs the TLS" in r.text
