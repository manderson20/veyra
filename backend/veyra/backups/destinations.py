# SPDX-License-Identifier: AGPL-3.0-or-later
"""Backup destinations (docs/PRODUCTION_HARDENING.md §2.7, issue #44): a
mounted folder, an SFTP server or an S3-compatible bucket. The root runner
copies every verified backup a destination is missing (so a failed copy is
retried at the next run), checks each copy, and prunes the destination with
its own keep policy. Recording archives will use the same destinations.

SFTP goes through the system ``sftp`` client with Veyra's own SSH key and a
pinned host key; S3 through signed (SigV4) requests with httpx, where the
storage checks the SHA-256 of every request body. No SDKs.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from veyra.backups import policy

KINDS = ("directory", "sftp", "s3")
SECRET_PURPOSE = "backups.destination"  # noqa: S105 - an encryption purpose, + ":<id>"
SSH_KEY_PURPOSE = "backups.ssh_key"
MAX_DESTINATIONS = 5
PART_SIZE = 64 * 1024 * 1024  # S3 multipart part size
MULTIPART_OVER = 100 * 1024 * 1024
MANIFEST = "manifest.json"
PARTIAL = ".partial"
_NAME_RE = re.compile(r"^veyra-\d{8}-\d{6}(\.tar\.age)?$")
_ARCHIVE_NAME_RE = re.compile(r"^veyra-recording-[0-9a-f-]{36}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$|^\[?[0-9A-Fa-f:.]{2,45}\]?$")
_USER_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


class DestinationError(Exception):
    pass


def secret_purpose(dest_id: str) -> str:
    return f"{SECRET_PURPOSE}:{dest_id}"


# ---------------------------------------------------------------- the document


def _clean_path(value: str, what: str, *, absolute: bool) -> str:
    v = value.strip()
    if absolute and not v.startswith("/"):
        raise ValueError(f"The {what} is an absolute path, such as /mnt/backups.")
    if any(c in v for c in "\n\r\0") or ".." in v.split("/"):
        raise ValueError(f"The {what} is not a valid path.")
    return v.rstrip("/") or "/"


def normalize(value: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """One destination as stored (secrets stay as their ciphertexts); raises
    ValueError with a message for the person."""
    kind = str(value.get("kind") or (existing or {}).get("kind") or "")
    if kind not in KINDS:
        raise ValueError("Choose a folder, an SFTP server or S3-compatible storage.")
    out: dict[str, Any] = {
        "id": str((existing or {}).get("id") or value.get("id") or uuid.uuid4().hex[:12]),
        "kind": kind,
        "name": str(value.get("name") or "").strip()[:80] or kind.upper(),
        "enabled": bool(value.get("enabled", True)),
        "keep": None,
    }
    keep = value.get("keep")
    if isinstance(keep, dict):
        out["keep"] = {
            k: max(0, min(int(keep.get(k, d)), lim))
            for (k, d), lim in zip(policy.DEFAULTS["keep"].items(), (3650, 520, 100), strict=True)
        }
    if kind == "directory":
        out["path"] = _clean_path(str(value.get("path") or ""), "folder", absolute=True)
        if out["path"] == "/":
            raise ValueError("Choose a folder, not the root of the file system.")
    elif kind == "sftp":
        host = str(value.get("host") or "").strip()
        if not _HOST_RE.match(host):
            raise ValueError("Enter the SFTP server's host name or address.")
        user = str(value.get("username") or "").strip()
        if not _USER_RE.match(user):
            raise ValueError("Enter the user name on the SFTP server.")
        port = int(value.get("port") or 22)
        if not 1 <= port <= 65535:
            raise ValueError("The port is a number from 1 to 65535.")
        path = _clean_path(str(value.get("path") or "."), "folder", absolute=False)
        # A changed host or port forgets the pinned host key.
        same = (
            existing is not None and existing.get("host") == host and existing.get("port") == port
        )
        out.update(
            host=host,
            port=port,
            username=user,
            path=path,
            host_key=(existing or {}).get("host_key") if same else None,
        )
    else:
        endpoint = str(value.get("endpoint") or "").strip().rstrip("/")
        if endpoint and not re.match(r"^https://[^\s/]+(:\d+)?$", endpoint):
            raise ValueError(
                "The endpoint is the storage's https:// address, such as "
                "https://s3.us-west-002.backblazeb2.com (leave it empty for Amazon S3)."
            )
        bucket = str(value.get("bucket") or "").strip()
        if not _BUCKET_RE.match(bucket):
            raise ValueError("Enter the bucket name (lower-case letters, digits, dots, dashes).")
        region = str(value.get("region") or "").strip() or "us-east-1"
        if not re.match(r"^[a-z0-9-]{2,40}$", region):
            raise ValueError("The region looks like us-east-1.")
        access = str(value.get("access_key_id") or "").strip()
        if not re.match(r"^[A-Za-z0-9+/=_-]{3,128}$", access):
            raise ValueError("Enter the access key ID.")
        prefix = str(value.get("prefix") or "").strip().strip("/")
        if prefix:
            _clean_path(prefix, "prefix", absolute=False)
        addressing = str(value.get("addressing") or ("path" if endpoint else "virtual"))
        if addressing not in ("path", "virtual"):
            raise ValueError("Addressing is path or virtual.")
        out.update(
            endpoint=endpoint,
            bucket=bucket,
            region=region,
            prefix=prefix,
            access_key_id=access,
            addressing=addressing,
            secret_ciphertext=(existing or {}).get("secret_ciphertext"),
        )
    return out


def public(dest: dict[str, Any], last: dict[str, Any] | None = None) -> dict[str, Any]:
    """What the interface sees: never a secret."""
    out = {k: v for k, v in dest.items() if k != "secret_ciphertext"}
    if dest.get("kind") == "s3":
        out["has_secret"] = bool(dest.get("secret_ciphertext"))
    if dest.get("kind") == "sftp":
        out["host_key_fingerprint"] = host_key_fingerprint(dest.get("host_key"))
    out["target"] = describe(dest)
    out["last"] = last
    return out


def describe(dest: dict[str, Any]) -> str:
    if dest["kind"] == "directory":
        return str(dest["path"])
    if dest["kind"] == "sftp":
        port = f":{dest['port']}" if dest.get("port") != 22 else ""
        return f"sftp://{dest['username']}@{dest['host']}{port}/{dest['path'].lstrip('/')}"
    where = dest.get("endpoint") or f"Amazon S3 ({dest.get('region')})"
    prefix = f"/{dest['prefix']}" if dest.get("prefix") else ""
    return f"{where} · {dest['bucket']}{prefix}"


def keep_for(dest: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    return dict(dest.get("keep") or settings.get("keep") or policy.DEFAULTS["keep"])


# ------------------------------------------------------------------- SSH keys


def generate_ssh_key(comment: str) -> tuple[str, str]:
    """A new Ed25519 key pair: (private key in OpenSSH format, public line)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode()
    public_line = (
        key.public_key()
        .public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
        .decode()
    )
    return private, f"{public_line} {comment}"


