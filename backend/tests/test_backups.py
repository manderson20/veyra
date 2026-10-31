# SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: S603, S607
"""Milestone 17 backups (docs/PRODUCTION_HARDENING.md §2): keep policy and
schedule, the runner against a fake system, the restore checks, the
database side, the API and the alert checks."""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from veyra import __version__
from veyra.backups import policy, restore, runner, service
from veyra.core.db import session_scope
from veyra.core.models import AuditEvent, Backup, Installation

# ------------------------------------------------------------------ policy


def _e(name: str, kind: str, days_ago: float, now: datetime) -> policy.Entry:
    at = now - timedelta(days=days_ago)
    return policy.Entry(f"veyra-{at.strftime('%Y%m%d-%H%M%S')}", kind, at)


def test_keep_policy():
    now = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
    keep = {"daily_days": 3, "weekly_weeks": 2, "upgrades": 1}
    entries = [_e("d", "scheduled", d, now) for d in (0, 1, 2, 3, 4, 5, 9, 10, 11, 20, 30)]
    entries += [_e("u", "upgrade", d + 0.5, now) for d in (0, 40)]
    gone = {e.at for e in policy.to_delete(entries, keep, now)}
    kept = {e.at for e in entries} - gone
    # Every daily within 3 days; one per ISO week for the next 2 weeks; the newest upgrade.
    assert all(
        now - e.at <= timedelta(days=3)
        for e in entries
        if e.at in kept and e.kind != "upgrade" and now - e.at <= timedelta(days=3)
    )
    assert sum(1 for e in entries if e.at in kept and e.kind == "upgrade") == 1
    weekly_kept = [
        e
        for e in entries
        if e.at in kept and e.kind != "upgrade" and now - e.at > timedelta(days=3)
    ]
    weeks = {e.at.isocalendar()[:2] for e in weekly_kept}
    assert len(weeks) == len(weekly_kept)  # one per week
    assert all(now - e.at <= timedelta(days=3, weeks=2) for e in weekly_kept)
    assert _e("d", "scheduled", 30, now).at in gone
    assert policy.to_delete([], keep, now) == []
    assert policy.Entry.parse("veyra-20261016-030000.tar.age", "manual").at == now
    assert policy.Entry.parse("junk", "manual") is None


def test_schedule_and_settings():
    tz = ZoneInfo("America/Chicago")
    now = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)  # 03:00 Chicago
    assert policy.next_due(None, "02:30", now, tz) is True
    assert policy.next_due(None, "03:30", now, tz) is False
    yesterday = now - timedelta(days=1)
    assert policy.next_due(yesterday, "02:30", now, tz) is True
    assert policy.next_due(now - timedelta(minutes=20), "02:30", now, tz) is False
    doc = policy.settings_doc(
        {"time": "2:05", "keep": {"daily_days": -1}, "recipients": [" age1x "]}
    )
    assert (
        doc["time"] == "02:05" and doc["keep"]["daily_days"] == 0 and doc["recipients"] == ["age1x"]
    )
    with pytest.raises(ValueError):
        policy.settings_doc({"time": "25:00"})
    assert policy.valid_recipient("age1" + "q" * 58) and policy.valid_recipient(
        "ssh-ed25519 AAAA x"
    )
    assert not policy.valid_recipient("password")


# ------------------------------------------------------------------ runner


