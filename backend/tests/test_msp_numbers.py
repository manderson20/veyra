# SPDX-License-Identifier: AGPL-3.0-or-later
"""The number inventory and dedicated trunks (docs/MULTI_TENANCY_MSP.md §4,
C4), with two organizations that use the same numbers."""

from conftest import org_user, two_organizations
from test_api_routing import INBOUND, OUTBOUND, TRUNKS, _fake, _trunk

from veyra.core.db import session_scope
from veyra.core.models import InboundRoute, OrganizationNumber

DID = "5735550100"


def _numbers(org_id):
    return f"/api/v1/organizations/{org_id}/numbers"


def _route(org_id, ext, did=DID, **extra):
    return {"organization_id": org_id, "did": did, "destination_extension_id": ext["id"], **extra}


def _setup(admin, app):
    a, b = two_organizations(admin)
    alice = org_user(admin, app, "admin@a.local", "org_admin", a.id)
    bob = org_user(admin, app, "admin@b.local", "org_admin", b.id)
    return a, b, alice, bob


def test_an_organization_routes_only_its_own_numbers(admin, app):
    a, b, alice, bob = _setup(admin, app)
    r = admin.post(_numbers(a.id), json={"first": "+1 (573) 555-0100", "label": "Main"})
    assert r.status_code == 201, r.text
    assert r.json()["first"] == DID and r.json()["count"] == 1
    # Nobody else may hold it, in any form.
    r = admin.post(_numbers(b.id), json={"first": "15735550100"})
    assert r.status_code == 409 and r.json()["code"] == "number_assigned"

    assert alice.post(INBOUND, json=_route(a.id, a.extensions["1001"])).status_code == 201
    # Beta's administrator: not Beta's number, and not one that is unassigned.
    r = bob.post(INBOUND, json=_route(b.id, b.extensions["1001"]))
    assert r.status_code == 409 and r.json()["code"] in ("did_in_use_elsewhere", "number_not_owned")
    r = bob.post(INBOUND, json=_route(b.id, b.extensions["1001"], did="5735550200"))
    assert r.status_code == 422 and r.json()["code"] == "number_not_assigned"
    # Not even through a trunk restriction.
    trunk = _trunk(admin)
    r = admin.post(INBOUND, json=_route(b.id, b.extensions["1001"], trunk_id=trunk["id"]))
    assert r.status_code == 409
    # Reading: own numbers only.
    assert [n["first"] for n in alice.get(_numbers(a.id)).json()] == [DID]
    assert alice.get(_numbers(a.id)).json()[0]["routed"] == 1
    assert alice.get(_numbers(b.id)).status_code == 404
    assert alice.post(_numbers(a.id), json={"first": "5735550300"}).status_code == 403


def test_any_is_platform_only_unless_the_trunk_is_dedicated(admin, app):
    a, b, _, bob = _setup(admin, app)
    shared = _trunk(admin)
    own = _trunk(admin, name="Beta carrier", organization_id=b.id)
    assert own["organization_id"] == b.id
    body = _route(b.id, b.extensions["1001"], did="any", trunk_id=shared["id"])
    r = bob.post(INBOUND, json=body)
    assert r.status_code == 422 and r.json()["code"] == "any_needs_dedicated_trunk"
    assert bob.post(INBOUND, json={**body, "trunk_id": own["id"]}).status_code == 201
    # Alpha cannot use Beta's trunk at all.
    r = admin.post(INBOUND, json=_route(a.id, a.extensions["1001"], did="any", trunk_id=own["id"]))
    assert r.status_code == 422
    # A platform administrator may catch everything on a shared trunk.
    assert (
        admin.post(
            INBOUND,
            json={
                **body,
                "organization_id": a.id,
                "destination_extension_id": a.extensions["1001"]["id"],
            },
        ).status_code
        == 201
    )


def test_dedicated_trunks_and_outbound_routes(admin, app):
    a, b, _, _ = _setup(admin, app)
    trunk = _trunk(admin)
    admin.post(_numbers(a.id), json={"first": DID})
    assert (
        admin.post(
            INBOUND, json=_route(a.id, a.extensions["1001"], trunk_id=trunk["id"])
        ).status_code
        == 201
    )
    # Alpha's route uses the trunk: it cannot become Beta's.
    r = admin.patch(f"{TRUNKS}/{trunk['id']}", json={"organization_id": b.id})
    assert r.status_code == 409 and r.json()["code"] == "trunk_in_use"
    beta = _trunk(admin, name="Beta carrier", organization_id=b.id)
    out = {"name": "Long distance", "patterns": [{"prefix": "9", "match": "NXXNXXXXXX"}]}
    r = admin.post(OUTBOUND, json={**out, "trunk_ids": [beta["id"]]})
    assert r.status_code == 422  # a route for every organization
    r = admin.post(OUTBOUND, json={**out, "trunk_ids": [beta["id"]], "organization_id": a.id})
    assert r.status_code == 422  # another organization's route
    r = admin.post(OUTBOUND, json={**out, "trunk_ids": [beta["id"]], "organization_id": b.id})
    assert r.status_code == 201, r.text
    r = admin.patch(f"{OUTBOUND}/{r.json()['id']}", json={"organization_id": a.id})
    assert r.status_code == 422