def host_key_fingerprint(line: str | None) -> str | None:
    """``SHA256:…`` of a known_hosts line ("host type base64"), as ssh shows it."""
    if not line:
        return None
    parts = line.split()
    if len(parts) < 3:
        return None
    try:
        raw = base64.b64decode(parts[2])
    except ValueError:
        return None
    digest = base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
    return f"{parts[1]} SHA256:{digest}"


Runner = Callable[[Sequence[str], str | None], subprocess.CompletedProcess[str]]


def _run(argv: Sequence[str], stdin: str | None) -> subprocess.CompletedProcess[str]:
    # A fixed program; the arguments come from validated settings.
    return subprocess.run(  # noqa: S603
        list(argv), input=stdin, capture_output=True, text=True, timeout=3600, check=False
    )


def scan_host_key(host: str, port: int, run: Runner = _run) -> str:
    """The server's Ed25519 (or other) host key, for the person to confirm."""
    r = run(["ssh-keyscan", "-T", "10", "-p", str(port), "-t", "ed25519,ecdsa,rsa", host], None)
    lines = [ln for ln in r.stdout.splitlines() if ln and not ln.startswith("#")]
    if not lines:
        raise DestinationError(
            f"{host}:{port} did not answer as an SSH server "
            f"({(r.stderr or 'no answer').strip()[-200:]})."
        )
    for kind in ("ssh-ed25519", "ecdsa-sha2-nistp256", "ssh-rsa"):
        for ln in lines:
            if ln.split()[1:2] == [kind]:
                return ln
    return lines[0]


