# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extension Routing (FreePBX, issue #392): an outbound route only for the
extensions it lists; never on an emergency route."""

from test_api_ivr import _ext, _org
from test_api_routing import OUTBOUND, _trunk
from test_features import _section, _snapshot
from test_generator_routing import _route
from test_generator_routing import _trunk as _trunk_snap

from veyra.telephony.asterisk import generator


def _dial(**route):
    snap = _snapshot(trunks=[_trunk_snap()], outbound_routes=[_route(**route)])
    return _section(
        {f.path: f.content for f in generator.generate(snap)}["extensions.conf"],
        "veyra-out-local",
    )


def test_only_listed_phones_use_the_route():
    assert "cosdenied" not in _dial()
    d = _dial(allowed_extensions=["example/1001", "example/1002"])
    assert '${REGEX("^(example/1001|example/1002)$" ${VEYRA_ORG}/${VEYRA_EXT})}]?cosdenied)' in d
    assert "n(cosdenied),NoOp(" in d
    assert " same => n,Goto(cosdenied)" in _dial(allowed_extensions=[])


def test_api_list(admin):
    org = _org(admin)
    a = _ext(admin, org["id"], "3301")
    trunk = _trunk(admin)
    body = {
        "name": "Long distance",
        "patterns": [{"match": "1NXXNXXXXXX"}],
        "trunk_ids": [trunk["id"]],
        "organization_id": org["id"],
        "allowed_extension_ids": [a["id"]],
    }
    r = admin.post(OUTBOUND, json=body)
    assert r.status_code == 201, r.text
    route = r.json()
    assert route["allowed_extension_ids"] == [a["id"]]
    url = f"{OUTBOUND}/{route['id']}"
    r = admin.patch(url, json={"allowed_extension_ids": None})
    assert r.status_code == 200 and r.json()["allowed_extension_ids"] is None
    r = admin.patch(url, json={"allowed_extension_ids": ["00000000-0000-0000-0000-000000000001"]})
    assert r.status_code == 422
    r = admin.post(
        OUTBOUND,
        json={
            "name": "911",
            "is_emergency": True,
            "patterns": [{"match": "911"}],
            "trunk_ids": [trunk["id"]],
            "allowed_extension_ids": [a["id"]],
        },
    )
    assert r.status_code == 422, r.text
