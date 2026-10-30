# SPDX-License-Identifier: AGPL-3.0-or-later
"""Custom dialplan (docs/CUSTOM_DIALPLAN.md)."""

import pytest

from veyra.telephony import custom_dialplan as cd

GOOD = """; after-hours trick
[custom-night]
exten => s,1,NoOp(night)
 same => n(again),Playback(system-message)
 same => n,Set(X=${CALLERID(num)})
 same => n,Goto(custom-other,s,1)
include => custom-other

[custom-other]
exten => _1XX,1,Hangup()
"""


def test_good_text_is_accepted():
    assert cd.problems(GOOD) == []
    assert cd.contexts(GOOD) == ["custom-night", "custom-other"]


@pytest.mark.parametrize(
    "line",
    [
        "exten => s,1,System(id)",
        "exten => s,1,system (id)",
        "exten => s,1,TrySystem(id)",
        "exten => s,1,NoOp(${SHELL(id)})",
        "exten => s,1,Set(X=${FILE(/etc/passwd)})",
        "exten => s,1,Set(FILE(/tmp/x)=y)",
        "exten => s,1,NoOp(${AST_CONFIG(pjsip.conf,a,b)})",
        "exten => s,1,NoOp(${EVAL(${X})})",
        "exten => s,1,NoOp(${${A}${B}(id)})",
        "exten => s,1,Set(${A}(x)=y)",
        "exten => s,1,ExecIf($[1]?System(id))",
        "exten => s,1,Exec(${X})",
        "exten => s,1,AGI(x.sh)",
        "exten => s,1,MixMonitor(a.wav,,rm -rf x)",
        "exten => s,1,Originate(Local/1,app,System,id)",
        "exten => s,1,${APP}(x)",
        "exten => s,1,Sys\\tem(id)",
        "same => n,NoOp(x)--;",
        "#include /etc/passwd",
        '#exec "id"',
        "include => from-internal",
        "switch => Realtime/x",
        "eswitch => x",
        "ignorepat => 9",
        "VAR=1",
        "exten = s,1,NoOp()",
        "[general]",
        "[custom-x](!)",
        "[custom-X]",
        "[veyra-internal]",
        "; open --;",
        ";-- open",
    ],
)
def test_refused(line):
    assert cd.problems(f"[custom-a]\nexten => s,1,NoOp()\n{line}\n")


def test_lines_outside_a_context_are_refused():
    assert cd.problems("exten => s,1,NoOp()\n")


def test_include_must_be_defined_here():
    assert cd.problems("[custom-a]\ninclude => custom-b\n")


def test_harmless_words_are_not_refused():
    assert not cd.problems("[custom-a]\nexten => s,1,Playback(system-file-queue)\n")


def test_generated_dialplan_carries_the_text_and_refuses_bad_text():
    from test_generator_voicemail_ivr import _snapshot

    from veyra.telephony.asterisk import generator

    snap = _snapshot()
    snap["custom_dialplan"] = GOOD
    files = {f.path: f for f in generator.generate(snap, prompts_dir="/var/lib/veyra/prompts")}
    assert "[custom-night]" in files[generator.FILE_DIALPLAN].content
    snap["custom_dialplan"] = "[custom-a]\nexten => s,1,System(id)\n"
    with pytest.raises(generator.GenerationError):
        generator.generate(snap, prompts_dir="/var/lib/veyra/prompts")


def test_api_saves_audits_and_refuses(admin):
    r = admin.put("/api/v1/telephony/custom-dialplan", json={"text": GOOD})
    assert r.status_code == 200, r.text
    assert r.json()["contexts"] == ["custom-night", "custom-other"]
    assert admin.get("/api/v1/telephony/custom-dialplan").json()["text"] == GOOD
    r = admin.put(
        "/api/v1/telephony/custom-dialplan", json={"text": "[custom-a]\nexten => s,1,System(id)\n"}
    )
    assert r.status_code == 422
    assert "System" in r.json()["errors"][0]["message"]
    assert admin.get("/api/v1/telephony/custom-dialplan").json()["text"] == GOOD
    log = admin.get("/api/v1/audit", params={"action": "telephony.custom_dialplan_update"}).json()
    assert log["items"]


