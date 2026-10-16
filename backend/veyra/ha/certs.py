# SPDX-License-Identifier: AGPL-3.0-or-later
"""Certificates for the pair (docs/HIGH_AVAILABILITY.md §2, §4.1): the Veyra
CA issues the HTTPS certificate for the service name and both node names,
and a PostgreSQL server certificate per node. The installer created the CA
with name constraints for one server; ``widen_ca`` re-signs it with the same
key when the names grow (phones that pinned the old CA certificate must
trust the new one; the page says so).
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from veyra.ha.postgres import Result, Runner, subprocess_runner


class CertError(RuntimeError):
    pass


def _check(r: Result, what: str) -> None:
    if not r.ok:
        raise CertError(f"{what}: {(r.stderr or r.stdout).strip()[:400]}")


def ca_permitted_names(ca_crt: Path, run: Runner | None = None) -> list[str] | None:
    """The DNS names a constrained CA may vouch for; None when unconstrained."""
    run = run or subprocess_runner()
    r = run(["openssl", "x509", "-in", str(ca_crt), "-noout", "-ext", "nameConstraints"])
    if not r.ok or "nameConstraints" not in r.stdout:
        return None
    return re.findall(r"DNS:([^\s,]+)", r.stdout)


def widen_ca(tls_dir: Path, names: list[str], run: Runner | None = None, days: int = 3650) -> bool:
    """Re-sign the CA with its own key so its constraints permit ``names``;
    returns True when it was changed."""
    run = run or subprocess_runner()
    ca_crt, ca_key = tls_dir / "ca.crt", tls_dir / "ca.key"
    permitted = ca_permitted_names(ca_crt, run)
    if permitted is None or all(n in permitted for n in names):
        return False
    wanted = list(dict.fromkeys([*permitted, *names]))
    r = run(["openssl", "x509", "-in", str(ca_crt), "-noout", "-subject", "-nameopt", "RFC2253"])
    _check(r, "reading the CA subject")
    subject = r.stdout.partition("=")[2].strip()
    cnf = (
        "[req]\ndistinguished_name = dn\n[dn]\n[ca]\n"
        "basicConstraints = critical, CA:TRUE, pathlen:0\n"
        "keyUsage = critical, keyCertSign, cRLSign\n"
        "subjectKeyIdentifier = hash\n"
        "nameConstraints = critical" + "".join(f", permitted;DNS:{n}" for n in wanted) + "\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".cnf", delete=False) as f:
        f.write(cnf)
        cnf_path = f.name
    out = ca_crt.with_suffix(".crt.new")
    r = run(
        [
            "openssl",
            "req",
            "-x509",
            "-new",
            "-key",
            str(ca_key),
            "-days",
            str(days),
            "-subj",
            "/" + "/".join(reversed(subject.split(","))),
            "-config",
            cnf_path,
            "-extensions",
            "ca",
            "-out",
            str(out),
        ]
    )
    Path(cnf_path).unlink(missing_ok=True)
    _check(r, "re-signing the CA")
    out.replace(ca_crt)
    return True


def issue(
    tls_dir: Path,
    names: list[str],
    out_crt: Path,
    out_key: Path,
    *,
    addresses: list[str] | None = None,
    server_auth_only: bool = True,
    run: Runner | None = None,
    days: int = 825,
) -> None:
    """A server certificate for ``names`` (and ``addresses``) signed by the CA."""
    run = run or subprocess_runner()
    san = ", ".join([f"DNS:{n}" for n in names] + [f"IP:{a}" for a in (addresses or [])])
    cnf = (
        "[req]\ndistinguished_name = dn\n[dn]\n[ext]\n"
        "basicConstraints = CA:FALSE\n"
        "keyUsage = critical, digitalSignature, keyEncipherment\n"
        f"extendedKeyUsage = {'serverAuth' if server_auth_only else 'serverAuth, clientAuth'}\n"
        "subjectKeyIdentifier = hash\nauthorityKeyIdentifier = keyid\n"
        f"subjectAltName = {san}\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        cnf_path = Path(tmp) / "ext.cnf"
        cnf_path.write_text(cnf)
        csr = Path(tmp) / "req.csr"
        r = run(
            [
                "openssl",
                "req",
                "-new",
                "-newkey",
                "ec",
                "-pkeyopt",
                "ec_paramgen_curve:prime256v1",
                "-nodes",
                "-subj",
                f"/CN={names[0]}",
                "-keyout",
                str(out_key),
                "-out",
                str(csr),
            ]
        )
        _check(r, "creating the certificate request")
        r = run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                str(csr),
                "-CA",
                str(tls_dir / "ca.crt"),
                "-CAkey",
                str(tls_dir / "ca.key"),
                "-CAcreateserial",
                "-days",
                str(days),
                "-extfile",
                str(cnf_path),
                "-extensions",
                "ext",
                "-out",
                str(out_crt),
            ]
        )
        _check(r, "signing the certificate")
