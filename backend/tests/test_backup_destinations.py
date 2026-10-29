# SPDX-License-Identifier: AGPL-3.0-or-later
"""Backup destinations (docs/PRODUCTION_HARDENING.md §2.7, issue #44): the
settings and API, syncing with retry and per-destination pruning, SFTP
through the system client (faked), and S3 signing and transfers (faked)."""

import json
import re
import shlex
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from veyra.backups import destinations as dests
from veyra.backups import policy
from veyra.core.db import session_scope
from veyra.core.security import rotation
from veyra.core.security.crypto import load_installation_key

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
PRIVATE = "-----BEGIN OPENSSH PRIVATE KEY-----\nx\n"


def _backup(store: Path, at: datetime, encrypted: bool = False) -> str:
    name = policy.stamp(at)
    if encrypted:
        (store / f"{name}.tar.age").write_bytes(b"age-encrypted" * 10)
        return f"{name}.tar.age"
    d = store / name
    d.mkdir()
    (d / "db.dump").write_bytes(b"dump" * 100)
    (d / "etc.tar").write_bytes(b"etc" * 50)
    (d / "manifest.json").write_text(json.dumps({"name": name}))
    return name


# ----------------------------------------------------------------- the API


def test_destinations_api_keeps_secrets_write_only(admin, app):
    r = admin.post("/api/v1/backups/destinations", json={"kind": "directory", "path": "/mnt/nas"})
    assert r.status_code == 201, r.text
    folder = r.json()
    assert folder["target"] == "/mnt/nas" and folder["enabled"] is True

    body = {
        "kind": "s3",
        "name": "Off-site",
        "endpoint": "https://s3.us-west-002.backblazeb2.com",
        "bucket": "district-veyra",
        "region": "us-west-002",
        "prefix": "pbx1",
        "access_key_id": "0025exampleKEY",
    }
    r = admin.post("/api/v1/backups/destinations", json=body)
    assert r.status_code == 400 and "secret access key" in r.json()["detail"]
    r = admin.post("/api/v1/backups/destinations", json={**body, "secret_access_key": "s3cr3t"})
    assert r.status_code == 201, r.text
    s3 = r.json()
    assert s3["has_secret"] is True and s3["addressing"] == "path"
    assert "secret" not in json.dumps(s3).replace("has_secret", "")

    # The settings show both, without secrets; a change without the secret keeps it.
    shown = admin.get("/api/v1/backups/settings").json()
    assert [d["kind"] for d in shown["destinations"]] == ["directory", "s3"]
    assert "ciphertext" not in json.dumps(shown)
    r = admin.put(f"/api/v1/backups/destinations/{s3['id']}", json={**body, "name": "B2"})
    assert r.status_code == 200 and r.json()["has_secret"] is True and r.json()["name"] == "B2"

    # The runner gets the secret, decrypted.
    from veyra.backups import service

    key = load_installation_key(app.state.settings)
    with session_scope() as db:
        full = service.runner_settings(db, key)
        assert [d.get("secret") for d in full["destinations"]] == [None, "s3cr3t"]
        # Key rotation knows the secret.
        labels = [c.label for c in rotation.ciphers(db)]
        assert any("backup destination B2" in label for label in labels)

    # Same target twice is refused; bad values name the field's problem.
    r = admin.post("/api/v1/backups/destinations", json={"kind": "directory", "path": "/mnt/nas/"})
    assert r.status_code == 400 and r.json()["code"] == "duplicate"
    r = admin.post(
        "/api/v1/backups/destinations",
        json={"kind": "sftp", "host": "nas.example.org", "username": "bad user"},
    )
    assert r.status_code == 400 and "user name" in r.json()["detail"]

    r = admin.delete(f"/api/v1/backups/destinations/{folder['id']}")
    assert r.status_code == 204
    assert [d["id"] for d in admin.get("/api/v1/backups/settings").json()["destinations"]] == [
        s3["id"]
    ]


