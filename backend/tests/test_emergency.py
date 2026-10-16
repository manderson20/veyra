# SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: E501
"""Emergency calling validation (docs/PRODUCTION_HARDENING.md §6): the
generator's site-bound routes, notification event and PSAP callback; the
service's record, notification and readiness; the API."""

from __future__ import annotations

import uuid
from datetime import timedelta

from conftest import ADMIN_EMAIL
from sqlalchemy import select
from test_generator_routing import _files, _route, _section, _snapshot

from veyra.core.db import session_scope
from veyra.core.models import EmergencyCall, Extension, Organization, Site
from veyra.core.models.base import utcnow
from veyra.emergency import service
from veyra.telephony.asterisk.events import is_emergency_event

SITE_A = "11111111-1111-1111-1111-111111111111"
SITE_B = "22222222-2222-2222-2222-222222222222"


def test_generator_site_routes_event_and_callback():
    site_route = _route(
        "em-a",
        is_emergency=True,
        site=SITE_A,
        patterns=[{"prefix": "", "match": "911", "prepend": ""}],
        caller_id_number="5735550101",
    )
    global_route = _route(
        "em-all",
        is_emergency=True,
        patterns=[{"prefix": "", "match": "911", "prepend": ""}],
        caller_id_number="5735550199",
    )
    local = _route()
    ext = {
        "endpoint_name": "example-1001",
        "number": "1001",
        "display_name": "Front Office",
        "organization": "example",
        "secret": "s3cret",
        "site": SITE_A,
        "emergency_caller_id_number": "5735550101",
    }
    sites = [
        {
            "id": SITE_A,
            "slug": "main",
            "name": "Main",
            "organization": "example",
            "emergency_caller_id_number": "5735550101",
            "callback_minutes": 20,
            "responder": "1001",
        }
    ]
    files = _files(
        _snapshot(
            extensions=[ext],
            outbound_routes=[local, global_route, site_route],
            inbound_routes=[],
            sites=sites,
        )
    )
    d = files["extensions.conf"].content
    pj = files["pjsip.endpoints.conf"].content
    assert f"set_var=__VEYRA_SITE={SITE_A}" in pj
    outbound = _section(d, "veyra-outbound")
    # Site-bound first, then the installation-wide one, then normal routes.
    assert (
        outbound.index("veyra-out-em-a")
        < outbound.index("veyra-out-em-all")
        < outbound.index("veyra-out-local")
    )
    em_a = _section(d, "veyra-out-em-a")
    assert f'GotoIf($["${{VEYRA_SITE}}"!="{SITE_A}"]?veyra-out-em-all,${{EXTEN}},1)' in em_a
    assert (
        "UserEvent(VeyraEmergency,Extension: ${CALLERID(num)},Site: ${VEYRA_SITE},Number: ${EXTEN},Route: em-a,"
        in em_a
    )
    assert "Set(DB(veyra_ecb/${VEYRA_EMERGENCY_CID})=${CALLERID(num)}|${EPOCH})" in em_a
    em_all = _section(d, "veyra-out-em-all")
    assert 'GotoIf($["${VEYRA_SITE}"' not in em_all  # the last emergency route serves everyone
    # The ELIN without an inbound route of its own takes the callback.
    shared = _section(d, "veyra-from-trunk")
    assert "exten => 5735550101,1,NoOp(Veyra emergency callback for main)" in shared
    assert "Set(VEYRA_ECB=${DB(veyra_ecb/5735550101)})" in shared
    assert "GotoIf($[${EPOCH} - ${VEYRA_ECB_AT} > 1200]?responder)" in shared
    assert "Goto(veyra-internal,${VEYRA_ECB_EXT},1)" in shared
    assert "Goto(veyra-internal,1001,1)" in shared  # the responder
    assert "[veyra-emergency-notify]" in d and "SayDigits(${EXTEN})" in d
    # An ELIN that is also a routed DID gets the callback inside its route.
    files = _files(
        _snapshot(
            extensions=[ext],
            outbound_routes=[site_route],
            inbound_routes=[
                {
                    "did": "5735550101",
                    "destination": {"type": "extension", "number": "1001"},
                    "organization_slug": "example",
                }
            ],
            sites=sites,
        )
    )
    d = files["extensions.conf"].content
    shared = _section(d, "veyra-from-trunk")
    assert shared.count("exten => 5735550101,1,") == 1
    assert "Set(VEYRA_ECB=${DB(veyra_ecb/5735550101)})" in shared