class FakeSystem:
    """psql/pg_dump/pg_restore/tar/age stand-ins; tar is real."""

    def __init__(self, tmp: Path):
        self.calls: list[list[str]] = []
        self.tmp = tmp
        self.scratch: dict[str, str] = {}
        self.fail_restore = False
        self.age = shutil.which("age") is not None

    def __call__(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        if argv[:3] == ["runuser", "-u", "postgres"]:
            cmd = argv[4:] if argv[3] == "--" else argv[3:]
            if cmd[0] == "psql":
                stmt = cmd[-1]
                db = cmd[cmd.index("-d") + 1] if "-d" in cmd else "veyra"
                if "count(*)" in stmt:
                    return runner.Result(
                        0, "7\n" if db != runner.SCRATCH_DB or not self.fail_restore else "6\n"
                    )
                if "alembic_version" in stmt:
                    return runner.Result(0, "0030\n")
                if "instance_id" in stmt:
                    return runner.Result(0, "11111111-1111-1111-1111-111111111111\n")
                return runner.Result(0, "")
            if cmd[0] == "pg_restore":
                return runner.Result(
                    0 if not self.fail_restore else 1, "", "boom" if self.fail_restore else ""
                )
            return runner.Result(0, "")
        if argv[0] == "bash" and "pg_restore" in argv[-1]:
            return runner.Result(
                0 if not self.fail_restore else 1, "", "boom" if self.fail_restore else ""
            )
        if argv[0] == "bash" and "pg_dump" in argv[-1]:
            out = Path(argv[-1].split(" > ")[-1])
            out.write_bytes(b"PGDMP fake dump")
            return runner.Result(0, "")
        if argv[0] in ("tar", "age"):
            import subprocess

            p = subprocess.run(argv, capture_output=True, text=True, check=False)
            return runner.Result(p.returncode, p.stdout, p.stderr)
        if argv[:4] == ["runuser", "-u", "veyra", "--"]:
            if "record" in argv:
                self.recorded = json.loads(argv[-1])
                return runner.Result(0, '{"id": "x"}')
            if "list" in argv:
                return runner.Result(0, "[]")
            return runner.Result(0, "{}")
        return runner.Result(0, "")


@pytest.fixture
def world(tmp_path: Path):
    data = tmp_path / "data"
    (data / "prompts").mkdir(parents=True)
    (data / "prompts" / "hello.wav").write_bytes(b"RIFF")
    (data / "recordings").mkdir()
    (data / "recordings" / "r.wav").write_bytes(b"R")
    etc = tmp_path / "etc" / "veyra"
    (etc / "secrets").mkdir(parents=True)
    (etc / "secrets" / "installation.key").write_text("k")
    store = tmp_path / "store"
    status = tmp_path / "status"
    ast = tmp_path / "etc" / "asterisk"
    (ast / "veyra").mkdir(parents=True)
    (ast / "veyra" / "pjsip.endpoints.conf").write_text("[x]\n")
    vm = tmp_path / "spool" / "voicemail"
    (vm / "default" / "100" / "INBOX").mkdir(parents=True)
    return {
        "data": data,
        "etc": etc,
        "store": store,
        "status": status,
        "sys": FakeSystem(tmp_path),
        "ast": ast,
        "vm": vm,
    }


def test_runner_takes_verifies_and_records(world):
    s = {
        "recipients": [],
        "copy_dir": str(world["store"].parent / "copy"),
        "keep": {},
        "recordings": True,
    }
    (world["store"].parent / "copy").mkdir()
    out = runner.run_backup(
        "manual",
        created_by="test",
        run=world["sys"],
        store=world["store"],
        status_dir=world["status"],
        settings=s,
        data_dir=world["data"],
        config_dir=world["etc"],
        asterisk_etc=world["ast"],
        voicemail=world["vm"],
    )
    assert out["state"] == "verified", out.get("error")
    names = [p["name"] for p in out["parts"]]
    assert names == [
        "db.dump",
        "etc.tar",
        "engine.tar",
        "data.tar",
        "voicemail.tar",
        "recordings.tar",
    ]
    bdir = Path(out["path"])
    assert bdir.is_dir() and (bdir / "manifest.json").exists()
    with tarfile.open(bdir / "data.tar") as t:
        assert "prompts/hello.wav" in t.getnames()
    with tarfile.open(bdir / "etc.tar") as t:
        assert "veyra/secrets/installation.key" in t.getnames()
    assert (
        out["verify"]["ok"] and out["verify"]["schema"] and out["verify"]["counts"]["users"]["ok"]
    )
    # The copy directory of earlier releases is a folder destination now.
    assert out["copies"]["copy-dir"]["state"] == "ok", out["copies"]
    assert out["copies"]["copy-dir"]["copied"] == [bdir.name]
    assert (Path(s["copy_dir"]) / bdir.name / "manifest.json").exists()
    assert (
        world["sys"].recorded["name"] == bdir.name and world["sys"].recorded["state"] == "verified"
    )
    status = json.loads((world["status"] / "status.json").read_text())
    assert status["state"] == "finished" and status["backup"] == bdir.name
    assert oct(bdir.stat().st_mode & 0o777) == "0o700"


def test_runner_failed_restore_test_is_reported(world):
    world["sys"].fail_restore = True
    out = runner.run_backup(
        "scheduled",
        run=world["sys"],
        store=world["store"],
        status_dir=world["status"],
        settings={"recipients": [], "keep": {}},
        data_dir=world["data"],
        config_dir=world["etc"],
        asterisk_etc=world["ast"],
        voicemail=world["vm"],
    )
    assert out["state"] == "failed" and "restore test" in out["error"]
    assert world["sys"].recorded["state"] == "failed"
    # The scratch database is always dropped.
    drops = [c for c in world["sys"].calls if "DROP DATABASE" in c[-1]]
    assert len(drops) >= 2


@pytest.mark.skipif(
    shutil.which("age") is None or shutil.which("age-keygen") is None, reason="age not installed"
)
def test_runner_encrypts_with_age(world, tmp_path):
    import subprocess

    ident = tmp_path / "id.txt"
    subprocess.run(["age-keygen", "-o", str(ident)], check=True, capture_output=True)
    recipient = subprocess.run(
        ["age-keygen", "-y", str(ident)], check=True, capture_output=True, text=True
    ).stdout.strip()
    out = runner.run_backup(
        "manual",
        run=world["sys"],
        store=world["store"],
        status_dir=world["status"],
        settings={"recipients": [recipient], "keep": {}},
        data_dir=world["data"],
        config_dir=world["etc"],
        asterisk_etc=world["ast"],
        voicemail=world["vm"],
    )
    assert out["state"] == "verified" and out["path"].endswith(".tar.age")
    assert not (world["store"] / out["name"]).exists()  # plaintext gone
    # Restore unpacks it with the identity.
    work = tmp_path / "work"
    work.mkdir()
    d = restore.unpack(Path(out["path"]), ident, world["sys"], work)
    assert (d / "manifest.json").exists()
    restore.verify_parts(d, json.loads((d / "manifest.json").read_text()))


def test_runner_prunes_by_policy(world):
    now = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
    store = world["store"]
    store.mkdir()
    old = store / f"veyra-{(now - timedelta(days=40)).strftime('%Y%m%d-%H%M%S')}"
    old.mkdir()
    fresh = store / f"veyra-{(now - timedelta(days=1)).strftime('%Y%m%d-%H%M%S')}.tar.age"
    fresh.write_bytes(b"x")
    b = runner.Backup(
        "manual",
        {"keep": {"daily_days": 3, "weekly_weeks": 2, "upgrades": 1}},
        store,
        world["sys"],
        now=now,
    )
    removed = b.prune(
        [
            {"name": old.name, "kind": "scheduled"},
            {"name": fresh.name.split(".")[0], "kind": "manual"},
        ]
    )
    assert removed == [old.name] and fresh.exists() and not old.exists()


# ------------------------------------------------------------------ restore checks


def test_restore_manifest_checks():
    ok = {"format": 1, "version": "0.23.0", "ha_role": "standalone"}
    assert restore.check_manifest(ok, "0.23.0") == []
    assert restore.check_manifest(ok, "0.24.1") == []
    assert "newer" in restore.check_manifest({**ok, "version": "0.24.0"}, "0.23.0")[0]
    assert "newer" in restore.check_manifest({**ok, "version": "0.23.1"}, "0.23.0")[0]
    assert "HA" in restore.check_manifest({**ok, "ha_role": "primary"}, "0.23.0")[0]
    assert "format" in restore.check_manifest({"format": 2}, "0.23.0")[0]


# ------------------------------------------------------------------ database side and API


@pytest.fixture
def recorder(monkeypatch):
    calls: list[list[str]] = []

    class R:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(service, "systemctl", lambda cmd: calls.append(cmd) or R())
    monkeypatch.setattr(service, "running", lambda path=None: False)
    return calls


def test_settings_rows_summary_and_tick(admin, recorder):
    r = admin.put("/api/v1/backups/settings", json={"time": "03:15", "recipients": ["nope"]})
    assert r.status_code == 400 and r.json()["code"] == "bad_recipient"
    r = admin.post("/api/v1/backups/destinations", json={"kind": "directory", "path": "relative"})
    assert r.status_code == 400 and "absolute" in r.json()["detail"]
    r = admin.put(
        "/api/v1/backups/settings",
        json={
            "time": "03:15",
            "keep": {"daily_days": 5, "weekly_weeks": 1, "upgrades": 2},
            "recordings": True,
            "recipients": ["age1" + "q" * 58],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["time"] == "03:15" and r.json()["keep"]["daily_days"] == 5
    # Nothing yet: stale.
    lst = admin.get("/api/v1/backups").json()
    assert lst["summary"]["stale"] is True and lst["backups"] == []
    # The runner records a backup.
    with session_scope() as db:
        row = service.record(
            db,
            {
                "name": "veyra-20261016-031500",
                "kind": "scheduled",
                "state": "verified",
                "started_at": "2026-10-01T03:15:00+00:00",
                "finished_at": "2026-10-01T03:16:00+00:00",
                "path": "/var/backups/veyra/veyra-20261016-031500.tar.age",
                "encrypted": True,
                "recipients": ["age1qqqq…"],
                "bytes": 1234,
                "parts": [{"name": "db.dump", "bytes": 10, "sha256": "x"}],
                "verify": {"ok": True, "counts": {"users": {"ok": True}}},
                "manifest": {"name": "veyra-20261016-031500", "version": "0.23.0"},
            },
        )
        assert row.state == "verified"
        # A second record for the same name updates it (pruned later).
        service.record(
            db,
            {
                "name": "veyra-20261016-031500",
                "kind": "scheduled",
                "state": "verified",
                "started_at": "2026-10-01T03:15:00+00:00",
                "removed": [],
            },
        )
        assert db.query(Backup).count() == 1
    lst = admin.get("/api/v1/backups").json()
    assert (
        len(lst["backups"]) == 1
        and lst["backups"][0]["encrypted"]
        and lst["backups"][0]["version"] == "0.23.0"
    )
    assert "counts" not in lst["backups"][0]["verify"] and lst["backups"][0]["verify"]["ok"] is True
    assert lst["summary"]["stale"] is True  # the only good backup is two weeks old
    one = admin.get(f"/api/v1/backups/{lst['backups'][0]['id']}").json()
    assert one["verify"]["counts"]["users"]["ok"] and one["manifest"]["version"] == "0.23.0"
    # Run now and delete go through the unit.
    assert admin.post("/api/v1/backups/run").status_code == 202
    assert recorder[-1] == ["systemctl", "start", "--no-block", "veyra-backup@run-manual.service"]
    r = admin.delete(f"/api/v1/backups/{lst['backups'][0]['id']}")
    assert (
        r.status_code == 202
        and recorder[-1][-1] == f"veyra-backup@delete-{lst['backups'][0]['id']}.service"
    )
    assert admin.get("/api/v1/backups/status").json()["state"] == "idle"
    # The worker's tick starts the scheduled unit once per day.
    now = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
    with session_scope() as db:
        assert service.tick(db, now, ZoneInfo("UTC")) is True
        assert recorder[-1][-1] == "veyra-backup@run.service"
        assert service.tick(db, now + timedelta(minutes=5), ZoneInfo("UTC")) is False
        assert db.query(Backup).filter_by(kind="scheduled", state="running").count() == 1
    # Disabled: never.
    admin.put("/api/v1/backups/settings", json={"enabled": False})
    with session_scope() as db:
        assert service.tick(db, now + timedelta(days=1), ZoneInfo("UTC")) is False


def test_backup_alerts(admin):
    from veyra.core.models.base import utcnow
    from veyra.reporting import alerts

    with session_scope() as db:
        found = {f.rule for f in alerts.check_backups(db, utcnow())}
        assert found == {"backup_stale"}
        service.record(
            db,
            {
                "name": "veyra-20261016-000000",
                "kind": "manual",
                "state": "failed",
                "error": "disk full",
                "started_at": utcnow().isoformat(),
            },
        )
        found = {f.rule for f in alerts.check_backups(db, utcnow())}
        assert found == {"backup_failed", "backup_stale"}
        service.record(
            db,
            {
                "name": "veyra-20261016-000001",
                "kind": "manual",
                "state": "verified",
                "started_at": utcnow().isoformat(),
                "finished_at": utcnow().isoformat(),
            },
        )
        assert alerts.check_backups(db, utcnow()) == []
        service.save_settings(db, {"enabled": False}, None)
        db.commit()


def test_scheduled_run_adopts_the_pending_row(admin, recorder):
    """The worker's row (named by its clock) is the one the runner's report
    updates, even when the runner's stamp is a second later; a pending row
    the unit never reported on is failed after STALE_RUNNING_HOURS."""
    now = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
    with session_scope() as db:
        assert service.tick(db, now, ZoneInfo("UTC")) is True
        later = now + timedelta(seconds=1)
        row = service.record(
            db,
            {
                "name": policy.stamp(later),
                "kind": "scheduled",
                "state": "failed",
                "path": f"/var/backups/veyra/{policy.stamp(later)}",
                "started_at": later.isoformat(),
                "finished_at": (later + timedelta(seconds=3)).isoformat(),
                "error": "boom",
            },
        )
        db.commit()
        assert db.query(Backup).filter_by(kind="scheduled").count() == 1
        assert row.state == "failed" and row.path.endswith(policy.stamp(later))
        # A deletion record carries no start: the row keeps its own.
        service.record(db, {"name": policy.stamp(later), "kind": "scheduled", "state": "deleted"})
        assert row.state == "deleted" and row.started_at == later
        # A second pending row that nobody reports on.
        assert service.tick(db, now + timedelta(days=1), ZoneInfo("UTC")) is True
        pending = db.query(Backup).filter_by(kind="scheduled", state="running").one()
        service.tick(db, now + timedelta(days=1, hours=9), ZoneInfo("UTC"))
        db.refresh(pending)
        assert pending.state == "failed" and "did not report" in (pending.error or "")


def test_settings_partial_update_keeps_the_rest(admin):
    r = admin.put(
        "/api/v1/backups/settings",
        json={"recipients": ["age1tjp6mpjd2jcnsyujzl4efy36jy4zm9mawtqfkkrn2nnflcxwhfkq9cxc3m"]},
    )
    assert r.status_code == 200 and len(r.json()["recipients"]) == 1
    r = admin.put("/api/v1/backups/settings", json={"time": "04:00"})
    assert r.status_code == 200
    assert len(r.json()["recipients"]) == 1 and r.json()["time"] == "04:00"
    assert r.json()["enabled"] is True
    r = admin.put("/api/v1/backups/settings", json={"recipients": []})
    assert r.json()["recipients"] == [] and r.json()["time"] == "04:00"


def test_prepare_download(tmp_path, monkeypatch):
    """Issue #348: root's copy for the page, encrypted or as a tar of the folder."""
    monkeypatch.setattr(runner.shutil, "chown", lambda *a, **k: None)
    store, out = tmp_path / "store", tmp_path / "out"
    store.mkdir()
    name = "veyra-20261030-120000"
    (store / f"{name}.tar.age").write_bytes(b"age-bytes")
    bid = "0f0e0d0c-0b0a-0908-0706-050403020100"
    assert runner.prepare_download(bid, name, store=store, out=out)
    state = json.loads((out / f"{bid}.json").read_text())
    assert state["state"] == "ready" and state["filename"] == f"{name}.tar.age"
    assert state["bytes"] == 9 and state["sha256"] == runner.sha256_file(store / f"{name}.tar.age")
    assert (out / state["file"]).stat().st_mode & 0o777 == 0o640
    assert service.download_file(uuid.UUID(bid), out) == out / state["file"]

    # A new one replaces it; a folder becomes a tar; the store is untouched.
    (store / f"{name}.tar.age").unlink()
    (store / name).mkdir()
    (store / name / "db.dump").write_text("x")
    other = "1f0e0d0c-0b0a-0908-0706-050403020100"
    assert runner.prepare_download(other, name, store=store, out=out)
    assert not (out / f"{bid}.json").exists()
    state = json.loads((out / f"{other}.json").read_text())
    with tarfile.open(out / state["file"]) as archive:
        assert f"{name}/db.dump" in archive.getnames()
    assert (store / name / "db.dump").exists()

    # Gone, and names that are not backups.
    assert not runner.prepare_download(other, "veyra-20261030-120001", store=store, out=out)
    assert json.loads((out / f"{other}.json").read_text())["state"] == "failed"
    assert service.download_file(uuid.UUID(other), out) is None
    for bad in ("../../etc/passwd", "veyra-20261030-120000./../../etc/shadow"):
        with pytest.raises(runner.BackupError):
            runner.prepare_download(other, bad, store=store, out=out)
    runner.clean_downloads(out)
    assert not list(out.iterdir())


def test_download_api(admin, monkeypatch, tmp_path):
    class R:
        returncode = 0
        stderr = ""

    calls = []
    monkeypatch.setattr(service, "systemctl", lambda cmd: calls.append(cmd) or R())
    monkeypatch.setattr(service.download_state, "__defaults__", (tmp_path,))
    monkeypatch.setattr(service.download_file, "__defaults__", (tmp_path,))

    def row(state, encrypted):
        return Backup(kind="manual", state=state, path="/x", encrypted=encrypted, manifest={})

    with session_scope() as db:
        clear, enc, failed = row("verified", False), row("verified", True), row("failed", False)
        db.add_all([clear, enc, failed])
        db.flush()
        clear_id, enc_id, failed_id = clear.id, enc.id, failed.id
    base = "/api/v1/backups"
    r = admin.post(f"{base}/{clear_id}/download", json={})
    assert r.status_code == 409 and r.json()["code"] == "unencrypted"
    assert admin.post(f"{base}/{failed_id}/download", json={}).status_code == 409
    assert not calls
    r = admin.post(f"{base}/{clear_id}/download", json={"allow_unencrypted": True})
    assert r.status_code == 202
    assert admin.post(f"{base}/{enc_id}/download", json={}).status_code == 202
    assert calls[-1][3] == f"veyra-backup@download-{enc_id}.service"
    assert admin.get(f"{base}/{enc_id}/download").json()["state"] == "none"
    assert admin.get(f"{base}/{enc_id}/download/file").status_code == 409
    (tmp_path / f"{enc_id}.tar.age").write_bytes(b"secret-age")
    (tmp_path / f"{enc_id}.json").write_text(
        json.dumps(
            {
                "state": "ready",
                "file": f"{enc_id}.tar.age",
                "filename": "20261030-120001.tar.age",
                "bytes": 10,
                "sha256": "abc",
            }
        )
    )
    assert admin.get(f"{base}/{enc_id}/download").json()["sha256"] == "abc"
    r = admin.get(f"{base}/{enc_id}/download/file")
    assert r.status_code == 200 and r.content == b"secret-age"
    assert "20261030-120001.tar.age" in r.headers["content-disposition"]
    # The clean-up job starts when the stream ends, and the download is on record.
    assert calls[-1][3] == "veyra-backup@download-clean.service"
    with session_scope() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "backups.download")).one()
        assert ev.details["sha256"] == "abc" and ev.details["encrypted"] is True


def test_clean_downloads_due(tmp_path):
    assert not service.clean_downloads_due(tmp_path / "none")
    assert not service.clean_downloads_due(tmp_path)
    (tmp_path / "a.tar").write_text("x")
    assert not service.clean_downloads_due(tmp_path)
    assert service.clean_downloads_due(tmp_path, now=time.time() + 7 * 3600)


def test_delete_accepts_only_a_plain_name(tmp_path):
    with pytest.raises(runner.BackupError):
        runner.delete_backup("veyra-20261030-120000./../../victim", store=tmp_path)


# ------------------------------------------------------------------ restore from the web


NAME = "veyra-20261030-120000"
BID = "0f0e0d0c-0b0a-0908-0706-050403020100"


def _restore_world(tmp_path, *, version=__version__, identity=""):
    """A backup directory in a store and a request from the service account."""
    store = tmp_path / "store"
    folder = store / NAME
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(
        json.dumps({"format": 1, "version": version, "name": NAME, "parts": []})
    )
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"id": "r1", "backup_id": BID, "identity": identity, "actor": "a"})
    )
    calls = []

    def run(argv):
        argv = list(argv)
        calls.append(argv)
        if "list" in argv:
            return runner.Result(0, json.dumps([{"id": BID, "name": NAME}]))
        return runner.Result(0, "")

    kw = {
        "run": run,
        "request": request,
        "request_owner": None,
        "store": store,
        "status_dir": tmp_path / "status",
        "public_dir": tmp_path / "public",
    }
    return kw, calls


