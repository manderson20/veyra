# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Google Drive destination against an in-memory Drive (issue #344)."""

import hashlib
import json
import re
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from veyra.backups import destinations, gdrive

ROOT = "shared-drive-0001"
FOLDER = gdrive.FOLDER_TYPE


def _key_json():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return json.dumps(
        {
            "type": "service_account",
            "client_email": "v@p.iam.gserviceaccount.com",
            "private_key": pem,
        }
    )


KEY = _key_json()


class Drive:
    def __init__(self, *, can_delete=True, corrupt=False):
        self.files = {}
        self.sessions = {}
        self.can_delete = can_delete
        self.corrupt = corrupt
        self.tokens = 0
        self.busy = 0
        self.trashed = []

    def handler(self, req):
        url = str(req.url)
        if url == gdrive.TOKEN_URL:
            self.tokens += 1
            return httpx.Response(200, json={"access_token": f"t{self.tokens}", "expires_in": 3600})
        assert req.headers["authorization"].startswith("Bearer ")
        if self.busy:
            self.busy -= 1
            return httpx.Response(503, json={"error": {"message": "busy"}})
        parts = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        if parts.path.startswith("/session/"):
            return self._chunk(req, parts.path.rsplit("/", 1)[1])
        if parts.path == "/upload/drive/v3/files":
            sid = uuid.uuid4().hex
            self.sessions[sid] = {"meta": json.loads(req.content), "data": b""}
            return httpx.Response(
                200, headers={"location": f"https://www.googleapis.com/session/{sid}"}
            )
        assert q.get("supportsAllDrives") == "true"
        fid = parts.path.rsplit("/", 1)[1]
        if parts.path == "/drive/v3/files":
            if req.method == "POST":
                body = json.loads(req.content)
                return httpx.Response(200, json={"id": self._add(body, b"")})
            return self._list(q)
        if fid not in self.files:
            return httpx.Response(404, json={"error": {"message": "File not found"}})
        if req.method == "GET":
            return httpx.Response(200, json=self.files[fid])
        if req.method == "PATCH":
            self.files[fid]["name"] = json.loads(req.content)["name"]
            return httpx.Response(200, json={"id": fid})
        if req.method == "DELETE":
            if not self.can_delete:
                return httpx.Response(
                    403,
                    json={
                        "error": {
                            "message": "Insufficient permissions",
                            "errors": [{"reason": "insufficientFilePermissions"}],
                        }
                    },
                )
            del self.files[fid]
            return httpx.Response(204)
        raise AssertionError(req.method)

    def _add(self, meta, data):
        fid = uuid.uuid4().hex
        self.files[fid] = {
            "id": fid,
            "name": meta["name"],
            "parents": meta["parents"],
            "mimeType": meta.get("mimeType", "application/octet-stream"),
            "size": str(len(data)),
            "md5Checksum": hashlib.md5(
                data + (b"x" if self.corrupt else b""), usedforsecurity=False
            ).hexdigest(),
        }
        return fid

    def _chunk(self, req, sid):
        session = self.sessions[sid]
        m = re.match(r"bytes (\d+)-(\d+)/(\d+)", req.headers["content-range"])
        assert int(m.group(1)) == len(session["data"])
        session["data"] += req.content
        if len(session["data"]) < int(m.group(3)):
            return httpx.Response(308)
        return httpx.Response(200, json={"id": self._add(session["meta"], session["data"])})

    def _list(self, q):
        parent = re.search(r"'([^']+)' in parents", q["q"]).group(1)
        name = re.search(r"name = '([^']+)'", q["q"])
        items = [
            f
            for f in self.files.values()
            if parent in f["parents"] and (not name or f["name"] == name.group(1))
        ]
        return httpx.Response(200, json={"files": items})

    def paths(self):
        def path(f):
            p = f["parents"][0]
            return (path(self.files[p]) + "/" if p in self.files else "") + f["name"]

        return sorted(path(f) for f in self.files.values())


def _remote(drive, folder="pbx1"):
    client = httpx.Client(transport=httpx.MockTransport(drive.handler))
    dest = {"id": "g", "kind": "gdrive", "drive_id": ROOT, "folder": folder}
    return gdrive.DriveRemote(dest, KEY, client, sleep=lambda _s: None)