def test_event_detection():
    assert is_emergency_event({"type": "ChannelUserevent", "eventname": "VeyraEmergency"})
    assert not is_emergency_event({"type": "ChannelUserevent", "eventname": "Other"})
    assert not is_emergency_event({"type": "ChannelCreated"})


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def originate(self, endpoint, number, *, caller_id, context, timeout=30):
        self.calls.append((endpoint, number, caller_id, context))
        return "chan-1"

    def capabilities(self):
        from veyra.telephony.adapter import Capability

        return {Capability.CLICK_TO_DIAL}


def _site_and_ext(admin, **site_over):
    with session_scope() as db:
        org = db.query(Organization).first()
        org_id = str(org.id)
    site = admin.post(
        "/api/v1/sites",
        json={
            "organization_id": org_id,
            "name": "Main Campus",
            "street": "1 School St",
            "city": "Brookfield",
            "region": "MO",
            "postal_code": "64628",
            "country": "US",
            "emergency_caller_id_number": "5735550101",
            **site_over,
        },
    ).json()
    ext = admin.post(
        "/api/v1/extensions",
        json={
            "organization_id": org_id,
            "number": "1001",
            "display_name": "Front Office",
            "site_id": site["id"],
            "location": "Room 101, first floor",
        },
    ).json()
    return org_id, site, ext


def test_service_records_notifies_and_readiness(admin, app, tmp_path):
    org_id, site, ext = _site_and_ext(admin)
    assert ext["location"] == "Room 101, first floor"
    responder = admin.post(
        "/api/v1/extensions",
        json={
            "organization_id": org_id,
            "number": "1000",
            "display_name": "Office",
            "site_id": site["id"],
            "location": "Front desk",
        },
    ).json()
    adapter = FakeAdapter()
    settings = app.state.settings
    with session_scope() as db:
        s = db.get(Site, uuid.UUID(site["id"]))
        s.emergency_recipients = {
            "emails": ["office@district.local"],
            "extensions": ["1000"],
            "webhook": True,
        }
        db.commit()
        call = service.handle_event(
            db,
            settings,
            adapter,
            {
                "Extension": "1001",
                "Site": site["id"],
                "Number": "911",
                "Route": "em-a",
                "EmergencyCID": "5735550101",
                "Channel": "PJSIP/example-1001-0001",
            },
        )
        db.commit()
        assert call.site_id == uuid.UUID(site["id"]) and call.extension_id == uuid.UUID(ext["id"])
        assert call.location == "Room 101, first floor, 1 School St, Brookfield, MO, 64628, US"
        assert call.caller_id == "5735550101" and call.callback_until > utcnow()
        assert call.notifications["email"]["state"] == "queued"
        assert call.notifications["extensions"] == {"1000": "ringing"}
        assert call.notifications["webhook"]["state"] == "queued"
        assert (
            adapter.calls[0][0] == f"PJSIP/{responder['endpoint_name']}"
            and adapter.calls[0][3] == "veyra-emergency-notify"
        )
        assert adapter.calls[0][2] == "EMERGENCY 1001"
    queued = list(settings.mailqueue_dir.glob("*.eml"))
    assert len(queued) == 1 and b"EMERGENCY call from Front Office (1001)" in queued[0].read_bytes()
    with session_scope() as db:
        s = db.get(Site, uuid.UUID(site["id"]))
        r = service.readiness(db, s)
        by = {c["key"]: c for c in r["checks"]}
        assert not r["ready"]
        assert (
            by["elin"]["ok"]
            and by["address"]["ok"]
            and by["locations"]["ok"]
            and by["recipients"]["ok"]
        )
        assert not by["route"]["ok"] and not by["attested"]["ok"] and not by["test_call"]["ok"]
        assert not by["notification_test"]["ok"]


