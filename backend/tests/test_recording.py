# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call recording (docs/REPORTING.md §4): policies in the generated dialplan,
the worker's conversion and retention, and the API (validation, audited
playback, hold and delete)."""

import csv
import io
import shutil
import uuid
import wave
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from conftest import ADMIN_PASSWORD, enable_multi_tenancy, login
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_api_routing import INBOUND, OUTBOUND, _ext, _fake, _org, _trunk
from test_call_history import line

from veyra.core.db import session_scope
from veyra.core.models import AuditEvent, CallRecord, CallRecording, Organization, User
from veyra.core.models.base import utcnow
from veyra.reporting import cdr, recordings
from veyra.reporting import recording_export as export

POL = "/api/v1/recording-policies"
REC = "/api/v1/recordings"


def _deploy(admin, deployer, cfg):
    r = admin.post("/api/v1/telephony/apply", json={})
    assert r.status_code in (200, 202), r.text
    with session_scope() as db:
        deployer.run_once(db)
    return (cfg / "extensions.conf").read_text()


def test_policies_reach_the_dialplan(admin, app, tmp_path):
    _, deployer, cfg = _fake(app, tmp_path)
    org = _org(admin)
    a = _ext(admin, org["id"], "1001")
    _ext(admin, org["id"], "1002")
    trunk = _trunk(admin)
    route = admin.post(
        INBOUND,
        json={
            "organization_id": org["id"],
            "did": "5735550100",
            "destination_extension_id": a["id"],
        },
    ).json()
    admin.post(
        OUTBOUND,
        json={
            "name": "Local",
            "patterns": [{"prefix": "9", "match": "NXXNXXXXXX"}],
            "trunk_ids": [trunk["id"]],
        },
    )
    # No policy: nothing about recording in the dialplan.
    plain = _deploy(admin, deployer, cfg)
    assert "[veyra-record]" not in plain and "MixMonitor(" not in plain.split("[veyra-ondemand]")[0]

    inbound = admin.post(POL, json={"organization_id": org["id"], "name": "All inbound"}).json()
    assert inbound["problems"] == [
        "Inbound callers hear no announcement that the call is recorded."
    ]
    internal = admin.post(
        POL,
        json={
            "organization_id": org["id"],
            "name": "Front office",
            "inbound": False,
            "internal": True,
            "outbound": True,
            "scope": "selected",
            "extension_ids": [a["id"]],
        },
    ).json()
    dialplan = _deploy(admin, deployer, cfg)
    ctx = dialplan[dialplan.index("[veyra-record]") :]
    assert 'GotoIf($["${VEYRA_CALLREC}"!=""]?done)' in ctx
    assert "MixMonitor(/var/lib/veyra/recordings/incoming/${VEYRA_CALLREC}--${ARG2}.wav,b)" in ctx
    assert "Set(CDR(veyra_rec)=${VEYRA_CALLREC})" in ctx
    # All inbound: recorded where the DID enters.
    did = dialplan[dialplan.index("exten => 5735550100,1,") :]
    assert f"GosubIf($[1]?veyra-record,s,1(example,{inbound['id']},))" in did.split("\n\n")[0]
    # The chosen phone, called internally, and calling another phone.
    ext1 = dialplan[dialplan.index("exten => 1001,1,") :].split("exten => 1001,hint")[0]
    assert f'GosubIf($["${{VEYRA_DID}}"=""]?veyra-record,s,1(example,{internal["id"]},))' in ext1
    ext2 = dialplan[dialplan.index("exten => 1002,1,") :]
    assert (
        '${REGEX("^(example\\-1001)$" ${CHANNEL(endpoint)})}' in ext2.split("same => n,Hangup()")[0]
    )
    # Outbound from the chosen phone.
    out = dialplan[dialplan.index("[veyra-out-local]") :]
    assert '"${VEYRA_ORG}"="example" & ${REGEX("^(example\\-1001)$" ${CHANNEL(endpoint)})}' in out
    # A disabled policy disappears again.
    admin.patch(f"{POL}/{inbound['id']}", json={"is_enabled": False})
    assert f"1(example,{inbound['id']}," not in _deploy(admin, deployer, cfg)
    assert route["did"] == "5735550100"


def test_policy_validation_and_scope(admin):
    org = _org(admin)
    enable_multi_tenancy()
    other = admin.post("/api/v1/organizations", json={"name": "Beta", "slug": "beta"}).json()
    b = _ext(admin, other["id"], "2001")
    r = admin.post(
        POL,
        json={
            "organization_id": org["id"],
            "name": "X",
            "scope": "selected",
            "extension_ids": [b["id"]],
        },
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "extension_ids"
    r = admin.post(
        POL,
        json={
            "organization_id": org["id"],
            "name": "Nothing",
            "scope": "selected",
            "inbound": False,
            "internal": False,
        },
    )
    assert r.status_code == 201
    assert set(r.json()["problems"]) == {
        "No direction is chosen: nothing is recorded.",
        "Nothing is selected: nothing is recorded.",
    }
    assert (
        admin.post(POL, json={"organization_id": org["id"], "name": "Nothing"}).status_code == 409
    )
    assert admin.delete(f"{POL}/{r.json()['id']}").status_code == 204


def _wav(path, seconds=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x01\x00" * 8000 * seconds)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_worker_converts_retains_and_api_plays(admin, app):
    org = _org(admin)
    a = _ext(admin, org["id"], "1001")
    b = _ext(admin, org["id"], "1002", "Nurse")
    with session_scope() as db:
        from veyra.core.models import Extension

        ea, eb = db.get(Extension, a["id"]).endpoint_name, db.get(Extension, b["id"]).endpoint_name
    policy = admin.post(
        POL,
        json={
            "organization_id": org["id"],
            "name": "Internal",
            "inbound": False,
            "internal": True,
            "retention_days": 30,
        },
    ).json()
    rec_dir = app.state.settings.recordings_dir
    now = utcnow()
    stamp = (now - timedelta(minutes=5)).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    end = (now - timedelta(minutes=4)).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    with session_scope() as db:
        cdr.ingest(
            db,
            [
                line(
                    "77.1",
                    "77.1",
                    stamp,
                    stamp,
                    end,
                    src="1001",
                    dst="1002",
                    channel=f"PJSIP/{ea}-00000001",
                    dstchannel=f"PJSIP/{eb}-00000002",
                    rec="77.1",
                ),
                # Rang, nobody answered: MixMonitor wrote only a header.
                line(
                    "78.1",
                    "78.1",
                    stamp,
                    "",
                    end,
                    disposition="NO ANSWER",
                    src="1001",
                    dst="1002",
                    channel=f"PJSIP/{ea}-00000003",
                    dstchannel=f"PJSIP/{eb}-00000004",
                    rec="78.1",
                ),
            ],
            now=now,
        )
    wav = rec_dir / "incoming" / f"77.1--{policy['id']}.wav"
    _wav(wav)
    empty = rec_dir / "incoming" / f"78.1--{policy['id']}.wav"
    empty.write_bytes(b"RIFF" + b"\0" * 40)
    with session_scope() as db:
        assert recordings.process(db, rec_dir) == 1
    assert not wav.exists() and not empty.exists()
    with session_scope() as db:
        rec = db.scalar(select(CallRecording))
        call = db.scalar(select(CallRecord).where(CallRecord.linkedid == "77.1"))
        assert rec.call_id == call.id and rec.duration_seconds == 2 and rec.size_bytes > 0
        assert rec.path.startswith("example/") and rec.path.endswith("/77.1.ogg")
        assert (rec.delete_after - rec.created_at).days == 30
        rec_id = str(rec.id)

    detail = admin.get(f"/api/v1/calls/history/{call.id}").json()
    assert detail["recording_id"] == rec_id and detail["recorded"] is True
    listing = admin.get(REC).json()
    assert listing["total"] == 1 and listing["items"][0]["from_number"] == "1001"
    audio = admin.get(f"{REC}/{rec_id}/audio")
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/ogg"
    assert audio.content[:4] == b"OggS"
    with session_scope() as db:
        plays = db.scalars(select(AuditEvent).where(AuditEvent.action == "recording.play")).all()
        assert len(plays) == 1

    # Staff without recordings.read see nothing, unless they may hear their own calls.
    user = admin.post(
        "/api/v1/users",
        json={
            "email": "nurse@example.org",
            "display_name": "Nurse",
            "password": ADMIN_PASSWORD,
            "home_organization_id": org["id"],
        },
    ).json()
    admin.patch(f"/api/v1/extensions/{b['id']}", json={"user_id": user["id"]})
    with session_scope() as db:
        db.get(User, user["id"]).must_change_password = False
    nurse = login(
        TestClient(app, base_url="http://veyra.test"), "nurse@example.org", ADMIN_PASSWORD
    )
    assert nurse.get(REC).status_code == 403
    assert nurse.get(f"{REC}/{rec_id}/audio").status_code == 403

    # Hold protects from retention and deletion; release, then retention deletes.
    assert admin.post(f"{REC}/{rec_id}/hold", json={"held": True}).json()["held"] is True
    assert admin.delete(f"{REC}/{rec_id}").status_code == 409
    with session_scope() as db:
        assert recordings.prune(db, rec_dir, now=now + timedelta(days=31)) == 0
    admin.post(f"{REC}/{rec_id}/hold", json={"held": False})
    with session_scope() as db:
        assert recordings.prune(db, rec_dir, now=now + timedelta(days=31)) == 1
        rec = db.get(CallRecording, rec_id)
        assert rec.deleted_at is not None and not (rec_dir / rec.path).exists()
    assert admin.get(f"{REC}/{rec_id}/audio").status_code in (404, 410)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_conference_recordings_are_stored_and_listed(admin, app):
    """ConfBridge recordings land on the Call Recording page with their room (#133)."""
    import os
    import time

    org = _org(admin)
    room = admin.post(
        "/api/v1/conferences",
        json={"organization_id": org["id"], "name": "Board", "number": "7100", "record": True},
    )
    assert room.status_code == 201, room.text
    slug = room.json()["slug"]
    rec_dir = app.state.settings.recordings_dir
    ts = int(time.time()) - 600
    done = rec_dir / "conferences" / f"example--{slug}-{ts}.wav"
    _wav(done, seconds=3)
    old = time.time() - 300
    os.utime(done, (old, old))
    live = rec_dir / "conferences" / f"example--{slug}-{ts + 1}.wav"
    _wav(live)  # still being written: left alone
    (rec_dir / "conferences" / "not-ours.wav").write_bytes(b"x")
    with session_scope() as db:
        assert recordings.process_conferences(db, rec_dir) == 1
    assert not done.exists() and live.exists()
    items = admin.get("/api/v1/recordings").json()["items"]
    conf = next(i for i in items if i["conference_room_id"])
    assert conf["conference_name"] == "Board" and conf["call_id"] is None
    assert conf["duration_seconds"] == 3
    assert conf["started_at"].startswith(
        __import__("datetime")
        .datetime.fromtimestamp(ts, __import__("datetime").UTC)
        .isoformat()[:16]
    )
    assert admin.get(f"/api/v1/recordings/{conf['id']}/audio").status_code == 200
    with session_scope() as db:  # a second pass does not store it again
        assert recordings.process_conferences(db, rec_dir) == 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_recordings_are_encrypted_at_rest(admin, app):
    """Each recording has its own key, wrapped by the installation key (#122):
    the file on disk is not audio, playback decrypts and seeks, older clear
    files are encrypted by the worker, and a key rotation keeps them playable."""
    import time
    import uuid

    from veyra.core.security import rotation
    from veyra.core.security.crypto import InstallationKey, load_installation_key

    key = load_installation_key(app.state.settings)
    rec_dir = app.state.settings.recordings_dir
    org = _org(admin)
    policy = admin.post(
        POL, json={"organization_id": org["id"], "name": "All", "inbound": True}
    ).json()
    wav = rec_dir / "incoming" / f"91.1--{policy['id']}.wav"
    _wav(wav)
    with session_scope() as db:
        assert recordings.process(db, rec_dir, clock=time.time() + 90000, key=key) == 1
        rec = db.scalar(select(CallRecording).where(CallRecording.ref == "91.1"))
        rec_id = rec.id
        assert rec.path.endswith(".ogg.enc") and rec.key_ciphertext
        on_disk = (rec_dir / rec.path).read_bytes()
    assert not on_disk.startswith(b"OggS") and b"OggS" not in on_disk[:64]
    audio = admin.get(f"{REC}/{rec_id}/audio")
    assert audio.status_code == 200 and audio.content[:4] == b"OggS"
    part = admin.get(f"{REC}/{rec_id}/audio", headers={"Range": "bytes=0-3"})
    assert part.status_code == 206 and part.content == b"OggS"
    assert part.headers["content-range"] == f"bytes 0-3/{len(audio.content)}"
    tail = admin.get(f"{REC}/{rec_id}/audio", headers={"Range": "bytes=-2"})
    assert tail.status_code == 206 and tail.content == audio.content[-2:]

    # A recording stored in the clear before 0.27.4 is encrypted by the worker.
    clear = rec_dir / "example" / "old.ogg"
    clear.parent.mkdir(parents=True, exist_ok=True)
    clear.write_bytes(audio.content)
    with session_scope() as db:
        db.add(
            CallRecording(
                id=uuid.uuid4(),
                ref="old",
                organization_id=uuid.UUID(org["id"]),
                path="example/old.ogg",
                format="ogg",
                size_bytes=len(audio.content),
                duration_seconds=2,
            )
        )
    with session_scope() as db:
        assert recordings.encrypt_existing(db, rec_dir, key) == 1
        old = db.scalar(select(CallRecording).where(CallRecording.ref == "old"))
        old_id = old.id
        assert old.path == "example/old.ogg.enc" and not clear.exists()
    assert admin.get(f"{REC}/{old_id}/audio").content == audio.content

    # Rotation re-wraps the file keys; the audio stays readable with the new key.
    new = InstallationKey.generate()
    with session_scope() as db:
        assert rotation.rotate(db, key, new) >= 2
    with session_scope() as db:
        rec = db.get(CallRecording, rec_id)
        assert recordings.audio_of(rec_dir, rec, new) == audio.content
        assert recordings.audio_of(rec_dir, rec, key) is None


def _exportable_recording(tmp_dir, ref, audio=True, **call):
    """A real Ogg file with its call, as the worker leaves them."""
    now = utcnow()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with session_scope() as db:
        org = db.scalars(select(Organization)).first()
        c = CallRecord(
            id=uuid.uuid4(),
            linkedid=ref,
            organization_id=org.id,
            direction="inbound",
            outcome="answered",
            started_at=call.pop("started_at", now),
            ring_seconds=3,
            talk_seconds=20,
            recording_ref=ref,
            **call,
        )
        db.add(c)
        db.flush()
        rel = f"{org.slug}/{ref}.ogg"
        if audio:
            wav = tmp_dir / f"{ref}.wav"
            _wav(wav)
            recordings.convert(wav, tmp_dir / rel)
        else:
            (tmp_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_dir / rel).write_bytes(b"OggS")
        r = CallRecording(
            id=uuid.uuid4(),
            ref=ref,
            organization_id=org.id,
            call_id=c.id,
            path=rel,
            size_bytes=(tmp_dir / rel).stat().st_size,
            duration_seconds=2,
            created_at=now,
        )
        db.add(r)
        return str(r.id)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg")
def test_export_zip(admin, app):
    _org(admin)
    rec_dir = app.state.settings.recordings_dir
    when = datetime(2026, 10, 30, 19, 32, tzinfo=UTC)
    a = _exportable_recording(
        rec_dir,
        "exp-a",
        started_at=when,
        from_number="5551234",
        from_name="=HYPERLINK(evil)",
        to_number="1001",
    )
    _exportable_recording(
        rec_dir, "exp-b", started_at=when, from_number="5551234", to_number="1001"
    )
    gone = _exportable_recording(rec_dir, "exp-c", started_at=when, from_number="77", to_number="1")
    with session_scope() as db:
        rec = db.get(CallRecording, uuid.UUID(gone))
        (rec_dir / rec.path).unlink()
    assert admin.get(f"{REC}/export/summary").json()["count"] == 3
    r = admin.get(f"{REC}/export.zip")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["x-accel-buffering"] == "no"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert z.testzip() is None
    names = z.namelist()
    # Same minute and numbers: the name stays unique; the time is the organization's.
    mp3s = sorted(n for n in names if n.endswith(".mp3"))
    assert len(mp3s) == 2 and mp3s[0].endswith("_inbound_5551234_to_1001.mp3")
    assert mp3s[1].endswith("_inbound_5551234_to_1001_2.mp3")
    assert z.read(mp3s[0])[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
    rows = list(csv.DictReader(io.StringIO(z.read("recordings.csv").decode("utf-8-sig"))))
    assert len(rows) == 3
    by_id = {x["recording_id"]: x for x in rows}
    assert by_id[a]["from_name"] == "'=HYPERLINK(evil)" and by_id[a]["talk_seconds"] == "20"
    assert by_id[a]["file"] in names and by_id[a]["status"] == "ok"
    assert by_id[gone]["file"] == "" and by_id[gone]["status"] == "missing or unreadable"
    with session_scope() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "recording.export")).one()
        assert ev.details["count"] == 3 and a in ev.details["recording_ids"]
    # The original audio, filters and a single readable download.
    r = admin.get(f"{REC}/export.zip", params={"format": "ogg", "q": "77"})
    assert r.status_code == 200
    assert zipfile.ZipFile(io.BytesIO(r.content)).namelist() == ["recordings.csv"]
    assert admin.get(f"{REC}/export.zip", params={"q": "nomatch"}).status_code == 404
    one = admin.get(f"{REC}/{a}/audio", params={"download": True, "format": "mp3"})
    assert one.headers["content-type"] == "audio/mpeg"
    assert "_inbound_5551234_to_1001" in one.headers["content-disposition"]