def _stopped(calls):
    return any(c[:2] == ["systemctl", "stop"] and "veyra-api" in c for c in calls)


def test_restore_unit_takes_a_safety_backup_then_restores(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "known_backups", lambda run: [{"id": BID, "name": NAME}])
    monkeypatch.setattr(restore, "known_backups", lambda run: [{"id": BID, "name": NAME}])
    kw, calls = _restore_world(tmp_path)
    order = []

    def safety(kind, **a):
        assert a["local_only"] is True and not _stopped(calls)
        order.append("safety")
        return {"name": "veyra-20261031-010000", "state": "verified"}

    assert restore.restore_unit(BID, backup=safety, **kw)
    assert order == ["safety"] and _stopped(calls)
    assert not kw["request"].exists()
    state = json.loads((tmp_path / "status" / "restore.json").read_text())
    assert state["state"] == "finished" and state["safety_backup"] == "veyra-20261031-010000"
    public = json.loads((tmp_path / "public" / "status.json").read_text())
    assert public["id"] == "r1" and "error" not in public
    # The safety backup and the audit entry go into the restored database.
    assert any("record" in c for c in calls) and any("restore-note" in c for c in calls)


def test_restore_unit_failures_before_the_stop_change_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(restore, "known_backups", lambda run: [{"id": BID, "name": NAME}])
    # A failed safety backup.
    kw, calls = _restore_world(tmp_path / "a")
    bad = lambda kind, **a: {"state": "failed", "error": "disk full"}  # noqa: E731
    assert not restore.restore_unit(BID, backup=bad, **kw)
    assert not _stopped(calls)
    state = json.loads((tmp_path / "a" / "status" / "restore.json").read_text())
    assert state["state"] == "failed" and "disk full" in state["error"] and not state["stopped"]
    # A backup from a newer release: refused before even the safety backup.
    kw, calls = _restore_world(tmp_path / "b", version="99.0.0")

    def never(kind, **a):
        raise AssertionError("no safety backup for a refused backup")

    assert not restore.restore_unit(BID, backup=never, **kw)
    assert not _stopped(calls)
    # A request for another backup, or a name that is not a stamp.
    kw, calls = _restore_world(tmp_path / "c")
    assert not restore.restore_unit("00000000-0000-0000-0000-000000000000", backup=never, **kw)
    monkeypatch.setattr(restore, "known_backups", lambda run: [{"id": BID, "name": "../../etc"}])
    kw, calls = _restore_world(tmp_path / "d")
    assert not restore.restore_unit(BID, backup=never, **kw)
    assert not _stopped(calls)


