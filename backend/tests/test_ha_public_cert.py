# SPDX-License-Identifier: AGPL-3.0-or-later
"""The public certificate on the standby (docs/PUBLIC_CERTIFICATES.md §8)."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from veyra.ha import public_cert, sync


def _pem(*names):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "x")])
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=90))
    )
    if names:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(n) for n in names]), critical=False
        )
    cert = builder.sign(key, hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.PEM), key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


class System:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def run(self, argv):
        self.calls.append(list(argv))
        return SimpleNamespace(ok=self.ok, stderr="bad")

    def systemctl(self, verb, *units):
        self.calls.append(["systemctl", verb, *units])


def _setup(tmp_path, crt, key):
    etc = tmp_path / "etc"
    (etc / "tls").mkdir(parents=True)
    (etc / "tls" / "public.crt").write_bytes(crt)
    (etc / "tls" / "public.key").write_bytes(key)
    return etc, {"state_dir": tmp_path / "acme", "asterisk_dir": tmp_path / "ast"}


def test_standby_takes_over_the_certificate_once(tmp_path):
    etc, kw = _setup(tmp_path, *_pem("pbx.example.org", "voice.example.org"))
    system = System()
    assert public_cert.apply(etc, system, **kw) is True
    assert (etc / public_cert.NAME_CONF).read_text() == (
        "server_name pbx.example.org voice.example.org;\n"
    )
    assert ["systemctl", "reload", "nginx"] in system.calls
    assert (tmp_path / "ast" / "public.crt").exists() and (tmp_path / "ast" / "public.key").exists()
    # What the worker's renewal looks for.
    info = json.loads((tmp_path / "acme" / "certificate.json").read_text())
    assert info["names"] == ["pbx.example.org", "voice.example.org"] and info["not_after"]

    # Nothing to do on the next sync, so no reload every 30 seconds.
    system.calls.clear()
    assert public_cert.apply(etc, system, **kw) is False
    assert system.calls == []


def test_renewed_certificate_with_the_same_names_is_picked_up(tmp_path):
    etc, kw = _setup(tmp_path, *_pem("pbx.example.org"))
    public_cert.apply(etc, System(), **kw)
    crt, key = _pem("pbx.example.org")
    (etc / "tls" / "public.crt").write_bytes(crt)
    (etc / "tls" / "public.key").write_bytes(key)
    system = System()
    assert public_cert.apply(etc, system, **kw) is True
    assert ["systemctl", "reload", "nginx"] in system.calls
    assert (tmp_path / "ast" / "public.crt").read_bytes() == crt


def test_nginx_refusing_keeps_the_old_name_and_retries(tmp_path):
    etc, kw = _setup(tmp_path, *_pem("pbx.example.org"))
    (etc / public_cert.NAME_CONF).write_text(public_cert.PLACEHOLDER)
    system = System(ok=False)
    assert public_cert.apply(etc, system, **kw) is False
    assert (etc / public_cert.NAME_CONF).read_text() == public_cert.PLACEHOLDER
    assert not (tmp_path / "acme" / "certificate.json").exists()
    assert not any(c[0] == "systemctl" for c in system.calls)
    assert public_cert.apply(etc, System(), **kw) is True


def test_removed_certificate_goes_back_to_the_placeholder(tmp_path):
    etc, kw = _setup(tmp_path, *_pem("pbx.example.org"))
    public_cert.apply(etc, System(), **kw)
    veyra_crt, veyra_key = _pem("veyra.local")
    for name, data in (
        ("veyra.crt", veyra_crt),
        ("public.crt", veyra_crt),
        ("public.key", veyra_key),
    ):
        (etc / "tls" / name).write_bytes(data)
    assert public_cert.apply(etc, System(), **kw) is True
    assert (etc / public_cert.NAME_CONF).read_text() == public_cert.PLACEHOLDER
    assert not (tmp_path / "acme" / "certificate.json").exists()
    assert not (tmp_path / "ast" / "public.key").exists()
    assert public_cert.apply(etc, System(), **kw) is False


def test_nothing_happens_without_the_files(tmp_path):
    (tmp_path / "etc" / "tls").mkdir(parents=True)
    system = System()
    assert public_cert.apply(tmp_path / "etc", system) is False
    assert system.calls == []


def test_sync_takes_the_request_but_not_certbots_tree(tmp_path):
    roots = sync.roots_for(tmp_path / "d", tmp_path / "e", recordings=False)
    assert roots["etc/acme"] == tmp_path / "e" / "acme"
    assert not sync.excluded("etc/acme/request.json")
    assert not sync.excluded("etc/acme/credentials.ini")
    assert sync.excluded("etc/acme/certbot/accounts/x/private_key.json")
