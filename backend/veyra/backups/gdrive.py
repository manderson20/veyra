# SPDX-License-Identifier: AGPL-3.0-or-later
"""Google Drive backup destination (issue #44 follow-up #344): a Shared drive,
through Drive API v3 with a service account's key. No SDK: httpx and a JWT
signed with ``cryptography``. Service accounts have no storage of their own, so
files must go to a Shared drive, which also keeps them the district's.

The service account must be a **Manager** of the Shared drive: a Content manager
can only move files to the trash, where they stay for 30 days, and Veyra's keep
policies and the recording archive promise that a deleted file is gone. The
destination test therefore deletes a file for real."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from veyra.backups.destinations import (
    _ARCHIVE_NAME_RE,
    _NAME_RE,
    MANIFEST,
    PARTIAL,
    DestinationError,
    Remote,
    _compare_sizes,
    _files,
)

TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - an address
API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
SCOPE = "https://www.googleapis.com/auth/drive"
FOLDER_TYPE = "application/vnd.google-apps.folder"
CHUNK = 32 * 1024 * 1024  # a multiple of 256 KiB, as resumable uploads require
RETRIES = 5
_RATE_REASONS = ("rateLimitExceeded", "userRateLimitExceeded")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,100}$")
_LINK_RE = re.compile(r"/(?:folders|drives)/([A-Za-z0-9_-]{10,100})")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def parse_key(text: str) -> dict[str, str]:
    """The service account's key file; ValueError with a message for the person."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError("The key is not the JSON file Google gives you.") from e
    if not isinstance(data, dict) or data.get("type") != "service_account":
        raise ValueError("This is not a service account's key file.")
    email, pem = str(data.get("client_email") or ""), str(data.get("private_key") or "")
    if not email or not pem:
        raise ValueError("The key file has no client_email or private_key.")
    try:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
    except (ValueError, TypeError) as e:
        raise ValueError("The private key in this file cannot be read.") from e
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("Google service account keys are RSA keys; this one is not.")
    return {"client_email": email, "private_key": pem}


def drive_id_of(value: str) -> str:
    """The ID of a Shared drive or a folder in it, or its address pasted whole."""
    value = value.strip()
    link = _LINK_RE.search(value)
    if link:
        value = link.group(1)
    if not _ID_RE.match(value):
        raise ValueError("Enter the Shared drive's ID, the last part of its address.")
    return value


