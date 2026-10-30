# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recording archive (docs/RECORDING_ARCHIVE.md)."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from veyra.backups import destinations, recording_archive, service
from veyra.core.db import session_scope
from veyra.core.models import CallRecording


def _rec(db, tmp_path, **kw):
    rid = uuid.uuid4()
    (tmp_path / f"{rid}.ogg").write_bytes(b"audio-bytes")
    row = CallRecording(id=rid, ref=str(rid)[:30], path=f"{rid}.ogg", format="ogg", **kw)
    db.add(row)
    db.flush()
    return row


def _settings(path):
    return {
        "destinations": [{"id": "d1", "kind": "directory", "name": "NAS", "path": str(path)}],
        "recording_archive": {"destination_id": "d1"},
    }


@pytest.fixture
def stores(tmp_path, admin):
    src, dest = tmp_path / "rec", tmp_path / "nas"
    src.mkdir()
    dest.mkdir()
    yield src, dest
    with session_scope() as db:
        db.query(CallRecording).delete()
        row = db.get(recording_archive.SystemSetting, recording_archive.STATUS_KEY)
        if row is not None:
            db.delete(row)


def test_copy_then_delete_with_the_recording(stores):
    src, dest = stores
    with session_scope() as db:
        rec = _rec(db, src, key_ciphertext="wrapped")
        rid = rec.id
        todo = recording_archive.work(db, "d1")
    assert [i["id"] for i in todo["copy"]] == [str(rid)]

    result = recording_archive.run(_settings(dest), todo, src)
    assert result["errors"] == [] and result["copied"][0]["destination"] == "d1"
    folder = dest / "recordings" / recording_archive.name_of(rid)
    assert (folder / f"{rid}.ogg").read_bytes() == b"audio-bytes"
    assert json.loads((folder / "manifest.json").read_text())["wrapped_key"] == "wrapped"

    with session_scope() as db:
        recording_archive.report(db, result)
        assert db.get(CallRecording, rid).archived_at is not None
        # Nothing more to do while the recording lives.
        assert recording_archive.work(db, "d1") == {"copy": [], "remove": []}
        assert recording_archive.uses_destination(db, "d1") == 1
        # Deleted: by hand or by retention, the row looks the same.
        db.get(CallRecording, rid).deleted_at = datetime.now(UTC)
        db.flush()
        todo = recording_archive.work(db, "d1")
    assert todo["remove"] == [{"id": str(rid), "destination": "d1"}]

    result = recording_archive.run(_settings(dest), todo, src)
    assert result["removed"] == [str(rid)] and not folder.exists()
    with session_scope() as db:
        recording_archive.report(db, result)
        assert db.get(CallRecording, rid).archive_removed_at is not None
        assert recording_archive.work(db, "d1") == {"copy": [], "remove": []}
        assert recording_archive.uses_destination(db, "d1") == 0


class Stubborn(destinations.DirectoryRemote):
    """A server that says yes to a delete and keeps the file, as ``-rm`` hides."""

    def delete(self, name):
        pass


def test_a_copy_still_there_is_not_marked_removed(stores):
    src, dest = stores
    (dest / "recordings").mkdir()
    rid = uuid.uuid4()
    (dest / "recordings" / recording_archive.name_of(rid)).mkdir()
    sub = {"id": "d1", "kind": "directory", "path": str(dest / "recordings")}
    result = recording_archive.run(
        _settings(dest),
        {"copy": [], "remove": [{"id": str(rid), "destination": "d1"}]},
        src,
        make_remote=lambda d: Stubborn(sub),
    )
    assert result["removed"] == []
    assert "still there" in result["errors"][0]


def test_unreachable_destination_keeps_everything_waiting(stores):
    src, dest = stores
    with session_scope() as db:
        rec = _rec(db, src)
        rid = rec.id
        todo = recording_archive.work(db, "d1")
    settings = _settings(dest / "not-mounted")
    result = recording_archive.run(settings, todo, src)
    assert result["copied"] == [] and "is not a folder" in result["errors"][0]
    with session_scope() as db:
        recording_archive.report(db, result)
        assert db.get(CallRecording, rid).archived_at is None
        assert recording_archive.last_errors(db)
        assert any(n == "Recording archive" for n, _ in service.summary(db)["copies_failed"])


def test_a_path_outside_the_recordings_folder_is_not_copied(stores):
    src, dest = stores
    (src.parent / "secret").write_text("x")
    item = {"id": str(uuid.uuid4()), "path": "../secret"}
    result = recording_archive.run(_settings(dest), {"copy": [item], "remove": []}, src)
    assert result["copied"] == [] and "not on this server" in result["errors"][0]


def test_a_copy_of_a_recording_deleted_during_the_run_is_still_removed(stores):
    src, dest = stores
    with session_scope() as db:
        rec = _rec(db, src)
        rid = rec.id
        todo = recording_archive.work(db, "d1")
        rec.deleted_at = datetime.now(UTC)
    result = recording_archive.run(_settings(dest), todo, src)
    with session_scope() as db:
        recording_archive.report(db, result)
        assert recording_archive.work(db, "d1")["remove"] == [{"id": str(rid), "destination": "d1"}]


def test_worker_starts_the_job_only_when_due(stores, monkeypatch):
    src, _ = stores
    started = []
    monkeypatch.setattr(service, "start", started.append)
    monkeypatch.setattr(service, "running", lambda: False)
    now = datetime.now(UTC)
    with session_scope() as db:
        monkeypatch.setattr(
            service,
            "settings",
            lambda _db: {"recording_archive": {"destination_id": "d1"}},
        )
        assert service.archive_tick(db, now) is False  # no work
        _rec(db, src)
        assert service.archive_tick(db, now) is True
        assert service.archive_tick(db, now + timedelta(minutes=5)) is False
        assert service.archive_tick(db, now + timedelta(hours=1, minutes=1)) is True
    assert started == ["recordings", "recordings"]


def test_api_and_destination_in_use(admin, tmp_path, stores):
    src, _ = stores
    folder = tmp_path / "share"
    folder.mkdir()
    r = admin.post(
        "/api/v1/backups/destinations",
        json={"kind": "directory", "name": "NAS", "path": str(folder)},
    )
    assert r.status_code == 201, r.text
    dest_id = r.json()["id"]
    assert admin.get("/api/v1/backups/recording-archive").json()["destination_id"] == ""
    r = admin.put("/api/v1/backups/recording-archive", json={"destination_id": "nope"})
    assert r.status_code == 404
    r = admin.put("/api/v1/backups/recording-archive", json={"destination_id": dest_id})
    assert r.status_code == 200 and r.json()["destination_id"] == dest_id
    assert admin.delete(f"/api/v1/backups/destinations/{dest_id}").status_code == 409

    # No longer chosen, but a copy is still there to delete one day.
    r = admin.put("/api/v1/backups/recording-archive", json={"destination_id": ""})
    assert r.status_code == 200
    with session_scope() as db:
        rec = _rec(db, src)
        rec.archive_destination = dest_id
        rec.archived_at = datetime.now(UTC)
    assert admin.delete(f"/api/v1/backups/destinations/{dest_id}").status_code == 409
    with session_scope() as db:
        db.query(CallRecording).delete()
    assert admin.delete(f"/api/v1/backups/destinations/{dest_id}").status_code == 204