# ---------------------------------------------------------------- the clients


@dataclass
class Remote:
    """A destination as the runner uses it."""

    dest: dict[str, Any]

    def names(self) -> set[str]:
        """Complete backups present: ``veyra-…`` directories and ``….tar.age`` files."""
        raise NotImplementedError

    def upload(self, artifact: Path) -> None:
        """Copy and check one backup (a directory or a ``.tar.age`` file)."""
        raise NotImplementedError

    def delete(self, name: str) -> None:
        raise NotImplementedError

    def exists(self, name: str) -> bool:
        """Whether anything of this name is there (the archive checks deletes)."""
        raise NotImplementedError

    def test(self) -> None:
        """Write, check and remove a small file."""
        raise NotImplementedError


def _files(artifact: Path) -> list[Path]:
    """A directory backup's files with the manifest last, so a backup
    without its manifest is known to be incomplete."""
    if artifact.is_file():
        return [artifact]
    files = sorted(p for p in artifact.iterdir() if p.is_file())
    return [p for p in files if p.name != MANIFEST] + [p for p in files if p.name == MANIFEST]


class DirectoryRemote(Remote):
    @property
    def root(self) -> Path:
        return Path(self.dest["path"])

    def _check(self) -> None:
        if not self.root.is_dir():
            raise DestinationError(f"{self.root} is not a folder (is the share mounted?)")

    def names(self) -> set[str]:
        self._check()
        out = set()
        for p in self.root.iterdir():
            if not _NAME_RE.match(p.name):
                continue
            if p.is_file() or (p / MANIFEST).is_file():
                out.add(p.name)
        return out

    def upload(self, artifact: Path) -> None:
        self._check()
        target = self.root / artifact.name
        tmp = self.root / (artifact.name + PARTIAL)
        if tmp.is_dir():
            shutil.rmtree(tmp)
        tmp.unlink(missing_ok=True)
        if artifact.is_dir():
            shutil.copytree(artifact, tmp)
        else:
            shutil.copy2(artifact, tmp)
        _compare_sizes(artifact, _local_sizes(tmp))
        if target.is_dir():
            shutil.rmtree(target)
        target.unlink(missing_ok=True)
        tmp.rename(target)

    def delete(self, name: str) -> None:
        p = self.root / name
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)

    def exists(self, name: str) -> bool:
        return (self.root / name).exists()

    def test(self) -> None:
        self._check()
        probe = self.root / f".veyra-test-{uuid.uuid4().hex[:8]}"
        probe.write_text("veyra\n")
        ok = probe.read_text() == "veyra\n"
        probe.unlink()
        if not ok:
            raise DestinationError("The test file read back differently.")


def _local_sizes(path: Path) -> dict[str, int]:
    if path.is_file():
        return {"": path.stat().st_size}
    return {p.name: p.stat().st_size for p in path.iterdir() if p.is_file()}


def _compare_sizes(artifact: Path, got: dict[str, int]) -> None:
    want = (
        {"": artifact.stat().st_size}
        if artifact.is_file()
        else {p.name: p.stat().st_size for p in _files(artifact)}
    )
    if got != want:
        missing = sorted(set(want) - set(got)) or sorted(k for k in want if got.get(k) != want[k])
        raise DestinationError(f"The copy does not match: {', '.join(missing) or 'size'} differs.")


