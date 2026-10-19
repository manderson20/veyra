# SPDX-License-Identifier: AGPL-3.0-or-later
"""Report builder (docs/REPORT_BUILDER.md): periods, schedules, groupings,
measures and filters, queue detection, the API with saved reports, and the
scheduled email with its CSV attachment."""

import email
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from test_api_routing import TCS
from test_call_history import _setup, line

from veyra.core import mail
from veyra.core.db import session_scope
from veyra.core.models import CallRecord, SavedReport
from veyra.reporting import builder, cdr, schedule

RUN = "/api/v1/reports/run"
SAVED = "/api/v1/saved-reports"


def test_periods_in_local_time():
    now = datetime(2026, 1, 7, 15, 0, tzinfo=UTC)  # Wednesday 09:00 in Chicago (CST)

    def p(kind, **kw):
        start, end, label = builder.resolve_period(
            builder.Period(kind=kind, **kw), "America/Chicago", now
        )
        return start.astimezone(UTC), end.astimezone(UTC), label

    assert p("today")[2] == "2026-01-07"
    assert p("today")[0] == datetime(2026, 1, 7, 6, 0, tzinfo=UTC)  # local midnight
    assert p("yesterday")[2] == "2026-01-06"
    assert p("this_week")[2] == "2026-01-05 to 2026-01-11"
    assert p("last_week")[2] == "2025-12-29 to 2026-01-04"
    assert p("last_month")[2] == "2025-12-01 to 2025-12-31"
    assert p("this_month")[2] == "2026-01-01 to 2026-01-31"
    assert p("last_7_days")[2] == "2026-01-01 to 2026-01-07"
    assert p("custom", from_date=date(2026, 1, 1), to_date=date(2026, 1, 1))[2] == "2026-01-01"


def test_schedule_next_run_follows_local_hour_across_dst():
    s = schedule.Schedule(frequency="daily", hour=7, recipients=["a@example.org"])
    # Sunday 1 Nov 2026: DST ends in Chicago; 07:00 local is 13:00 UTC after, 12:00 before.
    before = schedule.next_run(s, "America/Chicago", datetime(2026, 10, 31, 13, 0, tzinfo=UTC))
    assert before == datetime(2026, 11, 1, 13, 0, tzinfo=UTC)
    assert schedule.next_run(
        s, "America/Chicago", datetime(2026, 10, 30, 11, 0, tzinfo=UTC)
    ) == datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    weekly = schedule.Schedule(frequency="weekly", weekday=0, hour=6, recipients=["a@example.org"])
    assert schedule.next_run(weekly, "UTC", datetime(2026, 10, 15, 12, 0, tzinfo=UTC)) == datetime(
        2026, 10, 19, 6, 0, tzinfo=UTC
    )
    monthly = schedule.Schedule(frequency="monthly", day=1, hour=0, recipients=["a@example.org"])
    assert schedule.next_run(monthly, "UTC", datetime(2026, 12, 15, tzinfo=UTC)) == datetime(
        2027, 1, 1, tzinfo=UTC
    )


