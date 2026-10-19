# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone trust (docs/FIREWALL_TRUST.md §6): the plain-HTTP bootstrap carries
only the Veyra CA and the HTTPS address, is limited to the bootstrap
networks, and is refused once a phone has provisioned over HTTPS."""

import base64
from xml.etree import ElementTree

from fastapi.testclient import TestClient
from test_provisioning_devices import PROV, _setup

from veyra.core.db import session_scope
from veyra.firewall.settings import FirewallSettings, save_settings
from veyra.provisioning import bootstrap
from veyra.telephony.settings import SipSettings, save_sip_settings

CA = "-----BEGIN CERTIFICATE-----\nMIIBfakeCA\nlinetwo\n-----END CERTIFICATE-----\n"
UA = {"User-Agent": "PolycomVVX-VVX_450-UA/6.4.5.1234", "X-Forwarded-For": "172.16.3.40"}


def test_poly_config_keeps_pem_newlines_and_optional_credential():
    xml = bootstrap.poly_config(CA, "veyra.example/provisioning/")
    assert "&#10;" in xml and "password" not in xml
    device = ElementTree.fromstring(xml).find("device")  # noqa: S314 (our own output)
    assert device is not None
    assert device.get("device.sec.TLS.customCaCert1") == CA
    assert device.get("device.prov.serverType") == bootstrap.POLY_HTTPS
    assert device.get("device.prov.serverName") == "veyra.example/provisioning/"
    with_cred = ElementTree.fromstring(  # noqa: S314 (our own output)
        bootstrap.poly_config(CA, "h/provisioning/", "veyra-example", 'p"w<d')
    ).find("device")
    assert with_cred is not None and with_cred.get("device.prov.password") == 'p"w<d'


def test_client_allowed():
    import ipaddress

    nets = [ipaddress.ip_network("172.16.0.0/21")]
    assert bootstrap.client_allowed("172.16.3.40", nets)
    assert bootstrap.client_allowed("::ffff:172.16.3.40", nets)
    assert not bootstrap.client_allowed("203.0.113.9", nets)
    assert not bootstrap.client_allowed(None, nets)


def _ca(app):
    path = app.state.settings.config_dir / bootstrap.CA_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CA)


def test_http_bootstrap_then_https_downgrade_protection(admin, app):
    org, _ext, _other, _zone, _profile, device = _setup(admin, app)
    with session_scope() as db:
        save_sip_settings(db, SipSettings(local_nets=["172.16.0.0/21"]))
    phone = TestClient(app, base_url="http://veyra.test")
    mac = device["mac_address"]
    # No CA yet: the bootstrap cannot be served.
    assert phone.get(f"{PROV}/{mac}.cfg", headers=UA).status_code == 503
    _ca(app)
    master = phone.get(f"{PROV}/{mac}.cfg", headers=UA)
    assert master.status_code == 200 and f"veyra-bootstrap-{mac}.cfg" in master.text
    cfg = phone.get(f"{PROV}/veyra-bootstrap-{mac}.cfg", headers=UA)
    assert cfg.status_code == 200
    assert "customCaCert1" in cfg.text and 'serverName="veyra.test/provisioning/"' in cfg.text
    assert "prov.password" not in cfg.text and "reg.1" not in cfg.text
    # Nothing else over HTTP, even with a valid credential.
    assert phone.get(f"{PROV}/{mac}-sip.cfg", headers=UA).status_code == 404
    # Outside the bootstrap networks: refused.
    outside = {**UA, "X-Forwarded-For": "203.0.113.9"}
    assert phone.get(f"{PROV}/{mac}.cfg", headers=outside).status_code == 403

    # The organization may carry the enrollment credential in the bootstrap.
    cred = admin.post(f"/api/v1/organizations/{org['id']}/provisioning-credential/rotate").json()
    r = admin.patch(
        f"/api/v1/organizations/{org['id']}", json={"bootstrap_includes_credential": True}
    )
    assert r.json()["bootstrap_includes_credential"] is True
    cfg = phone.get(f"{PROV}/veyra-bootstrap-{mac}.cfg", headers=UA).text
    assert f'device.prov.user="{cred["username"]}"' in cfg

    # Over HTTPS with the credential: the full files, then HTTP is refused.
    secure = TestClient(app, base_url="https://veyra.test")
    auth = base64.b64encode(f"{cred['username']}:{cred['password']}".encode()).decode()
    r = secure.get(f"{PROV}/{mac}.cfg", headers={**UA, "Authorization": f"Basic {auth}"})
    assert r.status_code == 200
    d = admin.get(f"/api/v1/devices/{device['id']}").json()
    assert d["https_seen_at"] and d["allow_bootstrap"] is False
    assert phone.get(f"{PROV}/{mac}.cfg", headers=UA).status_code == 403
    d = admin.post(f"/api/v1/devices/{device['id']}/allow-bootstrap").json()
    assert d["allow_bootstrap"] is True and d["https_seen_at"] is None
    assert phone.get(f"{PROV}/{mac}.cfg", headers=UA).status_code == 200


def test_unknown_poly_gets_bootstrap_without_credential_and_others_404(admin, app):
    _ca(app)
    with session_scope() as db:
        save_settings(db, FirewallSettings(bootstrap_networks=["172.16.3.0/24"]))
    phone = TestClient(app, base_url="http://veyra.test")
    assert phone.get(f"{PROV}/0004f2123456.cfg", headers=UA).status_code == 200
    grandstream = {**UA, "User-Agent": "Grandstream GRP2614 1.0.5.33"}
    assert phone.get(f"{PROV}/c074ad123456.cfg", headers=grandstream).status_code == 404


def test_yealink_bootstrap(admin, app):
    """Yealink phones get the CA and the HTTPS address over HTTP too (#116)."""
    _ca(app)
    with session_scope() as db:
        save_settings(db, FirewallSettings(bootstrap_networks=["172.16.3.0/24"]))
    phone = TestClient(app, base_url="http://veyra.test")
    yealink = {**UA, "User-Agent": "Yealink SIP-T54W 96.86.0.70"}
    common = phone.get(f"{PROV}/y000000000096.cfg", headers=yealink)
    assert common.status_code == 200 and common.text == "#!version:1.0.0.1\n"
    cfg = phone.get(f"{PROV}/805ec0123456.cfg", headers=yealink)
    assert cfg.status_code == 200
    text = cfg.text
    assert "static.trusted_certificates.url = http://veyra.test/provisioning/veyra-ca.crt" in text
    assert "static.security.trust_certificates = 1" in text
    assert "static.auto_provision.server.url = https://veyra.test/provisioning/" in text
    assert "password" not in text and "account.1" not in text
    ca = phone.get(f"{PROV}/veyra-ca.crt", headers=yealink)
    assert ca.status_code == 200 and ca.text == CA
    # The Poly second file is not offered to Yealink, and outside the networks nothing is.
    assert phone.get(f"{PROV}/veyra-bootstrap-805ec0123456.cfg", headers=yealink).status_code == 404
    outside = {**yealink, "X-Forwarded-For": "203.0.113.9"}
    assert phone.get(f"{PROV}/veyra-ca.crt", headers=outside).status_code == 403
    assert phone.get(f"{PROV}/805ec0123456.cfg", headers=outside).status_code == 403


def test_yealink_config_with_credential():
    text = bootstrap.yealink_config(
        "http://h/provisioning/veyra-ca.crt", "https://h/provisioning/", "veyra-example", "s3cret"
    )
    assert "static.auto_provision.server.username = veyra-example" in text
    assert "static.auto_provision.server.password = s3cret" in text