class SftpRemote(Remote):
    """Through the system ``sftp`` client in batch mode."""

    def __init__(self, dest: dict[str, Any], private_key: str, run: Runner = _run) -> None:
        super().__init__(dest)
        if not dest.get("host_key"):
            raise DestinationError(
                "The server's host key is not confirmed yet: use Test on the destination first."
            )
        self.private_key = private_key
        self.run = run

    @contextlib.contextmanager
    def _session_files(self) -> Iterator[tuple[str, str]]:
        with tempfile.TemporaryDirectory(prefix="veyra-sftp-") as d:
            key = Path(d) / "key"
            key.write_text(self.private_key.rstrip("\n") + "\n")
            os.chmod(key, 0o600)
            known = Path(d) / "known_hosts"
            host = self.dest["host"]
            label = host if int(self.dest["port"]) == 22 else f"[{host}]:{self.dest['port']}"
            parts = str(self.dest["host_key"]).split()
            known.write_text(f"{label} {parts[1]} {parts[2]}\n")
            yield str(key), str(known)

    def _batch(self, commands: list[str]) -> str:
        with self._session_files() as (key, known):
            argv = [
                "sftp",
                "-q",
                "-b",
                "-",
                "-i",
                key,
                "-P",
                str(self.dest["port"]),
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                f"UserKnownHostsFile={known}",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "ConnectTimeout=20",
                f"{self.dest['username']}@{self.dest['host']}",
            ]
            r = self.run(argv, "\n".join(commands) + "\n")
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            if "Host key verification failed" in err or "REMOTE HOST IDENTIFICATION" in err:
                err = (
                    "the server's host key changed since it was confirmed — if that is expected "
                    "(a reinstalled server), confirm the new key with Test"
                )
            elif "Permission denied" in err:
                err = (
                    "the server refused Veyra's SSH key — add the public key shown on the "
                    "Backups page to the user's authorized_keys"
                )
            raise DestinationError(f"SFTP: {err[-400:]}")
        return r.stdout

    def _q(self, path: str) -> str:
        if any(c in path for c in '"\n\r'):
            raise DestinationError("unexpected character in a path")
        return f'"{path}"'

    def _dir(self, *parts: str) -> str:
        base = self.dest["path"]
        return "/".join([base.rstrip("/") if base != "/" else "", *parts]) if parts else base

    def _listing(self, path: str) -> list[tuple[str, int, bool]]:
        """(name, size, is_dir) for the entries of ``path``."""
        out = self._batch([f"ls -ln {self._q(path)}"])
        entries = []
        for line in out.splitlines():
            f = line.split(None, 8)
            if len(f) < 9 or f[0][:1] not in "-d" or line.startswith("sftp>"):
                continue
            entries.append((f[8].rsplit("/", 1)[-1], int(f[4]), f[0].startswith("d")))
        return entries

    def names(self) -> set[str]:
        out = set()
        for name, _, is_dir in self._listing(self._dir()):
            if not _NAME_RE.match(name):
                continue
            if not is_dir or any(n == MANIFEST for n, _, _ in self._listing(self._dir(name))):
                out.add(name)
        return out

    def upload(self, artifact: Path) -> None:
        name = artifact.name
        tmp = self._dir(name + PARTIAL)
        cmds = [f"-mkdir {self._q(self._dir())}"]
        if artifact.is_dir():
            cmds += [f"-rm {self._q(tmp)}/*", f"-rmdir {self._q(tmp)}", f"mkdir {self._q(tmp)}"]
            cmds += [
                f"put {self._q(str(p))} {self._q(tmp + '/' + p.name)}" for p in _files(artifact)
            ]
        else:
            cmds += [f"-rm {self._q(tmp)}", f"put {self._q(str(artifact))} {self._q(tmp)}"]
        self._batch(cmds)
        # Check the sizes before the copy takes its real name.
        if artifact.is_dir():
            got = {n: s for n, s, d in self._listing(tmp) if not d}
        else:
            got = dict(("", s) for n, s, _ in self._listing(self._dir()) if n == name + PARTIAL)
        _compare_sizes(artifact, got)
        self.delete(name)
        self._batch([f"rename {self._q(tmp)} {self._q(self._dir(name))}"])

    def delete(self, name: str) -> None:
        bare = name.removesuffix(PARTIAL)
        if not _NAME_RE.match(bare) and not _ARCHIVE_NAME_RE.match(bare):
            raise DestinationError("not a backup name")
        p = self._dir(name)
        self._batch([f"-rm {self._q(p)}/*", f"-rmdir {self._q(p)}", f"-rm {self._q(p)}"])

    def exists(self, name: str) -> bool:
        return any(n == name for n, _, _ in self._listing(self._dir()))

    def test(self) -> None:
        probe = self._dir(f".veyra-test-{uuid.uuid4().hex[:8]}")
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("veyra\n")
        try:
            self._batch(
                [f"-mkdir {self._q(self._dir())}", f"put {self._q(f.name)} {self._q(probe)}"]
            )
            sizes = [s for n, s, _ in self._listing(self._dir()) if n == probe.rsplit("/", 1)[-1]]
            self._batch([f"rm {self._q(probe)}"])
        finally:
            os.unlink(f.name)
        if sizes != [6]:
            raise DestinationError("The test file did not arrive complete.")