def test_sftp_key_and_host_key_confirmation(admin, monkeypatch):
    key = admin.get("/api/v1/backups/ssh-key").json()["public_key"]
    assert key.startswith("ssh-ed25519 ") and key.endswith(" veyra-backup")
    assert admin.get("/api/v1/backups/ssh-key").json()["public_key"] == key  # stays

    r = admin.post(
        "/api/v1/backups/destinations",
        json={"kind": "sftp", "host": "nas.example.org", "username": "veyra", "path": "backups"},
    )
    dest = r.json()
    assert dest["host_key"] is None and dest["target"] == "sftp://veyra@nas.example.org/backups"

    host_line = f"nas.example.org {KEY}"
    monkeypatch.setattr(dests, "scan_host_key", lambda host, port, run=None: host_line)
    r = admin.post(f"/api/v1/backups/destinations/{dest['id']}/test").json()
    assert r["state"] == "host_key" and r["fingerprint"].startswith("ssh-ed25519 SHA256:")
    r = admin.post(
        f"/api/v1/backups/destinations/{dest['id']}/host-key", json={"host_key": r["host_key"]}
    )
    assert r.status_code == 200
    shown = admin.get("/api/v1/backups/settings").json()["destinations"][0]
    assert shown["host_key_fingerprint"] == r.json()["fingerprint"]
    # Another server address forgets the confirmed key.
    r = admin.put(
        f"/api/v1/backups/destinations/{dest['id']}",
        json={"kind": "sftp", "host": "nas2.example.org", "username": "veyra", "path": "backups"},
    )
    assert r.json()["host_key"] is None


def test_failed_copy_raises_an_alert(admin):
    from veyra.core.models import Backup
    from veyra.reporting import alerts

    dest = admin.post(
        "/api/v1/backups/destinations",
        json={"kind": "directory", "path": "/mnt/nas", "name": "NAS"},
    ).json()
    with session_scope() as db:
        db.add(
            Backup(
                kind="scheduled",
                state="verified",
                path="/var/backups/veyra/veyra-20261029-023000",
                started_at=NOW,
                finished_at=NOW,
                copies={dest["id"]: {"state": "failed", "error": "not mounted", "name": "NAS"}},
            )
        )
    with session_scope() as db:
        found = alerts.check_backups(db, NOW)
    assert [(f.rule, f.message) for f in found if f.rule == "backup_copy_failed"] == [
        ("backup_copy_failed", "Copying to NAS failed: not mounted")
    ]
    last = admin.get("/api/v1/backups/settings").json()["destinations"][0]["last"]
    assert last["state"] == "failed"


def test_legacy_copy_dir_becomes_a_folder_destination():
    doc = policy.settings_doc({"copy_dir": "/mnt/old"})
    assert doc["destinations"] == [
        {
            "id": "copy-dir",
            "kind": "directory",
            "name": "Copy folder",
            "enabled": True,
            "keep": None,
            "path": "/mnt/old",
        }
    ]
    assert "copy_dir" not in doc


# ------------------------------------------------------------------- sync


def test_sync_copies_missing_backups_retries_and_prunes(tmp_path):
    store, target = tmp_path / "store", tmp_path / "nas"
    store.mkdir()
    target.mkdir()
    fresh = _backup(store, NOW - timedelta(hours=1))
    yesterday = _backup(store, NOW - timedelta(days=1), encrypted=True)
    old = _backup(store, NOW - timedelta(days=40))
    failed = _backup(store, NOW - timedelta(hours=2))
    verified = {n.split(".")[0]: "scheduled" for n in (fresh, yesterday, old)}
    rem = dests.DirectoryRemote({"kind": "directory", "path": str(target)})
    keep = {"daily_days": 7, "weekly_weeks": 0, "upgrades": 1}

    out = dests.sync(rem, store=store, verified=verified, keep=keep, now=NOW)
    # The new and yesterday's, not the one the destination's policy drops
    # nor the one that failed verification.
    assert out["state"] == "ok" and out["copied"] == [fresh, yesterday]
    assert rem.names() == {fresh, yesterday}
    assert (target / fresh / "manifest.json").exists() and not (target / failed).exists()
    assert not any(p.name.endswith(".partial") for p in target.iterdir())

    # Nothing new: nothing copied. A copy left half-done is not counted.
    (target / f"{fresh}.partial").mkdir()
    out = dests.sync(rem, store=store, verified=verified, keep=keep, now=NOW)
    assert out["copied"] == [] and out["count"] == 2

    # Ten days later the destination drops what its policy no longer keeps.
    out = dests.sync(rem, store=store, verified=verified, keep=keep, now=NOW + timedelta(days=10))
    assert sorted(out["removed"]) == sorted([fresh, yesterday])

    # An unmounted share fails without raising, and is retried next time.
    rem2 = dests.DirectoryRemote({"kind": "directory", "path": str(tmp_path / "gone")})
    with pytest.raises(dests.DestinationError, match="mounted"):
        dests.sync(rem2, store=store, verified=verified, keep=keep, now=NOW)


# ------------------------------------------------------------------- SFTP


