# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bulk CSV import and export (issue #41): dry run changes nothing, a real
run creates and updates in place through the API's own checks, a bad row
is reported and rolled back alone, and an export imports unchanged."""

from veyra.core.db import session_scope
from veyra.core.models import AuditEvent, Extension, VoicemailBox


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _import(admin, kind, org, text, dry_run):
    r = admin.post(
        f"/api/v1/bulk/{kind}/import",
        params={"organization_id": org, "dry_run": str(dry_run).lower()},
        json={"csv": text},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_users_extensions_dry_run_and_update(admin):
    org = _org(admin)["id"]
    pg = admin.post("/api/v1/pickup-groups", json={"organization_id": org, "name": "Office"})
    assert pg.status_code == 201, pg.text
    users = "email,display_name,roles\npat@example.org,Pat Lee,standard_user\n"
    out = _import(admin, "users", org, users, dry_run=True)
    assert out["counts"]["create"] == 1 and out["rows"][0]["notes"]
    assert admin.get("/api/v1/users", params={"q": "pat@"}).json()["total"] == 0
    assert _import(admin, "users", org, users, dry_run=False)["counts"]["create"] == 1

    csv_text = (
        "number,display_name,user_email,voicemail,voicemail_attach_audio,pickup_groups\n"
        "2001,Front desk,pat@example.org,yes,yes,Office\n"
        "2002,Hallway,,,,\n"
        "2003,Bad user,nobody@example.org,,,\n"
        "2002,Twice,,,,\n"
        "abc,Bad number,,,,\n"
    )
    dry = _import(admin, "extensions", org, csv_text, dry_run=True)
    assert [r["action"] for r in dry["rows"]] == ["create", "create", "error", "error", "error"]
    assert "import the users first" in dry["rows"][2]["message"]
    assert "twice" in dry["rows"][3]["message"]
    with session_scope() as db:
        assert db.query(Extension).filter(Extension.number.in_(["2001", "2002"])).count() == 0
        assert db.query(AuditEvent).filter_by(action="extension.create").count() == 0

    real = _import(admin, "extensions", org, csv_text, dry_run=False)
    assert real["counts"] == {"create": 2, "update": 0, "unchanged": 0, "error": 3}
    with session_scope() as db:
        ext = db.query(Extension).filter_by(number="2001").one()
        assert ext.user_id is not None
        box = db.query(VoicemailBox).filter_by(extension_id=ext.id).one()
        assert box.email == "pat@example.org"
        assert db.query(AuditEvent).filter_by(action="extension.create").count() == 2
        assert db.query(AuditEvent).filter_by(action="bulk.import").count() == 2
    groups = admin.get("/api/v1/pickup-groups").json()["items"]
    assert len(groups[0]["members"]) == 1

    # The export is a valid import: nothing changes.
    exp = admin.get("/api/v1/bulk/extensions/export.csv", params={"organization_id": org})
    assert exp.status_code == 200 and exp.text.startswith("number,display_name,user_email")
    again = _import(admin, "extensions", org, exp.text, dry_run=False)
    assert again["counts"]["unchanged"] == 2 and again["counts"]["error"] == 0, again
    # Update in place; "-" clears; empty leaves.
    upd = _import(
        admin,
        "extensions",
        org,
        "number,display_name,location,user_email,pickup_groups\n2001,Reception,Lobby,-,-\n",
        dry_run=False,
    )
    assert upd["rows"][0]["action"] == "update", upd
    with session_scope() as db:
        ext = db.query(Extension).filter_by(number="2001").one()
        assert (ext.display_name, ext.location, ext.user_id) == ("Reception", "Lobby", None)
    assert admin.get("/api/v1/pickup-groups").json()["items"][0]["members"] == []

    # Unknown columns and a missing key column are refused before any row.
    r = admin.post(
        "/api/v1/bulk/extensions/import",
        params={"organization_id": org},
        json={"csv": "nombre,display_name\n1,x\n"},
    )
    assert r.status_code == 422 and r.json()["code"] == "bad_header"
    t = admin.get(
        "/api/v1/bulk/extensions/export.csv", params={"organization_id": org, "template": "true"}
    )
    assert t.text.strip().count("\n") == 0


def test_inbound_routes_and_shared_inboxes(admin):
    org = _org(admin)["id"]
    r = admin.post(
        "/api/v1/extensions", json={"organization_id": org, "number": "3001", "display_name": "A"}
    )
    assert r.status_code == 201, r.text
    inbox = _import(
        admin,
        "shared_inboxes",
        org,
        "number,name,members,email\n3900,Attendance,3001,att@example.org\n",
        dry_run=False,
    )
    assert inbox["counts"]["create"] == 1, inbox
    routes = (
        "did,destination,description\n"
        "+15550100,extension:3001,Main line\n"
        "+15550101,voicemail_box:3900,Attendance line\n"
        "+15550102,ivr:Nope,Bad\n"
    )
    out = _import(admin, "inbound_routes", org, routes, dry_run=False)
    assert [r["action"] for r in out["rows"]] == ["create", "create", "error"], out
    exp = admin.get("/api/v1/bulk/inbound_routes/export.csv", params={"organization_id": org})
    assert "extension:3001" in exp.text and "voicemail_box:3900" in exp.text
    assert _import(admin, "inbound_routes", org, exp.text, dry_run=True)["counts"]["unchanged"] == 2
    exp = admin.get("/api/v1/bulk/shared_inboxes/export.csv", params={"organization_id": org})
    assert "3900,Attendance,3001,att@example.org" in exp.text


def test_ring_groups(admin):
    org = _org(admin)["id"]
    for n in ("4001", "4002"):
        r = admin.post(
            "/api/v1/extensions", json={"organization_id": org, "number": n, "display_name": n}
        )
        assert r.status_code == 201, r.text
    text = (
        "number,name,strategy,ring_seconds,members,failover\n"
        "6000,Front office,ringall,25,4001; 4002,extension:4001\n"
        "6001,Empty,sequential,,,hangup\n"
        "6002,Bad,ringall,,4999,\n"
    )
    out = _import(admin, "ring_groups", org, text, dry_run=False)
    assert [r["action"] for r in out["rows"]] == ["create", "create", "error"], out
    exp = admin.get("/api/v1/bulk/ring_groups/export.csv", params={"organization_id": org}).text
    assert "6000,Front office,,ringall,25,no,4001; 4002,,,extension:4001,yes" in exp, exp
    again = _import(admin, "ring_groups", org, exp, dry_run=True)
    assert again["counts"]["unchanged"] == 2, again
    upd = _import(
        admin, "ring_groups", org, "number,members,failover\n6000,4002,hangup\n", dry_run=False
    )
    assert upd["rows"][0]["action"] == "update", upd
    exp = admin.get("/api/v1/bulk/ring_groups/export.csv", params={"organization_id": org}).text
    assert "6000,Front office,,ringall,25,no,4002,,,hangup,yes" in exp, exp


def test_freepbx_dump_becomes_import_files(admin):
    """Issue #42: a FreePBX database dump → CSV files that check and import."""
    from pathlib import Path

    sql = (Path(__file__).parent / "data" / "freepbx_sample.sql").read_bytes()
    r = admin.post(
        "/api/v1/bulk/freepbx/convert", files={"file": ("asterisk.sql", sql, "application/sql")}
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["counts"] == {
        "extensions": 2,
        "ring_groups": 2,
        "queues": 1,
        "ivr_menus": 1,
        "time_conditions": 1,
        "inbound_routes": 3,
    }
    tc = out["csv"]["time_conditions"]
    assert "Office open,,,mon-fri 07:30-16:00,12-25; 11-23..11-27" in tc, tc
    assert "Office open" in out["csv"]["inbound_routes"]
    assert "voicemail:1101" in out["csv"]["inbound_routes"].split("5735550103")[1]
    ivr = out["csv"]["ivr_menus"]
    assert "1=extension:1101; 2=ring_group:6600; 9=queue:7700" in ivr, ivr
    assert "'12'" in " ".join(out["warnings"])
    qs = out["csv"]["queues"]
    assert "7700,Attendance,,rrmemory,20,0,600,yes,no,1101; 1102,,voicemail:1101" in qs, qs
    ext = out["csv"]["extensions"]
    assert "1101,Front Office,,Front Desk,,5735550100,,5735550199" in ext.replace('"', "")
    assert "Nurse O'Brien" in ext and "s3cr3t" not in ext
    rg = out["csv"]["ring_groups"]
    assert "6600,Office,,sequential,25,,1101; 1102,5735550123,OFC:,voicemail:1101" in rg
    assert "ring_group:6600" in out["csv"]["inbound_routes"]
    assert "ivr:Main menu" in out["csv"]["inbound_routes"]
    warnings = " ".join(out["warnings"])
    assert "timeconditions,3,1" in warnings and "catch-all" in warnings and "'abc'" in warnings
    # The files import: extensions first, then the groups.
    org = _org(admin)["id"]
    assert _import(admin, "extensions", org, ext, dry_run=False)["counts"]["create"] == 2
    groups = _import(admin, "ring_groups", org, rg, dry_run=True)
    assert groups["counts"]["create"] == 2, groups
    qrun = _import(admin, "queues", org, qs, dry_run=False)
    assert qrun["counts"]["create"] == 1, qrun
    exp = admin.get("/api/v1/bulk/queues/export.csv", params={"organization_id": org}).text
    assert _import(admin, "queues", org, exp, dry_run=True)["counts"]["unchanged"] == 1
    _import(admin, "ring_groups", org, rg, dry_run=False)
    menus = _import(admin, "ivr_menus", org, ivr, dry_run=False)
    assert menus["counts"]["create"] == 1, menus
    exp = admin.get("/api/v1/bulk/ivr_menus/export.csv", params={"organization_id": org}).text
    assert "Main menu" in exp and "9=queue:7700" in exp
    assert _import(admin, "ivr_menus", org, exp, dry_run=True)["counts"]["unchanged"] == 1
    assert _import(admin, "time_conditions", org, tc, dry_run=False)["counts"]["create"] == 1
    exp = admin.get("/api/v1/bulk/time_conditions/export.csv", params={"organization_id": org}).text
    assert _import(admin, "time_conditions", org, exp, dry_run=True)["counts"]["unchanged"] == 1
    routes = _import(admin, "inbound_routes", org, out["csv"]["inbound_routes"], dry_run=True)
    assert routes["counts"]["create"] == 3, routes
    # With voicemail.conf, boxes keep their PIN and email.
    vm = (Path(__file__).parent / "data" / "freepbx_voicemail.conf").read_bytes()
    r = admin.post(
        "/api/v1/bulk/freepbx/convert",
        files={
            "file": ("asterisk.sql", sql, "application/sql"),
            "voicemail": ("voicemail.conf", vm, "text/plain"),
        },
    )
    assert r.status_code == 200, r.text
    ext2 = r.json()["csv"]["extensions"]
    assert "office@example.org" in ext2 and ",4321," in ext2 and "9999" not in ext2
    assert "1102" in " ".join(r.json()["warnings"])  # its 2-digit PIN is refused
    pinned = _import(admin, "extensions", org, ext2, dry_run=False)
    assert "voicemail PIN set" in pinned["rows"][0]["notes"], pinned
    from veyra.core.models import Extension, VoicemailBox
    from veyra.core.security.crypto import load_installation_key
    from veyra.telephony.snapshot import pin_purpose

    with session_scope() as db:
        e = db.query(Extension).filter_by(number="1101").one()
        box = db.query(VoicemailBox).filter_by(extension_id=e.id).one()
        key = load_installation_key(admin.app.state.settings)
        assert key.decrypt(box.pin_ciphertext, pin_purpose(box.id)) == "4321"
    # A gzipped dump works too; garbage does not.
    import gzip

    r = admin.post(
        "/api/v1/bulk/freepbx/convert", files={"file": ("a.sql.gz", gzip.compress(sql), "x")}
    )
    assert r.status_code == 200
    r = admin.post("/api/v1/bulk/freepbx/convert", files={"file": ("a.sql", b"hello", "x")})
    assert r.status_code == 422 and r.json()["code"] == "freepbx_invalid"


def _wav(seconds: float = 0.2) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * int(8000 * seconds))
    return buf.getvalue()


