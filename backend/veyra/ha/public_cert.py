# SPDX-License-Identifier: AGPL-3.0-or-later
"""The public HTTPS certificate on the standby (docs/PUBLIC_CERTIFICATES.md §8).

The file sync brings ``tls/public.crt`` and ``tls/public.key``. What else the
helper ``veyra-acme`` sets up on the node that got the certificate is worked
out here from the certificate itself: the name NGINX serves it for, the copies
Asterisk reads, and ``certificate.json``, without which the worker of a new
primary would never renew. Safe to call on every sync: it acts on a difference."""

from __future__ import annotations

import contextlib
import grp
import json
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes

log = logging.getLogger("veyra.ha.public_cert")

PLACEHOLDER = "server_name public-certificate.invalid;\n"
NAME_CONF = "nginx-public-name.conf"
ACME_STATE_DIR = Path("/var/lib/veyra-acme")
ASTERISK_TLS_DIR = Path("/etc/asterisk/veyra-tls")


def describe(pem: bytes) -> dict[str, Any]:
    """The certificate as ``veyra-acme`` writes it to ``certificate.json``."""
    cert = x509.load_pem_x509_certificate(pem)
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names = san.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        names = []
    digest = cert.fingerprint(hashes.SHA256()).hex().upper()
    return {
        "names": names,
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "not_after": cert.not_valid_after_utc.isoformat(),
        "not_before": cert.not_valid_before_utc.isoformat(),
        "fingerprint_sha256": ":".join(digest[i : i + 2] for i in range(0, len(digest), 2)),
    }


def _copy(src: Path, dest: Path, mode: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.copyfile(src, tmp)
    os.chmod(tmp, mode)
    with contextlib.suppress(KeyError, PermissionError):
        os.chown(tmp, 0, grp.getgrnam("asterisk").gr_gid)
    os.replace(tmp, dest)


def apply(
    config_dir: Path,
    system: Any,
    *,
    state_dir: Path = ACME_STATE_DIR,
    asterisk_dir: Path = ASTERISK_TLS_DIR,
) -> bool:
    """Make this node serve what the synced files say; whether it changed
    anything. NGINX refusing the files (a certificate that arrived without its
    key) leaves it serving the old ones, and the next sync tries again."""
    tls = config_dir / "tls"
    crt, key = tls / "public.crt", tls / "public.key"
    if not crt.is_file() or not key.is_file():
        return False
    pem = crt.read_bytes()
    veyra = tls / "veyra.crt"
    # After "remove" the public files hold the Veyra certificate (veyra-acme).
    public = not veyra.is_file() or veyra.read_bytes() != pem
    info = describe(pem) if public else None
    if info is not None and not info["names"]:
        info = None
    wanted = f"server_name {' '.join(info['names'])};\n" if info else PLACEHOLDER

    name_conf = config_dir / NAME_CONF
    info_file = state_dir / "certificate.json"
    before = name_conf.read_text() if name_conf.is_file() else None
    known: dict[str, Any] | None = None
    with contextlib.suppress(OSError, ValueError):
        known = json.loads(info_file.read_text())
    same_cert = (known or {}).get("fingerprint_sha256") == (info or {}).get("fingerprint_sha256")
    if before == wanted and same_cert and (info is not None or known is None):
        return False

    name_conf.write_text(wanted)
    os.chmod(name_conf, 0o644)
    check = system.run(["nginx", "-t"])
    if not check.ok:
        if before is None:
            name_conf.unlink()
        else:
            name_conf.write_text(before)
        log.warning("nginx -t refused the synced certificate: %s", check.stderr.strip()[:300])
        return False
    system.systemctl("reload", "nginx")

    if info is None:
        for name in ("public.crt", "public.key"):
            (asterisk_dir / name).unlink(missing_ok=True)
        info_file.unlink(missing_ok=True)
        return True
    _copy(crt, asterisk_dir / "public.crt", 0o640)
    _copy(key, asterisk_dir / "public.key", 0o640)
    state_dir.mkdir(parents=True, exist_ok=True)
    info["deployed_at"] = datetime.now(UTC).isoformat()
    info_file.write_text(json.dumps(info, indent=1))
    return True