def test_restore_unit_restarts_the_services_after_a_late_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(restore, "known_backups", lambda run: [{"id": BID, "name": NAME}])
    kw, calls = _restore_world(tmp_path)
    (tmp_path / "store" / NAME / "manifest.json").write_text(
        json.dumps(
            {
                "format": 1,
                "version": __version__,
                "name": NAME,
                "parts": [{"name": "db.dump", "sha256": "x"}],
            }
        )
    )
    (tmp_path / "store" / NAME / "db.dump").write_bytes(b"d")
    monkeypatch.setattr(restore, "verify_parts", lambda d, m: None)
    inner = kw["run"]

    def run(argv):
        if "pg_restore" in " ".join(argv):
            inner(argv)
            return runner.Result(1, "", "boom")
        return inner(argv)

    kw["run"] = run
    ok = lambda kind, **a: {"name": "veyra-20261031-010000", "state": "verified"}  # noqa: E731
    assert not restore.restore_unit(BID, backup=ok, **kw)
    state = json.loads((tmp_path / "status" / "restore.json").read_text())
    assert state["state"] == "failed" and state["stopped"] and "boom" in state["error"]
    assert state["safety_backup"] == "veyra-20261031-010000"
    assert calls[-1][:2] == ["systemctl", "start"] and "veyra-api" in calls[-1]
    # The public copy carries no error text.
    assert "boom" not in (tmp_path / "public" / "status.json").read_text()