def _archive(files: dict[str, bytes]) -> bytes:
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_freepbx_queue_agents_become_dynamic_members():
    from pathlib import Path

    from veyra.bulk import freepbx

    sql = (Path(__file__).parent / "data" / "freepbx_sample.sql").read_text()
    without = freepbx.convert(sql)
    assert any("database show QPENALTY" in w for w in without.warnings)
    number = freepbx.parse_dump(sql)["queues_config"][0]["extension"]
    agents = f"/QPENALTY/{number}/agents/1234 : 0\n/QPENALTY/{number}/dynmemberonly : no\n"
    conv = freepbx.convert(sql, queue_agents=agents)
    assert not any("database show QPENALTY" in w for w in conv.warnings)
    assert "1234" in conv.csv["queues"]


def test_freepbx_audio_archive_adds_recordings_and_hold_music(admin):
    orgs = admin.get("/api/v1/organizations").json()["items"]
    org = orgs[0]["id"]
    dump = (
        b"CREATE TABLE `recordings` (\n  `id` int NOT NULL,\n  `displayname` varchar(50),\n"
        b"  `filename` blob\n);\n"
        b"INSERT INTO `recordings` VALUES (1,'Main Greeting','custom/main-gr'),"
        b"(2,'Joined','custom/a&custom/b'),(3,'Gone','custom/gone');\n"
    )
    archive = _archive(
        {
            "sounds/en/custom/main-gr.wav": _wav(),
            "sounds/en/custom/main-gr.ulaw": b"raw",
            "sounds/en/custom/only-raw.gsm": b"raw",
            "sounds/en/custom/broken.wav": b"not audio",
            "moh/lobby.wav": _wav(),
            "moh/jazz/one.wav": _wav(),
            "moh/.custom": b"",
            "../../etc/custom/evil.txt": b"ignored",
        }
    )

    def send():
        r = admin.post(
            "/api/v1/bulk/freepbx/audio",
            data={"organization_id": org},
            files={"file": ("audio.tar.gz", archive, "x"), "dump": ("a.sql", dump, "x")},
        )
        assert r.status_code == 200, r.text
        return r.json()

    out = send()
    assert out["recordings"] == 1 and out["music_tracks"] == 2 and out["hold_music_sets"] == 2
    text = " ".join(out["warnings"])
    for expected in ("Joined", "Gone", "only-raw", "broken"):
        assert expected in text
    names = {p["name"] for p in admin.get("/api/v1/prompts", params={"limit": 200}).json()["items"]}
    assert {"Main Greeting", "default - lobby", "jazz - one"} <= names
    sets = {s["name"] for s in admin.get("/api/v1/hold-music").json()["items"]}
    assert {"default", "jazz"} <= sets

    # A second run adds nothing and changes nothing.
    again = send()
    assert again["recordings"] == 0 and again["music_tracks"] == 0 and again["hold_music_sets"] == 0
    assert again["already_there"] == 3

    r = admin.post(
        "/api/v1/bulk/freepbx/audio",
        data={"organization_id": org},
        files={"file": ("audio.tar.gz", b"not a tar", "x")},
    )
    assert r.status_code == 422 and r.json()["code"] == "freepbx_invalid"