def test_blocks_trunks_and_removal(admin, app):
    a, b, _, _ = _setup(admin, app)
    trunk = _trunk(admin)
    r = admin.post(
        _numbers(a.id), json={"first": "5735550100", "last": "5735550199", "trunk_id": trunk["id"]}
    )
    assert r.status_code == 201 and r.json()["count"] == 100
    # A block that overlaps.
    r = admin.post(_numbers(b.id), json={"first": "5735550150", "last": "5735550250"})
    assert r.status_code == 409
    r = admin.post(_numbers(b.id), json={"first": "5735550000", "last": "5735559999"})
    assert r.status_code == 409  # covers Alpha's block
    assert (
        admin.post(_numbers(b.id), json={"first": "5735550200", "last": "57355502"}).status_code
        == 422
    )
    # The block arrives on its trunk only.
    other = _trunk(admin, name="Carrier B")
    r = admin.post(
        INBOUND, json=_route(a.id, a.extensions["1001"], did="5735550142", trunk_id=other["id"])
    )
    assert r.status_code == 422
    assert (
        admin.post(INBOUND, json=_route(a.id, a.extensions["1001"], did="5735550142")).status_code
        == 201
    )
    block = admin.get(_numbers(a.id)).json()[0]
    r = admin.delete(f"{_numbers(a.id)}/{block['id']}")
    assert r.status_code == 409 and r.json()["code"] == "number_in_use"


def test_single_organization_assigns_numbers_by_routing(admin, app):
    """Multi-tenancy off: nothing changes for the user."""
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    ext = admin.post(
        "/api/v1/extensions", json={"organization_id": org, "number": "1001", "display_name": "x"}
    ).json()
    tech = org_user(admin, app, "admin@one.local", "org_admin", org)
    assert tech.post(INBOUND, json=_route(org, ext)).status_code == 201
    assert tech.post(INBOUND, json=_route(org, ext, did="any")).status_code == 201
    numbers = admin.get(_numbers(org)).json()
    assert [(n["first"], n["source"]) for n in numbers] == [(DID, "auto")]


def test_a_conflict_is_skipped_and_listed(admin, app, tmp_path):
    _, deployer, cfg = _fake(app, tmp_path)
    a, b, _, _ = _setup(admin, app)
    admin.post(_numbers(a.id), json={"first": DID})
    admin.post(INBOUND, json=_route(a.id, a.extensions["1001"]))
    # A route from before the inventory, for Alpha's number, in Beta.
    with session_scope() as db:
        trunk = _trunk(admin)
        db.add(
            InboundRoute(
                organization_id=b.id,
                did="+15735550100",
                did_canonical=DID,
                trunk_id=trunk["id"],
                destination_type="extension",
                destination_extension_id=b.extensions["1002"]["id"],
            )
        )
    conflicts = admin.get("/api/v1/numbers/conflicts").json()
    assert [(c["did"], c["owner_organization_id"]) for c in conflicts] == [("+15735550100", a.id)]
    r = admin.post("/api/v1/telephony/apply", json={})
    assert r.status_code in (200, 202), r.text
    with session_scope() as db:
        deployer.run_once(db)
    dp = (cfg / "extensions.conf").read_text()
    assert (
        "Goto(veyra-internal,1001,1)" in dp and "beta-1002" not in dp.split("[veyra-from-trunk")[1]
    )


def test_migration_fills_the_inventory(admin, database_url):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import select, text

    import veyra

    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    ext = admin.post(
        "/api/v1/extensions", json={"organization_id": org, "number": "1001", "display_name": "x"}
    ).json()
    admin.post(INBOUND, json=_route(org, ext, did="+15735550123"))
    admin.post(INBOUND, json=_route(org, ext, did="any"))
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(veyra.__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(cfg, "0094")
    with session_scope() as db:
        db.execute(
            text("UPDATE extensions SET emergency_caller_id_number = '573-555-0911' WHERE id = :i"),
            {"i": ext["id"]},
        )
    command.upgrade(cfg, "head")
    with session_scope() as db:
        rows = db.scalars(select(OrganizationNumber).order_by(OrganizationNumber.first)).all()
        assert [(r.first, r.source) for r in rows] == [
            ("5735550123", "migration"),
            ("5735550911", "migration"),
        ]
