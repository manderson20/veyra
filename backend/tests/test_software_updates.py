# SPDX-License-Identifier: AGPL-3.0-or-later
"""Software update management (docs/SOFTWARE_UPDATES.md): release building
and metadata, download with checks, approval, the worker's start and finish,
maintenance windows, the root runner's verification, and the package list."""

import http.server
import io
import json
import shutil
import subprocess
import tarfile
import threading
from datetime import UTC, datetime, timedelta

import pytest

from veyra.cli.main import main as cli
from veyra.core.db import session_scope
from veyra.core.models import AvailableUpdate, UpdatePolicy
from veyra.core.signing import Keyring, generate_keypair
from veyra.updates import manager, release, runner

NEW = "99.0.0"


@pytest.fixture
def served(tmp_path):
    root = tmp_path / "www"
    root.mkdir()

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield root, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _repo(tmp_path, version=NEW, upgrade_sh="echo '==> Upgrading'\nexit 0\n"):
    """A tiny repository shaped like Veyra's, with prebuilt parts."""
    repo = tmp_path / f"repo-{version}"
    (repo / "backend/veyra").mkdir(parents=True)
    (repo / "backend/veyra/version.py").write_text(
        f'__version__ = "{version}"\nMODULE_API_VERSION = "1.1.0"\n'
    )
    (repo / "installer").mkdir()
    (repo / "installer/upgrade.sh").write_text("#!/bin/bash\n" + upgrade_sh)
    (repo / ".gitignore").write_text("out/\ndist/\nnode_modules/\n")
    git = ["git", "-C", str(repo), "-c", "user.email=t@example.org", "-c", "user.name=t"]
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "r"]):
        subprocess.run([*git, *args], check=True)  # noqa: S603
    (repo / "frontend/out").mkdir(parents=True)
    (repo / "frontend/out/index.html").write_text("<html></html>")
    (repo / "frontend/out/node_modules").mkdir()
    (repo / "frontend/out/node_modules/x.js").write_text("x")
    (repo / "companion/dist").mkdir(parents=True)
    (repo / "companion/dist/manifest.json").write_text("{}")
    return repo


def _publish(tmp_path, root, base, trust_dir, version=NEW, **kw):
    """Build, add and sign a release with an official key trusted in trust_dir."""
    priv, pub = generate_keypair()
    (trust_dir / "official").mkdir(parents=True, exist_ok=True)
    (trust_dir / "official" / "test-release.pub").write_text(pub)
    key = tmp_path / "release.key"
    key.write_text(priv)
    art = release.build(_repo(tmp_path, version, **kw), tmp_path / "dist")
    shutil.copy(art, root / art.name)
    meta = root / "stable.json"
    assert (
        cli(
            [
                "release",
                "add",
                str(art),
                "--url",
                f"{base}/{art.name}",
                "--metadata",
                str(meta),
                "--category",
                "security",
                "--notes",
                "Fixes",
                "--impact",
                "API restarts",
            ]
        )
        == 0
    )
    assert (
        cli(["release", "sign", str(meta), "--key-file", str(key), "--key-id", "test-release"]) == 0
    )
    return art, meta, priv


def test_release_build_contents_and_metadata(tmp_path):
    repo = _repo(tmp_path)
    art = release.build(repo, tmp_path / "dist")
    with tarfile.open(art) as tar:
        names = tar.getnames()
    top = f"veyra-{NEW}"
    assert (
        f"{top}/frontend/out/index.html" in names and f"{top}/companion/dist/manifest.json" in names
    )
    assert f"{top}/REVISION" in names and not any(
        ".git/" in n or "node_modules" in n for n in names
    )
    info = release.inspect(art)
    assert info["version"] == NEW and info["module_api"] == "1.1.0" and len(info["revision"]) == 10

    (repo / "installer/upgrade.sh").write_text("changed")
    with pytest.raises(release.ReleaseError, match="uncommitted"):
        release.build(repo, tmp_path / "dist")

    meta = tmp_path / "stable.json"
    e = release.add(
        meta, art, url="https://example.org/a.tar.gz", channel="stable", category="bugfix"
    )
    assert e["artifact"]["size"] == art.stat().st_size and e["module_api"] == "1.1.0"
    doc = json.loads(meta.read_text())
    assert doc["sequence"] == 1
    assert release.refresh(meta)["sequence"] == 2
    release.add(meta, art, url="https://example.org/b.tar.gz", channel="stable", category="bugfix")
    doc = json.loads(meta.read_text())
    assert doc["sequence"] == 3 and len(doc["releases"]) == 1  # replaced, not duplicated


