# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public HTTPS certificates (docs/PUBLIC_CERTIFICATES.md, issue #43): the
settings and their write-only credentials, the request handed to the root
helper, the firewall's challenge window, the alerts, the SIP TLS paths and
the helper itself run against a fake certbot."""
# ruff: noqa: S603, S607

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from veyra.core.db import session_scope
from veyra.core.models.base import utcnow
from veyra.firewall.ports import PortSpec
from veyra.firewall.render import Ruleset, render
from veyra.reporting.alerts import check_public_certificate
from veyra.system import certificate as cert
from veyra.telephony.asterisk import generator
from veyra.telephony.settings import SipSettings

BASE = "/api/v1/system/certificate"
HELPER = Path(__file__).resolve().parents[2] / "installer" / "bin" / "veyra-acme"

CLOUDFLARE = {
    "names": ["pbx.example.org"],
    "email": "it@example.org",
    "challenge": "dns",
    "provider": "cloudflare",
    "credentials": {"dns_cloudflare_api_token": "cf-secret-token"},
}


class Done:
    returncode = 0
    stderr = ""


@pytest.fixture
def acme(app, tmp_path):
    calls: list[list[str]] = []
    app.state.systemctl_run = lambda cmd: calls.append(cmd) or Done()
    app.state.acme_dir = str(tmp_path)
    return calls


# ------------------------------------------------------------------ settings


def test_settings_validation():
    s = cert.PublicCertSettings(names=[" PBX.Example.org. ", "pbx.example.org"])
    assert s.names == ["pbx.example.org"]
    with pytest.raises(ValueError, match="IP addresses"):
        cert.PublicCertSettings(names=["192.0.2.10"])
    with pytest.raises(ValueError, match="wildcard"):
        cert.PublicCertSettings(names=["*.example.org"], challenge="http")
    assert cert.PublicCertSettings(names=["*.example.org"], challenge="dns").names
    with pytest.raises(ValueError, match="directory address"):
        cert.PublicCertSettings(authority="custom")
    assert cert.PublicCertSettings(authority="letsencrypt_staging").directory == (
        cert.LETSENCRYPT_STAGING
    )
    problems = cert.PublicCertSettings(challenge="dns").problems()
    assert len(problems) == 3


def test_credentials_are_write_only(admin, acme):
    r = admin.put(f"{BASE}/settings", json=CLOUDFLARE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "cf-secret-token" not in r.text
    assert body["settings"]["credentials_set"] == ["dns_cloudflare_api_token"]
    assert body["problems"] == []
    # Leaving the credentials out keeps them.
    again = admin.put(f"{BASE}/settings", json={**CLOUDFLARE, "credentials": {}}).json()
    assert again["settings"]["credentials_set"] == ["dns_cloudflare_api_token"]
    # Non-secret fields are shown; another provider starts empty.
    rfc = admin.put(
        f"{BASE}/settings",
        json={
            **CLOUDFLARE,
            "provider": "rfc2136",
            "credentials": {"dns_rfc2136_server": "192.0.2.53", "dns_rfc2136_secret": "tsig"},
        },
    ).json()
    assert rfc["settings"]["credentials_public"] == {
        "dns_rfc2136_server": "192.0.2.53",
        "dns_rfc2136_port": "53",
        "dns_rfc2136_algorithm": "HMAC-SHA512",
    }
    assert "dns_cloudflare_api_token" not in rfc["settings"]["credentials_set"]
    bad = admin.put(f"{BASE}/settings", json={**CLOUDFLARE, "credentials": {"nope": "x"}})
    assert bad.status_code == 422
    ip = admin.put(f"{BASE}/settings", json={**CLOUDFLARE, "names": ["10.0.0.1"]})
    assert ip.status_code == 422 and "IP addresses" in ip.text


def test_only_platform_administrators(admin, app):
    from conftest import ADMIN_PASSWORD, login
    from fastapi.testclient import TestClient
    from test_api_rbac import make_user

    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    make_user(admin, "orgadmin@example.org", org, "org_admin")
    c = login(TestClient(app, base_url="http://veyra.test"), "orgadmin@example.org", ADMIN_PASSWORD)
    assert c.get(BASE).status_code == 403


# ------------------------------------------------------------------- request


def test_request_writes_the_request_and_starts_the_unit(admin, acme, tmp_path):
    assert admin.post(f"{BASE}/request").status_code == 422  # nothing set yet
    admin.put(f"{BASE}/settings", json=CLOUDFLARE)
    r = admin.post(f"{BASE}/request")
    assert r.status_code == 202, r.text
    assert acme == [["systemctl", "start", "--no-block", "veyra-acme@issue.service"]]
    req = json.loads((tmp_path / "request.json").read_text())
    assert oct((tmp_path / "request.json").stat().st_mode & 0o777) == "0o600"
    assert req["names"] == ["pbx.example.org"] and req["server"] == cert.LETSENCRYPT
    assert req["dns"]["plugin"] == "cloudflare"
    assert req["dns"]["credentials"] == {"dns_cloudflare_api_token": "cf-secret-token"}
    assert r.json()["challenge_window_open"] is False  # DNS-01 needs no port 80
    # A run in progress refuses another.
    (tmp_path / "started").write_text("2026-10-27T10:00:00Z\n")
    assert admin.post(f"{BASE}/request").status_code == 409
    (tmp_path / "exit").write_text("1\n")
    (tmp_path / "error").write_text("certbot exited with 1\n")
    run = admin.get(BASE).json()["run"]
    assert run["ok"] is False and run["error"] == "certbot exited with 1"
    events = admin.get("/api/v1/audit", params={"q": "certificate_issue"}).json()
    assert events["total"] == 1
    assert "cf-secret-token" not in json.dumps(events)


def test_http_challenge_opens_port_80_for_a_while(admin, acme):
    admin.put(
        f"{BASE}/settings",
        json={"names": ["pbx.example.org"], "email": "it@example.org", "challenge": "http"},
    )
    r = admin.post(f"{BASE}/request")
    assert r.status_code == 202, r.text
    assert r.json()["challenge_window_open"] is True
    now = utcnow()
    with session_scope() as db:
        assert cert.challenge_window_open(db, now)
        assert not cert.challenge_window_open(db, now + timedelta(minutes=11))


def test_renew_needs_a_certificate(admin, acme, tmp_path):
    admin.put(f"{BASE}/settings", json=CLOUDFLARE)
    assert admin.post(f"{BASE}/renew").status_code == 409
    (tmp_path / "certificate.json").write_text(
        json.dumps({"names": ["pbx.example.org"], "not_after": "2027-01-25T00:00:00+00:00"})
    )
    assert admin.post(f"{BASE}/renew").status_code == 202
    assert acme[-1][-1] == "veyra-acme@renew.service"
    out = admin.get(BASE).json()
    assert out["certificate"]["names"] == ["pbx.example.org"]
    assert admin.post(f"{BASE}/remove").status_code == 202  # reached from a fresh sign-in


def test_renew_due(db_ready, tmp_path):
    now = utcnow()
    with session_scope() as db:
        assert not cert.renew_due(db, tmp_path, now)  # no certificate
        (tmp_path / "certificate.json").write_text(
            json.dumps({"not_after": (now + timedelta(days=60)).isoformat()})
        )
        assert not cert.renew_due(db, tmp_path, now)
        (tmp_path / "certificate.json").write_text(
            json.dumps({"not_after": (now + timedelta(days=20)).isoformat()})
        )
        assert cert.renew_due(db, tmp_path, now)
        cert.note_renew_attempt(db, now)
        db.flush()
        assert not cert.renew_due(db, tmp_path, now + timedelta(hours=2))
        assert cert.renew_due(db, tmp_path, now + timedelta(hours=24))
    calls: list[list[str]] = []
    later = now + timedelta(days=1)
    with session_scope() as db:
        started = cert.process_renewal(db, later, tmp_path, lambda c: calls.append(c) or Done())
    assert started and calls == [["systemctl", "start", "--no-block", "veyra-acme@renew.service"]]
    with session_scope() as db:
        assert not cert.process_renewal(db, later, tmp_path, lambda c: calls.append(c) or Done())


# --------------------------------------------------- firewall, alerts, SIP TLS


def test_firewall_challenge_window_comes_before_the_allow_list():
    ports = {"web": PortSpec(tcp=("80", "443"))}
    closed = render(Ruleset(ports=ports, restricted=["web"]))
    assert "tcp dport { 80 } return" not in closed
    opened = render(Ruleset(ports=ports, restricted=["web"], open_tcp=("80",)))
    lines = opened.splitlines()
    window = lines.index("    tcp dport { 80 } return")
    assert window < lines.index("    tcp dport { 80, 443 } drop")
    # Bans and blocks are checked before it.
    assert lines.index("    ip saddr @ban4 drop") < window


def test_alerts(tmp_path):
    now = utcnow()
    assert check_public_certificate(now, 21, str(tmp_path)) == []
    (tmp_path / "certificate.json").write_text(
        json.dumps(
            {"names": ["pbx.example.org"], "not_after": (now + timedelta(days=10)).isoformat()}
        )
    )
    for name, text in (
        ("started", "x"),
        ("mode", "renew"),
        ("exit", "1"),
        ("error", "DNS timeout"),
    ):
        (tmp_path / name).write_text(text + "\n")
    findings = check_public_certificate(now, 21, str(tmp_path))
    assert {f.rule for f in findings} == {"certificate", "certificate_renewal"}
    assert any("DNS timeout" in f.message for f in findings)
    (tmp_path / "exit").write_text("0\n")
    assert {f.rule for f in check_public_certificate(now, 21, str(tmp_path))} == {"certificate"}


def test_sip_tls_reads_asterisk_copies():
    veyra = generator._transports(SipSettings(tls_enabled=True)).content
    assert "cert_file=/etc/asterisk/veyra-tls/veyra.crt" in veyra
    assert "priv_key_file=/etc/asterisk/veyra-tls/veyra.key" in veyra
    assert "/etc/veyra/tls" not in veyra
    public = generator._transports(SipSettings(tls_enabled=True, tls_certificate="public")).content
    assert "cert_file=/etc/asterisk/veyra-tls/public.crt" in public


# ------------------------------------------------------------- root helper


def _helper():
    loader = importlib.machinery.SourceFileLoader("veyra_acme", str(HELPER))
    spec = importlib.util.spec_from_loader("veyra_acme", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _self_signed(directory: Path, name: str) -> None:
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
         "-nodes", "-days", "90", "-subj", f"/CN={name}", "-addext", f"subjectAltName=DNS:{name}",
         "-keyout", str(directory / "privkey.pem"), "-out", str(directory / "fullchain.pem")],
        check=True, capture_output=True,
    )  # fmt: skip


@pytest.fixture
def helper_env(tmp_path, monkeypatch):
    etc, state, ast = tmp_path / "etc", tmp_path / "state", tmp_path / "ast"
    (etc / "tls").mkdir(parents=True)
    state.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "certbot-args"
    # A certbot that records its arguments and leaves a certificate.
    fake = bin_dir / "certbot"
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> {log}\n'
        'cfg=""; while [ $# -gt 0 ]; do [ "$1" = --config-dir ] && cfg="$2"; shift; done\n'
        'mkdir -p "$cfg/live/veyra"\n'
        f'cp {tmp_path}/fullchain.pem {tmp_path}/privkey.pem "$cfg/live/veyra/"\n'
    )
    fake.chmod(0o755)
    _self_signed(tmp_path, "pbx.example.org")
    for k, v in {
        "VEYRA_ETC": etc,
        "VEYRA_ACME_DIR": state,
        "VEYRA_ACME_WEBROOT": tmp_path / "webroot",
        "VEYRA_ASTERISK_TLS_DIR": ast,
        "VEYRA_ACME_CERTBOT": fake,
        "VEYRA_ACME_NGINX": "true",
        "VEYRA_ACME_SYSTEMCTL": "true",
        "VEYRA_ACME_SKIP_PACKAGES": "1",
    }.items():
        monkeypatch.setenv(k, str(v))
    return etc, state, ast, log


def _run_helper(mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(HELPER), mode], capture_output=True, text=True, check=False,
        env=dict(os.environ),
    )  # fmt: skip


def test_helper_issues_and_deploys(helper_env):
    etc, state, ast, log = helper_env
    req = cert.build_request(
        cert.PublicCertSettings(
            names=["pbx.example.org"], email="it@example.org", provider="rfc2136"
        ),
        "issue",
        {"dns_rfc2136_server": "192.0.2.53", "dns_rfc2136_secret": "tsig-secret"},
        None,
        "admin",
        utcnow(),
    )
    cert.write_request(state, req)
    res = _run_helper("issue")
    assert res.returncode == 0, (state / "last.log").read_text()
    assert (state / "exit").read_text().strip() == "0"
    assert not (state / "request.json").exists()  # the credentials moved
    ini = etc / "acme" / "credentials.ini"
    assert oct(ini.stat().st_mode & 0o777) == "0o600"
    assert "dns_rfc2136_secret = tsig-secret" in ini.read_text()
    stored = json.loads((etc / "acme" / "request.json").read_text())
    assert "credentials" not in stored["dns"]
    args = log.read_text()
    assert "--dns-rfc2136 --dns-rfc2136-credentials" in args
    assert "-d pbx.example.org" in args and "--key-type ecdsa" in args
    assert "tsig-secret" not in (state / "last.log").read_text()
    assert (etc / "nginx-public-name.conf").read_text() == "server_name pbx.example.org;\n"
    assert (etc / "tls" / "public.crt").exists() and (ast / "public.key").exists()
    info = json.loads((state / "certificate.json").read_text())
    assert info["names"] == ["pbx.example.org"] and info["not_after"]
    # Renewal reuses the stored request; nothing new: not deployed again.
    assert _run_helper("renew").returncode == 0
    assert "not due" in (state / "last.log").read_text()
    # Remove: back to the placeholder name.
    (etc / "tls" / "veyra.crt").write_text("veyra")
    (etc / "tls" / "veyra.key").write_text("veyra")
    assert _run_helper("remove").returncode == 0
    assert "public-certificate.invalid" in (etc / "nginx-public-name.conf").read_text()
    assert not (etc / "acme" / "credentials.ini").exists()
    assert not (state / "certificate.json").exists()


def test_helper_command_lines(helper_env):
    etc, _, _, _ = helper_env
    h = _helper()
    (etc / "acme").mkdir(exist_ok=True)
    h.store_request(
        {"dns": {"plugin": "route53", "style": "env", "credentials": {"AWS_ACCESS_KEY_ID": "AK"}}}
    )
    cmd, env = h.certbot_command(
        {
            "email": "it@example.org",
            "server": cert.LETSENCRYPT_STAGING,
            "challenge": "dns",
            "names": ["*.example.org", "example.org"],
            "dns": {"plugin": "route53", "style": "env", "propagation_seconds": None},
        }
    )
    assert "--dns-route53" in cmd and env["AWS_ACCESS_KEY_ID"] == "AK"
    assert not any(a.startswith("--dns-route53-propagation") for a in cmd)
    assert cmd[cmd.index("--server") + 1] == cert.LETSENCRYPT_STAGING
    http, _ = h.certbot_command(
        {"email": "a@b.co", "server": cert.LETSENCRYPT, "challenge": "http", "names": ["x.b.co"]}
    )
    assert http[http.index("--webroot") + 2].endswith("webroot")


def test_helper_reports_a_failure(helper_env):
    _, state, _, _ = helper_env
    res = _run_helper("issue")  # no request file
    assert res.returncode == 1
    assert "no request" in (state / "error").read_text()
    assert (state / "finished").exists()