def test_read_request_is_careful(tmp_path):
    good = tmp_path / "r.json"
    good.write_text('{"id": "1"}')
    link = tmp_path / "l.json"
    link.symlink_to(good)
    with pytest.raises(runner.BackupError):
        restore.read_request(link, owner=None)
    assert good.exists()
    assert restore.read_request(good, owner=None) == {"id": "1"}
    assert not good.exists()
    with pytest.raises(runner.BackupError):
        restore.read_request(good, owner=None)
    good.write_text('{"id": "1"}')
    with pytest.raises(runner.BackupError):
        restore.read_request(good, owner="root" if os.geteuid() else "nobody")
    assert restore.identity_lines("# public key: age1x\nAGE-SECRET-KEY-1ABC\nrm -rf /\n") == [
        "AGE-SECRET-KEY-1ABC"
    ]


def test_run_backup_local_only_leaves_the_keep_policy_alone(world):
    (world["store"]).mkdir(parents=True, exist_ok=True)
    old = world["store"] / "veyra-20200101-000000"
    old.mkdir()
    settings = {"keep": {"daily": 1, "weekly": 0, "monthly": 0}}
    args = {
        "run": world["sys"],
        "store": world["store"],
        "status_dir": world["status"],
        "data_dir": world["data"],
        "config_dir": world["etc"],
        "asterisk_etc": world["ast"],
        "voicemail": world["vm"],
        "settings": settings,
    }
    out = runner.run_backup("manual", local_only=True, **args)
    assert out["state"] == "verified" and out["removed"] == [] and old.exists()


