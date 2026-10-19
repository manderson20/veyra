# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fax (docs/USER_PORTAL.md §9): file helpers, inboxes as destinations, the
generated contexts, a user's send flow through the engine, the engine's
reports, a received fax, retention."""

import struct
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import ADMIN_PASSWORD, login
from fake_adapter import FakeAdapter
from fastapi.testclient import TestClient
from test_api_portal_calls import _ext, _user
from test_generator_callflow import _context, _files, _snapshot

from veyra.core import retention
from veyra.core.db import session_scope
from veyra.core.models import FaxJob
from veyra.fax import service

INBOXES = "/api/v1/fax/inboxes"
JOBS = "/api/v1/fax/jobs"
ME = "/api/v1/me/fax"
PDF = b"%PDF-1.4\n%fake\n%%EOF\n"


def _tiff(pages: int) -> bytes:
    """A little-endian TIFF with ``pages`` empty directories chained together."""
    out = bytearray(b"II*\x00" + struct.pack("<I", 8))
    for i in range(pages):
        nxt = 8 + (i + 1) * 6 if i + 1 < pages else 0
        out += struct.pack("<H", 0) + struct.pack("<I", nxt)
    return bytes(out)


def _fake(app):
    adapter = FakeAdapter(prompts_dir=app.state.settings.prompts_dir)
    app.state.telephony = adapter
    return adapter


def _fake_render(monkeypatch, pages=2):
    def render(pdf, cover, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_tiff(pages + (1 if cover else 0)))
        return pages + (1 if cover else 0)

    monkeypatch.setattr(service, "render", render)


def test_tiff_pages_and_cover_sheet(tmp_path):
    p = tmp_path / "a.tiff"
    p.write_bytes(_tiff(3))
    assert service.tiff_pages(p) == 3
    p.write_bytes(b"not a tiff")
    with pytest.raises(service.FaxError):
        service.tiff_pages(p)
    ps = service.cover_postscript(
        {
            "to": "Dr (Pat) Lee",
            "from": "Front \\ Office",
            "subject": "Forms",
            "note": "Line 1\nLine 2",
        },
        pages=4,
        when=datetime(2026, 10, 19, 12, 0, tzinfo=UTC),
    ).decode()
    assert "(Dr \\(Pat\\) Lee) show" in ps and "(Front \\\\ Office) show" in ps
    assert "(5 \\(including this cover\\)) show" in ps and "(Line 2) show" in ps
    assert service.normalize_number("(573) 555-0100") == "5735550100"
    assert service.normalize_number("+1 573 555 0100") == "+15735550100"
    assert service.normalize_number("call me") == ""


def test_inbox_crud_destination_and_generated_contexts(admin, app):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    r = admin.post(
        INBOXES,
        json={
            "organization_id": org["id"],
            "name": "Front office",
            "recipients": ["Office@Example.org", "office@example.org"],
            "station_id": "+1 573 555 0199",
            "header": "Example Schools",
        },
    )
    assert r.status_code == 201, r.text
    inbox = r.json()
    assert inbox["slug"] == "front-office" and inbox["context"] == "veyra-fax-in-front-office"
    assert inbox["recipients"] == ["office@example.org"]
    assert (
        admin.post(
            INBOXES, json={"organization_id": org["id"], "name": "x", "recipients": ["nope"]}
        ).status_code
        == 422
    )
    # A DID pointed at the inbox: the destination kind "fax".
    ext = _ext(admin, org["id"], "1001")
    route = admin.post(
        "/api/v1/routing/inbound",
        json={
            "organization_id": org["id"],
            "did": "5735550188",
            "destination_type": "fax",
            "destination_fax_inbox_id": inbox["id"],
        },
    )
    assert route.status_code == 201, route.text
    assert route.json()["destination"]["label"] == "Fax to email: Front office"
    assert route.json()["destination"]["fax_inbox_id"] == inbox["id"]
    r = admin.delete(f"{INBOXES}/{inbox['id']}")
    assert r.status_code == 409 and r.json()["code"] == "fax_inbox_in_use"
    # Admin patch and the list.
    r = admin.patch(
        f"{INBOXES}/{inbox['id']}", json={"recipients": ["a@example.org"], "header": " "}
    )
    assert (
        r.status_code == 200
        and r.json()["recipients"] == ["a@example.org"]
        and r.json()["header"] is None
    )
    assert admin.get(INBOXES, params={"organization_id": org["id"]}).json()["total"] == 1
    # The engine side: route → fax-in context, the fax-out context, T.38 on a trunk.
    files = _files(
        _snapshot(
            fax_inboxes=[
                {
                    "slug": "front-office",
                    "name": "Front office",
                    "organization": "example",
                    "header": "Example Schools",
                    "station_id": "+15735550199",
                }
            ],
            inbound_routes=[
                {
                    "did": "5735550188",
                    "organization_slug": "example",
                    "destination": {"type": "fax", "fax_inbox": "front-office"},
                    "trunks": [],
                }
            ],
            trunks=[
                {
                    "slug": "carrier",
                    "name": "Carrier",
                    "auth_mode": "ip",
                    "host": "203.0.113.10",
                    "port": 5060,
                    "transport": "udp",
                    "match_addresses": ["203.0.113.10"],
                    "fax_t38": True,
                }
            ],
        )
    )
    dialplan = files["extensions.conf"]
    inbound = _context(dialplan, "veyra-fax-in-front-office")
    assert "ReceiveFAX(${VEYRA_FAX_FILE})" in inbound
    assert "Set(FAXOPT(localstationid)=+15735550199)" in inbound
    assert "UserEvent(VeyraFax,Direction: in,Inbox: front-office,Org: example," in inbound
    assert "/var/lib/veyra/fax/incoming/front-office-${UNIQUEID}.tiff" in inbound
    out = _context(dialplan, "veyra-fax-out")
    assert "SendFAX(${VEYRA_FAX_FILE},d)" in out and "Direction: out,Job: ${VEYRA_FAX_JOB}" in out
    assert "Goto(veyra-fax-in-front-office,s,1)" in dialplan
    assert "t38_udptl=yes" in files["pjsip.trunks.conf"]
    assert _files(_snapshot())["pjsip.trunks.conf"].count("t38_udptl") == 0
    # Cleanup.
    admin.delete(f"/api/v1/routing/inbound/{route.json()['id']}")
    assert admin.delete(f"{INBOXES}/{inbox['id']}").status_code == 204
    admin.delete(f"/api/v1/extensions/{ext['id']}")


def test_send_flow_reports_retry_and_cancel(admin, app, monkeypatch):
    adapter = _fake(app)
    _fake_render(monkeypatch)
    settings = app.state.settings
    uid, org = _user(admin, "pat.fax@example.org")
    ext = _ext(admin, org, "1201", user_id=uid, outbound_caller_id_number="5735550100")
    pat = login(
        TestClient(app, base_url="http://veyra.test"), "pat.fax@example.org", ADMIN_PASSWORD
    )
    sent_mail: list[tuple[str, str]] = []
    monkeypatch.setattr(service, "_sender", lambda db: ("veyra@example.org", "Veyra"))
    monkeypatch.setattr(
        service, "_enqueue", lambda s, msg: sent_mail.append((msg["To"], msg["Subject"]))
    )

    files = {"file": ("forms.pdf", PDF, "application/pdf")}
    r = pat.post(ME, data={"number": "(573) 555-0123"}, files=files)
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["state"] == "queued" and job["pages"] == 2 and job["number"] == "5735550123"
    assert job["caller_id"] == "5735550100" and job["extension_number"] == "1201"
    # Validation: not a PDF, bad number, cover sheet adds a page.
    assert (
        pat.post(
            ME, data={"number": "5735550123"}, files={"file": ("a.txt", b"hello", "text/plain")}
        ).status_code
        == 415
    )
    assert pat.post(ME, data={"number": "abc"}, files=files).status_code == 422
    r = pat.post(
        ME,
        data={"number": "5735550124", "cover": "true", "cover_to": "Pat", "cover_subject": "Forms"},
        files=files,
    )
    assert r.status_code == 201 and r.json()["pages"] == 3 and r.json()["has_cover"]
    second = r.json()["id"]

    # The worker starts the sends through the engine with the job's variables.
    with session_scope() as db:
        assert service.start_due(db, settings, adapter) == 2
    endpoint, exten, context, variables = adapter.originated_channels[0]
    assert endpoint == "Local/5735550123@veyra-outbound/n" and exten == "send"
    assert context == "veyra-fax-out"
    assert (
        variables["__VEYRA_FAX_JOB"] == job["id"] and variables["__VEYRA_OUT_CID"] == "5735550100"
    )
    assert variables["__VEYRA_FAX_FILE"].endswith(f"/{job['id']}.tiff")
    listed = pat.get(ME).json()
    assert {j["id"]: j["state"] for j in listed} == {job["id"]: "dialling", second: "dialling"}

    # Busy: another attempt later; then success with the pages reported.
    with session_scope() as db:
        row = service.channel_gone(db, settings, "chan-1", cause=17, cause_txt="User busy")
        assert row is not None and row.state == "queued" and row.attempts == 1
        assert row.next_attempt_at is not None and "User busy" in (row.error or "")
        row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    with session_scope() as db:
        assert service.start_due(db, settings, adapter) == 1
    with session_scope() as db:
        row = service.handle_userevent(
            db,
            settings,
            {
                "Direction": "out",
                "Job": job["id"],
                "Status": "SUCCESS",
                "Pages": "2",
                "Remote": "573 555 0123",
            },
        )
        assert row is not None and row.state == "sent" and row.remote_id == "573 555 0123"
    assert (
        sent_mail and sent_mail[-1][0] == "pat.fax@example.org" and "delivered" in sent_mail[-1][1]
    )
    # A late report for a finished job changes nothing.
    with session_scope() as db:
        assert (
            service.handle_userevent(
                db, settings, {"Direction": "out", "Job": job["id"], "Status": "FAILED"}
            )
            is None
        )

    # The second connected but failed twice: given up, the user is told.
    with session_scope() as db:
        row = service.handle_userevent(
            db,
            settings,
            {"Direction": "out", "Job": second, "Status": "FAILED", "Error": "T.30 timeout"},
        )
        assert row is not None and row.state == "queued" and row.attempts == 1
        row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    with session_scope() as db:
        service.start_due(db, settings, adapter)
        row = service.handle_userevent(
            db,
            settings,
            {"Direction": "out", "Job": second, "Status": "FAILED", "Error": "T.30 timeout"},
        )
        assert row is not None and row.state == "failed" and "T.30 timeout" in (row.error or "")
    assert "failed" in sent_mail[-1][1]
    # Retry from My Phone, then cancel while queued; download the PDF.
    assert pat.post(f"{ME}/{second}/retry").json()["state"] == "queued"
    assert pat.post(f"{ME}/{second}/cancel").json()["state"] == "cancelled"
    assert pat.post(f"{ME}/{second}/cancel").status_code == 409
    r = pat.get(f"{ME}/{job['id']}/file")
    assert (
        r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content == PDF
    )
    # Another user sees nothing of Pat's.
    _user(admin, "sam.fax@example.org")
    sam = login(
        TestClient(app, base_url="http://veyra.test"), "sam.fax@example.org", ADMIN_PASSWORD
    )
    assert sam.get(ME).json() == [] and sam.get(f"{ME}/{job['id']}/file").status_code == 404
    # No extension → 409; class of service without fax → 422.
    assert sam.post(ME, data={"number": "5735550123"}, files=files).json()["code"] == "no_extension"
    cos = admin.post(
        "/api/v1/classes-of-service",
        json={"organization_id": org, "name": "No fax", "allow_fax": False},
    )
    assert cos.status_code == 201, cos.text
    assert (
        admin.patch(
            f"/api/v1/extensions/{ext['id']}", json={"class_of_service_id": cos.json()["id"]}
        ).status_code
        == 200
    )
    assert pat.post(ME, data={"number": "5735550123"}, files=files).json()["code"] == "cos_denied"
    # Administrators: the organization's jobs, audit of the self-service actions.
    r = admin.get(JOBS, params={"organization_id": org})
    assert r.status_code == 200 and r.json()["total"] == 2
    assert admin.get(JOBS, params={"state": "sent"}).json()["total"] == 1
    r = admin.get(f"{JOBS}/{job['id']}/file")
    assert r.status_code == 200 and r.content == PDF
    actions = {
        e["action"]
        for e in admin.get("/api/v1/audit", params={"q": "fax", "limit": 200}).json()["items"]
    }
    assert {"fax.send", "fax.cancel", "fax.retry", "fax.download"} <= actions
    # Attempts the engine never reported on time out.
    with session_scope() as db:
        stuck = FaxJob(
            id=uuid.uuid4(),
            organization_id=uuid.UUID(org),
            direction="out",
            number="5735550199",
            state="dialling",
            attempts=3,
            started_at=datetime.now(UTC) - timedelta(minutes=11),
            pages=1,
        )
        db.add(stuck)
        db.flush()
        assert service.expire(db, settings) == 1 and stuck.state == "failed"
        db.delete(stuck)


def test_received_fax_becomes_pdf_by_email_and_retention(admin, app, monkeypatch):
    settings = app.state.settings
    org = admin.get("/api/v1/organizations").json()["items"][0]
    r = admin.post(
        INBOXES,
        json={
            "organization_id": org["id"],
            "name": "Attendance",
            "recipients": ["att@example.org", "boss@example.org"],
        },
    )
    assert r.status_code == 201, r.text
    inbox = r.json()
    mails: list[tuple[str, str, list[str]]] = []
    monkeypatch.setattr(service, "_sender", lambda db: ("veyra@example.org", "Veyra"))
    monkeypatch.setattr(
        service,
        "_enqueue",
        lambda s, msg: mails.append(
            (msg["To"], msg["Subject"], [p.get_filename() for p in msg.iter_attachments()])
        ),
    )

    def to_pdf(tiff: Path, dest: Path) -> None:
        dest.write_bytes(PDF)

    monkeypatch.setattr(service, "to_pdf", to_pdf)
    incoming = settings.fax_dir / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    src = incoming / "attendance-1760900000.123.tiff"
    src.write_bytes(_tiff(3))
    with session_scope() as db:
        job = service.handle_userevent(
            db,
            settings,
            {
                "Direction": "in",
                "Inbox": "attendance",
                "Org": org["slug"],
                "File": str(src),
                "Status": "SUCCESS",
                "Pages": "3",
                "Remote": "Clinic",
                "Caller": "5735550177",
            },
        )
        assert (
            job is not None
            and job.state == "received"
            and job.pages == 3
            and job.number == "5735550177"
        )
        assert job.pdf_file and (settings.fax_dir / job.pdf_file).read_bytes() == PDF
        assert job.file and (settings.fax_dir / job.file).exists() and not src.exists()
        job_id = job.id
    assert [m[0] for m in mails] == ["att@example.org", "boss@example.org"]
    assert mails[0][1] == "Fax from 5735550177 for Attendance (3 pages)"
    assert mails[0][2] and mails[0][2][0].endswith("-5735550177.pdf")
    # A file outside the incoming directory is refused; the job still records the fax.
    with session_scope() as db:
        bad = service.handle_userevent(
            db,
            settings,
            {
                "Direction": "in",
                "Inbox": "attendance",
                "File": "/etc/passwd",
                "Status": "SUCCESS",
                "Pages": "1",
                "Caller": "anonymous",
            },
        )
        assert (
            bad is not None
            and bad.state == "received"
            and bad.pdf_file is None
            and "not found" in (bad.error or "")
        )
    # Administrators list it with the inbox name and download the PDF.
    r = admin.get(JOBS, params={"direction": "in"})
    assert r.status_code == 200
    mine = [j for j in r.json()["items"] if j["id"] == str(job_id)][0]
    assert mine["inbox_name"] == "Attendance" and mine["has_file"]
    assert admin.get(f"{JOBS}/{job_id}/file").content == PDF
    # Retention removes old faxes and their files, never those in progress.
    with session_scope() as db:
        row = db.get(FaxJob, job_id)
        assert row is not None
        row.created_at = datetime.now(UTC) - timedelta(days=400)
        pdf_path = settings.fax_dir / str(row.pdf_file)
        active = FaxJob(
            id=uuid.uuid4(),
            organization_id=uuid.UUID(org["id"]),
            direction="out",
            number="1",
            state="queued",
            pages=0,
            created_at=datetime.now(UTC) - timedelta(days=400),
        )
        db.add(active)
    assert "fax" in {rule.key for rule in retention.RULES}
    with session_scope() as db:
        removed = retention.run(db, app_settings=settings)
        assert removed.get("fax", 0) >= 1
        assert db.get(FaxJob, job_id) is None and db.get(FaxJob, active.id) is not None
        db.delete(db.get(FaxJob, active.id))
    assert not pdf_path.exists()
    assert admin.delete(f"{INBOXES}/{inbox['id']}").status_code == 204