class S3Remote(Remote):
    """An S3-compatible bucket through SigV4-signed requests. Every request
    carries the SHA-256 of its body, which the storage checks."""

    def __init__(
        self,
        dest: dict[str, Any],
        secret: str,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(dest)
        self.secret = secret
        self.client = client or httpx.Client(timeout=httpx.Timeout(60.0, read=600.0))
        self.now = now or (lambda: datetime.now(UTC))
        endpoint = dest.get("endpoint") or f"https://s3.{dest['region']}.amazonaws.com"
        u = urlsplit(endpoint)
        if dest.get("addressing") == "virtual":
            self.host = f"{dest['bucket']}.{u.netloc}"
            self.base_path = ""
        else:
            self.host = u.netloc
            self.base_path = f"/{dest['bucket']}"

    # -- signing

    def _key(self, *parts: str) -> str:
        prefix = self.dest.get("prefix") or ""
        return "/".join(p for p in (prefix, *parts) if p)

    def _request(
        self,
        method: str,
        key: str = "",
        query: dict[str, str] | None = None,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        now = self.now()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        day = now.strftime("%Y%m%d")
        path = self.base_path + "/" + quote(key, safe="/~") if key else (self.base_path or "/")
        query = query or {}
        canonical_query = "&".join(
            f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(query.items())
        )
        payload_hash = hashlib.sha256(body).hexdigest()
        hdrs = {
            "host": self.host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
            **{k.lower(): v for k, v in (headers or {}).items()},
        }
        signed = ";".join(sorted(hdrs))
        canonical = "\n".join(
            [
                method,
                path,
                canonical_query,
                "".join(f"{k}:{hdrs[k].strip()}\n" for k in sorted(hdrs)),
                signed,
                payload_hash,
            ]
        )
        scope = f"{day}/{self.dest['region']}/s3/aws4_request"
        to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical.encode()).hexdigest(),
            ]
        )
        k = hmac.new(("AWS4" + self.secret).encode(), day.encode(), hashlib.sha256).digest()
        for part in (self.dest["region"], "s3", "aws4_request"):
            k = hmac.new(k, part.encode(), hashlib.sha256).digest()
        signature = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
        hdrs["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self.dest['access_key_id']}/{scope}, "
            f"SignedHeaders={signed}, Signature={signature}"
        )
        url = f"https://{self.host}{path}" + (f"?{canonical_query}" if canonical_query else "")
        try:
            r = self.client.request(method, url, content=body, headers=hdrs)
        except httpx.HTTPError as e:
            raise DestinationError(f"S3: cannot reach {self.host}: {e}") from e
        if r.status_code >= 300:
            raise DestinationError(f"S3: {method} {key or '/'}: {_s3_error(r)}")
        return r

    # -- operations

    def _list(self, prefix: str) -> list[tuple[str, int]]:
        keys: list[tuple[str, int]] = []
        token = None
        while True:
            q = {"list-type": "2", "prefix": prefix}
            if token:
                q["continuation-token"] = token
            root = _parse_xml(self._request("GET", query=q).content)
            ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
            for c in root.findall(f"{ns}Contents"):
                keys.append((c.findtext(f"{ns}Key") or "", int(c.findtext(f"{ns}Size") or 0)))
            if root.findtext(f"{ns}IsTruncated") != "true":
                return keys
            token = root.findtext(f"{ns}NextContinuationToken")

    def names(self) -> set[str]:
        base = self._key() + "/" if self._key() else ""
        out = set()
        for key, _ in self._list(base + "veyra-"):
            rest = key[len(base) :]
            if _NAME_RE.match(rest) and rest.endswith(".tar.age"):
                out.add(rest)
            elif rest.endswith("/" + MANIFEST) and _NAME_RE.match(rest.split("/")[0]):
                out.add(rest.split("/")[0])
        return out

    def _put_file(self, path: Path, key: str) -> None:
        size = path.stat().st_size
        if size <= MULTIPART_OVER:
            self._request("PUT", key, body=path.read_bytes())
            return
        r = self._request("POST", key, query={"uploads": ""})
        upload_id = _xml_text(r.content, "UploadId")
        done = []
        try:
            with path.open("rb") as f:
                n = 0
                while chunk := f.read(PART_SIZE):
                    n += 1
                    r = self._request(
                        "PUT", key, query={"partNumber": str(n), "uploadId": upload_id}, body=chunk
                    )
                    done.append((n, r.headers.get("etag", "")))
            body = (
                "<CompleteMultipartUpload>"
                + "".join(
                    f"<Part><PartNumber>{n}</PartNumber><ETag>{etag}</ETag></Part>"
                    for n, etag in done
                )
                + "</CompleteMultipartUpload>"
            ).encode()
            r = self._request("POST", key, query={"uploadId": upload_id}, body=body)
            if b"<Error>" in r.content:  # S3 can report a failure with 200
                raise DestinationError(f"S3: completing {key}: {_s3_error(r)}")
        except DestinationError:
            with contextlib.suppress(DestinationError):
                self._request("DELETE", key, query={"uploadId": upload_id})
            raise

    def upload(self, artifact: Path) -> None:
        name = artifact.name
        if artifact.is_file():
            self._put_file(artifact, self._key(name))
            got = dict(("", s) for k, s in self._list(self._key(name)) if k == self._key(name))
        else:
            for p in _files(artifact):
                self._put_file(p, self._key(name, p.name))
            got = {k.rsplit("/", 1)[-1]: s for k, s in self._list(self._key(name) + "/")}
        _compare_sizes(artifact, got)

    def exists(self, name: str) -> bool:
        return bool(self._list(self._key(name) + "/") or self._list(self._key(name)))

    def delete(self, name: str) -> None:
        if not _NAME_RE.match(name) and not _ARCHIVE_NAME_RE.match(name):
            raise DestinationError("not a backup name")
        if name.endswith(".tar.age"):
            self._request("DELETE", self._key(name))
            return
        for key, _ in self._list(self._key(name) + "/"):
            self._request("DELETE", key)

    def test(self) -> None:
        key = self._key(f".veyra-test-{uuid.uuid4().hex[:8]}")
        self._request("PUT", key, body=b"veyra\n")
        r = self._request("HEAD", key)
        self._request("DELETE", key)
        if r.headers.get("content-length") not in ("6", None):
            raise DestinationError("The test file did not arrive complete.")


