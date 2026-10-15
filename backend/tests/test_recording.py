# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call recording (docs/REPORTING.md §4): policies in the generated dialplan,
the worker's conversion and retention, and the API (validation, audited
playback, hold and delete)."""

import shutil
import wave
from datetime import timedelta

import pytest
from conftest import ADMIN_PASSWORD, enable_multi_tenancy, login
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_api_routing import INBOUND, OUTBOUND, _ext, _fake, _org, _trunk
from test_call_history import line

from veyra.core.db import session_scope
from veyra.core.models import AuditEvent, CallRecord, CallRecording, User
from veyra.core.models.base import utcnow
from veyra.reporting import cdr, recordings

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
    assert "veyra-record" not in plain and "MixMonitor" not in plain

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
