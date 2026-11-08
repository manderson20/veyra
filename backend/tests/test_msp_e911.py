# SPDX-License-Identifier: AGPL-3.0-or-later
"""911 with several organizations (docs/MULTI_TENANCY_MSP.md §6): each
organization's own emergency number, its own callback, and notifications
that name the right caller."""

import pytest
from conftest import org_user, two_organizations

from veyra.telephony.asterisk import generator

A_NUM, B_NUM = "5735550100", "5735550200"


def _numbers(org_id):
    return f"/api/v1/organizations/{org_id}/numbers"


def _setup(admin, app):
    a, b = two_organizations(admin)
    for org, num in ((a, A_NUM), (b, B_NUM)):
        assert admin.post(_numbers(org.id), json={"first": num}).status_code == 201
        r = admin.patch(
            f"/api/v1/organizations/{org.id}",
            json={"main_number": num, "emergency_caller_id_number": num},
        )
        assert r.status_code == 200, r.text
    return a, b


# ----------------------------------------------------------------- generated


def _two():
    from test_generator_routing import _route
    from test_generator_routing import _trunk as _trunk_snap
    from test_multi_tenancy import _base, _org_b

    snap = _org_b(_base())
    snap["installation"]["multi_tenancy_enabled"] = True
    snap["organizations"][0].update(main_number=A_NUM, emergency_caller_id_number=A_NUM)
    snap["organizations"][1].update(main_number=B_NUM, emergency_caller_id_number=B_NUM)
    snap["trunks"] = [_trunk_snap(default_caller_id="5735551111")]
    snap["outbound_routes"] = [
        _route("e911", is_emergency=True, patterns=[{"prefix": "", "match": "911", "prepend": ""}])
    ]
    snap["sites"] = [
        {
            "id": "s1",
            "slug": "main",
            "name": "Main",
            "organization": "beta",
            "emergency_caller_id_number": "5735550299",
            "callback_minutes": 30,
            "responder": None,
        }
    ]
    return snap


def test_911_presents_the_organizations_own_number_and_calls_back_inside_it():
    from test_multi_tenancy import _files

    files = _files(_two())
    ep, dp = files["pjsip.endpoints.conf"].content, files["extensions.conf"].content
    beta = ep.split("[beta-1002](veyra-endpoint)")[1].split("\n\n")[0]
    example = ep.split("[example-1002](veyra-endpoint)")[1].split("\n\n")[0]
    assert f"set_var=VEYRA_EMERGENCY_CID={B_NUM}" in beta
    assert f"set_var=VEYRA_EMERGENCY_CID={A_NUM}" in example
    route = dp.split("[veyra-out-e911]")[1].split("\n[")[0]
    assert "DB(veyra_ecb/${VEYRA_ORG}/${VEYRA_EMERGENCY_CID})" in route
    assert "without an emergency number of its own" in route
    assert "DB(veyra_ecb/beta/5735550299)" in dp


def test_one_elin_for_two_organizations_is_refused():
    from test_multi_tenancy import _files

    snap = _two()
    snap["sites"].append(
        {**snap["sites"][0], "id": "s2", "slug": "other", "organization": "example"}
    )
    with pytest.raises(generator.GenerationError, match="share the emergency number"):
        _files(snap)


def test_one_organization_keeps_todays_callback_key():
    from test_multi_tenancy import _base, _files

    snap = _base()
    snap["organizations"][0]["emergency_caller_id_number"] = A_NUM
    snap["sites"] = [{**_two()["sites"][0], "organization": "example"}]
    dp = _files(snap)["extensions.conf"].content
    assert "DB(veyra_ecb/5735550299)" in dp and "veyra_ecb/example" not in dp
    ep = _files(snap)["pjsip.endpoints.conf"].content
    assert f"VEYRA_EMERGENCY_CID={A_NUM}" not in ep  # the site or phone decides, as before


# ----------------------------------------------------------------- API


def test_the_911_notification_names_the_right_caller(admin, app):
    from veyra.core.db import session_scope
    from veyra.emergency import service

    _a, b = _setup(admin, app)
    with session_scope() as db:
        call = service.record_call(
            db, {"extension": "1001", "number": "911", "channel": "PJSIP/beta-1001-0000002a"}
        )
        assert str(call.extension_id) == b.extensions["1001"]["id"]
        assert str(call.organization_id) == b.id
        # Without a channel or a site, a number alone names nobody.
        call = service.record_call(db, {"extension": "1001", "number": "911"})
        assert call.extension_id is None


def test_the_emergency_number_belongs_to_the_organization(admin, app):
    a, _b = _setup(admin, app)
    r = admin.patch(f"/api/v1/organizations/{a.id}", json={"emergency_caller_id_number": B_NUM})
    assert r.status_code == 422
    r = admin.patch(f"/api/v1/organizations/{a.id}", json={"emergency_caller_id_number": None})
    assert r.status_code == 422  # required while several organizations share the server
    admin.post(_numbers(a.id), json={"first": "5735550111"})
    r = admin.patch(
        f"/api/v1/organizations/{a.id}", json={"emergency_caller_id_number": "5735550111"}
    )
    assert r.status_code == 200 and r.json()["emergency_caller_id_number"] == "5735550111"
    row = next(n for n in admin.get(_numbers(a.id)).json() if n["first"] == "5735550111")
    r = admin.delete(f"{_numbers(a.id)}/{row['id']}")
    assert r.status_code == 409 and r.json()["code"] == "emergency_caller_id_number"


def test_readiness_per_organization(admin, app):
    a, _b = _setup(admin, app)
    r = admin.post("/api/v1/sites", json={"organization_id": a.id, "name": "Main"})
    assert r.status_code == 201, r.text
    site = r.json()["id"]
    detail = admin.get(f"/api/v1/emergency/sites/{site}").json()
    checks = {c["key"]: c for c in detail["readiness"]["checks"]}
    assert checks["elin"]["ok"] and A_NUM in checks["elin"]["detail"]
    assert not checks["own_elin"]["ok"] and checks["own_elin"]["advisory"]
    overview = admin.get("/api/v1/emergency/sites").json()["organizations"]
    rows = {o["id"]: o for o in overview}
    assert rows[a.id]["emergency_number"] == A_NUM and rows[a.id]["phones"]["organization"] == 2
    alice = org_user(admin, app, "admin@a.local", "org_admin", a.id)
    mine = alice.get("/api/v1/emergency/sites").json()["organizations"]
    assert [o["id"] for o in mine] == [a.id]


def test_migration_fills_the_emergency_number(admin, database_url):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    import veyra
    from veyra.core.db import session_scope
    from veyra.core.models import Organization

    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    admin.post(_numbers(org), json={"first": "5735550100", "last": "5735550199"})
    admin.patch(f"/api/v1/organizations/{org}", json={"main_number": "5735550100"})
    admin.post(
        "/api/v1/sites",
        json={"organization_id": org, "name": "Main", "emergency_caller_id_number": "5735550150"},
    )
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(veyra.__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(cfg, "0096")
    command.upgrade(cfg, "head")
    with session_scope() as db:
        assert db.get(Organization, org).emergency_caller_id_number == "5735550150"