class FakeSftp:
    """Runs ``sftp -b -`` batches against a local folder, as the server."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.argvs: list[list[str]] = []

    def __call__(self, argv, stdin):
        self.argvs.append(list(argv))
        out = []
        for line in (stdin or "").splitlines():
            ignore = line.startswith("-")
            words = shlex.split(line.lstrip("-"))
            try:
                out += self.do(words)
            except OSError as e:
                if not ignore:
                    return subprocess.CompletedProcess(argv, 1, "\n".join(out), str(e))
        return subprocess.CompletedProcess(argv, 0, "\n".join(out) + "\n", "")

    def p(self, path: str) -> Path:
        return self.root / path.lstrip("/")

    def do(self, w: list[str]) -> list[str]:
        cmd, args = w[0], w[1:]
        if cmd == "mkdir":
            self.p(args[0]).mkdir()
        elif cmd == "rmdir":
            self.p(args[0]).rmdir()
        elif cmd == "rm":
            target = args[0]
            if target.endswith("/*"):
                d = self.p(target[:-2])
                if not d.is_dir():
                    raise FileNotFoundError(target)
                for f in d.iterdir():
                    f.unlink()
            else:
                self.p(target).unlink()
        elif cmd == "put":
            self.p(args[1]).write_bytes(Path(args[0]).read_bytes())
        elif cmd == "rename":
            self.p(args[0]).rename(self.p(args[1]))
        elif cmd == "ls":
            d = self.p(args[-1])
            return [
                f"{'d' if f.is_dir() else '-'}rw-r--r--    1 1000 1000 "
                f"{f.stat().st_size if f.is_file() else 4096} Oct 29 12:00 {args[-1]}/{f.name}"
                for f in sorted(d.iterdir())
            ]
        return []


def test_sftp_upload_list_delete_through_the_client(tmp_path):
    server, store = tmp_path / "server", tmp_path / "store"
    (server / "home").mkdir(parents=True)
    store.mkdir()
    fake = FakeSftp(server)
    dest = {
        "kind": "sftp",
        "host": "nas.example.org",
        "port": 2222,
        "username": "veyra",
        "path": "home/backups",
        "host_key": f"nas.example.org {KEY}",
    }
    rem = dests.remote(dest, ssh_private_key=PRIVATE, run=fake)
    rem.test()
    a = _backup(store, NOW)
    b = _backup(store, NOW - timedelta(days=1), encrypted=True)
    rem.upload(store / a)
    rem.upload(store / b)
    assert rem.names() == {a, b}
    assert (server / "home/backups" / a / "db.dump").read_bytes() == (
        store / a / "db.dump"
    ).read_bytes()
    rem.delete(a)
    assert rem.names() == {b}
    argv = fake.argvs[0]
    assert argv[0] == "sftp" and "-P" in argv and argv[argv.index("-P") + 1] == "2222"
    assert "StrictHostKeyChecking=yes" in argv and argv[-1] == "veyra@nas.example.org"


def test_sftp_errors_say_what_to_do(tmp_path):
    def refused(argv, stdin):
        return subprocess.CompletedProcess(
            argv, 255, "", "veyra@nas: Permission denied (publickey)."
        )

    dest = {
        "kind": "sftp", "host": "nas", "port": 22, "username": "veyra", "path": ".",
        "host_key": f"nas {KEY}",
    }  # fmt: skip
    with pytest.raises(dests.DestinationError, match="authorized_keys"):
        dests.remote(dest, ssh_private_key="k", run=refused).test()
    with pytest.raises(dests.DestinationError, match="host key is not confirmed"):
        dests.remote({**dest, "host_key": None}, ssh_private_key="k", run=refused)


# --------------------------------------------------------------------- S3


def test_s3_signature_matches_the_aws_example():
    """The GET example of the SigV4 documentation (examplebucket, 2013-05-24)."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, content=b"0123456789")

    dest = {
        "kind": "s3",
        "endpoint": "",
        "region": "us-east-1",
        "bucket": "examplebucket",
        "prefix": "",
        "access_key_id": "AKIAIOSFODNN7EXAMPLE",
        "addressing": "virtual",
    }
    rem = dests.S3Remote(
        dest,
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=lambda: datetime(2013, 5, 24, tzinfo=UTC),
    )
    rem.host = "examplebucket.s3.amazonaws.com"
    rem._request("GET", "test.txt", headers={"Range": "bytes=0-9"})
    assert seen["auth"] == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )


class FakeBucket:
    """Enough of S3 for the client: put (checking the body's SHA-256), head,
    delete, list, and multipart uploads."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.uploads: dict[str, dict[int, bytes]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        import hashlib

        assert request.url.path.startswith("/bucket")
        key = request.url.path[len("/bucket/") :]
        q = dict(request.url.params)
        body = request.content
        if hashlib.sha256(body).hexdigest() != request.headers["x-amz-content-sha256"]:
            return httpx.Response(
                400, content=b"<Error><Code>XAmzContentSHA256Mismatch</Code></Error>"
            )
        if request.method == "GET" and q.get("list-type") == "2":
            items = "".join(
                f"<Contents><Key>{k}</Key><Size>{len(v)}</Size></Contents>"
                for k, v in sorted(self.objects.items())
                if k.startswith(q.get("prefix", ""))
            )
            return httpx.Response(
                200,
                content=(
                    '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                    f"{items}<IsTruncated>false</IsTruncated></ListBucketResult>"
                ).encode(),
            )
        if request.method == "POST" and "uploads" in q:
            self.uploads["u1"] = {}
            return httpx.Response(200, content=b"<R><UploadId>u1</UploadId></R>")
        if request.method == "PUT" and "partNumber" in q:
            self.uploads[q["uploadId"]][int(q["partNumber"])] = body
            return httpx.Response(200, headers={"etag": f'"{q["partNumber"]}"'})
        if request.method == "POST" and "uploadId" in q:
            parts = self.uploads.pop(q["uploadId"])
            self.objects[key] = b"".join(parts[n] for n in sorted(parts))
            return httpx.Response(200, content=b"<CompleteMultipartUploadResult/>")
        if request.method == "PUT":
            self.objects[key] = body
            return httpx.Response(200)
        if request.method == "HEAD":
            if key not in self.objects:
                return httpx.Response(404)
            return httpx.Response(200, headers={"content-length": str(len(self.objects[key]))})
        if request.method == "DELETE":
            self.objects.pop(key, None)
            return httpx.Response(204)
        return httpx.Response(400)


def test_s3_upload_multipart_list_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(dests, "MULTIPART_OVER", 100)
    monkeypatch.setattr(dests, "PART_SIZE", 160)
    bucket = FakeBucket()
    dest = {
        "kind": "s3",
        "endpoint": "https://minio.example.org:9000",
        "region": "us-east-1",
        "bucket": "bucket",
        "prefix": "pbx1",
        "access_key_id": "minio",
        "addressing": "path",
    }
    rem = dests.remote(
        dest, secret="minio-secret", client=httpx.Client(transport=httpx.MockTransport(bucket))
    )
    rem.test()
    assert bucket.objects == {}
    store = tmp_path / "store"
    store.mkdir()
    a = _backup(store, NOW)  # db.dump is 400 bytes: three parts
    b = _backup(store, NOW - timedelta(days=1), encrypted=True)
    rem.upload(store / a)
    rem.upload(store / b)
    assert bucket.objects[f"pbx1/{a}/db.dump"] == (store / a / "db.dump").read_bytes()
    assert rem.names() == {a, b}
    # Without its manifest a directory backup is incomplete.
    del bucket.objects[f"pbx1/{a}/manifest.json"]
    assert rem.names() == {b}
    rem.delete(b)
    assert rem.names() == set() and not any(k.endswith(".tar.age") for k in bucket.objects)


def test_s3_errors_name_the_likely_cause():
    def handler(request):
        return httpx.Response(
            403,
            content=b"<Error><Code>SignatureDoesNotMatch</Code><Message>no</Message></Error>",
        )

    dest = {
        "kind": "s3", "endpoint": "", "region": "us-east-2", "bucket": "b-x", "prefix": "",
        "access_key_id": "AKIA", "addressing": "virtual",
    }  # fmt: skip
    rem = dests.remote(
        dest, secret="x", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(
        dests.DestinationError,
        match=re.escape("403 SignatureDoesNotMatch — the secret access key or the region is wrong"),
    ):
        rem.test()


def test_rotation_knows_the_public_certificate_secrets(app):
    from veyra.core.models import SystemSetting
    from veyra.system import certificate

    key = load_installation_key(app.state.settings)
    with session_scope() as db:
        db.add(
            SystemSetting(
                key=certificate.SETTINGS_KEY,
                value={
                    "credentials_ciphertext": key.encrypt("{}", certificate.CREDENTIALS_PURPOSE),
                    "eab_hmac_ciphertext": key.encrypt("hmac", certificate.EAB_PURPOSE),
                },
            )
        )
    with session_scope() as db:
        labels = [c.label for c in rotation.ciphers(db)]
        assert rotation.check(db, key).ok
    assert f"setting {certificate.SETTINGS_KEY}.credentials_ciphertext" in labels
    assert f"setting {certificate.SETTINGS_KEY}.eab_hmac_ciphertext" in labels
