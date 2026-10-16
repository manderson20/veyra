# SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: S603, S607
"""Milestone 17 backups (docs/PRODUCTION_HARDENING.md §2): keep policy and
schedule, the runner against a fake system, the restore checks, the
database side, the API and the alert checks."""

from __future__ import annotations

import json
import shutil
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from veyra.backups import policy, restore, runner, service
from veyra.core.db import session_scope
from veyra.core.models import Backup

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
    assert out["copies"][s["copy_dir"]]["state"] == "ok"
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
    removed = b.prune([(old.name, "scheduled"), (fresh.name.split(".")[0], "manual")])
    assert removed == [old.name] and fresh.exists() and not old.exists()


# ------------------------------------------------------------------ restore checks


def test_restore_manifest_checks():
    ok = {"format": 1, "version": "0.23.0", "ha_role": "standalone"}
    assert restore.check_manifest(ok, "0.23.0") == []
    assert restore.check_manifest(ok, "0.24.1") == []
    assert "newer" in restore.check_manifest({**ok, "version": "0.24.0"}, "0.23.0")[0]
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
    r = admin.put("/api/v1/backups/settings", json={"time": "03:15", "copy_dir": "relative"})
    assert r.status_code == 400
    r = admin.put(
        "/api/v1/backups/settings",
        json={
            "time": "03:15",
            "keep": {"daily_days": 5, "weekly_weeks": 1, "upgrades": 2},
            "recordings": True,
            "recipients": ["age1" + "q" * 58],
            "copy_dir": "/mnt/nas/veyra",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["time"] == "03:15" and r.json()["keep"]["daily_days"] == 5
    assert admin.get("/api/v1/backups/settings").json()["copy_dir"] == "/mnt/nas/veyra"
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
