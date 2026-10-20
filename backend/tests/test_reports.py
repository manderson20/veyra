# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reports (docs/REPORTING.md §5.1): call totals, days and hours in the
organization's time zone, extensions, trunks; the queue log and queue
statistics; scoping."""

from datetime import UTC, datetime, timedelta

from conftest import ADMIN_PASSWORD, login
from fastapi.testclient import TestClient
from test_call_history import _setup, line

from veyra.core.db import session_scope
from veyra.core.models import QueueEvent, User
from veyra.reporting import cdr, queues

REP = "/api/v1/reports"


def _local(dt):
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def test_calls_report_buckets_in_org_time(admin):
    org, (a, _a_id), (b, _b_id), (c, _), trunk = _setup(admin)
    admin.patch(f"/api/v1/organizations/{org['id']}", json={"timezone": "America/Chicago"})
    # Monday 2026-10-12 14:00 UTC = 09:00 in Chicago (CDT, UTC-5).
    t0 = datetime(2026, 10, 12, 14, 0, tzinfo=UTC)

    def at(minutes, seconds=0):
        return _local(t0 + timedelta(minutes=minutes, seconds=seconds))

    with session_scope() as db:
        cdr.ingest(
            db,
            [
                line(
                    "1.1",
                    "1.1",
                    at(0),
                    at(0, 5),
                    at(2),
                    src="1001",
                    dst="1002",
                    channel=f"PJSIP/{a}-00000001",
                    dstchannel=f"PJSIP/{b}-00000002",
                ),
                line(
                    "2.1",
                    "2.1",
                    at(10),
                    at(10, 30),
                    at(12),
                    src="5735551234",
                    dst="5735550100",
                    channel=f"PJSIP/{trunk}-00000003",
                    dstchannel=f"PJSIP/{a}-00000004",
                ),
                line(
                    "3.1",
                    "3.1",
                    at(20),
                    "",
                    at(20, 25),
                    disposition="NO ANSWER",
                    src="1003",
                    dst="1002",
                    channel=f"PJSIP/{c}-00000005",
                    dstchannel=f"PJSIP/{b}-00000006",
                ),
                line(
                    "4.1",
                    "4.1",
                    at(30),
                    at(30, 2),
                    at(31),
                    src="1002",
                    dst="918005550199",
                    channel=f"PJSIP/{b}-00000007",
                    dstchannel=f"PJSIP/{trunk}-00000008",
                ),
            ],
            now=t0 + timedelta(hours=1),
        )
    r = admin.get(
        f"{REP}/calls",
        params={
            "organization_id": org["id"],
            "from": (t0 - timedelta(days=1)).isoformat(),
            "to": (t0 + timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["timezone"] == "America/Chicago"
    t = rep["totals"]
    assert (t["calls"], t["answered"], t["missed"], t["inbound"]) == (4, 3, 1, 1)
    assert t["inbound_answered_within_sl"] == 0  # answered after 30 s
    assert t["avg_ring_seconds"] == round((5 + 30 + 2) / 3, 1)
    assert rep["by_day"] == [
        {
            "day": "2026-10-12",
            "inbound": 1,
            "outbound": 1,
            "internal": 2,
            "answered": 3,
            "missed": 1,
            "total": 4,
        }
    ]
    assert rep["heatmap"][0][9] == 4  # Monday 09:00 local
    top = {e["number"]: e for e in rep["extensions"]}
    assert top["1002"]["answered"] == 1 and top["1002"]["missed"] == 1
    assert top["1001"]["answered"] == 1
    assert rep["trunks"][0]["inbound"] == 1 and rep["trunks"][0]["outbound"] == 1
    assert rep["trunks"][0]["peak_calls"] == 1  # the two trunk calls do not overlap
    # Bad periods and zones.
    assert admin.get(f"{REP}/calls", params={"tz": "Mars/Base"}).status_code == 422
    assert (
        admin.get(
            f"{REP}/calls",
            params={"from": t0.isoformat(), "to": (t0 - timedelta(hours=1)).isoformat()},
        ).status_code
        == 422
    )


def test_queue_log_and_queue_report(admin, app):
    org, (a, _), (b, _), _, _ = _setup(admin)
    q = admin.post(
        "/api/v1/queues",
        json={"organization_id": org["id"], "name": "Front desk", "number": "2400"},
    ).json()
    slug = q["slug"]
    base = int(datetime.now(UTC).timestamp()) - 600
    log = [
        f"{base}|NONE|NONE|NONE|QUEUESTART|",
        f"{base + 1}|c1|veyra-{slug}|NONE|ENTERQUEUE||5735551234|1",
        f"{base + 9}|c1|veyra-{slug}|PJSIP/{a}|CONNECT|8|c1.2|2",
        f"{base + 90}|c1|veyra-{slug}|PJSIP/{a}|COMPLETECALLER|8|81|1",
        f"{base + 100}|c2|veyra-{slug}|NONE|ENTERQUEUE||5735559999|1",
        # c2 leaves through the break-out menu and comes back (#139): one call.
        f"{base + 110}|c2|veyra-{slug}|NONE|EXITWITHKEY|1|10|1",
        f"{base + 120}|c2|veyra-{slug}|NONE|ENTERQUEUE||5735559999|1",
        f"{base + 140}|c2|veyra-{slug}|NONE|ABANDON|1|1|40",
        f"{base + 200}|c3|veyra-{slug}|NONE|ENTERQUEUE||5735558888|1",
        f"{base + 230}|c3|veyra-{slug}|PJSIP/{b}|CONNECT|30|c3.2|1",
        f"{base + 300}|c4|other-queue|NONE|ENTERQUEUE||1|1",
        "garbage",
        # Agent states (issue #135): a logs in, pauses 60 s, logs out.
        f"{base + 10}|NONE|veyra-{slug}|PJSIP/{a}|ADDMEMBER|",
        f"{base + 200}|NONE|veyra-{slug}|PJSIP/{a}|PAUSE|lunch",
        f"{base + 260}|NONE|veyra-{slug}|PJSIP/{a}|UNPAUSE|",
        f"{base + 310}|NONE|veyra-{slug}|PJSIP/{a}|REMOVEMEMBER|",
    ]
    with session_scope() as db:
        assert queues.ingest(db, log) == 13
        assert db.query(QueueEvent).count() == 13
    rep = admin.get(f"{REP}/queues", params={"organization_id": org["id"]}).json()["queues"]
    assert len(rep) == 1
    r = rep[0]
    assert (r["offered"], r["answered"], r["abandoned"], r["answered_within_sl"]) == (3, 2, 1, 1)
    assert r["avg_wait_seconds"] == 19.0
    assert [x["agent"] for x in r["agents"]] == ["1001 Front Office", "1002 Nurse"]
    a_row = r["agents"][0]
    assert (a_row["logged_in_seconds"], a_row["paused_seconds"]) == (300, 60)
    assert r["agents"][1]["logged_in_seconds"] is None
    assert r["left_with_key"] == 1

    # Someone without reports.read gets nothing.
    user = admin.post(
        "/api/v1/users",
        json={
            "email": "u@example.org",
            "display_name": "U",
            "password": ADMIN_PASSWORD,
            "home_organization_id": org["id"],
        },
    ).json()
    with session_scope() as db:
        db.get(User, user["id"]).must_change_password = False
    u = login(TestClient(app, base_url="http://veyra.test"), "u@example.org", ADMIN_PASSWORD)
    assert u.get(f"{REP}/calls").status_code == 403


def test_peak_calls_per_trunk(admin):
    import uuid

    from veyra.core.models import CallRecord, SipTrunk

    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    t0 = datetime(2026, 10, 12, 14, 0, tzinfo=UTC)
    with session_scope() as db:
        trunks = []
        for name in ("Carrier A", "Carrier B"):
            t = SipTrunk(
                id=uuid.uuid4(),
                name=name,
                slug=name.lower().replace(" ", "-"),
                auth_mode="ip",
                host="sip.example.org",
            )
            db.add(t)
            trunks.append(t.id)
        db.flush()

        def call(trunk, start, end):
            db.add(
                CallRecord(
                    id=uuid.uuid4(),
                    linkedid=str(uuid.uuid4()),
                    organization_id=uuid.UUID(org),
                    direction="outbound",
                    outcome="answered",
                    from_number="1001",
                    to_number="5551234",
                    trunk_id=trunk,
                    started_at=t0 + timedelta(minutes=start),
                    answered_at=t0 + timedelta(minutes=start),
                    ended_at=t0 + timedelta(minutes=end) if end is not None else None,
                    ring_seconds=0,
                    talk_seconds=60,
                    leg_count=1,
                )
            )

        # A: 0-10, 5-15, 8-9 overlap (3 at once), then 15-20 starts as one ends.
        call(trunks[0], 0, 10)
        call(trunks[0], 5, 15)
        call(trunks[0], 8, 9)
        call(trunks[0], 15, 20)
        # B: back to back, and one still up at the end of the period.
        call(trunks[1], 0, 5)
        call(trunks[1], 5, 10)
        call(trunks[1], 7, None)
    r = admin.get(
        f"{REP}/calls",
        params={"from": t0.isoformat(), "to": (t0 + timedelta(hours=1)).isoformat()},
    ).json()
    peaks = {t["name"]: t["peak_calls"] for t in r["trunks"]}
    assert peaks == {"Carrier A": 3, "Carrier B": 2}