def test_restore_api(admin, monkeypatch, tmp_path):
    request = tmp_path / "request.json"
    monkeypatch.setattr(service, "RESTORE_REQUEST", request)
    monkeypatch.setattr(service.write_restore_request, "__defaults__", (request,))
    state_file = tmp_path / "restore.json"
    monkeypatch.setattr(service.restore_state, "__defaults__", (state_file,))
    monkeypatch.setattr(service.restore_running, "__defaults__", (state_file, None))
    monkeypatch.setattr(service, "running", lambda *a: False)
    started = []
    monkeypatch.setattr(service, "start", started.append)
    with session_scope() as db:
        enc = Backup(kind="manual", state="verified", path="/x", encrypted=True, manifest={})
        clear = Backup(kind="manual", state="verified", path="/x", encrypted=False, manifest={})
        failed = Backup(kind="manual", state="failed", path="/x", encrypted=False, manifest={})
        db.add_all([enc, clear, failed])
        db.flush()
        enc_id, clear_id, failed_id = enc.id, clear.id, failed.id
    base = "/api/v1/backups"
    key = "# public key: age1x\nAGE-SECRET-KEY-1ABC\n"
    assert admin.get(f"{base}/restore").json() == {"state": "none"}
    # Confirmation, state and the private key are all checked; nothing starts.
    r = admin.post(f"{base}/{enc_id}/restore", json={"identity": key})
    assert r.status_code == 422 and r.json()["code"] == "not_confirmed"
    r = admin.post(f"{base}/{failed_id}/restore", json={"confirm": "RESTORE"})
    assert r.status_code == 409 and r.json()["code"] == "not_verified"
    r = admin.post(f"{base}/{enc_id}/restore", json={"confirm": "RESTORE", "identity": "nonsense"})
    assert r.status_code == 422 and "nonsense" not in r.text
    assert not started and not request.exists()
    # Busy.
    monkeypatch.setattr(service, "running", lambda *a: True)
    r = admin.post(f"{base}/{clear_id}/restore", json={"confirm": "RESTORE"})
    assert r.status_code == 409 and r.json()["code"] == "busy"
    monkeypatch.setattr(service, "running", lambda *a: False)
    state_file.write_text(
        json.dumps({"state": "running", "started_at": datetime.now(UTC).isoformat()})
    )
    r = admin.post(f"{base}/{clear_id}/restore", json={"confirm": "RESTORE"})
    assert r.status_code == 409 and r.json()["code"] == "busy"
    state_file.unlink()
    # A pair.
    with session_scope() as db:
        db.scalar(select(Installation)).deployment_mode = "ha"
    r = admin.post(f"{base}/{clear_id}/restore", json={"confirm": "RESTORE"})
    assert r.status_code == 409 and r.json()["code"] == "ha_enabled"
    with session_scope() as db:
        db.scalar(select(Installation)).deployment_mode = "standalone"
    # Started: only the key lines reach root, and the file is the account's alone.
    r = admin.post(f"{base}/{enc_id}/restore", json={"confirm": "RESTORE", "identity": key})
    assert r.status_code == 202
    assert started == [f"restore-{enc_id}"]
    assert request.stat().st_mode & 0o777 == 0o600
    sent = json.loads(request.read_text())
    assert sent["identity"] == "AGE-SECRET-KEY-1ABC" and sent["id"] == r.json()["id"]
    with session_scope() as db:
        rows = db.scalars(select(AuditEvent).where(AuditEvent.action == "backups.restore_start"))
        entry = rows.one()
        assert "AGE-SECRET" not in json.dumps(entry.details)

    # The unit cannot start: the private key does not stay behind.
    def refuse(instance):
        raise service.BackupError(503, "unit_failed", "no")

    monkeypatch.setattr(service, "start", refuse)
    assert admin.post(f"{base}/{clear_id}/restore", json={"confirm": "RESTORE"}).status_code == 503
    assert not request.exists()


def test_restore_note_writes_the_audit_entry(admin):
    import argparse

    from veyra.cli.main import cmd_backup_restore_note

    note = {"backup": NAME, "safety_backup": "s", "actor": "owner", "ip": "10.0.0.9", "parts": []}
    assert cmd_backup_restore_note(argparse.Namespace(json=json.dumps(note))) == 0
    with session_scope() as db:
        entry = db.scalars(select(AuditEvent).where(AuditEvent.action == "backups.restore")).one()
        assert entry.actor_label == "owner" and entry.details["backup"] == NAME
