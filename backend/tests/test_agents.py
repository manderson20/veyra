# SPDX-License-Identifier: AGPL-3.0-or-later
"""Queue dynamic agents and the break-out menu (docs/CALL_FEATURES.md §4.9,
§4.10): the queue API, the live state endpoint, phone events, the worker's
sync and the generated configuration."""

from fake_adapter import FakeAdapter
from test_api_ivr import _ext, _org
from test_generator_callflow import _context, _files, _snapshot

from veyra.core.db import session_scope
from veyra.telephony import agents

QUEUES = "/api/v1/queues"
IVR = "/api/v1/ivr"


def _fake(app):
    adapter = FakeAdapter(prompts_dir=app.state.settings.prompts_dir)
    app.state.telephony = adapter
    return adapter


def _queue(admin, org, members, **extra):
    r = admin.post(
        QUEUES,
        json={
            "organization_id": org["id"],
            "name": extra.pop("name", "Support"),
            "number": extra.pop("number", "2400"),
            "members": members,
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_dynamic_agents_state_api_events_and_sync(admin, app):
    adapter = _fake(app)
    org = _org(admin)
    a = _ext(admin, org["id"], "6001", "Front")
    b = _ext(admin, org["id"], "6002", "Back")
    q = _queue(
        admin,
        org,
        [
            {"extension_id": a["id"], "penalty": 0, "dynamic": True},
            {"extension_id": b["id"], "penalty": 1},
        ],
    )
    by_ext = {m["extension_id"]: m for m in q["members"]}
    assert by_ext[a["id"]]["dynamic"] and not by_ext[a["id"]]["logged_in"]
    assert not by_ext[b["id"]]["dynamic"] and by_ext[b["id"]]["logged_in"]  # static: always in
    # A static agent has no state to change; a dynamic one logs in live.
    r = admin.post(f"{QUEUES}/{q['id']}/agents/{b['id']}/state", json={"logged_in": True})
    assert r.status_code == 409 and r.json()["code"] == "agent_not_dynamic"
    r = admin.post(f"{QUEUES}/{q['id']}/agents/{a['id']}/state", json={"logged_in": True})
    assert r.status_code == 200, r.text
    m = {x["extension_id"]: x for x in r.json()["members"]}[a["id"]]
    assert m["logged_in"] and not m["paused"] and m["state_by"]
    queue_name = f"veyra-{q['slug']}"
    assert adapter.queue_calls[-1] == (queue_name, f"PJSIP/{a['endpoint_name']}", True, False)
    assert adapter.switch_states[("agent", org["slug"], "6001")] == "1"
    # Pause, then log out (which also clears the pause).
    r = admin.post(f"{QUEUES}/{q['id']}/agents/{a['id']}/state", json={"paused": True})
    assert {x["extension_id"]: x for x in r.json()["members"]}[a["id"]]["paused"]
    assert adapter.queue_calls[-1] == (queue_name, f"PJSIP/{a['endpoint_name']}", True, True)
    assert adapter.switch_states[("agentpause", org["slug"], "6001")] == "1"
    r = admin.post(f"{QUEUES}/{q['id']}/agents/{a['id']}/state", json={"logged_in": False})
    m = {x["extension_id"]: x for x in r.json()["members"]}[a["id"]]
    assert not m["logged_in"] and not m["paused"]
    assert adapter.queue_calls[-1] == (queue_name, f"PJSIP/{a['endpoint_name']}", False, False)
    assert ("agent", org["slug"], "6001") not in adapter.switch_states
    # Editing the member list keeps a dynamic agent's state.
    admin.post(f"{QUEUES}/{q['id']}/agents/{a['id']}/state", json={"logged_in": True})
    r = admin.patch(
        f"{QUEUES}/{q['id']}",
        json={"members": [{"extension_id": a["id"], "penalty": 3, "dynamic": True}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["members"][0]["logged_in"] and r.json()["members"][0]["penalty"] == 3
    # Phone events: a per-queue logout, then the sync re-adds a lost member.
    with session_scope() as db:
        assert (
            agents.handle_userevent(
                db,
                {"Org": org["slug"], "Extension": "6001", "Action": "logout", "Queue": q["slug"]},
            )
            == 1
        )
        assert (
            agents.handle_userevent(
                db, {"Org": org["slug"], "Extension": "6001", "Action": "login"}
            )
            == 1
        )
        assert (
            agents.handle_userevent(
                db, {"Org": org["slug"], "Extension": "nope", "Action": "login"}
            )
            == 0
        )
        adapter.queue_state.clear()
        assert agents.sync(db, adapter) == 1
        assert adapter.queue_state[queue_name][f"PJSIP/{a['endpoint_name']}"]["paused"] is False
        # A stray dynamic member in the engine is removed.
        adapter.queue_state[queue_name]["PJSIP/ghost"] = {
            "dynamic": True,
            "paused": False,
            "penalty": 0,
        }
        assert (
            agents.sync(db, adapter) == 1 and "PJSIP/ghost" not in adapter.queue_state[queue_name]
        )


def test_breakout_menu_is_validated_and_rendered(admin, app):
    org = _org(admin)
    a = _ext(admin, org["id"], "6003")
    menu = admin.post(IVR, json={"organization_id": org["id"], "name": "Hold menu"}).json()
    q = _queue(admin, org, [{"extension_id": a["id"]}], breakout_ivr_id=menu["id"], number="2401")
    assert q["breakout_ivr_name"] == "Hold menu"
    r = admin.patch(
        f"{QUEUES}/{q['id']}", json={"breakout_ivr_id": "00000000-0000-0000-0000-000000000001"}
    )
    assert r.status_code == 422 and "IVR menu not found" in r.text
    admin.patch(f"{IVR}/{menu['id']}", json={"is_enabled": False})
    r = admin.patch(f"{QUEUES}/{q['id']}", json={"breakout_ivr_id": menu["id"], "description": "x"})
    assert r.status_code == 422 and "disabled" in r.text


def _snap_queue(**over):
    q = {
        "slug": "support",
        "name": "Support",
        "number": "2400",
        "organization": "example",
        "strategy": "ringall",
        "member_timeout": 15,
        "retry_seconds": 5,
        "wrapup_seconds": 0,
        "max_wait_seconds": 300,
        "max_callers": 0,
        "join_when_empty": False,
        "announce_position": False,
        "announce_frequency": 60,
        "announcement_prompt": None,
        "periodic_prompt": None,
        "periodic_seconds": 60,
        "music": "default",
        "hold_music": None,
        "breakout": None,
        "members": [
            {
                "endpoint_name": "example-1001",
                "number": "1001",
                "name": "Front",
                "penalty": 0,
                "dynamic": True,
            },
            {
                "endpoint_name": "example-1002",
                "number": "1002",
                "name": "Back",
                "penalty": 1,
                "dynamic": False,
            },
        ],
        "failover": {"type": "hangup"},
    }
    q.update(over)
    return q


CODES = {"queue_login": "*45", "queue_pause": "*46", "queue_count": "*47"}


def test_generated_queue_agents_and_breakout():
    ext2 = {
        "endpoint_name": "example-1002",
        "number": "1002",
        "display_name": "Back",
        "organization": "example",
        "secret": "s3cret-value",
        "max_contacts": 1,
    }
    snap = _snapshot(feature_codes=CODES)
    snap["extensions"].append(ext2)
    snap["queues"] = [_snap_queue(breakout="hold-menu")]
    snap["ivr_menus"] = [
        {
            "slug": "hold-menu",
            "name": "Hold menu",
            "organization": "example",
            "prompt": "hold",
            "invalid_prompt": None,
            "timeout_seconds": 5,
            "max_retries": 3,
            "allow_direct_dial": False,
            "direct_dial": [],
            "timeout": {"type": "hangup"},
            "invalid": {"type": "hangup"},
            "entries": [{"digit": "1", "type": "extension", "number": "1001"}],
        }
    ]
    files = _files(snap)
    conf = _context(files["queues.conf"], "veyra-support")
    assert "persistentmembers=yes" in files["queues.conf"]
    assert "context=veyra-ivr-hold-menu" in conf
    assert "member => PJSIP/example-1002,1,Back,PJSIP/example-1002" in conf
    assert "example-1001" not in conf  # dynamic: joins at login
    dp = files["extensions.conf"]
    login = _context(dp, "veyra-agent-login")
    assert "exten => 1001,1,NoOp(Veyra agent 1001 toggles every queue)" in login
    assert "AddQueueMember(veyra-support,PJSIP/example-1001,0,,Front,PJSIP/example-1001)" in login
    assert "Set(DB(veyra/agent/example/1001/support)=1)" in login
    assert "UserEvent(VeyraAgent,Org: example,Extension: 1001,Action: login)" in login
    per_queue = _context(dp, "veyra-agent-login-support")
    assert 'GotoIf($["${DB(veyra/agent/example/1001/support)}"="1"]?logout)' in per_queue
    assert "Action: logout,Queue: support" in per_queue
    features = _context(dp, "veyra-features")
    assert "Goto(veyra-agent-login,${VEYRA_EXT},1)" in features
    assert (
        "exten => *452400,1" in features
        and "Goto(veyra-agent-login-support,${VEYRA_EXT},1)" in features
    )
    assert "PauseQueueMember(,PJSIP/${CHANNEL(endpoint)},,veyra)" in features
    assert "QUEUE_WAITING_COUNT(veyra-support)" in features
    internal = _context(dp, "veyra-internal")
    assert "exten => *45*1001,hint,Custom:veyra-agent-example-1001" in internal
    assert "exten => *46*1001,hint,Custom:veyra-agentpause-example-1001" in internal
    # No dynamic agents: no login contexts or codes, only the count code.
    snap["queues"] = [_snap_queue(members=[_snap_queue()["members"][1]])]
    dp2 = _files(snap)["extensions.conf"]
    assert (
        "[veyra-agent-login]" not in dp2
        and "exten => *45,1" not in dp2
        and "exten => *472400,1" in dp2
    )
