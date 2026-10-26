# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ring group hunting (issue #166): circular, round robin and longest idle
ring one member at a time in a moving order kept in AstDB; members may have
their own ring time."""

import pytest
from test_api_groups import RG, _org
from test_api_groups import _ext as _api_ext
from test_generator_groups import _files, _group, _member, _snapshot

from veyra.telephony.asterisk import generator


def _ctx(dp: str, slug: str = "sales") -> str:
    return dp.split(f"[veyra-rg-{slug}]")[1].split("\n[")[0]


def test_circular_rings_one_at_a_time_from_after_the_last_answer():
    group = _group(
        strategy="circular",
        members=[_member("1001"), _member("1002", ring_seconds=30), _member("1003")],
    )
    dp = _files(_snapshot(ring_groups=[group]))["extensions.conf"].content
    ctx = _ctx(dp)
    assert "Set(VEYRA_EPS=example-1001:example-1002:example-1003)" in ctx
    assert "Set(VEYRA_RINGS=20:30:20)" in ctx
    assert "Set(VEYRA_S=${DB(veyra/rg/example/sales/next)})" in ctx
    assert "While($[${VEYRA_T} < 3])" in ctx
    assert "Set(VEYRA_I=$[(${VEYRA_S} + ${VEYRA_T}) % 3])" in ctx
    assert "Set(VEYRA_EP=${CUT(VEYRA_EPS,:,$[${VEYRA_I} + 1])})" in ctx
    assert (
        "Dial(PJSIP/${VEYRA_EP},${CUT(VEYRA_RINGS,:,$[${VEYRA_I} + 1])},${VEYRA_XFER}"
        "U(veyra-rg-answered^example^sales^next^$[(${VEYRA_I} + 1) % 3]))" in ctx
    )
    assert '"${DEVICE_STATE(PJSIP/${VEYRA_EP})}" : "(INUSE|BUSY|RINGINUSE)"]?hnext)' in ctx
    assert "n(hnext),EndWhile()" in ctx and "Goto(failover)" in ctx
    # The round robin start moves on every call, not on answers.
    assert "Set(DB(veyra/rg/example/sales/next)" not in ctx
    answered = dp.split("[veyra-rg-answered]")[1].split("\n[")[0]
    assert "Gosub(veyra-lastcid,s,1)" in answered
    assert "Set(DB(veyra/rg/${ARG1}/${ARG2}/${ARG3})=${ARG4})" in answered


def test_round_robin_and_longest_idle():
    dp = _files(_snapshot(ring_groups=[_group(strategy="roundrobin", ring_busy_members=True)]))[
        "extensions.conf"
    ].content
    ctx = _ctx(dp)
    assert "Set(DB(veyra/rg/example/sales/next)=$[(${VEYRA_S} + 1) % 2])" in ctx
    assert "U(veyra-lastcid)" in ctx and "DEVICE_STATE" not in ctx
    dp = _files(_snapshot(ring_groups=[_group(strategy="longest_idle")]))["extensions.conf"].content
    ctx = _ctx(dp)
    assert "Set(VEYRA_LEFT=-0-1-)" in ctx
    assert (
        'Set(VEYRA_C=$[${REGEX("-1-" ${VEYRA_LEFT})} & '
        "0${DB(veyra/rg/example/sales/idle_example-1002)} < ${VEYRA_BT}])" in ctx
    )
    assert "Set(VEYRA_LEFT=${STRREPLACE(VEYRA_LEFT,-${VEYRA_I}-,-)})" in ctx
    assert "U(veyra-rg-answered^example^sales^idle_${VEYRA_EP}^${EPOCH})" in ctx
    with pytest.raises(generator.GenerationError, match="member ring time"):
        generator.generate(
            _snapshot(ring_groups=[_group(members=[_member("1001", ring_seconds=200)])])
        )


def test_api_keeps_member_ring_times(admin):
    org = _org(admin)
    a = _api_ext(admin, org["id"], "1001")
    b = _api_ext(admin, org["id"], "1002", "Back Office")
    r = admin.post(
        RG,
        json={
            "organization_id": org["id"],
            "name": "Front desk",
            "number": "2301",
            "strategy": "longest_idle",
            "members": [a["id"], b["id"]],
            "member_ring_seconds": {b["id"]: 40},
        },
    )
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["strategy"] == "longest_idle"
    assert [m["ring_seconds"] for m in g["members"]] == [None, 40]
    r = admin.patch(f"{RG}/{g['id']}", json={"member_ring_seconds": {a["id"]: 15}})
    assert r.status_code == 200, r.text
    assert [m["ring_seconds"] for m in r.json()["members"]] == [15, None]
    r = admin.patch(f"{RG}/{g['id']}", json={"member_ring_seconds": {a["id"]: 3}})
    assert r.status_code == 422


def test_sequential_uses_each_members_ring_time():
    group = _group(
        strategy="sequential", members=[_member("1001"), _member("1002", ring_seconds=45)]
    )
    ctx = _ctx(_files(_snapshot(ring_groups=[group]))["extensions.conf"].content)
    assert "Dial(PJSIP/example-1001,20," in ctx and "Dial(PJSIP/example-1002,45," in ctx
