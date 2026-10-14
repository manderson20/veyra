# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 9c API: zone numbers and policy, pages, send, log, and the
paging dialplan plus the sender's zone table (docs/PAGING_RECORDINGS.md §2)."""

from fake_adapter import FakeAdapter
from test_api_ivr import _upload

from veyra.configmgmt import service
from veyra.core.db import session_scope
from veyra.core.security.crypto import load_installation_key

ZONES = "/api/v1/paging-zones"
PAGES = "/api/v1/pages"
EXT = "/api/v1/extensions"


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _ext(admin, org_id, number, name="Front Office"):
    r = admin.post(EXT, json={"organization_id": org_id, "number": number, "display_name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _zone(admin, org_id, name, group, **over):
    r = admin.post(
        ZONES,
        json={
            "organization_id": org_id,
            "name": name,
            "multicast_address": "239.1.2.10",
            "multicast_port": 5004,
            "poly_group": group,
            **over,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _fake(app, tmp_path):
    adapter = FakeAdapter(prompts_dir=app.state.settings.prompts_dir)
    app.state.telephony = adapter
    cfg = tmp_path / "asterisk-veyra"
    cfg.mkdir(exist_ok=True)
    app.state.settings.asterisk_config_dir = cfg
    return adapter, service.Deployer(adapter, cfg, load_installation_key(app.state.settings)), cfg


def test_zone_numbers_share_the_number_space_and_members_policy(admin):
    org = _org(admin)
    ext = _ext(admin, org["id"], "1001")
    zone = _zone(
        admin, org["id"], "Building A", 3, number="2500", allowed="members", members=[ext["id"]]
    )
    assert zone["number"] == "2500" and zone["allowed"] == "members"
    assert zone["members"][0]["number"] == "1001" and zone["max_seconds"] == 120
    r = admin.post(EXT, json={"organization_id": org["id"], "number": "2500", "display_name": "x"})
    assert r.status_code == 409 and r.json()["code"] == "number_in_use"
    r = admin.post(PAGES, json={"organization_id": org["id"], "name": "All call", "number": "2500"})
    assert r.status_code == 409
    assert admin.get(f"{EXT}/next-number", params={"after": "2499"}).json()["number"] == "2501"
    r = admin.patch(f"{ZONES}/{zone['id']}", json={"allowed": "members", "members": []})
    assert r.status_code == 200 and "has none" in r.json()["problems"][0]
    assert admin.get("/api/v1/telephony/engine").json()["pending_since"] is not None


def test_pages_crud_send_and_log(admin, app, tmp_path):
    org = _org(admin)
    a = _zone(admin, org["id"], "Building A", 3, number="2500")
    b = _zone(admin, org["id"], "Building B", 4)
    bell = _upload(admin, org["id"], "First period", kind="bell")
    r = admin.post(
        PAGES,
        json={
            "organization_id": org["id"],
            "name": "All call",
            "number": "2600",
            "zones": [a["id"], b["id"]],
            "pre_tone": False,
            "priority": "priority",
        },
    )
    assert r.status_code == 201, r.text
    live = r.json()
    assert live["slug"] == "all-call" and [z["slug"] for z in live["zones"]] == [
        "building-a",
        "building-b",
    ]
    assert live["audio"] is None and live["problems"] == []
    r = admin.post(PAGES, json={"organization_id": org["id"], "name": "Empty"})
    assert r.status_code == 201 and "No zones" in r.json()["problems"][0]
    r = admin.post(
        PAGES,
        json={
            "organization_id": org["id"],
            "name": "Bell",
            "zones": [a["id"]],
            "audio_id": bell["id"],
            "repeat": 2,
        },
    )
    assert r.status_code == 201, r.text
    recorded = r.json()
    assert recorded["audio"]["name"] == "First period" and recorded["number"] is None
    # A live page cannot be sent from the API; a recorded one originates the play leg.
    adapter, deployer, cfg = _fake(app, tmp_path)
    r = admin.post(f"{PAGES}/{live['id']}/send", json={})
    assert r.status_code == 200 and r.json()["started"] is False
    r = admin.post(f"{PAGES}/{recorded['id']}/send", json={})
    assert r.status_code == 200, r.text
    assert r.json()["started"] is True and r.json()["channel_id"]
    assert adapter.originated[-1][0] == "play-bell@veyra-page-play"
    log = admin.get(f"{PAGES}/log").json()
    assert (
        log["total"] == 2
        and log["items"][0]["outcome"] == "started"
        and log["items"][0]["trigger"] == "ui"
    )
    assert admin.get(f"{PAGES}/{recorded['id']}").json()["last_sent_at"] is not None
    # Dialplan and the sender's zone table.
    with session_scope() as db:
        gen = service.create_revision(
            db, adapter, created_by="t", key=load_installation_key(app.state.settings)
        )
        service.request_deploy(db, gen.revision)
    with session_scope() as db:
        rev = deployer.run_once(db)
        assert rev is not None and rev.state.value == "deployed"
    files = {p.name: p.read_text() for p in cfg.iterdir() if p.is_file()}
    dp = files["extensions.conf"]
    assert "include => veyra-paging" in dp
    assert "exten => 2500,1,NoOp(Veyra page zone building-a" in dp
    assert "Page(MulticastRTP/basic/127.0.0.1:40000,i,120)" in dp
    assert "exten => 2600,1,NoOp(Veyra page all-call" in dp
    assert "Page(MulticastRTP/basic/127.0.0.1:40000&MulticastRTP/basic/127.0.0.1:40001,i,120)" in dp
    assert "exten => bell,1,NoOp(Veyra recorded page bell)" in dp
    assert "exten => play-bell,1,NoOp(Veyra plays first-period into page bell)" in dp
    assert dp.count("first-period)") >= 2  # repeat=2
    import json

    table = json.loads(files["paging.json"])
    assert [z["slug"] for z in table["zones"]] == ["building-a", "building-b"]
    assert table["zones"][0]["port"] == 40000 and table["zones"][1]["port"] == 40001
    assert table["zones"][0]["poly_group"] == 3 and table["defaults"]["delay_ms"] == 200
    # Deleting a zone in use by a page is allowed (the link goes away) and the page reports it.
    assert admin.delete(f"{ZONES}/{b['id']}").status_code == 204
    assert [z["slug"] for z in admin.get(f"{PAGES}/{live['id']}").json()["zones"]] == ["building-a"]
    assert admin.delete(f"{PAGES}/{live['id']}").status_code == 204