def _fixture(admin):
    """Calls on Monday 12 Oct 2026 in Chicago: 09:00, 09:10 (inbound, queue),
    18:30 (missed, after hours), 09:20 (outbound)."""
    org, (a, a_id), (b, b_id), (c, c_id), trunk = _setup(admin)
    admin.patch(f"/api/v1/organizations/{org['id']}", json={"timezone": "America/Chicago"})
    t0 = datetime(2026, 10, 12, 14, 0, tzinfo=UTC)  # 09:00 CDT

    def at(minutes, seconds=0):
        return (
            (t0 + timedelta(minutes=minutes, seconds=seconds))
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S")
        )

    queued = line(
        "2.2",
        "2.1",
        at(10, 2),
        at(10, 30),
        at(12),
        src="5735551234",
        dst="1003",
        channel="Local/2400@veyra-queue-frontdesk-0000000a;2",
        dstchannel=f"PJSIP/{c}-00000005",
        lastapp="Queue",
    ).replace('"veyra-internal"', '"veyra-queue-frontdesk"')
    lines = [
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
            dstchannel="Local/2400@veyra-queue-frontdesk-0000000a;1",
        ),
        queued,
        line(
            "3.1",
            "3.1",
            at(570),
            "",
            at(570, 25),
            disposition="NO ANSWER",
            src="1003",
            dst="1002",
            channel=f"PJSIP/{c}-00000006",
            dstchannel=f"PJSIP/{b}-00000007",
        ),
        line(
            "4.1",
            "4.1",
            at(20),
            at(20, 2),
            at(21),
            src="1002",
            dst="918005550199",
            channel=f"PJSIP/{b}-00000008",
            dstchannel=f"PJSIP/{trunk}-00000009",
        ),
    ]
    with session_scope() as db:
        cdr.ingest(db, lines, now=t0 + timedelta(days=1))
    tc = admin.post(
        TCS,
        json={
            "organization_id": org["id"],
            "name": "School hours",
            "timezone": "America/Chicago",
            "ranges": [
                {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "07:30", "end": "16:00"}
            ],
        },
    ).json()
    period = {"kind": "custom", "from_date": "2026-10-12", "to_date": "2026-10-12"}
    return org, (a_id, b_id, c_id), tc, period


def test_groupings_measures_filters(admin):
    org, (_a_id, _b_id, c_id), tc, period = _fixture(admin)
    with session_scope() as db:
        q = db.query(CallRecord).filter(CallRecord.linkedid == "2.1").one()
        assert q.queue == "frontdesk" and q.ring_group is None

    def run(**body):
        r = admin.post(RUN, json={"organization_id": org["id"], "period": period, **body})
        assert r.status_code == 200, r.text
        return r.json()

    r = run(group_by=["direction"], measures=["calls", "answered", "answer_rate", "avg_talk"])
    by = {row["group"][0]["key"]: row for row in r["rows"]}
    assert by["internal"]["calls"] == 2 and by["internal"]["answer_rate"] == 50.0
    assert by["inbound"]["calls"] == 1 and by["outbound"]["calls"] == 1
    assert r["totals"]["calls"] == 4 and r["period"]["timezone"] == "America/Chicago"
    assert [c["label"] for c in r["columns"]] == [
        "Direction",
        "Calls",
        "Answered",
        "Answer rate",
        "Average talk",
    ]

    r = run(group_by=["hour"], measures=["calls"])
    assert [(row["group"][0]["label"], row["calls"]) for row in r["rows"]] == [
        ("09:00", 3),
        ("18:00", 1),
    ]

    r = run(group_by=["answered_by", "direction"], measures=["calls"], sort_by="calls")
    labels = [(row["group"][0]["label"], row["group"][1]["label"]) for row in r["rows"]]
    assert ("1002 Nurse", "Internal") in labels and ("1003 Library", "Inbound") in labels

    r = run(group_by=["queue"], measures=["calls", "within_sl"], sl_seconds=10)
    by = {row["group"][0]["key"]: row for row in r["rows"]}
    assert by["frontdesk"]["calls"] == 1 and by["frontdesk"]["within_sl"] == 0.0

    assert (
        run(
            measures=["calls"], filters={"business_hours": "inside", "time_condition_id": tc["id"]}
        )["totals"]["calls"]
        == 3
    )
    assert (
        run(
            measures=["missed"],
            filters={"business_hours": "outside", "time_condition_id": tc["id"]},
        )["totals"]["missed"]
        == 1
    )
    assert run(measures=["calls"], filters={"directions": ["outbound"]})["totals"]["calls"] == 1
    assert run(measures=["calls"], filters={"extension_ids": [c_id]})["totals"]["calls"] == 2
    assert run(measures=["calls"], filters={"caller_contains": "5551234"})["totals"]["calls"] == 1

    # Validation.
    bad = admin.post(RUN, json={"group_by": ["planet"]})
    assert bad.status_code == 422
    assert admin.post(RUN, json={"measures": ["calls"], "sort_by": "answered"}).status_code == 422
    assert admin.post(RUN, json={"filters": {"business_hours": "inside"}}).status_code == 422
    csv_text = admin.post(
        f"{RUN}.csv",
        json={
            "organization_id": org["id"],
            "period": period,
            "group_by": ["direction"],
            "measures": ["calls"],
        },
    ).text
    assert csv_text.splitlines()[0] == "Direction,Calls" and csv_text.splitlines()[-1] == "Total,4"
    units = admin.post(
        f"{RUN}.csv",
        json={
            "organization_id": org["id"],
            "period": period,
            "measures": ["avg_talk", "answer_rate"],
        },
    ).text
    assert units.splitlines()[0] == "Average talk (seconds),Answer rate (%)"
    opts = admin.get("/api/v1/reports/options", params={"organization_id": org["id"]}).json()
    assert opts["dids"] == ["5735550100"] and opts["time_conditions"][0]["label"] == "School hours"