def _backup_dir(tmp_path, name="veyra-20261030-020000"):
    d = tmp_path / name
    d.mkdir()
    (d / "database.dump").write_bytes(b"d" * 1000)
    (d / destinations.MANIFEST).write_text("{}")
    return d


def test_directory_backup_round_trip(tmp_path):
    drive = Drive()
    rem = _remote(drive)
    art = _backup_dir(tmp_path)
    rem.upload(art)
    assert rem.names() == {art.name}
    assert "pbx1/veyra-20261030-020000/manifest.json" in drive.paths()
    assert not any(gdrive.PARTIAL in p for p in drive.paths())
    # Copying again replaces it rather than leaving two of the same name.
    rem.upload(art)
    assert sorted(p for p in drive.paths() if p.endswith("manifest.json")) == [
        "pbx1/veyra-20261030-020000/manifest.json"
    ]
    rem.delete(art.name)
    assert rem.names() == set() and not rem.exists(art.name)
    assert drive.paths() == ["pbx1"]


def test_encrypted_file_backup_and_large_file_in_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(gdrive, "CHUNK", 256 * 1024)
    drive = Drive()
    rem = _remote(drive)
    art = tmp_path / "veyra-20261030-020000.tar.age"
    art.write_bytes(b"e" * (600 * 1024))
    rem.upload(art)
    assert rem.names() == {art.name}


def test_checksum_mismatch_fails_and_the_name_is_not_taken(tmp_path):
    drive = Drive(corrupt=True)
    rem = _remote(drive)
    with pytest.raises(destinations.DestinationError, match="does not match"):
        rem.upload(_backup_dir(tmp_path))
    assert rem.names() == set()


def test_content_manager_role_fails_the_test_and_names_the_fix():
    with pytest.raises(destinations.DestinationError, match="must be a Manager"):
        _remote(Drive(can_delete=False)).test()


def test_test_leaves_nothing_behind():
    drive = Drive()
    _remote(drive).test()
    assert drive.paths() == ["pbx1"]


def test_busy_drive_is_retried():
    drive = Drive()
    rem = _remote(drive)
    drive.busy = 2
    assert rem.names() == set()


def test_archive_goes_to_its_own_folder_and_can_be_deleted(tmp_path):
    drive = Drive()
    client = httpx.Client(transport=httpx.MockTransport(drive.handler))
    dest = {"id": "g", "kind": "gdrive", "drive_id": ROOT, "folder": "pbx1"}
    rem = destinations.archive_remote(dest, secret=KEY, client=client)
    name = f"veyra-recording-{uuid.uuid4()}"
    art = tmp_path / name
    art.mkdir()
    (art / "a.ogg").write_bytes(b"audio")
    (art / destinations.MANIFEST).write_text("{}")
    rem.upload(art)
    assert f"pbx1/recordings/{name}/a.ogg" in drive.paths()
    rem.delete(name)
    assert not rem.exists(name)


def test_key_and_id_checks():
    for bad in ("not json", "{}", '{"type":"service_account"}'):
        with pytest.raises(ValueError):
            gdrive.parse_key(bad)
    assert gdrive.drive_id_of(f"https://drive.google.com/drive/folders/{ROOT}?usp=x") == ROOT
    with pytest.raises(ValueError):
        gdrive.drive_id_of("bad id!")


def test_api_stores_the_key_write_only(admin):
    bad = {"kind": "gdrive", "name": "G", "drive_id": ROOT, "service_account_json": "{}"}
    assert admin.post("/api/v1/backups/destinations", json=bad).status_code == 400
    body = {**bad, "service_account_json": KEY}
    r = admin.post("/api/v1/backups/destinations", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["has_secret"] is True and out["client_email"] == "v@p.iam.gserviceaccount.com"
    assert "PRIVATE KEY" not in r.text and "secret_ciphertext" not in r.text
    assert "PRIVATE KEY" not in admin.get("/api/v1/backups/settings").text
    # Saving without a key keeps it.
    r = admin.put(
        f"/api/v1/backups/destinations/{out['id']}",
        json={"kind": "gdrive", "name": "G2", "drive_id": ROOT},
    )
    assert r.status_code == 200 and r.json()["has_secret"] is True
    assert admin.delete(f"/api/v1/backups/destinations/{out['id']}").status_code == 204