def _parse_xml(content: bytes) -> ET.Element:
    """An S3 answer. The storage is one the administrator configured, and
    ElementTree resolves no external entities; expat limits entity expansion."""
    return ET.fromstring(content)  # noqa: S314


def _xml_text(content: bytes, tag: str) -> str:
    root = _parse_xml(content)
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == tag and el.text:
            return el.text
    raise DestinationError(f"S3: the answer has no {tag}")


def _s3_error(r: httpx.Response) -> str:
    code = message = ""
    with contextlib.suppress(ET.ParseError):
        root = _parse_xml(r.content)
        for el in root.iter():
            name = el.tag.rsplit("}", 1)[-1]
            if name == "Code":
                code = el.text or ""
            elif name == "Message":
                message = el.text or ""
    hints = {
        "SignatureDoesNotMatch": "the secret access key or the region is wrong",
        "InvalidAccessKeyId": "the access key ID is wrong",
        "AccessDenied": "the key may not write to this bucket or prefix",
        "NoSuchBucket": "the bucket does not exist (check the name and the region)",
        "PermanentRedirect": "the bucket is in another region, or needs virtual addressing",
        "AuthorizationHeaderMalformed": "the region is wrong",
    }
    detail = hints.get(code) or message or r.reason_phrase
    return f"{r.status_code} {code} — {detail}".strip(" —")