def test_saved_scheduled_and_emailed(admin, app):
    org, _, _, period = _fixture(admin)
    with session_scope() as db:
        mail.save_smtp_settings(
            db,
            mail.SmtpSettings(
                enabled=True, host="smtp.example.org", from_address="veyra@example.org"
            ),
        )
    body = {
        "organization_id": org["id"],
        "name": "Calls by direction",
        "definition": {
            "group_by": ["direction"],
            "measures": ["calls", "answered"],
            "period": period,
        },
        "schedule": {
            "frequency": "weekly",
            "weekday": 0,
            "hour": 7,
            "recipients": ["boss@example.org"],
        },
    }
    r = admin.post(SAVED, json=body)
    assert r.status_code == 201, r.text
    saved = r.json()
    assert (
        saved["next_run_at"]
        and saved["can_edit"]
        and saved["definition"]["organization_id"] == org["id"]
    )
    assert admin.post(SAVED, json=body).status_code == 409
    assert (
        admin.post(
            SAVED,
            json={**body, "name": "x", "schedule": {"frequency": "daily", "recipients": ["nope"]}},
        ).status_code
        == 422
    )
    assert admin.post(f"{SAVED}/{saved['id']}/run").json()["totals"]["calls"] == 4

    queue_dir = app.state.settings.mailqueue_dir
    queue_dir.mkdir(parents=True, exist_ok=True)
    r = admin.post(f"{SAVED}/{saved['id']}/send")
    assert r.status_code == 200, r.text
    files = sorted(queue_dir.glob("*.eml")) or sorted(p for p in queue_dir.iterdir() if p.is_file())
    assert len(files) == 1
    msg = email.message_from_bytes(files[0].read_bytes())
    assert msg["To"] == "boss@example.org" and "Calls by direction: 2026-10-12" in msg["Subject"]
    parts = [p for p in msg.walk() if p.get_filename()]
    assert parts and parts[0].get_content_type() == "text/csv"
    assert parts[0].get_payload(decode=True).decode().startswith("Direction,Calls,Answered")

    # The worker sends it when due and moves the next run on.
    with session_scope() as db:
        rep = db.get(SavedReport, saved["id"])
        due = rep.next_run_at
        assert schedule.process(db, queue_dir, now=due + timedelta(minutes=1)) == 1
        # A week on, at the organization's local hour: across the end of
        # daylight saving time that is not 7 x 24 hours.
        tz = schedule.org_tz(db, rep.organization_id)
        expected = schedule.next_run(schedule.Schedule.model_validate(rep.schedule), tz, due)
        assert rep.next_run_at == expected and rep.last_error is None
        zone = ZoneInfo(tz)
        assert (rep.next_run_at.astimezone(zone).date() - due.astimezone(zone).date()).days == 7
        assert rep.next_run_at.astimezone(zone).hour == due.astimezone(zone).hour
    # Without email delivery the error is kept, and the next run still moves on.
    with session_scope() as db:
        mail.save_smtp_settings(db, mail.SmtpSettings(enabled=False))
        rep = db.get(SavedReport, saved["id"])
        assert schedule.process(db, queue_dir, now=rep.next_run_at + timedelta(minutes=1)) == 0
        assert "email delivery is off" in rep.last_error
    assert (
        admin.patch(f"{SAVED}/{saved['id']}", json={"schedule": None}).json()["next_run_at"] is None
    )
    assert admin.delete(f"{SAVED}/{saved['id']}").status_code == 204