def test_download_approve_start_and_finish(admin, app, tmp_path, served, monkeypatch):
    root, base = served
    settings = app.state.settings
    art, _meta, _priv = _publish(tmp_path, root, base, settings.trust_dir)
    app.state.keyring = Keyring.load(settings.trust_dir)

    r = admin.put(
        "/api/v1/updates/source",
        json={
            "url": f"{base}/stable.json",
            "token": "secret-token",
            "recipients": ["a@example.org"],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["token_set"] and r.json()["effective_url"] == f"{base}/stable.json"
    assert "secret-token" not in r.text
    assert (
        admin.put("/api/v1/updates/source", json={"url": "http://example.org/x"}).status_code == 422
    )

    assert admin.post("/api/v1/updates/check").json()["outcome"] == "ok"
    upd = admin.get("/api/v1/updates/available").json()[0]
    assert upd["version"] == NEW and upd["state"] == "available"
    uid = upd["id"]

    # Approval needs a download first.
    assert (
        admin.post(f"/api/v1/updates/available/{uid}/approve", json={"when": "now"}).status_code
        == 409
    )

    # A file replaced on the server after signing is refused.
    good = (root / art.name).read_bytes()
    (root / art.name).write_bytes(good + b"x")
    r = admin.post(f"/api/v1/updates/available/{uid}/download")
    assert r.status_code == 502 and "signed size" in r.json()["detail"]
    (root / art.name).write_bytes(good)
    r = admin.post(f"/api/v1/updates/available/{uid}/download")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "downloaded"
    stored = settings.updates_dir / NEW
    assert (stored / "release.tar.gz").read_bytes() == good and (
        stored / "metadata.json.sig"
    ).exists()

    detail = admin.get(f"/api/v1/updates/available/{uid}").json()
    assert {c["key"] for c in detail["checks"]} >= {"newer", "modules", "idle_installer"}
    assert detail["service_impact"] == "API restarts"
    # No window in the policy: only "now".
    r = admin.post(f"/api/v1/updates/available/{uid}/approve", json={"when": "window"})
    assert r.json()["code"] == "no_window"
    r = admin.post(f"/api/v1/updates/available/{uid}/approve", json={"when": "now"})
    assert r.status_code == 200 and r.json()["state"] == "approved"

    calls = []

    class Done:
        returncode = 0
        stderr = ""

    def run(cmd):
        with session_scope() as other:  # committed before systemctl runs
            assert other.get(AvailableUpdate, upd_uuid).state == "installing"
        calls.append(cmd)
        return Done()

    import uuid

    upd_uuid = uuid.UUID(uid)
    sent = []
    monkeypatch.setattr(manager, "mail_notifier", lambda db, s: lambda what, row: sent.append(what))
    with session_scope() as db:
        manager.process(db, settings, app.state.keyring, lambda: 0, run=run)
    assert calls == [["systemctl", "start", "--no-block", f"veyra-upgrade@{NEW}.service"]]

    # The runner's status file finishes it (the new worker runs NEW).
    settings.upgrade_dir.mkdir(parents=True, exist_ok=True)
    later = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    (settings.upgrade_dir / "status.json").write_text(
        json.dumps({"version": NEW, "state": "succeeded", "finished_at": later})
    )
    monkeypatch.setattr(manager, "__version__", NEW)
    with session_scope() as db:
        manager.process(db, settings, app.state.keyring, lambda: 0, run=run)
    assert admin.get("/api/v1/updates/available").json()[0]["state"] == "installed"
    assert sent == ["installed"] and not stored.exists()
    assert admin.get("/api/v1/updates/status").json()["run"]["state"] == "succeeded"


def test_failed_start_and_policy_modes(admin, app, tmp_path, served, monkeypatch):
    root, base = served
    settings = app.state.settings
    _publish(tmp_path, root, base, settings.trust_dir)
    app.state.keyring = Keyring.load(settings.trust_dir)
    admin.put("/api/v1/updates/source", json={"url": f"{base}/stable.json"})
    # Mode C downloads by itself; mode D approves allowed categories for the window.
    r = admin.put(
        "/api/v1/updates/policies/veyra_core",
        json={
            "mode": "auto_install_window",
            "auto_install_categories": ["security"],
            "maintenance_window": {"days": ["sat"], "start": "02:00", "duration_minutes": 120},
        },
    )
    assert r.status_code == 200, r.text
    assert (
        admin.put("/api/v1/updates/policies/modules", json={"mode": "download_approve"}).status_code
        == 422
    )
    admin.post("/api/v1/updates/check")
    monkeypatch.setattr(manager, "mail_notifier", lambda db, s: lambda what, row: None)

    class Denied:
        returncode = 1
        stderr = "Access denied"

    saturday_night = datetime(2026, 10, 17, 2, 30, tzinfo=UTC)
    friday = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    with session_scope() as db:
        manager.process(
            db, settings, app.state.keyring, lambda: 0, run=lambda c: Denied(), now=friday
        )
        row = db.query(AvailableUpdate).one()
        assert row.state == "approved" and row.install_when == "window"
        # In the window but a call is in progress: wait.
        manager.process(
            db, settings, app.state.keyring, lambda: 2, run=lambda c: Denied(), now=saturday_night
        )
        assert db.query(AvailableUpdate).one().state == "approved"
        manager.process(
            db, settings, app.state.keyring, lambda: 0, run=lambda c: Denied(), now=saturday_night
        )
        row = db.query(AvailableUpdate).one()
        assert row.state == "failed" and "Access denied" in row.error


def test_maintenance_windows():
    w = {"days": ["sat"], "start": "23:00", "duration_minutes": 120, "timezone": "America/Chicago"}
    # Saturday 23:30 Chicago (CDT, UTC-5) = Sunday 04:30 UTC.
    assert manager.window_open(w, datetime(2026, 10, 18, 4, 30, tzinfo=UTC))
    # Sunday 00:40 Chicago: inside, past midnight.
    assert manager.window_open(w, datetime(2026, 10, 18, 5, 40, tzinfo=UTC))
    # From 00:45 (the last 15 minutes) nothing starts.
    assert not manager.window_open(w, datetime(2026, 10, 18, 5, 46, tzinfo=UTC))
    assert not manager.window_open(w, datetime(2026, 10, 17, 4, 30, tzinfo=UTC))  # Friday night
    assert not manager.window_open(None, datetime(2026, 10, 18, 4, 30, tzinfo=UTC))
    nxt = manager.next_window_start(w, datetime(2026, 10, 15, tzinfo=UTC))
    assert nxt is not None and (nxt.weekday(), nxt.hour) == (5, 23)


def _runner_settings(settings, tmp_path, served, trust_dir=None):
    root, base = served
    _art, meta, priv = _publish(tmp_path, root, base, trust_dir or settings.trust_dir)
    d = settings.updates_dir / NEW
    d.mkdir(parents=True)
    shutil.copy(root / f"veyra-{NEW}.tar.gz", d / "release.tar.gz")
    shutil.copy(meta, d / "metadata.json")
    shutil.copy(str(meta) + ".sig", d / "metadata.json.sig")
    return d, priv


def test_runner_verifies_then_runs_the_releases_upgrade(settings, tmp_path, served):
    _runner_settings(settings, tmp_path, served)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    assert runner.main([NEW], settings=settings) == 0
    status = json.loads((settings.upgrade_dir / "status.json").read_text())
    assert status["state"] == "succeeded" and "==> Upgrading" in status["log_tail"]
    assert not (settings.upgrade_dir / "work" / NEW).exists()
    assert runner.main(["../../etc"], settings=settings) == 2


def test_runner_refuses_tampering(settings, tmp_path, served):
    d, _priv = _runner_settings(settings, tmp_path, served)
    work = settings.upgrade_dir / "work" / NEW

    # Changed after the download.
    good = (d / "release.tar.gz").read_bytes()
    (d / "release.tar.gz").write_bytes(good[:-10] + b"0123456789")
    with pytest.raises(runner.RunnerError, match="checksum"):
        runner.verify_and_unpack(settings, NEW, work)
    (d / "release.tar.gz").write_bytes(good)

    # A link planted in place of the metadata is not followed.
    real = d / "metadata.json"
    moved = d / "m.json"
    real.rename(moved)
    real.symlink_to(moved)
    with pytest.raises(runner.RunnerError, match="regular file"):
        runner.verify_and_unpack(settings, NEW, work)
    real.unlink()
    moved.rename(real)

    # Metadata signed by an unknown key.
    other, _ = generate_keypair()
    from veyra.core.signing import sign

    (d / "metadata.json.sig").write_text(sign(real.read_bytes(), other, "test-release"))
    with pytest.raises(runner.RunnerError, match="signature"):
        runner.verify_and_unpack(settings, NEW, work)


def test_runner_refuses_path_tricks(tmp_path):
    art = tmp_path / "evil.tar.gz"
    with tarfile.open(art, "w:gz") as tar:
        data = b"x"
        ti = tarfile.TarInfo(f"veyra-{NEW}/../../escape")
        ti.size = len(data)
        tar.addfile(ti, io.BytesIO(data))
    with pytest.raises(runner.RunnerError, match="Unexpected path"):
        runner._extract(art, tmp_path / "out", NEW)
    assert not (tmp_path / "escape").exists()


def test_runner_refuses_older_versions(settings, tmp_path, served):
    root, base = served
    _publish(tmp_path, root, base, settings.trust_dir, version="0.0.1")
    d = settings.updates_dir / "0.0.1"
    d.mkdir(parents=True)
    shutil.copy(root / "veyra-0.0.1.tar.gz", d / "release.tar.gz")
    shutil.copy(root / "stable.json", d / "metadata.json")
    shutil.copy(root / "stable.json.sig", d / "metadata.json.sig")
    with pytest.raises(runner.RunnerError, match="not newer"):
        runner.verify_and_unpack(settings, "0.0.1", settings.upgrade_dir / "w")


def test_failed_upgrade_reported(settings, tmp_path, served):
    _runner_settings(settings, tmp_path, served)
    # The release's own upgrade.sh fails: rebuild with a failing script.
    root, base = served
    shutil.rmtree(settings.updates_dir / NEW)
    (tmp_path / "dist").exists() and shutil.rmtree(tmp_path / "dist")
    shutil.rmtree(tmp_path / f"repo-{NEW}")
    (root / "stable.json").unlink()
    _publish(tmp_path, root, base, settings.trust_dir, upgrade_sh="echo '==> Migrating'\nexit 3\n")
    d = settings.updates_dir / NEW
    d.mkdir(parents=True)
    shutil.copy(root / f"veyra-{NEW}.tar.gz", d / "release.tar.gz")
    shutil.copy(root / "stable.json", d / "metadata.json")
    shutil.copy(root / "stable.json.sig", d / "metadata.json.sig")
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    assert runner.main([NEW], settings=settings) == 1
    status = json.loads((settings.upgrade_dir / "status.json").read_text())
    assert (
        status["state"] == "failed"
        and "Migrating" in status["error"]
        and "exit 3" in status["error"]
    )


def test_apt_parsing():
    text = (
        "Listing...\n"
        "openssl/noble-updates,noble-security 3.0.13-0ubuntu3.6 amd64 "
        "[upgradable from: 3.0.13-0ubuntu3.5]\n"
        "asterisk/noble 1:22.5.2 amd64 [upgradable from: 1:22.5.1]\n"
        "vim/noble-updates 2:9.1 amd64 [upgradable from: 2:9.0]\n"
    )
    pk = manager.parse_apt_upgradable(text)
    assert [p["name"] for p in pk] == ["openssl", "asterisk", "vim"]
    assert pk[0]["security"] and pk[1]["telephony"] and pk[2]["from"] == "2:9.0"


def test_system_packages_endpoint(admin):
    class Out:
        returncode = 0
        stdout = "Listing...\nopenssl/noble-security 3.1 amd64 [upgradable from: 3.0]\n"
        stderr = ""

    with session_scope() as db:
        manager.refresh_system_packages(db, run=lambda c: Out())
        manager.refresh_system_packages(db, run=lambda c: pytest.fail("checked once a day"))
    r = admin.get("/api/v1/updates/system-packages").json()
    assert r["counts"] == {"total": 1, "security": 1, "telephony": 0}


def test_unused_policy_row_is_harmless(settings, db_ready):
    with session_scope() as db:
        assert db.get(UpdatePolicy, "veyra_core") is not None
        assert manager.due_for_start(db, datetime.now(UTC), lambda: 0) is None
