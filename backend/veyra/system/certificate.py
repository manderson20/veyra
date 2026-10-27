# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public HTTPS certificates from an ACME authority such as Let's Encrypt
(docs/PUBLIC_CERTIFICATES.md, issue #43).

The settings live in ``system_settings``; provider credentials are encrypted
with the installation key. The work is done as root by
``veyra-acme@<mode>.service`` (installer/bin/veyra-acme), which reads the
request file this module writes and leaves its status beside it."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from veyra.core.models import SystemSetting

SETTINGS_KEY = "tls.public_certificate"
CHALLENGE_WINDOW_KEY = "tls.acme_challenge_until"
CREDENTIALS_PURPOSE = "tls.acme.credentials"
EAB_PURPOSE = "tls.acme.eab"
ACME_DIR = "/var/lib/veyra-acme"
MODES = ("issue", "renew", "remove")
# certbot renews when this many days or fewer are left; the worker asks daily.
RENEW_DAYS = 30
CHALLENGE_WINDOW = timedelta(minutes=10)
LETSENCRYPT = "https://acme-v02.api.letsencrypt.org/directory"
LETSENCRYPT_STAGING = "https://acme-staging-v02.api.letsencrypt.org/directory"


@dataclass(frozen=True)
class CredentialField:
    key: str  # the certbot ini key, or the environment variable for route53
    label: str
    secret: bool = True
    multiline: bool = False
    optional: bool = False
    default: str | None = None


@dataclass(frozen=True)
class Provider:
    key: str  # certbot plugin: --dns-<key>
    label: str
    package: str
    fields: tuple[CredentialField, ...]
    # How the helper hands over the credentials: an ini file, a JSON file,
    # or environment variables (Route 53 reads the AWS variables).
    style: Literal["ini", "json", "env"] = "ini"
    propagation: bool = True  # takes --dns-<key>-propagation-seconds


PROVIDERS: dict[str, Provider] = {
    p.key: p
    for p in (
        Provider(
            "cloudflare",
            "Cloudflare",
            "python3-certbot-dns-cloudflare",
            (CredentialField("dns_cloudflare_api_token", "API token (Zone → DNS → Edit)"),),
        ),
        Provider(
            "route53",
            "Amazon Route 53",
            "python3-certbot-dns-route53",
            (
                CredentialField("AWS_ACCESS_KEY_ID", "Access key ID", secret=False),
                CredentialField("AWS_SECRET_ACCESS_KEY", "Secret access key"),
            ),
            style="env",
            propagation=False,
        ),
        Provider(
            "google",
            "Google Cloud DNS",
            "python3-certbot-dns-google",
            (
                CredentialField(
                    "service_account_json", "Service account key (JSON)", multiline=True
                ),
            ),
            style="json",
        ),
        Provider(
            "digitalocean",
            "DigitalOcean",
            "python3-certbot-dns-digitalocean",
            (CredentialField("dns_digitalocean_token", "API token"),),
        ),
        Provider(
            "linode",
            "Linode (Akamai)",
            "python3-certbot-dns-linode",
            (CredentialField("dns_linode_key", "API token"),),
        ),
        Provider(
            "dnsimple",
            "DNSimple",
            "python3-certbot-dns-dnsimple",
            (CredentialField("dns_dnsimple_token", "API token"),),
        ),
        Provider(
            "ovh",
            "OVH",
            "python3-certbot-dns-ovh",
            (
                CredentialField("dns_ovh_endpoint", "Endpoint", secret=False, default="ovh-eu"),
                CredentialField("dns_ovh_application_key", "Application key", secret=False),
                CredentialField("dns_ovh_application_secret", "Application secret"),
                CredentialField("dns_ovh_consumer_key", "Consumer key"),
            ),
        ),
        Provider(
            "rfc2136",
            "Your own DNS server (RFC 2136: BIND, Windows DNS with TSIG)",
            "python3-certbot-dns-rfc2136",
            (
                CredentialField("dns_rfc2136_server", "DNS server address", secret=False),
                CredentialField("dns_rfc2136_port", "Port", secret=False, default="53"),
                CredentialField("dns_rfc2136_name", "TSIG key name", secret=False),
                CredentialField("dns_rfc2136_secret", "TSIG key secret"),
                CredentialField(
                    "dns_rfc2136_algorithm", "TSIG algorithm", secret=False, default="HMAC-SHA512"
                ),
            ),
        ),
    )
}

_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
_NAME_RE = re.compile(rf"^(\*\.)?({_LABEL}\.)+[a-z]{{2,63}}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PublicCertSettings(BaseModel):
    """What the administrator chose. Credentials are stored encrypted and
    never leave the server except in the root helper's request file."""

    names: list[str] = Field(default_factory=list, max_length=10)
    email: str = ""
    challenge: Literal["http", "dns"] = "dns"
    provider: str | None = None
    credentials_ciphertext: str | None = None
    authority: Literal["letsencrypt", "letsencrypt_staging", "custom"] = "letsencrypt"
    directory_url: str | None = None
    eab_kid: str | None = None
    eab_hmac_ciphertext: str | None = None
    propagation_seconds: int = Field(60, ge=10, le=900)

    @field_validator("names")
    @classmethod
    def _names(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for raw in v:
            name = raw.strip().lower().rstrip(".")
            if not name:
                continue
            if not _NAME_RE.match(name) or len(name) > 253:
                raise ValueError(f"{raw!r} is not a host name (IP addresses cannot be used)")
            if name not in out:
                out.append(name)
        return out

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip()
        if v and not _EMAIL_RE.match(v):
            raise ValueError("not an email address")
        return v

    @field_validator("directory_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        if not v.startswith("https://"):
            raise ValueError("the directory address must start with https://")
        return v.strip()

    @model_validator(mode="after")
    def _consistent(self) -> PublicCertSettings:
        if self.challenge == "dns" and self.provider is not None and self.provider not in PROVIDERS:
            raise ValueError(f"unknown DNS provider {self.provider!r}")
        if self.challenge == "http" and any(n.startswith("*.") for n in self.names):
            raise ValueError("a wildcard name needs the DNS challenge")
        if self.authority == "custom" and not self.directory_url:
            raise ValueError("a custom authority needs its directory address")
        return self

    @property
    def directory(self) -> str:
        if self.authority == "letsencrypt_staging":
            return LETSENCRYPT_STAGING
        if self.authority == "custom" and self.directory_url:
            return self.directory_url
        return LETSENCRYPT

    def problems(self) -> list[str]:
        """What stops a request (the settings may be saved incomplete)."""
        out = []
        if not self.names:
            out.append("Enter the host name the certificate is for.")
        if not self.email:
            out.append("Enter an email address for expiry notices from the authority.")
        if self.challenge == "dns":
            if not self.provider:
                out.append("Choose the DNS provider that hosts the name.")
            elif not self.credentials_ciphertext:
                out.append("Enter the DNS provider's credentials.")
        return out


def load_settings(db: Session) -> PublicCertSettings:
    row = db.get(SystemSetting, SETTINGS_KEY)
    if row is None or not row.value:
        return PublicCertSettings()
    return PublicCertSettings.model_validate(row.value)


def save_settings(db: Session, s: PublicCertSettings) -> None:
    row = db.get(SystemSetting, SETTINGS_KEY)
    value = s.model_dump(mode="json")
    if row is None:
        db.add(SystemSetting(key=SETTINGS_KEY, value=value))
    else:
        row.value = value


def merge_credentials(
    provider: Provider, current: dict[str, str], given: dict[str, str | None]
) -> dict[str, str]:
    """Write-only credentials: a field left out keeps its value, an empty
    one removes it; fields the provider does not have are refused."""
    known = {f.key: f for f in provider.fields}
    out = {k: v for k, v in current.items() if k in known}
    for k, v in given.items():
        if k not in known:
            raise ValueError(f"{provider.label} has no field {k!r}")
        if v is None or v == "":
            out.pop(k, None)
        else:
            out[k] = v
    for f in provider.fields:
        if f.key not in out and f.default is not None:
            out[f.key] = f.default
    return out


def missing_credentials(provider: Provider, values: dict[str, str]) -> list[str]:
    return [f.label for f in provider.fields if not f.optional and not values.get(f.key)]


def build_request(
    s: PublicCertSettings,
    mode: str,
    credentials: dict[str, str],
    eab_hmac: str | None,
    by: str,
    now: datetime,
) -> dict[str, Any]:
    """The request file for the root helper. It is deleted by the helper as
    soon as it has stored the credentials root-only."""
    if mode not in MODES:
        raise ValueError(mode)
    req: dict[str, Any] = {
        "mode": mode,
        "names": s.names,
        "email": s.email,
        "challenge": s.challenge,
        "server": s.directory,
        "staging": s.authority == "letsencrypt_staging",
        "requested_by": by,
        "requested_at": now.isoformat(),
    }
    if s.authority == "custom" and s.eab_kid and eab_hmac:
        req["eab"] = {"kid": s.eab_kid, "hmac_key": eab_hmac}
    if s.challenge == "dns" and s.provider:
        p = PROVIDERS[s.provider]
        req["dns"] = {
            "plugin": p.key,
            "package": p.package,
            "style": p.style,
            "propagation_seconds": s.propagation_seconds if p.propagation else None,
            "credentials": credentials,
        }
    return req


def write_request(directory: str | Path, req: dict[str, Any]) -> Path:
    d = Path(directory)
    path = d / "request.json"
    tmp = d / ".request.json.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(req, f)
    os.replace(tmp, path)
    return path


def unit_name(mode: str) -> str:
    if mode not in MODES:
        raise ValueError(mode)
    return f"veyra-acme@{mode}.service"


def start_unit(mode: str, run: Callable[[list[str]], Any] | None = None) -> tuple[bool, str]:
    cmd = ["systemctl", "start", "--no-block", unit_name(mode)]
    res = (
        run(cmd)
        if run
        else subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)  # noqa: S603
    )
    ok = getattr(res, "returncode", 1) == 0
    return ok, "" if ok else (getattr(res, "stderr", "") or "systemctl failed").strip()[:500]


def run_status(directory: str | Path = ACME_DIR) -> dict[str, Any] | None:
    """The last run of the root helper, as the OS package runs report it."""
    d = Path(directory)

    def read(name: str) -> str | None:
        try:
            return (d / name).read_text(errors="replace").strip()
        except OSError:
            return None

    started = read("started")
    if started is None:
        return None
    exit_code = read("exit")
    return {
        "mode": read("mode"),
        "started_at": started,
        "finished_at": read("finished") if exit_code is not None else None,
        "running": exit_code is None,
        "ok": exit_code == "0",
        "error": read("error"),
        "output": (read("last.log") or "")[-4000:],
    }


def certificate_info(directory: str | Path = ACME_DIR) -> dict[str, Any] | None:
    """The deployed public certificate, as the helper describes it."""
    try:
        data = json.loads((Path(directory) / "certificate.json").read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def days_left(info: dict[str, Any] | None, now: datetime) -> float | None:
    if not info or not info.get("not_after"):
        return None
    try:
        end = datetime.fromisoformat(str(info["not_after"]))
    except ValueError:
        return None
    return (end - now).total_seconds() / 86400


def open_challenge_window(db: Session, now: datetime) -> None:
    """Let the ACME authority reach port 80 for ten minutes even when the
    web service is limited to the allow list (§6)."""
    until = (now + CHALLENGE_WINDOW).isoformat()
    row = db.get(SystemSetting, CHALLENGE_WINDOW_KEY)
    if row is None:
        db.add(SystemSetting(key=CHALLENGE_WINDOW_KEY, value={"until": until}))
    else:
        row.value = {"until": until}


def challenge_window_open(db: Session, now: datetime) -> bool:
    row = db.get(SystemSetting, CHALLENGE_WINDOW_KEY)
    if row is None or not row.value:
        return False
    try:
        return datetime.fromisoformat(str(row.value.get("until"))) > now
    except ValueError:
        return False


RENEW_STATE_KEY = "tls.acme_renew"


def renew_due(db: Session, directory: str | Path, now: datetime) -> bool:
    """Once a day, when a public certificate is deployed and no run is going."""
    if certificate_info(directory) is None:
        return False
    status = run_status(directory)
    if status and status["running"]:
        return False
    row = db.get(SystemSetting, RENEW_STATE_KEY)
    last = (row.value or {}).get("last_attempt") if row is not None else None
    if last:
        try:
            if now - datetime.fromisoformat(last) < timedelta(hours=23):
                return False
        except ValueError:
            pass
    left = days_left(certificate_info(directory), now)
    return left is None or left <= RENEW_DAYS


def note_renew_attempt(db: Session, now: datetime) -> None:
    row = db.get(SystemSetting, RENEW_STATE_KEY)
    value = {"last_attempt": now.isoformat()}
    if row is None:
        db.add(SystemSetting(key=RENEW_STATE_KEY, value=value))
    else:
        row.value = value


def process_renewal(
    db: Session,
    now: datetime,
    directory: str | Path = ACME_DIR,
    run: Callable[[list[str]], Any] | None = None,
) -> bool:
    """The worker's daily renewal (§5): start ``veyra-acme@renew`` when the
    certificate has 30 days or fewer left. Returns whether it started."""
    if not renew_due(db, directory, now):
        return False
    if load_settings(db).challenge == "http":
        open_challenge_window(db, now)
    note_renew_attempt(db, now)
    db.commit()
    ok, _ = start_unit("renew", run)
    return ok


def renewal_failure(directory: str | Path = ACME_DIR) -> str | None:
    """The error of the last run, when it was a renewal or an issue that
    failed (what the ``certificate_renewal`` alert reports)."""
    status = run_status(directory)
    if not status or status["running"] or status["ok"] or status["mode"] == "remove":
        return None
    return status["error"] or "The last certificate run failed; see its output."
