# SPDX-License-Identifier: AGPL-3.0-or-later
"""Supervisor listen, whisper and barge (issue #167): phone codes only for
classes that allow supervising, protected classes refuse, the web rings the
supervisor's phone, and every session is audited."""

from fake_adapter import FakeAdapter
from test_api_calls import _create, _org
from test_features import _section
from test_features import _snapshot as _ext_snapshot

from veyra.telephony.adapter import ActiveCall
from veyra.telephony.asterisk import events, generator

SPY = {"spy_listen": "*222", "spy_whisper": "*223", "spy_barge": "*224"}


def _cls(slug, **over):
    return {
        "slug": slug,
        "name": slug.title(),
        "organization": "example",
        "allowed_routes": [],
        "allowed_feature_codes": None,
        "allow_external_forwards": True,
        "allow_external_follow_me": True,
        "allow_intercom": True,
        "max_outbound_calls": None,
        **over,
    }


def _dialplan(classes, **ext_over):
    snap = _ext_snapshot(feature_codes=SPY, numbering={"extension_length": 4})
    snap["extensions"][0].update(ext_over)
    snap["classes_of_service"] = classes
    return {f.path: f.content for f in generator.generate(snap)}["extensions.conf"]


def test_codes_only_for_supervisor_classes_and_never_on_protected_phones():
    assert "_*222." not in _dialplan([_cls("office")])
    d = _dialplan(
        [_cls("office", allow_monitor=True), _cls("counselor", monitor_protected=True)],
        class_of_service="counselor",
    )
    calls = _section(d, "veyra-call-codes")
    listen = calls.split("exten => _*222.,1,")[1].split("exten => ")[0]
    assert '${REGEX("^(office)$" ${VEYRA_COS})}?spy:cosdenied)' in listen
    assert "Set(VEYRA_SPYDEV=${HINT(${EXTEN:4}@veyra-internal)})" in listen
    assert '${REGEX("^PJSIP/[A-Za-z0-9_.-]+$" ${VEYRA_SPYDEV})}]?cosdenied)' in listen
    assert "UserEvent(VeyraMonitor,Org: ${VEYRA_ORG},By: ${VEYRA_EXT}," in listen
    assert "ChanSpy(${VEYRA_SPYDEV}-,qE)" in listen
    assert "ChanSpy(${VEYRA_SPYDEV}-,qEw)" in calls and "ChanSpy(${VEYRA_SPYDEV}-,qEB)" in calls
    # The counselor's phone has its own refusing entry for every mode.
    for code in SPY.values():
        assert f"exten => {code}1001,1,NoOp(Veyra: 1001 may not be monitored)" in calls
    spy = _section(d, "veyra-spy")
    assert "ChanSpy(${VEYRA_SPY_CHAN},qE${VEYRA_OPT})" in spy
    assert '${REGEX("^PJSIP/[A-Za-z0-9_.-]+-[0-9a-f]+$" ${VEYRA_SPY_CHAN})}]?bad)' in spy


def test_web_monitor_rings_the_supervisor_and_is_audited(admin, app):
    adapter = FakeAdapter()
    app.state.telephony = adapter
    o = _org(admin)["id"]
    me = admin.get("/api/v1/auth/session").json()["user"]
    desk = _create(admin, o, "1001", "Front desk")
    mine = _create(admin, o, "1009", "Supervisor", user_id=me["id"])
    adapter.calls = [ActiveCall("1697.1", "1001", "5735550100", "Up", 30, desk["endpoint_name"])]
    r = admin.post("/api/v1/calls/1697.1/monitor", json={"mode": "whisper"})
    assert r.status_code == 202, r.text
    assert "1009 is ringing" in r.json()["message"]
    (chan, ep, mode, ctx) = adapter.monitor_calls[0]
    assert (chan, ep, mode, ctx) == ("1697.1", mine["endpoint_name"], "whisper", "veyra-spy")
    assert admin.post("/api/v1/calls/1697.1/monitor", json={"mode": "steal"}).status_code == 422
    assert admin.post("/api/v1/calls/9.9/monitor", json={"mode": "listen"}).status_code == 404
    # A protected class refuses.
    cls = admin.post(
        "/api/v1/classes-of-service",
        json={"organization_id": o, "name": "Counselor", "monitor_protected": True},
    ).json()
    assert cls["monitor_protected"] is True and cls["allow_monitor"] is False
    admin.patch(f"/api/v1/extensions/{desk['id']}", json={"class_of_service_id": cls["id"]})
    r = admin.post("/api/v1/calls/1697.1/monitor", json={"mode": "listen"})
    assert r.status_code == 409 and r.json()["code"] == "monitor_protected"
    audit = admin.get("/api/v1/audit", params={"q": "call.monitor"}).json()
    assert audit["total"] == 1


def test_phone_code_sessions_are_audited(admin):
    o = _org(admin)["id"]
    _create(admin, o, "1001", "Front desk")
    events._monitor(
        {
            "type": "ChannelUserevent",
            "eventname": "VeyraMonitor",
            "userevent": {"Org": "example", "By": "1009", "Target": "1001", "Mode": "barge"},
        }
    )
    rows = admin.get("/api/v1/audit", params={"q": "call.monitor"}).json()["items"]
    assert rows and rows[0]["details"]["mode"] == "barge"
    assert rows[0]["actor_label"] == "phone 1009"


def test_beep_when_the_organization_asks_for_it(admin, app):
    snap = _ext_snapshot(feature_codes=SPY, numbering={"extension_length": 4})
    snap["classes_of_service"] = [_cls("office", allow_monitor=True)]
    quiet = {f.path: f.content for f in generator.generate(snap)}["extensions.conf"]
    assert "Gosub(veyra-spy-beep" not in _section(quiet, "veyra-call-codes")
    snap["organizations"][0]["monitor_beep"] = True
    d = {f.path: f.content for f in generator.generate(snap)}["extensions.conf"]
    listen = _section(d, "veyra-call-codes").split("exten => _*222.,1,")[1].split("exten => ")[0]
    beep = (
        'ExecIf(${REGEX("^(example)$" ${VEYRA_ORG})}'
        "?Gosub(veyra-spy-beep,s,1(${CUT(VEYRA_SPYDEV,/,2)}-)))"
    )
    assert listen.index(beep) < listen.index("ChanSpy(${VEYRA_SPYDEV}-,qE)")
    ctx = _section(d, "veyra-spy-beep")
    assert "Originate(Local/play@veyra-spy-beep/n,exten,veyra-spy-beep,${ARG1},1,5)" in ctx
    assert "exten => _[A-Za-z0-9].,1,ChanSpy(PJSIP/${EXTEN},qBE)" in ctx
    assert "Playback(beep)" in ctx
    assert 'ExecIf($["${VEYRA_SPY_BEEP}"="1"]' in _section(d, "veyra-spy")

    # The web passes the organization's choice to the engine.
    adapter = FakeAdapter()
    app.state.telephony = adapter
    o = _org(admin)["id"]
    assert admin.patch(f"/api/v1/organizations/{o}", json={"monitor_beep": True}).json()[
        "monitor_beep"
    ]
    me = admin.get("/api/v1/auth/session").json()["user"]
    desk = _create(admin, o, "1001", "Front desk")
    _create(admin, o, "1009", "Supervisor", user_id=me["id"])
    adapter.calls = [ActiveCall("1697.1", "1001", "5735550100", "Up", 30, desk["endpoint_name"])]
    assert admin.post("/api/v1/calls/1697.1/monitor", json={"mode": "listen"}).status_code == 202
    assert adapter.monitor_beep is True