def test_export_limits_and_permission(admin, app, monkeypatch):
    from veyra.api.v1 import recording as api

    org = _org(admin)
    _exportable_recording(
        app.state.settings.recordings_dir, "lim-a", audio=False, from_number="1", to_number="2"
    )
    monkeypatch.setattr(api, "EXPORT_MAX_RECORDINGS", 0)
    r = admin.get(f"{REC}/export.zip")
    assert r.status_code == 422 and r.json()["code"] == "export_too_large"
    monkeypatch.undo()
    # An ordinary user does not reach the export.
    user = admin.post(
        "/api/v1/users",
        json={
            "email": "nurse2@example.org",
            "display_name": "Nurse",
            "password": ADMIN_PASSWORD,
            "home_organization_id": org["id"],
        },
    ).json()
    with session_scope() as db:
        db.get(User, user["id"]).must_change_password = False
    nurse = login(
        TestClient(app, base_url="http://veyra.test"), "nurse2@example.org", ADMIN_PASSWORD
    )
    assert nurse.get(f"{REC}/export.zip").status_code == 403
    assert nurse.get(f"{REC}/export/summary").status_code == 403


def test_file_names_cannot_escape():
    tz = export.zone("America/Chicago")
    when = datetime(2026, 10, 30, 19, 32, tzinfo=UTC)
    stem = export.file_stem(
        when,
        tz,
        direction="inbound",
        from_number="../../etc",
        to_number='a"b',
        conference=None,
        ref="x",
    )
    assert stem == "2026-10-30_1432_inbound_etc_to_a-b"
    assert export.safe_cell("+15551234") == "+15551234"
    assert export.safe_cell("+cmd") == "'+cmd"