def remote(
    dest: dict[str, Any],
    *,
    secret: str | None = None,
    ssh_private_key: str | None = None,
    run: Runner = _run,
    client: httpx.Client | None = None,
) -> Remote:
    if dest["kind"] == "directory":
        return DirectoryRemote(dest)
    if dest["kind"] == "sftp":
        if not ssh_private_key:
            raise DestinationError("Veyra's SSH key is missing; open the Backups page once.")
        return SftpRemote(dest, ssh_private_key, run)
    if not secret:
        raise DestinationError("The secret access key is missing; enter it again.")
    return S3Remote(dest, secret, client)


def archive_remote(
    dest: dict[str, Any],
    *,
    secret: str | None = None,
    ssh_private_key: str | None = None,
    run: Runner = _run,
    client: httpx.Client | None = None,
) -> Remote:
    """The destination's ``recordings`` folder, apart from its backups, so the
    backup keep policy never sees a recording."""
    sub = dict(dest)
    if dest["kind"] == "s3":
        sub["prefix"] = "/".join(p for p in (dest.get("prefix") or "", "recordings") if p)
        return remote(sub, secret=secret, client=client)
    sub["path"] = str(dest.get("path") or "").rstrip("/") + "/recordings"
    rem = remote(sub, ssh_private_key=ssh_private_key, run=run)
    if isinstance(rem, DirectoryRemote):
        if not Path(dest["path"]).is_dir():
            raise DestinationError(f"{dest['path']} is not a folder (is the share mounted?)")
        rem.root.mkdir(exist_ok=True)
    elif isinstance(rem, SftpRemote):
        rem._batch(
            [f"-mkdir {rem._q(str(dest.get('path') or ''))}", f"-mkdir {rem._q(sub['path'])}"]
        )
    return rem


# ---------------------------------------------------------------------- sync


def sync(
    rem: Remote,
    *,
    store: Path,
    verified: dict[str, str],
    keep: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Bring one destination in line: copy the verified local backups its
    keep policy wants and it does not have (newest first), then prune it.
    ``verified`` maps backup name → kind. Returns what happened."""
    have = rem.names()
    local = {}
    for p in store.iterdir():
        base = p.name.split(".")[0]
        if base in verified and _NAME_RE.match(p.name):
            local[p.name] = verified[base]
    entries = [ent for n, k in local.items() if (ent := policy.Entry.parse(n, k)) is not None]
    dropped = {ent.name for ent in policy.to_delete(entries, keep, now)}
    wanted = sorted((n for n in local if n not in dropped and n not in have), reverse=True)
    copied, errors = [], []
    for name in wanted:
        try:
            rem.upload(store / name)
            copied.append(name)
            have.add(name)
        except (DestinationError, OSError) as err:
            errors.append(f"{name}: {err}")
            break  # the next ones would fail the same way; the next run retries
    remote_entries = [
        ent
        for n in have
        if (ent := policy.Entry.parse(n, verified.get(n.split(".")[0], "scheduled"))) is not None
    ]
    removed = []
    if not errors:
        for ent in policy.to_delete(remote_entries, keep, now):
            try:
                rem.delete(ent.name)
                removed.append(ent.name)
            except (DestinationError, OSError) as err:
                errors.append(f"removing {ent.name}: {err}")
    return {
        "state": "failed" if errors else "ok",
        "at": now.isoformat(),
        "copied": copied,
        "removed": removed,
        "error": "; ".join(errors)[:1000] or None,
        "count": len(have) - len(removed),
    }


__all__ = [
    "KINDS",
    "DestinationError",
    "archive_remote",
    "describe",
    "generate_ssh_key",
    "host_key_fingerprint",
    "normalize",
    "public",
    "remote",
    "scan_host_key",
    "sync",
]
