# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caller ID with several organizations (docs/MULTI_TENANCY_MSP.md §5): an
organization presents only its own numbers; outside calls fall back to its
main number, never to a shared route's or a trunk's."""

from conftest import org_user, two_organizations
from test_api_routing import OUTBOUND, _trunk

EXT = "/api/v1/extensions"
A_NUM, B_NUM, A_EXTRA = "5735550100", "5735550200", "5735550101"


def _numbers(org_id):
    return f"/api/v1/organizations/{org_id}/numbers"


def _setup(admin, app):
    a, b = two_organizations(admin)
    for org, num in ((a, A_NUM), (b, B_NUM)):
        assert admin.post(_numbers(org.id), json={"first": num}).status_code == 201
        assert (
            admin.patch(f"/api/v1/organizations/{org.id}", json={"main_number": num}).status_code
            == 200
        )
    admin.post(_numbers(a.id), json={"first": A_EXTRA})
    alice = org_user(admin, app, "admin@a.local", "org_admin", a.id)
    return a, b, alice


def test_extension_caller_ids_are_the_organizations_own(admin, app):
    a, _, alice = _setup(admin, app)
    ext = a.extensions["1001"]["id"]
    r = alice.patch(f"{EXT}/{ext}", json={"outbound_caller_id_number": B_NUM})
    assert r.status_code == 422 and r.json()["code"] == "caller_id_not_allowed"
    assert (
        alice.patch(f"{EXT}/{ext}", json={"outbound_caller_id_number": A_EXTRA}).status_code == 200
    )
    # The allow list (set by the platform) widens the outbound caller ID only.
    admin.patch(f"/api/v1/organizations/{a.id}", json={"caller_id_allow_list": ["5735559999"]})
    assert (
        alice.patch(f"{EXT}/{ext}", json={"outbound_caller_id_number": "5735559999"}).status_code
        == 200
    )
    r = alice.patch(f"{EXT}/{ext}", json={"emergency_caller_id_number": "5735559999"})
    assert r.status_code == 422
    r = alice.patch(f"{EXT}/{ext}", json={"emergency_caller_id_number": B_NUM})
    assert r.status_code == 422
    assert (
        alice.patch(f"{EXT}/{ext}", json={"emergency_caller_id_number": A_NUM}).status_code == 200
    )
    # On a new extension too.
    r = alice.post(
        EXT,
        json={
            "organization_id": a.id,
            "number": "1003",
            "display_name": "x",
            "outbound_caller_id_number": B_NUM,
        },
    )
    assert r.status_code == 422
    # A platform administrator may set any number.
    assert admin.patch(f"{EXT}/{ext}", json={"outbound_caller_id_number": B_NUM}).status_code == 200


def test_templates_cannot_carry_another_organizations_number(admin, app):
    a, _, alice = _setup(admin, app)
    r = alice.post(
        "/api/v1/extension-templates",
        json={
            "organization_id": a.id,
            "name": "Front",
            "settings": {"outbound_caller_id_number": B_NUM},
        },
    )
    assert r.status_code == 201, r.text
    r = alice.post(
        EXT,
        json={
            "organization_id": a.id,
            "number": "1004",
            "display_name": "x",
            "template_id": r.json()["id"],
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "caller_id_not_allowed"


def test_sites_routes_and_the_main_number(admin, app):
    a, _, _ = _setup(admin, app)
    r = admin.post(
        "/api/v1/sites",
        json={"organization_id": a.id, "name": "Main", "emergency_caller_id_number": B_NUM},
    )
    assert r.status_code == 422
    r = admin.post(
        "/api/v1/sites",
        json={"organization_id": a.id, "name": "Main", "emergency_caller_id_number": A_NUM},
    )
    assert r.status_code == 201, r.text
    trunk = _trunk(admin)
    out = {
        "name": "Local",
        "patterns": [{"prefix": "9", "match": "NXXNXXXXXX"}],
        "trunk_ids": [trunk["id"]],
    }
    r = admin.post(OUTBOUND, json={**out, "caller_id_number": A_NUM})
    assert r.status_code == 422  # a route for every organization
    r = admin.post(OUTBOUND, json={**out, "caller_id_number": B_NUM, "organization_id": a.id})
    assert r.status_code == 422
    r = admin.post(OUTBOUND, json={**out, "caller_id_number": A_NUM, "organization_id": a.id})
    assert r.status_code == 201, r.text
    e911 = {
        "name": "911",
        "is_emergency": True,
        "patterns": [{"match": "911"}],
        "trunk_ids": [trunk["id"]],
        "caller_id_number": "5735550000",
    }
    assert admin.post(OUTBOUND, json=e911).status_code == 201
    # The main number is one of the organization's numbers, and stays while it is.
    r = admin.patch(f"/api/v1/organizations/{a.id}", json={"main_number": B_NUM})
    assert r.status_code == 422
    row = next(n for n in admin.get(_numbers(a.id)).json() if n["first"] == A_NUM)
    r = admin.delete(f"{_numbers(a.id)}/{row['id']}")
    assert r.status_code == 409 and r.json()["code"] == "main_number"


def test_the_switch_lists_caller_ids_to_review(admin, app):
    from veyra.core import tenancy
    from veyra.core.db import session_scope

    a, _, _ = _setup(admin, app)
    admin.patch(f"{EXT}/{a.extensions['1001']['id']}", json={"outbound_caller_id_number": B_NUM})
    with session_scope() as db:
        checks = {c["name"]: c for c in tenancy.caller_id_checks(db)}
    assert checks["main_numbers"]["ok"]
    assert checks["caller_ids"]["warning"] and "extension 1001" in checks["caller_ids"]["detail"]


def test_single_organization_keeps_todays_rule(admin, app):
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    ext = admin.post(
        EXT, json={"organization_id": org, "number": "1001", "display_name": "x"}
    ).json()
    alice = org_user(admin, app, "admin@one.local", "org_admin", org)
    # routing.write may set any number while multi-tenancy is off (docs/CALL_FEATURES.md §3.5).
    assert (
        alice.patch(f"{EXT}/{ext['id']}", json={"outbound_caller_id_number": B_NUM}).status_code
        == 200
    )


# ----------------------------------------------------------------- generated


def test_outside_calls_present_the_organizations_main_number():
    from test_generator_routing import _route
    from test_generator_routing import _trunk as _trunk_snap
    from test_multi_tenancy import _base, _files, _org_b

    snap = _org_b(_base())
    snap["installation"]["multi_tenancy_enabled"] = True
    snap["organizations"][0]["main_number"] = A_NUM
    snap["organizations"][1]["main_number"] = B_NUM
    snap["trunks"] = [_trunk_snap(default_caller_id="5735551111")]
    snap["outbound_routes"] = [_route(caller_id_number="5735552222", caller_id_force=True)]
    files = _files(snap)
    ep, dp = files["pjsip.endpoints.conf"].content, files["extensions.conf"].content
    assert f"set_var=__VEYRA_ORG_MAIN={B_NUM}" in ep and f"set_var=__VEYRA_ORG_MAIN={A_NUM}" in ep
    route = dp.split("[veyra-out-local]")[1].split("\n[")[0]
    assert "Set(CALLERID(num)=${VEYRA_ORG_MAIN})" in route
    assert "5735551111" not in route and "5735552222" not in route
    assert "(nocid),Log(ERROR" in route and '"${CALLERID(num)}"=""]?nocid' in route
    # One organization: the trunk's and the route's numbers, as before.
    one = _base()
    one["trunks"] = snap["trunks"]
    one["outbound_routes"] = snap["outbound_routes"]
    single = _files(one)["extensions.conf"].content.split("[veyra-out-local]")[1]
    assert "Set(CALLERID(num)=5735552222)" in single and "VEYRA_ORG_MAIN" not in single


def test_migration_fills_the_main_number(admin, database_url):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    import veyra
    from veyra.core.db import session_scope
    from veyra.core.models import Organization

    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    admin.post(_numbers(org), json={"first": "5735550100", "last": "5735550199"})
    _trunk(admin, default_caller_id="+15735550142")
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(veyra.__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(cfg, "0095")
    command.upgrade(cfg, "head")
    with session_scope() as db:
        assert db.get(Organization, org).main_number == "5735550142"
