# SPDX-License-Identifier: AGPL-3.0-or-later
"""Weighted trunk distribution on outbound routes and the trunk near-limit
alert (issue #392, from FreeSWITCH and the Grandstream UCM)."""

from fake_adapter import FakeAdapter
from test_api_routing import OUTBOUND, _trunk
from test_generator_routing import _files, _route, _section, _snapshot
from test_generator_routing import _trunk as _trunk_snap

from veyra.core.db import session_scope
from veyra.reporting.alerts import check_trunk_load
from veyra.telephony.adapter import ActiveCall


def _dial(**route):
    snap = _snapshot(
        trunks=[_trunk_snap("a"), _trunk_snap("b"), _trunk_snap("c")],
        outbound_routes=[_route(trunks=["a", "b", "c"], **route)],
    )
    return _section(_files(snap)["extensions.conf"].content, "veyra-out-local")


def test_weighted_route_picks_a_start_and_rings_round():
    d = _dial(trunk_weights=[5, 3, 2])
    assert " same => n,Set(VEYRA_PICK=${RAND(1,10)})" in d
    assert " same => n,GotoIf($[${VEYRA_PICK} <= 5]?t1)" in d
    assert " same => n,GotoIf($[${VEYRA_PICK} <= 8]?t2)" in d
    assert " same => n,Goto(t3)" in d
    assert " same => n(t1),Set(VEYRA_TRIED=$[0${VEYRA_TRIED} + 1])" in d
    assert " same => n,GotoIf($[${VEYRA_TRIED} > 3]?failed)" in d
    # The last trunk goes on to the first, not straight to failure.
    assert '"${DIALSTATUS}"="CONGESTION"]?t1)' in d


def test_failover_and_emergency_routes_are_unchanged():
    plain = _dial()
    assert "VEYRA_PICK" not in plain and "VEYRA_TRIED" not in plain
    assert '"${DIALSTATUS}"="CONGESTION"]?failed)' in plain
    # An emergency route never takes weights (the snapshot leaves them out).
    snap = _snapshot(
        trunks=[_trunk_snap("a"), _trunk_snap("b")],
        outbound_routes=[
            _route(
                "e911",
                is_emergency=True,
                patterns=[{"prefix": "", "match": "911", "prepend": ""}],
                trunks=["a", "b"],
            )
        ],
    )
    assert "VEYRA_PICK" not in _files(snap)["extensions.conf"].content


def test_api_weights_and_strategy(admin, app):
    a, b = _trunk(admin, "Carrier A"), _trunk(admin, "Carrier B")
    body = {
        "name": "Long distance",
        "patterns": [{"match": "1NXXNXXXXXX"}],
        "trunk_ids": [a["id"], b["id"]],
        "trunk_strategy": "weighted",
        "trunk_weights": [70, 30],
    }
    r = admin.post(OUTBOUND, json=body)
    assert r.status_code == 201, r.text
    route = r.json()
    assert route["trunk_strategy"] == "weighted"
    assert [t["weight"] for t in route["trunks"]] == [70, 30]
    url = f"{OUTBOUND}/{route['id']}"
    # Reordering keeps each trunk's weight.
    r = admin.patch(url, json={"trunk_ids": [b["id"], a["id"]]})
    assert r.status_code == 200 and [t["weight"] for t in r.json()["trunks"]] == [30, 70]
    for bad in ({"trunk_weights": [1]}, {"trunk_weights": [0, 5]}):
        assert admin.patch(url, json=bad).status_code == 422, bad
    # An emergency route always fails over.
    r = admin.patch(url, json={"is_emergency": True, "patterns": [{"match": "911"}]})
    assert r.status_code == 422, r.text


def test_trunk_near_its_limit(admin):
    t = _trunk(admin, "Carrier A", max_channels=4)
    _trunk(admin, "Carrier B")  # no limit: never reported
    adapter = FakeAdapter()
    adapter.calls = [
        ActiveCall(f"c{i}", "1001", "5735550100", "Up", 5, endpoint=f"trunk-{t['slug']}")
        for i in range(3)
    ]
    with session_scope() as db:
        found = check_trunk_load(db, adapter, 80)
        assert found == []  # 3 of 4 is 75 %
        adapter.calls.append(
            ActiveCall("c9", "1001", "5735550101", "Up", 5, endpoint=f"trunk-{t['slug']}")
        )
        found = check_trunk_load(db, adapter, 80)
    assert [(f.rule, f.subject) for f in found] == [("trunk_busy", t["slug"])]
    assert "4 of 4 channels" in found[0].message
