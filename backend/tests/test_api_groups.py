# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 8 API: ring groups, call queues, pickup groups, the shared
number space, group destinations in routes and menus, and deployment."""

from conftest import ADMIN_PASSWORD, login
from fake_adapter import FakeAdapter
from test_api_rbac import make_org, make_user

from veyra.configmgmt import service
from veyra.core.db import session_scope
from veyra.core.security.crypto import load_installation_key

RG = "/api/v1/ring-groups"
QUEUES = "/api/v1/queues"
PG = "/api/v1/pickup-groups"
EXT = "/api/v1/extensions"
INBOUND = "/api/v1/routing/inbound"
IVR = "/api/v1/ivr"


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _ext(admin, org_id, number, name="Front Office"):
    r = admin.post(EXT, json={"organization_id": org_id, "number": number, "display_name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _fake(app, tmp_path):
    adapter = FakeAdapter(prompts_dir=app.state.settings.prompts_dir)
    app.state.telephony = adapter
    cfg = tmp_path / "asterisk-veyra"
    cfg.mkdir(exist_ok=True)
    app.state.settings.asterisk_config_dir = cfg
    return adapter, service.Deployer(adapter, cfg, load_installation_key(app.state.settings)), cfg


def test_ring_group_crud_number_space_and_in_use(admin, app):
    org = _org(admin)
    a = _ext(admin, org["id"], "1001")
    b = _ext(admin, org["id"], "1002", "Library")
    admin.post("/api/v1/voicemail", json={"extension_id": b["id"], "pin": "1234"})
    r = admin.post(
        RG,
        json={
            "organization_id": org["id"],
            "name": "Front Desk",
            "number": "2300",
            "members": [b["id"], a["id"]],
            "caller_id_prefix": "Front:",
            "failover": {"type": "voicemail", "extension_id": b["id"]},
        },
    )
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["slug"] == "front-desk" and g["context"] == "veyra-rg-front-desk"
    assert [m["number"] for m in g["members"]] == ["1002", "1001"]
    assert g["members"][0]["position"] == 0 and g["strategy"] == "ringall"
    assert g["failover"]["label"].startswith("Voicemail of 1002") and g["problems"] == []
    assert g["in_use_by"] == 0
    # the number space is shared with extensions and queues
    r = admin.post(EXT, json={"organization_id": org["id"], "number": "2300", "display_name": "X"})
    assert r.status_code == 409 and r.json()["code"] == "number_in_use"
    assert "ring group" in r.json()["errors"][0]["message"]
    r = admin.post(RG, json={"organization_id": org["id"], "name": "Other", "number": "1001"})
    assert r.status_code == 409 and r.json()["code"] == "number_in_use"
    r = admin.post(RG, json={"organization_id": org["id"], "name": "Other", "number": "9000"})
    assert r.status_code == 422 and r.json()["code"] == "number_not_in_plan"
    assert admin.get(f"{EXT}/next-number", params={"after": "1002"}).json()["number"] == "1003"
    assert admin.get(f"{EXT}/next-number", params={"after": "2299"}).json()["number"] == "2301"
    # validation: duplicate member, foreign extension, self failover, bad prefix
    r = admin.post(
        RG,
        json={
            "organization_id": org["id"],
            "name": "Dup",
            "number": "2301",
            "members": [a["id"], a["id"]],
        },
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "members"
    r = admin.patch(
        f"{RG}/{g['id']}", json={"failover": {"type": "ring_group", "ring_group_id": g["id"]}}
    )
    assert r.status_code == 422 and "itself" in r.json()["errors"][0]["message"]
    r = admin.patch(f"{RG}/{g['id']}", json={"caller_id_prefix": "bad[prefix]"})
    assert r.status_code == 422
    # name conflict within the organization
    r = admin.post(RG, json={"organization_id": org["id"], "name": "Front Desk", "number": "2301"})
    assert r.status_code == 409 and r.json()["code"] == "name_in_use"
    # patch: reorder members, change strategy, sequential; the extension lists its groups
    r = admin.patch(
        f"{RG}/{g['id']}",
        json={
            "members": [a["id"]],
            "strategy": "sequential",
            "ring_seconds": 15,
            "is_enabled": True,
        },
    )
    assert r.status_code == 200, r.text
    assert [m["number"] for m in r.json()["members"]] == ["1001"] and r.json()[
        "strategy"
    ] == "sequential"
    ext = admin.get(f"{EXT}/{a['id']}").json()
    assert ext["ring_groups"] == [{"id": g["id"], "name": "Front Desk", "number": "2300"}]
    assert admin.get(f"{EXT}/{b['id']}").json()["ring_groups"] == []
    # a disabled member is flagged; an empty group too
    admin.patch(f"{EXT}/{a['id']}", json={"is_enabled": False})
    assert any("disabled" in p for p in admin.get(f"{RG}/{g['id']}").json()["problems"])
    admin.patch(f"{EXT}/{a['id']}", json={"is_enabled": True})
    # used by an inbound route: delete refused; the route labels it
    r = admin.post(
        INBOUND,
        json={
            "organization_id": org["id"],
            "did": "5735550100",
            "destination_type": "ring_group",
            "destination_ring_group_id": g["id"],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["destination"]["label"] == "Ring group: Front Desk (2300)"
    assert r.json()["destination_ring_group_id"] == g["id"]
    assert admin.get(f"{RG}/{g['id']}").json()["in_use_by"] == 1
    r = admin.delete(f"{RG}/{g['id']}")
    assert r.status_code == 409 and r.json()["code"] == "ring_group_in_use"
    assert "inbound route 5735550100" in r.json()["detail"]
    # a disabled group is not a valid destination
    admin.patch(f"{RG}/{g['id']}", json={"is_enabled": False})
    route = admin.get(f"{INBOUND}?organization_id={org['id']}").json()["items"][0]
    assert route["destination_missing"]
    r = admin.post(
        INBOUND,
        json={
            "organization_id": org["id"],
            "did": "5735550101",
            "destination_type": "ring_group",
            "destination_ring_group_id": g["id"],
        },
    )
    assert r.status_code == 422 and "disabled" in r.json()["errors"][0]["message"]
    admin.delete(f"{INBOUND}/{route['id']}")
    assert admin.delete(f"{RG}/{g['id']}").status_code == 204
    assert admin.get(f"{RG}/{g['id']}").status_code == 404
    assert admin.get(f"{RG}?q=front").json()["total"] == 0
    # the audit trail names the group and the Deploy flag is raised
    actions = [e["action"] for e in admin.get("/api/v1/audit?limit=50").json()["items"]]
    assert "ring_group.create" in actions and "ring_group.delete" in actions
    assert admin.get("/api/v1/telephony/engine").json()["pending_since"]


def test_queue_crud_prompts_and_in_use(admin, app):
    from test_api_ivr import _upload

    org = _org(admin)
    a = _ext(admin, org["id"], "1001")
    b = _ext(admin, org["id"], "1002", "Library")
    hold = _upload(admin, org["id"], "Please hold")
    r = admin.post(
        QUEUES,
        json={
            "organization_id": org["id"],
            "name": "Support",
            "number": "2400",
            "strategy": "rrmemory",
            "members": [{"extension_id": b["id"], "penalty": 2}, {"extension_id": a["id"]}],
            "periodic_prompt_id": hold["id"],
            "announce_position": True,
            "max_wait_seconds": 120,
        },
    )
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["queue_name"] == "veyra-support" and q["context"] == "veyra-queue-support"
    assert [(m["number"], m["penalty"]) for m in q["members"]] == [("1001", 0), ("1002", 2)]
    assert q["periodic_prompt_name"] == "Please hold" and q["failover"]["type"] == "hangup"
    # The queue plays it: it counts as used and cannot be deleted from under the queue.
    assert admin.get(f"/api/v1/prompts/{hold['id']}").json()["in_use_by"] == 1
    r = admin.delete(f"/api/v1/prompts/{hold['id']}")
    assert r.status_code == 409 and "call queues: Support" in r.json()["detail"]
    # validation
    r = admin.post(
        QUEUES,
        json={"organization_id": org["id"], "name": "Q2", "number": "2401", "max_wait_seconds": 10},
    )
    assert r.status_code == 422
    r = admin.post(QUEUES, json={"organization_id": org["id"], "name": "Q2", "number": "2400"})
    assert r.status_code == 409 and r.json()["code"] == "number_in_use"
    r = admin.patch(f"{QUEUES}/{q['id']}", json={"announcement_prompt_id": str(a["id"])})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "announcement_prompt_id"
    r = admin.patch(
        f"{QUEUES}/{q['id']}", json={"failover": {"type": "queue", "queue_id": q["id"]}}
    )
    assert r.status_code == 422
    # patch members and settings
    r = admin.patch(
        f"{QUEUES}/{q['id']}",
        json={
            "members": [{"extension_id": a["id"], "penalty": 1}],
            "music": "ring",
            "join_when_empty": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["members"] == [
        {
            "extension_id": a["id"],
            "number": "1001",
            "display_name": "Front Office",
            "is_enabled": True,
            "position": None,
            "penalty": 1,
            "dynamic": False,
            "logged_in": True,
            "paused": False,
            "state_by": None,
            "state_at": None,
        }
    ]
    assert r.json()["music"] == "ring"
    assert admin.get(f"{EXT}/{a['id']}").json()["queues"] == [
        {"id": q["id"], "name": "Support", "number": "2400"}
    ]
    # a ring group failing over to the queue keeps it alive; an IVR key too
    g = admin.post(
        RG,
        json={
            "organization_id": org["id"],
            "name": "Sales",
            "number": "2300",
            "members": [a["id"]],
            "failover": {"type": "queue", "queue_id": q["id"]},
        },
    ).json()
    assert g["failover"]["label"] == "Queue: Support (2400)"
    welcome = _upload(admin, org["id"], "Welcome")
    menu = admin.post(
        IVR,
        json={
            "organization_id": org["id"],
            "name": "Main",
            "prompt_id": welcome["id"],
            "entries": [{"digit": "1", "destination": {"type": "queue", "queue_id": q["id"]}}],
            "timeout_destination": {"type": "ring_group", "ring_group_id": g["id"]},
        },
    )
    assert menu.status_code == 201, menu.text
    assert menu.json()["entries"][0]["destination"]["queue_id"] == q["id"]
    assert menu.json()["timeout_destination"]["label"] == "Ring group: Sales (2300)"
    assert admin.get(f"{QUEUES}/{q['id']}").json()["in_use_by"] == 2
    r = admin.delete(f"{QUEUES}/{q['id']}")
    assert r.status_code == 409 and r.json()["code"] == "queue_in_use"
    assert sorted(e["message"] for e in r.json()["errors"]) == ["menu Main", "ring group Sales"]
    # deleting the prompt a queue announces with is refused? no: prompts are menu-only guarded
    # (queues point at prompts with SET NULL and are flagged on the next render)
    assert admin.delete(f"{IVR}/{menu.json()['id']}").status_code == 204
    assert admin.delete(f"{RG}/{g['id']}").status_code == 204
    assert admin.delete(f"{QUEUES}/{q['id']}").status_code == 204


def test_pickup_groups_and_extension_memberships(admin, app):
    org = _org(admin)
    a = _ext(admin, org["id"], "1001")
    b = _ext(admin, org["id"], "1002", "Library")
    r = admin.post(
        PG, json={"organization_id": org["id"], "name": "Front office", "members": [a["id"]]}
    )
    assert r.status_code == 201, r.text
    pg = r.json()
    assert pg["slug"] == "front-office" and pg["problems"] == [
        "A pickup group needs at least two members to be useful."
    ]
    r = admin.patch(
        f"{PG}/{pg['id']}", json={"members": [a["id"], b["id"]], "description": "Desk phones"}
    )
    assert r.status_code == 200 and [m["number"] for m in r.json()["members"]] == ["1001", "1002"]
    assert r.json()["problems"] == []
    assert admin.get(f"{EXT}/{b['id']}").json()["pickup_groups"] == [
        {"id": pg["id"], "name": "Front office", "number": None}
    ]
    r = admin.post(PG, json={"organization_id": org["id"], "name": "Front office"})
    assert r.status_code == 409 and r.json()["code"] == "name_in_use"
    r = admin.post(PG, json={"organization_id": org["id"], "name": "Front Office"})
    assert r.status_code == 201 and r.json()["slug"] == "front-office-2"
    assert admin.delete(f"{PG}/{r.json()['id']}").status_code == 204
    # deleting an extension removes it from the group
    assert admin.delete(f"{EXT}/{b['id']}").status_code == 204
    assert [m["number"] for m in admin.get(f"{PG}/{pg['id']}").json()["members"]] == ["1001"]
    assert admin.delete(f"{PG}/{pg['id']}").status_code == 204
    assert admin.get(PG).json()["total"] == 0


def test_groups_are_scoped_to_the_organization(admin, app):
    from fastapi.testclient import TestClient

    org = _org(admin)
    beta = make_org(admin, "beta")
    a = _ext(admin, org["id"], "1001")
    make_user(admin, "orgadmin@beta.local", beta, "org_admin")
    make_user(admin, "viewer@district.local", org["id"], "read_only")
    g = admin.post(
        RG,
        json={
            "organization_id": org["id"],
            "name": "Sales",
            "number": "2300",
            "members": [a["id"]],
        },
    ).json()
    c = login(TestClient(app, base_url="http://veyra.test"), "orgadmin@beta.local", ADMIN_PASSWORD)
    assert c.get(RG).json()["total"] == 0
    assert c.get(f"{RG}/{g['id']}").status_code == 404
    assert (
        c.post(RG, json={"organization_id": org["id"], "name": "X", "number": "2301"}).status_code
        == 403
    )
    # a member from another organization is refused
    r = c.post(
        RG, json={"organization_id": beta, "name": "X", "number": "2301", "members": [a["id"]]}
    )
    assert (
        r.status_code == 422
        and "not found in this organization" in r.json()["errors"][0]["message"]
    )
    r = c.post(
        RG,
        json={
            "organization_id": beta,
            "name": "X",
            "number": "2301",
            "failover": {"type": "ring_group", "ring_group_id": g["id"]},
        },
    )
    assert r.status_code == 422
    v = login(
        TestClient(app, base_url="http://veyra.test"), "viewer@district.local", ADMIN_PASSWORD
    )
    assert v.get(RG).json()["total"] == 1
    assert v.post(PG, json={"organization_id": org["id"], "name": "X"}).status_code == 403
    assert v.delete(f"{RG}/{g['id']}").status_code == 403


def test_deployment_writes_groups_queues_and_pickup(admin, app, tmp_path):
    adapter, deployer, cfg = _fake(app, tmp_path)
    org = _org(admin)
    a = _ext(admin, org["id"], "1001")
    b = _ext(admin, org["id"], "1002", "Library")
    admin.post(
        PG, json={"organization_id": org["id"], "name": "Front", "members": [a["id"], b["id"]]}
    )
    g = admin.post(
        RG,
        json={
            "organization_id": org["id"],
            "name": "Sales",
            "number": "2300",
            "members": [a["id"], b["id"]],
        },
    ).json()
    q = admin.post(
        QUEUES,
        json={
            "organization_id": org["id"],
            "name": "Support",
            "number": "2400",
            "members": [{"extension_id": a["id"], "penalty": 0}],
            "failover": {"type": "ring_group", "ring_group_id": g["id"]},
        },
    ).json()
    admin.post(
        INBOUND,
        json={
            "organization_id": org["id"],
            "did": "5735550100",
            "destination_type": "queue",
            "destination_queue_id": q["id"],
        },
    )
    with session_scope() as db:
        gen = service.create_revision(
            db, adapter, created_by="t", key=load_installation_key(app.state.settings)
        )
        service.request_deploy(db, gen.revision)
    with session_scope() as db:
        rev = deployer.run_once(db)
        assert rev is not None and rev.state.value == "deployed"
    dp = (cfg / "extensions.conf").read_text()
    ep = (cfg / "pjsip.endpoints.conf").read_text()
    qc = (cfg / "queues.conf").read_text()
    assert "named_pickup_group=front" in ep and ep.count("named_call_group=front") == 2
    assert "exten => 2300,1,NoOp(Veyra ring group Sales)" in dp
    assert "[veyra-rg-sales]" in dp and "[veyra-queue-support]" in dp
    assert "exten => 5735550100,1," in dp and "Goto(veyra-queue-support,s,1)" in dp
    assert "Goto(veyra-rg-sales,s,1)" in dp.split("[veyra-queue-support]")[1]
    assert "exten => **1001,1," in dp and "exten => *8,1," in dp
    assert "exten => 1002,hint,PJSIP/" in dp
    assert "[veyra-support]\n" in qc and "member => PJSIP/" in qc
    assert "app_queue.so" in adapter.reloads
    # disabling the queue takes it out of both files and flags the route
    admin.patch(f"{QUEUES}/{q['id']}", json={"is_enabled": False})
    with session_scope() as db:
        gen = service.create_revision(
            db, adapter, created_by="t", key=load_installation_key(app.state.settings)
        )
        assert set(gen.diff) == {"extensions.conf", "queues.conf"}
    route = admin.get(f"{INBOUND}?organization_id={org['id']}").json()["items"][0]
    assert route["destination_missing"]
