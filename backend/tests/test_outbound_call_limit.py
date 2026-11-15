# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outbound Call Limit (FreePBX, issue #392): each phone of a class of
service may place so many outside calls per hour, day, week or month;
emergency calls are never counted or refused."""

from test_api_ivr import _org
from test_features import _section, _snapshot
from test_generator_routing import _route, _trunk

from veyra.telephony.asterisk import generator


def _cls(**over):
    return {
        "slug": "classroom",
        "name": "Classroom",
        "organization": "example",
        "allowed_routes": ["local", "emergency"],
        "allowed_feature_codes": None,
        "allow_external_forwards": True,
        "allow_external_follow_me": True,
        "allow_intercom": True,
        "max_outbound_calls": None,
        **over,
    }


def _dialplan(cls):
    snap = _snapshot(
        trunks=[_trunk()],
        outbound_routes=[
            _route("local"),
            _route(
                "emergency",
                is_emergency=True,
                patterns=[{"prefix": "", "match": "911", "prepend": ""}],
            ),
        ],
    )
    snap["classes_of_service"] = [cls]
    snap["extensions"][0]["class_of_service"] = "classroom"
    return {f.path: f.content for f in generator.generate(snap)}["extensions.conf"]


def test_per_period_count_on_outside_routes_only():
    assert "VEYRA_OCLK" not in _dialplan(_cls())
    d = _dialplan(_cls(calls_per_period=20, call_period="week"))
    local = _section(d, "veyra-out-local")
    assert '"${VEYRA_COS}"!="classroom" | "${VEYRA_EXT}"=""]?ocl0)' in local
    assert "Set(VEYRA_OCLP=${STRFTIME(${EPOCH},,%G%V)})" in local
    assert "GotoIf($[0${VEYRA_OCLN} >= 20]?cosquota)" in local
    assert "Set(DB(${VEYRA_OCLK})=${VEYRA_OCLP}|$[0${VEYRA_OCLN} + 1])" in local
    assert "n(cosquota),NoOp(" in local
    emergency = _section(d, "veyra-out-emergency")
    assert "VEYRA_OCLK" not in emergency and "cosquota" not in emergency


def test_api_period_limit(admin):
    org = _org(admin)
    url = "/api/v1/classes-of-service"
    r = admin.post(
        url,
        json={
            "organization_id": org["id"],
            "name": "Students",
            "calls_per_period": 5,
            "call_period": "day",
        },
    )
    assert r.status_code == 201, r.text
    c = r.json()
    assert (c["calls_per_period"], c["call_period"]) == (5, "day")
    r = admin.patch(f"{url}/{c['id']}", json={"call_period": "month", "calls_per_period": 100})
    assert r.status_code == 200 and r.json()["calls_per_period"] == 100
    assert admin.patch(f"{url}/{c['id']}", json={"call_period": "year"}).status_code == 422
    r = admin.patch(f"{url}/{c['id']}", json={"no_period_limit": True})
    assert r.status_code == 200 and r.json()["calls_per_period"] is None