class DriveRemote(Remote):
    def __init__(
        self,
        dest: dict[str, Any],
        key_json: str,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(dest)
        try:
            self.key = parse_key(key_json)
        except ValueError as e:
            raise DestinationError(str(e)) from e
        self.client = client or httpx.Client(timeout=httpx.Timeout(60.0, read=600.0))
        self.sleep = sleep
        self._token = ""
        self._token_until = 0.0
        self._folder: str | None = None

    # -- auth

    def _access_token(self, *, fresh: bool = False) -> str:
        now = time.time()
        if self._token and not fresh and now < self._token_until - 60:
            return self._token
        head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claims = {
            "iss": self.key["client_email"],
            "scope": SCOPE,
            "aud": TOKEN_URL,
            "iat": int(now),
            "exp": int(now) + 3600,
        }
        signing = f"{head}.{_b64(json.dumps(claims).encode())}"
        key = serialization.load_pem_private_key(self.key["private_key"].encode(), password=None)
        assert isinstance(key, rsa.RSAPrivateKey)
        signature = key.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256())
        try:
            r = self.client.post(
                TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": f"{signing}.{_b64(signature)}",
                },
            )
        except httpx.HTTPError as e:
            raise DestinationError(f"Google could not be reached: {e}") from e
        if r.status_code != 200:
            raise DestinationError(
                "Google refused the service account's key; it may have been deleted "
                f"(HTTP {r.status_code})."
            )
        body = r.json()
        self._token = str(body["access_token"])
        self._token_until = now + float(body.get("expires_in", 3600))
        return self._token

    # -- requests

    def _error(self, r: httpx.Response) -> str:
        try:
            detail = str(r.json()["error"]["message"])
        except (ValueError, KeyError, TypeError):
            detail = r.text[:200]
        if r.status_code == 404:
            return (
                "Drive cannot find that Shared drive or file: is the ID right, and is "
                f"{self.key['client_email']} a member of the Shared drive?"
            )
        if r.status_code == 403:
            return (
                f"Drive refused: {detail} {self.key['client_email']} must be a Manager of the "
                "Shared drive (a Content manager cannot delete files)."
            )
        return f"Drive answered {r.status_code}: {detail}"

    @staticmethod
    def _retryable(r: httpx.Response) -> bool:
        if r.status_code == 429 or r.status_code >= 500:
            return True
        if r.status_code == 403:
            try:
                errors = r.json()["error"]["errors"]
            except (ValueError, KeyError, TypeError):
                return False
            return any(e.get("reason") in _RATE_REASONS for e in errors)
        return False

    def _send(self, method: str, url: str, **kw: Any) -> httpx.Response:
        """With the token, a new token once on 401, and backing off when busy."""
        fresh = False
        for attempt in range(RETRIES + 1):
            headers = {**kw.get("headers", {})}
            headers["Authorization"] = f"Bearer {self._access_token(fresh=fresh)}"
            fresh = False
            try:
                r = self.client.request(method, url, **{**kw, "headers": headers})
            except httpx.HTTPError as e:
                if attempt == RETRIES:
                    raise DestinationError(f"Google could not be reached: {e}") from e
                self.sleep(2**attempt)
                continue
            if r.status_code == 401 and attempt < RETRIES:
                fresh = True
                continue
            if self._retryable(r) and attempt < RETRIES:
                self.sleep(2**attempt)
                continue
            return r
        raise DestinationError("Drive kept refusing the request.")

    def _api(
        self, method: str, url: str, ok: tuple[int, ...] = (200,), **kw: Any
    ) -> httpx.Response:
        params = {"supportsAllDrives": "true", **kw.pop("params", {})}
        r = self._send(method, url, params=params, **kw)
        if r.status_code not in ok:
            raise DestinationError(self._error(r))
        return r

    def _children(self, parent: str, name: str | None = None) -> list[dict[str, Any]]:
        q = f"'{parent}' in parents and trashed = false"
        if name is not None:
            escaped = name.replace("\\", "\\\\").replace("'", "\\'")
            q += f" and name = '{escaped}'"
        out: list[dict[str, Any]] = []
        token = ""
        while True:
            params = {
                "q": q,
                "corpora": "allDrives",
                "includeItemsFromAllDrives": "true",
                "pageSize": "1000",
                "fields": "nextPageToken,files(id,name,mimeType,size,md5Checksum)",
            }
            if token:
                params["pageToken"] = token
            data = self._api("GET", API, params=params).json()
            out.extend(data.get("files") or [])
            token = str(data.get("nextPageToken") or "")
            if not token:
                return out

    def _mkdir(self, parent: str, name: str) -> str:
        r = self._api(
            "POST",
            API,
            params={"fields": "id"},
            json={"name": name, "mimeType": FOLDER_TYPE, "parents": [parent]},
        )
        return str(r.json()["id"])

    def _base(self) -> str:
        """The destination's folder, made when missing."""
        if self._folder is None:
            current = str(self.dest["drive_id"])
            for part in str(self.dest.get("folder") or "").split("/"):
                if not part:
                    continue
                found = [
                    f for f in self._children(current, part) if f.get("mimeType") == FOLDER_TYPE
                ]
                current = str(found[0]["id"]) if found else self._mkdir(current, part)
            self._folder = current
        return self._folder

    # -- files

    def _chunks(self, path: Path) -> Iterator[bytes]:
        with path.open("rb") as f:
            while chunk := f.read(CHUNK):
                yield chunk

    def _put(self, path: Path, name: str, parent: str) -> None:
        """A resumable upload, then the MD5 Drive computed against ours."""
        size = path.stat().st_size
        started = self._api(
            "POST",
            UPLOAD,
            params={"uploadType": "resumable", "fields": "id"},
            headers={"X-Upload-Content-Length": str(size)},
            json={"name": name, "parents": [parent]},
        )
        session = started.headers.get("location")
        if not session:
            raise DestinationError("Drive did not start the upload.")
        digest = hashlib.md5(usedforsecurity=False)
        result: httpx.Response | None = None
        if size == 0:
            result = self._send("PUT", session, content=b"")
        offset = 0
        for chunk in self._chunks(path):
            digest.update(chunk)
            end = offset + len(chunk) - 1
            result = self._send(
                "PUT",
                session,
                content=chunk,
                headers={"Content-Range": f"bytes {offset}-{end}/{size}"},
            )
            if result.status_code not in (200, 201, 308):
                raise DestinationError(self._error(result))
            offset = end + 1
        if result is None or result.status_code not in (200, 201):
            raise DestinationError("Drive did not finish the upload.")
        file_id = str(result.json()["id"])
        meta = self._api("GET", f"{API}/{file_id}", params={"fields": "size,md5Checksum"}).json()
        if int(meta.get("size") or -1) != size or meta.get("md5Checksum") != digest.hexdigest():
            raise DestinationError(f"The copy of {path.name} does not match what was sent.")

    def _remove(self, parent: str, name: str) -> None:
        """Everything of this name (Drive allows duplicates), permanently."""
        for item in self._children(parent, name):
            if item.get("mimeType") == FOLDER_TYPE:
                for child in self._children(str(item["id"])):
                    self._api("DELETE", f"{API}/{child['id']}", ok=(200, 204, 404))
            self._api("DELETE", f"{API}/{item['id']}", ok=(200, 204, 404))

    # -- Remote

    def names(self) -> set[str]:
        out = set()
        for item in self._children(self._base()):
            name = str(item.get("name"))
            if not _NAME_RE.match(name):
                continue
            if item.get("mimeType") != FOLDER_TYPE or self._children(str(item["id"]), MANIFEST):
                out.add(name)
        return out

    def upload(self, artifact: Path) -> None:
        base = self._base()
        name = artifact.name
        tmp = name + PARTIAL
        self._remove(base, tmp)
        if artifact.is_dir():
            folder = self._mkdir(base, tmp)
            for p in _files(artifact):
                self._put(p, p.name, folder)
            got = {str(f["name"]): int(f.get("size") or 0) for f in self._children(folder)}
            _compare_sizes(artifact, got)
            target = folder
        else:
            self._put(artifact, tmp, base)
            target = str(self._children(base, tmp)[0]["id"])
        self._remove(base, name)
        self._api("PATCH", f"{API}/{target}", json={"name": name})

    def delete(self, name: str) -> None:
        if not _NAME_RE.match(name) and not _ARCHIVE_NAME_RE.match(name):
            raise DestinationError("not a backup name")
        self._remove(self._base(), name)

    def exists(self, name: str) -> bool:
        return bool(self._children(self._base(), name))

    def test(self) -> None:
        """Write, check and permanently delete, so a role that can only trash
        fails here rather than when a backup is due for deletion."""
        import tempfile

        base = self._base()
        name = f".veyra-test-{uuid.uuid4().hex[:8]}"
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as f:
            f.write("veyra\n")
            f.flush()
            self._put(Path(f.name), name, base)
        self._remove(base, name)
        if self._children(base, name):
            raise DestinationError("The test file is still there after deleting it.")
