# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call history (docs/REPORTING.md §3): the CDR line format, folding legs
into calls (direction, organization, outcome, times), the file cursor, the
retention, and the API (scoping, own calls, export)."""

import csv
import io
from datetime import UTC, datetime, timedelta

from conftest import ADMIN_PASSWORD, login
from fastapi.testclient import TestClient
from sqlalchemy import select

from veyra.core.db import session_scope
from veyra.core.models import CallLeg, CallRecord, Extension, SystemSetting, User
from veyra.reporting import cdr

HIST = "/api/v1/calls/history"


def line(
    uniqueid,
    linkedid,
    start,
    answer="",
    end="",
    disposition="ANSWERED",
    src="",
    clid="",
    dst="",
    channel="",
    dstchannel="",
    lastapp="Dial",
    billsec=0,
    rec="",
):
    """A line as cdr_custom writes it: every field through CSV_QUOTE."""
    buf = io.StringIO()
    csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="").writerow(
        [
            "v1",
            uniqueid,
            linkedid,
            start,
            answer,
            end,
            "0",
            str(billsec),
            disposition,
            src,
            clid,
            dst,
            "veyra-internal",
            channel,
            dstchannel,
            lastapp,
            rec,
        ]
    )
    return buf.getvalue()


def t(minute, second=0):
    # CDR times are the server's local time without a zone.
    local = datetime(2026, 10, 15, 9, minute, second, tzinfo=UTC).astimezone()
    return local.strftime("%Y-%m-%d %H:%M:%S")


def test_parse_line_quotes_and_rejects_other_formats():
    c = cdr.parse_line(
        line("1.1", "1.1", t(0), clid='"Smith, \\"Jo\\"" <5551234>', src="5551234", dst="1001")
    )
    assert c is not None and c.linkedid == "1.1" and c.disposition == "ANSWERED"
    assert cdr.split_clid(c.clid) == ('Smith, "Jo"', "5551234")
    # The package's Master.csv layout, a partial line, a newer format.
    assert cdr.parse_line('"","*43","*43","veyra-internal"') is None
    assert cdr.parse_line('"v1","1.1"') is None
    assert cdr.parse_line(line("1", "1", t(0)).replace('"v1"', '"v2"')) is None
    assert cdr.endpoint_of("PJSIP/example-1001-0000002a") == "example-1001"
    assert cdr.endpoint_of("Local/200@veyra-rg-x-00000004;2") is None


def _ext(admin, org_id, number, name, **extra):
    r = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org_id, "number": number, "display_name": name, **extra},
    )
    assert r.status_code == 201, r.text
    with session_scope() as db:
        return db.get(Extension, r.json()["id"]).endpoint_name, r.json()["id"]


def _setup(admin):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    a, a_id = _ext(admin, org["id"], "1001", "Front Office")
    b, b_id = _ext(admin, org["id"], "1002", "Nurse")
    c, c_id = _ext(admin, org["id"], "1003", "Library")
    trunk = admin.post(
        "/api/v1/trunks",
        json={"name": "Carrier", "auth_mode": "ip", "host": "198.51.100.20"},
    )
    assert trunk.status_code == 201, trunk.text
    route = admin.post(
        "/api/v1/routing/inbound",
        json={"organization_id": org["id"], "did": "5735550100", "destination_extension_id": a_id},
    )
    assert route.status_code == 201, route.text
    return org, (a, a_id), (b, b_id), (c, c_id), f"trunk-{trunk.json()['slug']}"


def _calls():
    with session_scope() as db:
        return {c.linkedid: c for c in db.scalars(select(CallRecord))}


def test_fold_directions_outcomes_and_times(admin):
    org, (a, _a_id), (b, b_id), (c, c_id), trunk = _setup(admin)
    now = datetime(2026, 10, 15, 9, 30, tzinfo=UTC)
    lines = [
        # Internal, answered after 5 s, 60 s of talk.
        line(
            "10.1",
            "10.1",
            t(0),
            t(0, 5),
            t(1, 5),
            src="1001",
            clid='"Front Office" <1001>',
            dst="1002",
            channel=f"PJSIP/{a}-00000001",
            dstchannel=f"PJSIP/{b}-00000002",
            billsec=60,
        ),
        # Inbound to a ring group: two Local legs ring 1002 and 1003, 1003 answers.
        line(
            "20.1",
            "20.1",
            t(2),
            t(2, 1),
            t(4),
            src="5735551234",
            clid='"CALLER" <5735551234>',
            dst="5735550100",
            channel=f"PJSIP/{trunk}-00000003",
            dstchannel="Local/700@veyra-rg-x-00000001;1",
            billsec=119,
        ),
        line(
            "20.2",
            "20.1",
            t(2, 1),
            "",
            t(2, 9),
            disposition="NO ANSWER",
            src="5735551234",
            dst="1002",
            channel="Local/700@veyra-rg-x-00000001;2",
            dstchannel=f"PJSIP/{b}-00000004",
        ),
        line(
            "20.3",
            "20.1",
            t(2, 1),
            t(2, 9),
            t(4),
            src="5735551234",
            dst="1003",
            channel="Local/700@veyra-rg-x-00000002;2",
            dstchannel=f"PJSIP/{c}-00000005",
            billsec=111,
        ),
        # Outbound through the trunk, busy.
        line(
            "30.1",
            "30.1",
            t(5),
            "",
            t(5, 3),
            disposition="BUSY",
            src="1002",
            clid='"Nurse" <1002>',
            dst="918005550199",
            channel=f"PJSIP/{b}-00000006",
            dstchannel=f"PJSIP/{trunk}-00000007",
        ),
        # Internal, nobody answered, then voicemail picked up.
        line(
            "40.1",
            "40.1",
            t(6),
            "",
            t(6, 20),
            disposition="NO ANSWER",
            src="1001",
            dst="1003",
            channel=f"PJSIP/{a}-00000008",
            dstchannel=f"PJSIP/{c}-00000009",
        ),
        line(
            "40.1",
            "40.1",
            t(6, 20),
            t(6, 20),
            t(6, 50),
            src="1001",
            dst="vm-1003",
            channel=f"PJSIP/{a}-00000008",
            lastapp="VoiceMail",
        ),
        # Internal, missed.
        line(
            "50.1",
            "50.1",
            t(7),
            "",
            t(7, 30),
            disposition="NO ANSWER",
            src="1003",
            dst="1001",
            channel=f"PJSIP/{c}-0000000a",
            dstchannel=f"PJSIP/{a}-0000000b",
        ),
        # An unknown caller to a number no route knows: no organization.
        line(
            "60.1",
            "60.1",
            t(8),
            "",
            t(8, 1),
            disposition="FAILED",
            src="anonymous",
            dst="999",
            channel=f"PJSIP/{trunk}-0000000c",
        ),
    ]
    with session_scope() as db:
        assert cdr.ingest(db, lines, now=now) == len(lines)
        # The same lines again change nothing.
        cdr.ingest(db, lines, now=now)
        assert db.query(CallLeg).count() == len(lines)
    calls = _calls()
    internal = calls["10.1"]
    assert (internal.direction, internal.outcome) == ("internal", "answered")
    assert (internal.ring_seconds, internal.talk_seconds) == (5, 60)
    assert internal.from_name == "Front Office" and internal.to_number == "1002"
    assert str(internal.answered_extension_id) == b_id and internal.is_final

    group = calls["20.1"]
    assert (group.direction, group.outcome, group.leg_count) == ("inbound", "answered", 3)
    assert group.did == "5735550100" and str(group.answered_extension_id) == c_id
    assert str(group.organization_id) == org["id"] and group.trunk_id is not None
    assert group.ring_seconds == 9  # the person answered 9 s in

    assert (calls["30.1"].direction, calls["30.1"].outcome) == ("outbound", "busy")
    assert calls["40.1"].outcome == "voicemail"
    assert calls["50.1"].outcome == "missed" and calls["50.1"].talk_seconds == 0
    assert calls["60.1"].organization_id is None and calls["60.1"].outcome == "failed"


def test_reader_cursor_rotation_and_settle(admin, tmp_path):
    _org, (a, _), (b, _), _, _ = _setup(admin)
    f = tmp_path / "veyra.csv"
    first = line(
        "1.1",
        "1.1",
        t(0),
        t(0, 2),
        t(1),
        src="1001",
        dst="1002",
        channel=f"PJSIP/{a}-00000001",
        dstchannel=f"PJSIP/{b}-00000002",
    )
    f.write_text(first + "\n" + "partial")
    reader = cdr.CdrReader(f)
    with session_scope() as db:
        assert reader.read(db) == [first]
        assert reader.read(db) == []
        assert db.get(SystemSetting, cdr.CURSOR_KEY).value["offset"] == len(first) + 1
    f.unlink()
    f.write_text(first.replace("1.1", "2.2") + "\n")  # rotated: a new file
    with session_scope() as db:
        assert cdr.process(db, reader) == 1
    with session_scope() as db:
        call = db.scalar(select(CallRecord).where(CallRecord.linkedid == "2.2"))
        call.is_final = False
        assert cdr.settle(db, now=call.ended_at + timedelta(seconds=30)) == 0
        assert cdr.settle(db, now=call.ended_at + timedelta(seconds=61)) == 1


def test_retention_prunes_old_calls(admin):
    _org, (a, _), (b, _), _, _ = _setup(admin)
    old = line(
        "1.1",
        "1.1",
        t(0),
        t(0, 1),
        t(1),
        channel=f"PJSIP/{a}-00000001",
        dstchannel=f"PJSIP/{b}-00000002",
    )
    with session_scope() as db:
        cdr.ingest(db, [old])
        db.add(SystemSetting(key=cdr.RETENTION_KEY, value=30))
    with session_scope() as db:
        call = db.scalar(select(CallRecord))
        assert cdr.prune(db, now=call.started_at + timedelta(days=29)) == 0
        assert cdr.prune(db, now=call.started_at + timedelta(days=31)) == 1
        assert db.query(CallLeg).count() == 0


def test_api_search_detail_mine_and_export(admin, app):
    org, (a, _a_id), (b, b_id), (c, c_id), trunk = _setup(admin)
    user = admin.post(
        "/api/v1/users",
        json={
            "email": "nurse@example.org",
            "display_name": "Nurse",
            "password": ADMIN_PASSWORD,
            "home_organization_id": org["id"],
        },
    ).json()
    assert (
        admin.patch(f"/api/v1/extensions/{b_id}", json={"user_id": user["id"]}).status_code == 200
    )
    with session_scope() as db:
        db.get(User, user["id"]).must_change_password = False  # covered by the auth tests
    now = datetime.now(UTC)

    def at(minutes):
        return (now - timedelta(minutes=minutes)).astimezone().strftime("%Y-%m-%d %H:%M:%S")

    with session_scope() as db:
        cdr.ingest(
            db,
            [
                line(
                    "1.1",
                    "1.1",
                    at(10),
                    at(9),
                    at(8),
                    src="1001",
                    clid='"Front Office" <1001>',
                    dst="1002",
                    channel=f"PJSIP/{a}-00000001",
                    dstchannel=f"PJSIP/{b}-00000002",
                ),
                line(
                    "2.1",
                    "2.1",
                    at(7),
                    "",
                    at(6),
                    disposition="NO ANSWER",
                    src="5735551234",
                    clid='"Smith, Jo" <5735551234>',
                    dst="5735550100",
                    channel=f"PJSIP/{trunk}-00000003",
                    dstchannel=f"PJSIP/{a}-00000004",
                ),
                line(
                    "3.1",
                    "3.1",
                    at(5),
                    at(5),
                    at(4),
                    src="1001",
                    dst="1003",
                    channel=f"PJSIP/{a}-00000005",
                    dstchannel=f"PJSIP/{c}-00000006",
                ),
            ],
        )
    r = admin.get(HIST)
    assert r.status_code == 200 and r.json()["total"] == 3
    assert [i["from_number"] for i in r.json()["items"]] == ["1001", "5735551234", "1001"]
    assert admin.get(HIST, params={"outcome": "missed"}).json()["total"] == 1
    assert admin.get(HIST, params={"direction": "inbound"}).json()["total"] == 1
    assert admin.get(HIST, params={"q": "Smith"}).json()["total"] == 1
    assert admin.get(HIST, params={"q": "Nurse"}).json()["total"] == 1  # matches the extension
    assert admin.get(HIST, params={"extension_id": c_id}).json()["total"] == 1
    old = (now - timedelta(days=3)).isoformat()
    assert (
        admin.get(HIST, params={"from": old, "to": (now - timedelta(days=2)).isoformat()}).json()[
            "total"
        ]
        == 0
    )
    first = r.json()["items"][-1]
    detail = admin.get(f"{HIST}/{first['id']}").json()
    assert detail["answered_by"]["number"] == "1002" and len(detail["legs"]) == 1

    export = admin.get(f"{HIST}/export.csv")
    assert export.status_code == 200 and export.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(export.text)))
    assert rows[0][0] == "started_at" and len(rows) == 4
    assert any(r[4] == "Smith, Jo" for r in rows[1:])

    nurse = login(
        TestClient(app, base_url="http://veyra.test"), "nurse@example.org", ADMIN_PASSWORD
    )
    assert nurse.get(HIST).status_code == 403
    assert nurse.get(f"{HIST}/export.csv").status_code == 403
    resp = nurse.get("/api/v1/me/calls")
    assert resp.status_code == 200, resp.text
    mine = resp.json()
    assert mine["total"] == 1 and mine["items"][0]["to_extension"]["number"] == "1002"
