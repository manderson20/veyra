# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 6 API: trunks, inbound and outbound routes, time conditions,
scoping, pending-change flag and the deployed configuration."""

from conftest import ADMIN_PASSWORD, login
from fake_adapter import FakeAdapter
from fastapi.testclient import TestClient

from veyra.configmgmt import service
from veyra.core.security.crypto import load_installation_key
from veyra.telephony.adapter import EndpointStatus

TRUNKS = "/api/v1/trunks"
INBOUND = "/api/v1/routing/inbound"
OUTBOUND = "/api/v1/routing/outbound"
TCS = "/api/v1/routing/time-conditions"


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _ext(admin, org_id, number, name="Front Office"):
    r = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org_id, "number": number, "display_name": name},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _trunk(admin, name="Carrier A", **extra):
    body = {
        "name": name,
        "auth_mode": "registration",
        "host": "sip.carrier.example",
        "username": "acct1",
        "password": "Secr3t-pass",
        "default_caller_id": "5735550100",
        **extra,
    }
    r = admin.post(TRUNKS, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _fake(app, tmp_path):
    adapter = FakeAdapter()
    app.state.telephony = adapter
    cfg = tmp_path / "asterisk-veyra"
    cfg.mkdir(exist_ok=True)
    app.state.settings.asterisk_config_dir = cfg
    return adapter, service.Deployer(adapter, cfg, load_installation_key(app.state.settings)), cfg


def test_trunk_crud_status_and_audit(admin, app, tmp_path):
    adapter, _, _ = _fake(app, tmp_path)
    t = _trunk(admin)
    assert t["slug"] == "carrier-a" and t["has_password"] and "password" not in t
    assert t["auth_username"] is None and t["port"] == 5060 and t["transport"] == "udp"
    assert t["status"] == {"state": "unknown", "reachable": None}  # not deployed yet
    adapter.endpoints.append(EndpointStatus("trunk-carrier-a", True))
    assert admin.get(f"{TRUNKS}/{t['id']}").json()["status"]["state"] == "online"
    adapter.endpoints[-1] = EndpointStatus("trunk-carrier-a", False)
    listing = admin.get(TRUNKS, params={"q": "carrier"}).json()
    assert listing["total"] == 1 and listing["items"][0]["status"]["state"] == "offline"

    # name collisions and derived slugs
    assert admin.post(TRUNKS, json={**_body(), "name": "Carrier A"}).status_code == 409
    t2 = admin.post(TRUNKS, json={**_body(), "name": "Carrier-A"}).json()
    assert t2["slug"] == "carrier-a-2"

    r = admin.patch(
        f"{TRUNKS}/{t['id']}",
        json={
            "host": "sip2.carrier.example",
            "max_channels": 8,
            "match_addresses": ["203.0.113.0/24", "203.0.113.0/24"],
        },
    )
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["host"] == "sip2.carrier.example" and got["max_channels"] == 8
    assert got["match_addresses"] == ["203.0.113.0/24"]
    # a registration trunk cannot lose its password or user name
    assert admin.patch(f"{TRUNKS}/{t['id']}", json={"password": None}).status_code == 422
    assert admin.patch(f"{TRUNKS}/{t['id']}", json={"username": None}).status_code == 422
    # switching to IP mode may drop both
    r = admin.patch(
        f"{TRUNKS}/{t['id']}", json={"auth_mode": "ip", "password": None, "username": None}
    )
    assert r.status_code == 200, r.text
    assert r.json()["has_password"] is False and r.json()["auth_mode"] == "ip"

    engine = admin.get("/api/v1/telephony/engine").json()
    assert engine["changes_pending"] is True
    actions = [e["action"] for e in admin.get("/api/v1/audit").json()["items"]]
    assert "trunk.create" in actions and "trunk.update" in actions
    detail = next(
        e for e in admin.get("/api/v1/audit").json()["items"] if e["action"] == "trunk.update"
    )
    assert "Secr3t" not in str(detail)

    assert admin.delete(f"{TRUNKS}/{t['id']}").status_code == 204
    assert admin.get(f"{TRUNKS}/{t['id']}").status_code == 404


def _body(**over):
    return {
        "name": "X",
        "auth_mode": "ip",
        "host": "198.51.100.7",
        "match_addresses": ["198.51.100.7"],
        **over,
    }


def test_trunk_validation(admin):
    bad = [
        ({"password": None}, "password"),
        ({"username": None}, "user name"),
        ({"host": "bad host"}, "host"),
        ({"codecs": ["ulaw", "mp3"]}, "codec"),
        ({"match_addresses": ["not an address!"]}, "match"),
        ({"outbound_proxy": "proxy;lr"}, "proxy"),
        ({"default_caller_id": "abc"}, "digits"),
        ({"transport": "sctp"}, "transport"),
        ({"password": "has space"}, "password"),
        ({"name": "!!!"}, "name"),
    ]
    for over, _ in bad:
        body = {
            "name": "Carrier",
            "auth_mode": "registration",
            "host": "sip.carrier.example",
            "username": "acct1",
            "password": "pw-ok",
            **over,
        }
        r = admin.post(TRUNKS, json=body)
        assert r.status_code == 422, (over, r.text)
    assert admin.get(TRUNKS).json()["total"] == 0


def test_time_conditions_crud_open_now_and_in_use(admin):
    org = _org(admin)
    r = admin.post(
        TCS,
        json={
            "organization_id": org["id"],
            "name": "Office hours",
            "timezone": "America/Chicago",
            "ranges": [
                {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "07:30", "end": "16:00"}
            ],
            "holidays": ["12-25", "01-01", "12-25"],
        },
    )
    assert r.status_code == 201, r.text
    tc = r.json()
    assert tc["holidays"] == ["01-01", "12-25"] and tc["in_use_by"] == 0
    assert isinstance(tc["open_now"], bool) and tc["organization_name"] == org["name"]
    # default time zone comes from the organization
    r = admin.post(
        TCS,
        json={
            "organization_id": org["id"],
            "name": "Always",
            "ranges": [{"days": ["sun"], "start": "00:00", "end": "23:59"}],
        },
    )
    assert r.status_code == 201 and r.json()["timezone"] == org["timezone"]
    # validation
    for ranges in (
        [{"days": ["funday"], "start": "08:00", "end": "09:00"}],
        [{"days": ["mon"], "start": "10:00", "end": "09:00"}],
        [{"days": ["mon"], "start": "8am", "end": "09:00"}],
    ):
        r = admin.post(TCS, json={"organization_id": org["id"], "name": "Bad", "ranges": ranges})
        assert r.status_code == 422, r.text
    r = admin.post(
        TCS,
        json={
            "organization_id": org["id"],
            "name": "Bad",
            "timezone": "Mars/Base",
            "ranges": [{"days": ["mon"], "start": "08:00", "end": "09:00"}],
        },
    )
    assert r.status_code == 422
    assert (
        admin.post(
            TCS,
            json={
                "organization_id": org["id"],
                "name": "Office hours",
                "ranges": [{"days": ["mon"], "start": "08:00", "end": "09:00"}],
            },
        ).status_code
        == 409
    )

    r = admin.patch(
        f"{TCS}/{tc['id']}",
        json={"ranges": [{"days": ["sat"], "start": "09:00", "end": "12:00"}], "holidays": []},
    )
    assert (
        r.status_code == 200
        and r.json()["ranges"][0]["days"] == ["sat"]
        and r.json()["holidays"] == []
    )
    assert admin.get(TCS, params={"q": "office"}).json()["total"] == 1

    ext = _ext(admin, org["id"], "1001")
    route = admin.post(
        INBOUND,
        json={
            "organization_id": org["id"],
            "did": "5735550100",
            "destination_extension_id": ext["id"],
            "time_condition_id": tc["id"],
            "after_hours_extension_id": ext["id"],
        },
    )
    assert route.status_code == 201, route.text
    assert admin.get(f"{TCS}/{tc['id']}").json()["in_use_by"] == 1
    r = admin.delete(f"{TCS}/{tc['id']}")
    assert r.status_code == 409 and r.json()["code"] == "time_condition_in_use"
    admin.delete(f"{INBOUND}/{route.json()['id']}")
    assert admin.delete(f"{TCS}/{tc['id']}").status_code == 204


def test_inbound_routes_crud_validation_and_did_uniqueness(admin):
    org = _org(admin)
    ext = _ext(admin, org["id"], "1001")
    other = _ext(admin, org["id"], "1002", "Hallway")
    trunk = _trunk(admin)
    r = admin.post(
        INBOUND,
        json={
            "organization_id": org["id"],
            "did": "(573) 555-0100",
            "destination_extension_id": ext["id"],
            "caller_id_prefix": "Main: ",
            "description": "Main number",
        },
    )
    assert r.status_code == 201, r.text
    route = r.json()
    assert route["did"] == "5735550100" and route["did_canonical"] == "5735550100"
    assert route["aliases"] == ["15735550100", "+15735550100"]
    assert route["destination_number"] == "1001" and route["destination_missing"] is False
    assert route["trunk_id"] is None and route["organization_name"] == org["name"]

    # the same number in another form collides; restricted to a trunk it does not
    dup = admin.post(
        INBOUND,
        json={
            "organization_id": org["id"],
            "did": "+15735550100",
            "destination_extension_id": ext["id"],
        },
    )
    assert dup.status_code == 409 and dup.json()["code"] == "did_in_use"
    restricted = admin.post(
        INBOUND,
        json={
            "organization_id": org["id"],
            "did": "+15735550100",
            "trunk_id": trunk["id"],
            "destination_extension_id": other["id"],
        },
    )
    assert restricted.status_code == 201, restricted.text
    assert restricted.json()["trunk_name"] == "Carrier A"
    # catch-all routes, shared and per trunk
    assert (
        admin.post(
            INBOUND,
            json={
                "organization_id": org["id"],
                "did": "any",
                "destination_extension_id": ext["id"],
            },
        ).status_code
        == 201
    )
    assert (
        admin.post(
            INBOUND,
            json={
                "organization_id": org["id"],
                "did": "ANY",
                "destination_extension_id": ext["id"],
            },
        ).status_code
        == 409
    )

    # validation
    base = {
        "organization_id": org["id"],
        "did": "5735550199",
        "destination_extension_id": ext["id"],
    }
    bad = [
        {**base, "did": "12ab"},
        {**base, "destination_extension_id": None},
        {**base, "after_hours_extension_id": other["id"]},  # needs a time condition
        {**base, "caller_id_prefix": "Bad;prefix"},
        {**base, "trunk_id": "00000000-0000-0000-0000-000000000001"},
    ]
    for body in bad:
        r = admin.post(INBOUND, json=body)
        assert r.status_code == 422, (body, r.text)

    r = admin.patch(
        f"{INBOUND}/{route['id']}",
        json={"destination_extension_id": other["id"], "is_enabled": False, "did": "5735550101"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["destination_number"] == "1002" and r.json()["is_enabled"] is False
    assert r.json()["did_canonical"] == "5735550101"
    # the trunk is now referenced: it cannot be deleted
    r = admin.delete(f"{TRUNKS}/{trunk['id']}")
    assert r.status_code == 409 and r.json()["code"] == "trunk_in_use"
    # deleting the destination extension leaves the route flagged, not broken
    admin.delete(f"/api/v1/extensions/{other['id']}")
    got = admin.get(f"{INBOUND}/{route['id']}").json()
    assert got["destination_extension_id"] is None and got["destination_missing"] is True
    listing = admin.get(INBOUND, params={"q": "main"}).json()
    assert listing["total"] == 1
    assert admin.delete(f"{INBOUND}/{route['id']}").status_code == 204


def test_outbound_routes_order_warnings_and_trunk_links(admin):
    a = _trunk(admin, "Carrier A")
    b = _trunk(admin, "Backup", auth_mode="ip", username=None, password=None, host="198.51.100.7")
    assert admin.get(OUTBOUND).json() == {
        "items": [],
        "warnings": [
            "No enabled emergency route: 911 dialled from a phone will not reach a carrier "
            "through Veyra."
        ],
    }
    r = admin.post(
        OUTBOUND,
        json={
            "name": "Local calls",
            "patterns": [
                {"prefix": "9", "match": "nxxnxxxxxx", "prepend": "1"},
                {"prefix": "9", "match": "1NXXNXXXXXX"},
            ],
            "trunk_ids": [a["id"], b["id"]],
        },
    )
    assert r.status_code == 201, r.text
    local = r.json()
    assert local["slug"] == "local-calls" and local["position"] == 1
    assert local["patterns"][0]["match"] == "NXXNXXXXXX"
    assert local["examples"] == ["_9NXXNXXXXXX", "_91NXXNXXXXXX"]
    assert [t["name"] for t in local["trunks"]] == ["Carrier A", "Backup"]
    em = admin.post(
        OUTBOUND,
        json={
            "name": "Emergency",
            "is_emergency": True,
            "patterns": [{"match": "911"}, {"match": "933"}],
            "trunk_ids": [a["id"]],
            "caller_id_number": "5735550199",
        },
    ).json()
    assert em["position"] == 2 and em["examples"] == ["911", "933"]
    listing = admin.get(OUTBOUND).json()
    assert [r["name"] for r in listing["items"]] == ["Emergency", "Local calls"]  # emergency first
    assert listing["warnings"] == []

    # validation
    for body in (
        {"name": "Bad", "patterns": [{"match": "NXX;"}], "trunk_ids": [a["id"]]},
        {"name": "Bad", "patterns": [{"match": "NXX"}, {"match": "nxx"}], "trunk_ids": [a["id"]]},
        {"name": "Bad", "patterns": [{"match": "NXX"}], "trunk_ids": []},
        {"name": "Bad", "patterns": [{"match": "NXX"}], "trunk_ids": [a["id"], a["id"]]},
        {
            "name": "Bad",
            "patterns": [{"match": "NXX"}],
            "trunk_ids": ["00000000-0000-0000-0000-000000000001"],
        },
        {"name": "Bad", "patterns": [], "trunk_ids": [a["id"]]},
    ):
        r = admin.post(OUTBOUND, json=body)
        assert r.status_code == 422, (body, r.text)
    assert (
        admin.post(
            OUTBOUND,
            json={"name": "Local calls", "patterns": [{"match": "1"}], "trunk_ids": [a["id"]]},
        ).status_code
        == 409
    )

    # reorder: every id exactly once
    third = admin.post(
        OUTBOUND,
        json={
            "name": "Long distance",
            "patterns": [{"prefix": "9", "match": "011."}],
            "trunk_ids": [b["id"]],
        },
    ).json()
    r = admin.put(f"{OUTBOUND}/order", json={"ids": [third["id"], local["id"], em["id"]]})
    assert r.status_code == 200, r.text
    assert [x["name"] for x in r.json()["items"]] == ["Emergency", "Long distance", "Local calls"]
    assert admin.put(f"{OUTBOUND}/order", json={"ids": [local["id"]]}).status_code == 422

    # patch trunks and flags; disabling a trunk raises a warning
    r = admin.patch(
        f"{OUTBOUND}/{local['id']}",
        json={"trunk_ids": [b["id"]], "caller_id_number": "+15735550123"},
    )
    assert r.status_code == 200, r.text
    assert [t["slug"] for t in r.json()["trunks"]] == ["backup"]
    admin.patch(f"{TRUNKS}/{b['id']}", json={"is_enabled": False})
    warnings = admin.get(OUTBOUND).json()["warnings"]
    assert any("Local calls" in w for w in warnings) and any("Long distance" in w for w in warnings)
    r = admin.delete(f"{TRUNKS}/{b['id']}")
    assert r.status_code == 409 and "Local calls" in r.json()["detail"]
    assert admin.delete(f"{OUTBOUND}/{local['id']}").status_code == 204
    assert admin.delete(f"{OUTBOUND}/{third['id']}").status_code == 204
    assert admin.delete(f"{TRUNKS}/{b['id']}").status_code == 204
    assert admin.get(f"{OUTBOUND}/{local['id']}").status_code == 404


def test_org_admin_scope_for_routing_and_trunks(admin, app):
    a = _org(admin)["id"]
    b = admin.post("/api/v1/organizations", json={"name": "Beta", "slug": "beta"}).json()["id"]
    ext_a = _ext(admin, a, "1001", "Alpha phone")
    ext_b = _ext(admin, b, "2001", "Beta phone")
    trunk = _trunk(admin)
    route_a = admin.post(
        INBOUND,
        json={"organization_id": a, "did": "5735550100", "destination_extension_id": ext_a["id"]},
    ).json()
    tc_a = admin.post(
        TCS,
        json={
            "organization_id": a,
            "name": "Alpha hours",
            "ranges": [{"days": ["mon"], "start": "08:00", "end": "09:00"}],
        },
    ).json()
    r = admin.post(
        "/api/v1/users",
        json={
            "email": "orgadmin@beta.local",
            "display_name": "Beta admin",
            "password": ADMIN_PASSWORD,
            "home_organization_id": b,
            "require_password_change": False,
        },
    )
    uid = r.json()["id"]
    admin.post(
        f"/api/v1/users/{uid}/roles",
        json={"role_key": "org_admin", "scope_type": "organization", "organization_id": b},
    )
    c = login(TestClient(app, base_url="http://veyra.test"), "orgadmin@beta.local", ADMIN_PASSWORD)

    assert c.get(INBOUND).json()["items"] == []
    assert c.get(f"{INBOUND}/{route_a['id']}").status_code == 404
    assert c.get(f"{TCS}/{tc_a['id']}").status_code == 404
    assert (
        c.post(
            INBOUND,
            json={
                "organization_id": a,
                "did": "5735550101",
                "destination_extension_id": ext_a["id"],
            },
        ).status_code
        == 403
    )
    # an extension from another organization is not a valid destination
    r = c.post(
        INBOUND,
        json={"organization_id": b, "did": "5735550102", "destination_extension_id": ext_a["id"]},
    )
    assert r.status_code == 422
    r = c.post(
        INBOUND,
        json={
            "organization_id": b,
            "did": "5735550102",
            "trunk_id": trunk["id"],
            "destination_extension_id": ext_b["id"],
        },
    )
    assert r.status_code == 201, r.text
    # trunks: read yes (org_admin), write no
    assert c.get(TRUNKS).json()["total"] == 1
    assert c.post(TRUNKS, json=_body()).status_code == 403
    assert c.patch(f"{TRUNKS}/{trunk['id']}", json={"port": 5080}).status_code == 403
    # outbound routes: read yes, write no
    assert c.get(OUTBOUND).status_code == 200
    assert (
        c.post(
            OUTBOUND, json={"name": "X", "patterns": [{"match": "911"}], "trunk_ids": [trunk["id"]]}
        ).status_code
        == 403
    )
    assert c.put(f"{OUTBOUND}/order", json={"ids": [trunk["id"]]}).status_code == 403


def test_routing_reaches_the_generated_configuration(admin, app, tmp_path):
    adapter, deployer, cfg = _fake(app, tmp_path)
    from veyra.core.db import session_scope

    org = _org(admin)
    ext = _ext(admin, org["id"], "1001")
    trunk = _trunk(admin, outbound_proxy="proxy.carrier.example:5080")
    tc = admin.post(
        TCS,
        json={
            "organization_id": org["id"],
            "name": "Hours",
            "timezone": "America/Chicago",
            "ranges": [{"days": ["mon", "tue"], "start": "08:00", "end": "17:00"}],
        },
    ).json()
    admin.post(
        INBOUND,
        json={
            "organization_id": org["id"],
            "did": "5735550100",
            "destination_extension_id": ext["id"],
            "time_condition_id": tc["id"],
            "after_hours_extension_id": ext["id"],
            "caller_id_prefix": "Main: ",
        },
    )
    admin.post(
        OUTBOUND,
        json={
            "name": "Local",
            "patterns": [{"prefix": "9", "match": "NXXNXXXXXX", "prepend": "1"}],
            "trunk_ids": [trunk["id"]],
        },
    )
    admin.post(
        OUTBOUND,
        json={
            "name": "Emergency",
            "is_emergency": True,
            "patterns": [{"match": "911"}],
            "trunk_ids": [trunk["id"]],
        },
    )
    r = admin.post("/api/v1/telephony/apply", json={})
    assert r.status_code in (200, 202), r.text
    with session_scope() as db:
        deployer.run_once(db)
    trunks = (cfg / "pjsip.trunks.conf").read_text()
    assert "[trunk-carrier-a]" in trunks and "password=Secr3t-pass" in trunks
    assert r"outbound_proxy=sip:proxy.carrier.example:5080\;lr" in trunks
    dialplan = (cfg / "extensions.conf").read_text()
    assert (
        "exten => 5735550100,1," in dialplan
        and "GotoIfTime(08:00-17:00,mon-tue,*,*,America/Chicago?open)" in dialplan
    )
    assert "[veyra-out-emergency]" in dialplan and "[veyra-out-local]" in dialplan
    assert "Dial(PJSIP/${VEYRA_DIAL}@trunk-carrier-a,60)" in dialplan
    assert "set_var=VEYRA_ORG=brookfield" in (cfg / "pjsip.endpoints.conf").read_text()
    assert "res_pjsip.so" in adapter.reloads and "pbx_config.so" in adapter.reloads
    engine = admin.get("/api/v1/telephony/engine").json()
    assert engine["changes_pending"] is False
    # the trunk password never appears in a revision's readable artifacts
    revs = admin.get("/api/v1/telephony/revisions").json()["items"]
    rev = admin.get(f"/api/v1/telephony/revisions/{revs[0]['id']}").json()
    assert "Secr3t-pass" not in str(rev)