def test_emergency_api(admin, app):
    org_id, site, ext = _site_and_ext(admin)
    overview = admin.get("/api/v1/emergency/sites").json()
    assert overview["ready"] == 0 and overview["sites"][0]["name"] == "Main Campus"
    assert "carrier" in overview["disclaimer"]
    detail = admin.get(f"/api/v1/emergency/sites/{site['id']}").json()
    assert detail["readiness"]["ready"] is False and detail["settings"]["attested"] is False
    r = admin.put(
        f"/api/v1/emergency/sites/{site['id']}",
        json={
            "attested": True,
            "responder_extension_id": ext["id"],
            "callback_minutes": 45,
            "recipients": {
                "emails": ["office@district.local"],
                "extensions": ["1001"],
                "webhook": True,
            },
        },
    )
    assert r.status_code == 200, r.text
    st = r.json()["settings"]
    assert st["attested"] and st["attested_by"] == ADMIN_EMAIL and st["responder_number"] == "1001"
    assert st["callback_minutes"] == 45 and st["recipients"]["extensions"] == ["1001"]
    r = admin.put(
        f"/api/v1/emergency/sites/{site['id']}", json={"recipients": {"extensions": ["9999"]}}
    )
    assert r.status_code == 422
    # A notification test records a test call and the notification date.
    r = admin.post(f"/api/v1/emergency/sites/{site['id']}/test-notification")
    assert r.status_code == 200 and r.json()["ok"] and r.json()["call"]["kind"] == "test"
    assert admin.get(f"/api/v1/emergency/sites/{site['id']}").json()["settings"][
        "last_notification_test_at"
    ]
    # Test calls count toward readiness for a year.
    r = admin.post(
        f"/api/v1/emergency/sites/{site['id']}/test-call",
        json={"result": "933 read back 1 School St"},
    )
    by = {c["key"]: c for c in r.json()["readiness"]["checks"]}
    assert by["test_call"]["ok"] and by["notification_test"]["ok"] and by["attested"]["ok"]
    old = (utcnow() - timedelta(days=400)).isoformat()
    r = admin.post(
        f"/api/v1/emergency/sites/{site['id']}/test-call", json={"result": "old", "at": old}
    )
    assert not {c["key"]: c for c in r.json()["readiness"]["checks"]}["test_call"]["ok"]
    r = admin.post(
        f"/api/v1/emergency/sites/{site['id']}/test-call",
        json={"result": "no audio", "succeeded": False},
    )
    assert "FAILED" in r.json()["settings"]["last_test_result"]
    calls = admin.get("/api/v1/emergency/calls").json()
    assert len(calls) == 1 and calls[0]["kind"] == "test" and calls[0]["number"] == "933"
    # A route bound to the site shows on the outbound route API.
    trunk = admin.post(
        "/api/v1/trunks",
        json={
            "name": "Carrier",
            "auth_mode": "ip",
            "host": "198.51.100.7",
            "match_addresses": ["198.51.100.7"],
        },
    ).json()
    r = admin.post(
        "/api/v1/routing/outbound",
        json={
            "name": "Emergency Main",
            "is_emergency": True,
            "site_id": site["id"],
            "patterns": [{"prefix": "", "match": "911"}],
            "trunk_ids": [trunk["id"]],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["site_id"] == site["id"]
    by = {
        c["key"]: c
        for c in admin.get(f"/api/v1/emergency/sites/{site['id']}").json()["readiness"]["checks"]
    }
    assert by["route"]["ok"]
    with session_scope() as db:
        assert (
            db.scalar(select(Extension.location).where(Extension.id == uuid.UUID(ext["id"])))
            == "Room 101, first floor"
        )
        assert db.query(EmergencyCall).count() == 1