ENTRY = "[custom-night]\nexten => s,1,NoOp(night)\n[custom-lib]\nexten => 5,1,NoOp(lib)\n"


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]["id"]


def _route(org, did, **dest):
    return {"organization_id": org, "did": did, **dest}


def test_entry_contexts_need_an_s_extension():
    assert cd.entry_contexts(ENTRY) == ["custom-night"]


def test_custom_destination_on_a_route(admin):
    admin.put("/api/v1/telephony/custom-dialplan", json={"text": ENTRY})
    org = _org(admin)
    body = _route(org, "+13125550101", destination_type="custom")
    r = admin.post("/api/v1/routing/inbound", json=body)
    assert r.status_code == 422

    for bad in ("custom-lib", "custom-gone"):
        r = admin.post("/api/v1/routing/inbound", json={**body, "destination_custom_context": bad})
        assert r.status_code == 422, bad

    r = admin.post(
        "/api/v1/routing/inbound", json={**body, "destination_custom_context": "custom-night"}
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["destination"]["label"] == "Custom dialplan: custom-night"
    assert out["destination"]["missing"] is False

    # A context in use cannot be taken away; one nothing uses can.
    r = admin.put("/api/v1/telephony/custom-dialplan", json={"text": ""})
    assert r.status_code == 409
    assert out["did"] in r.text
    assert admin.delete(f"/api/v1/routing/inbound/{out['id']}").status_code == 204
    assert admin.put("/api/v1/telephony/custom-dialplan", json={"text": ""}).status_code == 200


def test_custom_destination_on_a_menu_key_is_generated(admin):
    from veyra.telephony.asterisk import generator

    lines = generator._goto({"type": "custom", "context": "custom-night"})
    assert lines[0] == " same => n,Goto(custom-night,s,1)"
    with pytest.raises(generator.GenerationError):
        generator._goto({"type": "custom", "context": "bad]\n#exec x"})


def test_org_admin_cannot_read_or_choose_custom_dialplan(admin, app):
    from conftest import login
    from test_api_mfa import ADMIN_PASSWORD, _client, _make_user

    admin.put("/api/v1/telephony/custom-dialplan", json={"text": ENTRY})
    org = _org(admin)
    _make_user(admin, "oa-custom@district.local", "org_admin")
    oa = login(_client(app), "oa-custom@district.local", ADMIN_PASSWORD)
    assert oa.get("/api/v1/telephony/custom-dialplan").status_code == 403
    assert oa.put("/api/v1/telephony/custom-dialplan", json={"text": ""}).status_code == 403

    body = _route(
        org,
        "+13125550102",
        destination_type="custom",
        destination_custom_context="custom-night",
    )
    r = oa.post("/api/v1/routing/inbound", json=body)
    assert r.status_code == 422, r.text
    assert "platform administrator" in r.text

    # Once a platform administrator has used it in the organization, the
    # organization's administrator can keep it when editing.
    r = admin.post("/api/v1/routing/inbound", json=body)
    assert r.status_code == 201, r.text
    route = r.json()["id"]
    r = oa.patch(f"/api/v1/routing/inbound/{route}", json={"description": "Night line"})
    assert r.status_code == 200, r.text
    assert r.json()["destination"]["custom_context"] == "custom-night"


def test_org_admin_cannot_switch_a_route_to_custom_by_patching(admin, app):
    from conftest import login
    from test_api_mfa import ADMIN_PASSWORD, _client, _make_user

    admin.put("/api/v1/telephony/custom-dialplan", json={"text": ENTRY})
    org = _org(admin)
    r = admin.post(
        "/api/v1/routing/inbound",
        json=_route(org, "+13125550103", destination_type="directory"),
    )
    assert r.status_code == 201, r.text
    _make_user(admin, "oa-patch@district.local", "org_admin")
    oa = login(_client(app), "oa-patch@district.local", ADMIN_PASSWORD)
    r = oa.patch(
        f"/api/v1/routing/inbound/{r.json()['id']}",
        json={"destination_type": "custom", "destination_custom_context": "custom-night"},
    )
    assert r.status_code == 422, r.text
