# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outside line access (issue #392): the API's PIN rules and references, and
the generated dialplan's PIN, lock-out, class and emergency refusal."""

import uuid

import pytest
from test_api_ivr import _org
from test_generator_callflow import _context, _files, _snapshot

from veyra.core.db import session_scope
from veyra.core.models import DisaLine
from veyra.telephony.asterisk import generator

URL = "/api/v1/disa"


def _class(admin, org):
    r = admin.post(
        "/api/v1/classes-of-service", json={"organization_id": org["id"], "name": "Remote staff"}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _body(org, cos, **over):
    return {
        "organization_id": org["id"],
        "name": "Staff line",
        "pin": "482916",
        "class_of_service_id": cos["id"],
        "caller_id_number": "+15551230000",
        **over,
    }


def test_disa_api_rules_and_references(admin):
    org = _org(admin)
    cos = _class(admin, org)
    for weak in ("1234", "111111", "123456", "987654", "12ab56", ""):
        assert admin.post(URL, json=_body(org, cos, pin=weak)).status_code == 422, weak
    assert admin.post(URL, json=_body(org, cos, caller_id_number="x")).status_code == 422
    missing = {**_body(org, cos), "class_of_service_id": "00000000-0000-0000-0000-000000000001"}
    assert admin.post(URL, json=missing).status_code == 422

    r = admin.post(URL, json=_body(org, cos))
    assert r.status_code == 201, r.text
    line = r.json()
    assert "pin" not in line and "pin_ciphertext" not in line
    assert line["class_of_service_name"] == "Remote staff"
    assert admin.post(URL, json=_body(org, cos)).status_code == 409

    # A route can point at it; the line can't be removed or disabled meanwhile.
    dest = {"type": "disa", "custom_context": line["slug"]}
    menu = admin.post(
        "/api/v1/ivr",
        json={"organization_id": org["id"], "name": "Remote", "timeout_destination": dest},
    )
    assert menu.status_code == 201, menu.text
    assert menu.json()["timeout_destination"]["label"] == "Outside line access: Staff line"
    assert menu.json()["timeout_destination"]["missing"] is False
    assert admin.get(URL).json()[0]["in_use_by"] == ["menu Remote"]
    assert admin.delete(f"{URL}/{line['id']}").status_code == 409
    assert admin.patch(f"{URL}/{line['id']}", json={"is_enabled": False}).status_code == 409
    bad = {"type": "disa", "custom_context": "no-such-line"}
    unknown = admin.post(
        "/api/v1/ivr",
        json={"organization_id": org["id"], "name": "Other", "timeout_destination": bad},
    )
    assert unknown.status_code == 422

    # The PIN changes through the key and reaches the snapshot decrypted.
    assert admin.patch(f"{URL}/{line['id']}", json={"pin": "111"}).status_code == 422
    assert admin.patch(f"{URL}/{line['id']}", json={"pin": "739201"}).status_code == 200
    with session_scope() as db:
        row = db.get(DisaLine, uuid.UUID(line["id"]))
        assert "739201" not in row.pin_ciphertext

    assert admin.delete(f"/api/v1/ivr/{menu.json()['id']}").status_code == 204
    assert admin.delete(f"{URL}/{line['id']}").status_code == 204


LINE = {
    "slug": "staff-line",
    "name": "Staff line",
    "organization": "example",
    "pin": "482916",
    "class_of_service": "remote-staff",
    "caller_id_number": "+15551230000",
}


def test_generated_disa():
    route = {
        "slug": "nine11",
        "name": "911",
        "organization": "example",
        "is_emergency": True,
        "trunks": [],
        "patterns": [{"prefix": "", "match": "911", "prepend": ""}],
    }
    dp = _files(_snapshot(disa_lines=[LINE], outbound_routes=[route]))["extensions.conf"]
    ctx = _context(dp, "veyra-disa-staff-line")
    assert 'GotoIf($["${VEYRA_PIN}"="482916"]?ok)' in ctx
    # The wrong-PIN count survives hanging up, and locks the line.
    assert "Set(DB(veyra/disa/example/staff-line/fails)=$[0${DB(" in ctx
    assert "GotoIf($[${DB(veyra/disa/example/staff-line/fails)} >= 5]?lock)" in ctx
    assert "GotoIf($[${EPOCH} < 0${DB(veyra/disa/example/staff-line/locked)}]?locked)" in ctx
    # After the PIN: the class, the caller ID, and only the outbound routes.
    assert "Set(VEYRA_COS=remote-staff)" in ctx and "Set(VEYRA_OUT_CID=+15551230000)" in ctx
    assert "DIALPLAN_EXISTS(veyra-outbound,${VEYRA_NUM},1)" in ctx
    assert ctx.index("(ok)") < ctx.index("__VEYRA_HOPS=0")
    assert "veyra-internal" not in ctx and "veyra-features" not in ctx
    # An emergency route refuses this line; without any line it says nothing.
    out = _context(dp, "veyra-out-nine11")
    assert 'ExecIf($["${VEYRA_DISA}"="1"]?Hangup())' in out
    plain = _files(_snapshot(outbound_routes=[route]))["extensions.conf"]
    assert "VEYRA_DISA" not in plain

    with pytest.raises(generator.GenerationError, match="PIN"):
        _files(_snapshot(disa_lines=[{**LINE, "pin": ""}]))
    with pytest.raises(generator.GenerationError, match="caller ID"):
        _files(_snapshot(disa_lines=[{**LINE, "caller_id_number": "x;y"}]))
    # A destination reaches it.
    assert generator._goto({"type": "disa", "disa": "staff-line"})[0].endswith(
        "Goto(veyra-disa-staff-line,s,1)"
    )
