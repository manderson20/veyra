# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 7 API: prompts (upload, playback, recordings from phones) and
IVR menus (key map, fallbacks, in-use rules), plus their deployment."""

import time

from fake_adapter import FakeAdapter
from test_audio import make_wav

from veyra.configmgmt import service
from veyra.core.db import session_scope
from veyra.core.security.crypto import load_installation_key

PROMPTS = "/api/v1/prompts"
IVR = "/api/v1/ivr"
VM = "/api/v1/voicemail"
INBOUND = "/api/v1/routing/inbound"


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _ext(admin, org_id, number, name="Front Office"):
    r = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org_id, "number": number, "display_name": name},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _upload(admin, org_id, name, wav=None, **fields):
    r = admin.post(
        PROMPTS,
        data={"organization_id": org_id, "name": name, **fields},
        files={"file": (f"{name}.wav", wav or make_wav(1.0, 16000, 2), "audio/wav")},
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


def test_prompt_upload_conversion_playback_replace_and_delete(admin, app):
    org = _org(admin)
    p = _upload(admin, org["id"], "Welcome Message", description="Main greeting")
    assert p["slug"] == "welcome-message" and p["source"] == "upload"
    assert p["duration_seconds"] == 1.0 and p["file_present"] and p["in_use_by"] == 0
    path = app.state.settings.prompts_dir / org["slug"] / "welcome-message.wav"
    assert path.is_file() and p["size_bytes"] == path.stat().st_size
    # stored as 8 kHz mono 16-bit: 1 s = 16000 bytes + 44-byte header
    assert path.stat().st_size == 16044
    # playback streams the stored file
    r = admin.get(f"{PROMPTS}/{p['id']}/audio")
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/wav")
    assert r.content == path.read_bytes()
    # same name twice gets a numbered slug
    assert _upload(admin, org["id"], "Welcome-Message")["slug"] == "welcome-message-2"
    # bad uploads are refused with the accepted format
    r = admin.post(
        PROMPTS,
        data={"organization_id": org["id"], "name": "Bad"},
        files={"file": ("x.mp3", b"ID3\x04\x00 not audio", "audio/mpeg")},
    )
    assert r.status_code == 422 and r.json()["code"] == "unsupported_audio"
    assert "WAV" in r.json()["detail"]
    assert admin.get(PROMPTS).json()["total"] == 2
    # rename and describe
    r = admin.patch(f"{PROMPTS}/{p['id']}", json={"name": "Welcome", "description": ""})
    assert (
        r.status_code == 200 and r.json()["name"] == "Welcome" and r.json()["description"] is None
    )
    assert r.json()["slug"] == "welcome-message"  # slugs are stable
    # replace the audio in place
    r = admin.put(
        f"{PROMPTS}/{p['id']}/audio",
        files={"file": ("new.wav", make_wav(2.0, 8000, 1), "audio/wav")},
    )
    assert r.status_code == 200 and r.json()["duration_seconds"] == 2.0
    assert path.stat().st_size == 32044
    assert admin.get(PROMPTS, params={"q": "welc"}).json()["total"] == 2
    assert admin.delete(f"{PROMPTS}/{p['id']}").status_code == 204
    assert not path.exists()
    actions = [e["action"] for e in admin.get("/api/v1/audit").json()["items"]]
    assert {"prompt.create", "prompt.update", "prompt.replace_audio", "prompt.delete"} <= set(
        actions
    )


def test_recordings_from_phones_are_listed_adopted_and_deleted(admin, app):
    org = _org(admin)
    base = app.state.settings.prompts_dir
    # listing makes the incoming folder (the worker does the same every minute)
    assert admin.get(f"{PROMPTS}/recordings").json() == []
    incoming = base / org["slug"] / "incoming"
    assert incoming.is_dir()
    epoch = int(time.time()) - 60
    (incoming / f"rec-1001-{epoch}.wav").write_bytes(make_wav(1.5, 8000, 1))
    (incoming / "notes.txt").write_text("ignored")
    (incoming / "rec-1001-1234.tmp").write_bytes(b"x")
    rows = admin.get(f"{PROMPTS}/recordings").json()
    assert len(rows) == 1
    rec = rows[0]
    assert rec["extension_number"] == "1001" and rec["duration_seconds"] == 1.5
    assert rec["organization_id"] == org["id"]
    r = admin.get(
        f"{PROMPTS}/recordings/{rec['file']}/audio", params={"organization_id": org["id"]}
    )
    assert r.status_code == 200 and len(r.content) == 24044
    # path tricks are not recordings
    assert (
        admin.get(
            f"{PROMPTS}/recordings/..%2Fwelcome.wav/audio", params={"organization_id": org["id"]}
        ).status_code
        == 404
    )
    r = admin.post(
        f"{PROMPTS}/recordings/{rec['file']}/adopt",
        json={"organization_id": org["id"], "name": "Front desk greeting"},
    )
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["source"] == "recording" and p["slug"] == "front-desk-greeting"
    assert (base / org["slug"] / "front-desk-greeting.wav").is_file()
    assert not (incoming / rec["file"]).exists()
    assert admin.get(f"{PROMPTS}/recordings").json() == []
    (incoming / f"rec-1002-{epoch}.wav").write_bytes(make_wav(0.5, 8000, 1))
    file = admin.get(f"{PROMPTS}/recordings").json()[0]["file"]
    assert (
        admin.delete(
            f"{PROMPTS}/recordings/{file}", params={"organization_id": org["id"]}
        ).status_code
        == 204
    )
    assert admin.get(f"{PROMPTS}/recordings").json() == []


def test_ivr_menu_crud_validation_and_in_use(admin, app, tmp_path):
    _fake(app, tmp_path)
    org = _org(admin)
    ext = _ext(admin, org["id"], "1001")
    ext2 = _ext(admin, org["id"], "1002", "Library")
    box = admin.post(VM, json={"extension_id": ext2["id"]}).json()
    welcome = _upload(admin, org["id"], "Welcome")
    oops = _upload(admin, org["id"], "Oops")
    # a menu needs a usable organization; names are unique per organization
    r = admin.post(
        IVR,
        json={
            "organization_id": org["id"],
            "name": "Main menu",
            "prompt_id": welcome["id"],
            "invalid_prompt_id": oops["id"],
            "timeout_seconds": 8,
            "max_retries": 2,
            "entries": [
                {"digit": "1", "destination": {"type": "extension", "extension_id": ext["id"]}},
                {"digit": "2", "destination": {"type": "voicemail", "extension_id": ext2["id"]}},
                {"digit": "0", "destination": {"type": "hangup"}},
            ],
            "timeout_destination": {"type": "extension", "extension_id": ext["id"]},
        },
    )
    assert r.status_code == 201, r.text
    menu = r.json()
    assert menu["slug"] == "main-menu" and menu["context"] == "veyra-ivr-main-menu"
    assert [e["digit"] for e in menu["entries"]] == ["0", "1", "2"]
    assert menu["entries"][2]["destination"]["label"].startswith("Voicemail of 1002")
    assert menu["timeout_destination"]["label"] == "1001 — Front Office"
    assert menu["invalid_destination"] == {
        "type": "hangup",
        "extension_id": None,
        "ivr_id": None,
        "ring_group_id": None,
        "queue_id": None,
        "label": "Hang up",
        "missing": False,
    }
    assert menu["problems"] == [] and menu["prompt_name"] == "Welcome"
    assert admin.get(f"{VM}/{box['id']}").json()["in_use_by"] == 1
    assert admin.get(f"{PROMPTS}/{welcome['id']}").json()["in_use_by"] == 1
    assert (
        admin.post(IVR, json={"organization_id": org["id"], "name": "Main menu"}).status_code == 409
    )
    # validation: duplicate keys, bad key, targets from elsewhere, disabled box
    bad = {**menu, "name": "Bad"}
    r = admin.post(
        IVR,
        json={
            "organization_id": org["id"],
            "name": "Dup",
            "entries": [
                {"digit": "1", "destination": {"type": "hangup"}},
                {"digit": "1", "destination": {"type": "hangup"}},
            ],
        },
    )
    assert r.status_code == 422
    r = admin.post(
        IVR,
        json={
            "organization_id": org["id"],
            "name": "Key",
            "entries": [{"digit": "A", "destination": {"type": "hangup"}}],
        },
    )
    assert r.status_code == 422
    r = admin.post(
        IVR,
        json={
            "organization_id": org["id"],
            "name": "Vm",
            "entries": [
                {"digit": "1", "destination": {"type": "voicemail", "extension_id": ext["id"]}}
            ],
        },
    )
    assert r.status_code == 422 and "no voicemail box" in r.text
    del bad
    # a second menu pointing at the first; the first cannot be deleted while referenced
    sub = admin.post(
        IVR,
        json={
            "organization_id": org["id"],
            "name": "After hours",
            "prompt_id": welcome["id"],
            "allow_direct_dial": False,
            "entries": [{"digit": "9", "destination": {"type": "ivr", "ivr_id": menu["id"]}}],
            "timeout_destination": {"type": "ivr", "ivr_id": menu["id"]},
        },
    ).json()
    assert admin.get(f"{IVR}/{menu['id']}").json()["in_use_by"] == 2
    r = admin.delete(f"{IVR}/{menu['id']}")
    assert r.status_code == 409 and r.json()["code"] == "ivr_in_use" and "After hours" in r.text
    # the prompt in use cannot be deleted
    r = admin.delete(f"{PROMPTS}/{welcome['id']}")
    assert r.status_code == 409 and r.json()["code"] == "prompt_in_use"
    # patch: replace the key map, change the prompt, disable
    r = admin.patch(
        f"{IVR}/{menu['id']}",
        json={
            "entries": [{"digit": "1", "destination": {"type": "ivr", "ivr_id": sub["id"]}}],
            "prompt_id": None,
            "allow_direct_dial": False,
        },
    )
    assert r.status_code == 200, r.text
    m = r.json()
    assert [e["digit"] for e in m["entries"]] == ["1"] and m["entries"][0]["destination"][
        "label"
    ] == "Menu: After hours"
    assert any("No prompt" in p for p in m["problems"])
    # a disabled menu is no longer a valid destination
    admin.patch(f"{IVR}/{sub['id']}", json={"is_enabled": False})
    r = admin.patch(
        f"{IVR}/{menu['id']}",
        json={"entries": [{"digit": "1", "destination": {"type": "ivr", "ivr_id": sub["id"]}}]},
    )
    assert r.status_code == 422 and "disabled" in r.text
    assert any("Key 1" in p for p in admin.get(f"{IVR}/{menu['id']}").json()["problems"])
    # listing and search
    assert admin.get(IVR).json()["total"] == 2
    assert admin.get(IVR, params={"q": "after"}).json()["total"] == 1
    # delete order: the referencing menu first
    admin.patch(f"{IVR}/{menu['id']}", json={"entries": []})
    assert admin.delete(f"{IVR}/{sub['id']}").status_code == 204
    assert admin.delete(f"{IVR}/{menu['id']}").status_code == 204
    assert admin.get(f"{PROMPTS}/{welcome['id']}").json()["in_use_by"] == 0
    assert admin.get("/api/v1/telephony/engine").json()["changes_pending"] is True


def test_inbound_routes_to_ivr_and_deployment(admin, app, tmp_path):
    adapter, deployer, cfg = _fake(app, tmp_path)
    org = _org(admin)
    ext = _ext(admin, org["id"], "1001")
    ext2 = _ext(admin, org["id"], "1002", "Library")
    admin.post(VM, json={"extension_id": ext2["id"], "pin": "1234"})
    welcome = _upload(admin, org["id"], "Welcome")
    tc = admin.post(
        "/api/v1/routing/time-conditions",
        json={
            "organization_id": org["id"],
            "name": "Hours",
            "ranges": [{"days": ["mon"], "start": "08:00", "end": "17:00"}],
        },
    ).json()
    menu = admin.post(
        IVR,
        json={
            "organization_id": org["id"],
            "name": "Main menu",
            "prompt_id": welcome["id"],
            "entries": [
                {"digit": "1", "destination": {"type": "extension", "extension_id": ext["id"]}},
                {"digit": "2", "destination": {"type": "voicemail", "extension_id": ext2["id"]}},
            ],
            "invalid_destination": {"type": "voicemail", "extension_id": ext2["id"]},
        },
    ).json()
    r = admin.post(
        INBOUND,
        json={
            "organization_id": org["id"],
            "did": "5735550100",
            "destination_type": "ivr",
            "destination_ivr_id": menu["id"],
            "time_condition_id": tc["id"],
            "after_hours_type": "voicemail",
            "after_hours_extension_id": ext2["id"],
        },
    )
    assert r.status_code == 201, r.text
    route = r.json()
    assert (
        route["destination"]["label"] == "Menu: Main menu" and route["destination_number"] is None
    )
    assert route["after_hours"]["type"] == "voicemail" and route["after_hours_number"] == "1002"
    assert not route["destination_missing"]
    # an IVR destination without the id, and an after-hours branch without a condition
    r = admin.post(
        INBOUND, json={"organization_id": org["id"], "did": "5735550101", "destination_type": "ivr"}
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "destination_ivr_id"
    r = admin.post(
        INBOUND,
        json={
            "organization_id": org["id"],
            "did": "5735550101",
            "destination_extension_id": ext["id"],
            "after_hours_type": "ivr",
            "after_hours_ivr_id": menu["id"],
        },
    )
    assert r.status_code == 422
    # switching the type clears the other target column
    r = admin.patch(
        f"{INBOUND}/{route['id']}",
        json={"destination_type": "extension", "destination_extension_id": ext["id"]},
    )
    assert r.status_code == 200 and r.json()["destination_ivr_id"] is None
    assert admin.get(f"{IVR}/{menu['id']}").json()["in_use_by"] == 0
    admin.patch(
        f"{INBOUND}/{route['id']}",
        json={"destination_type": "ivr", "destination_ivr_id": menu["id"]},
    )
    assert admin.get(f"{IVR}/{menu['id']}").json()["in_use_by"] == 1
    r = admin.post("/api/v1/telephony/apply", json={})
    assert r.status_code in (200, 202), r.text
    with session_scope() as db:
        deployer.run_once(db)
    dp = (cfg / "extensions.conf").read_text()
    assert "[veyra-ivr-main-menu]" in dp
    prompts_dir = str(app.state.settings.prompts_dir)
    assert f"Background({prompts_dir}/{org['slug']}/welcome)" in dp
    assert "exten => 1001,1,Goto(veyra-internal,1001,1)" in dp  # direct dialling
    body = dp.split("exten => 5735550100,1,")[1].split("\nexten =>")[0]
    assert "Goto(veyra-ivr-main-menu,s,1)" in body and "VoiceMail(1002@veyra,u)" in body
    assert "GotoIfTime(08:00-17:00,mon,*,*,America/Chicago?open)" in body
    assert "pbx_config.so" in adapter.reloads
    # disabling the menu: the route is flagged and renders congestion
    admin.patch(f"{IVR}/{menu['id']}", json={"is_enabled": False})
    flagged = admin.get(f"{INBOUND}/{route['id']}").json()
    assert (
        flagged["destination_missing"]
        and flagged["destination"]["label"] == "Menu: Main menu (disabled)"
    )
    admin.post("/api/v1/telephony/apply", json={})
    with session_scope() as db:
        deployer.run_once(db)
    dp = (cfg / "extensions.conf").read_text()
    assert "[veyra-ivr-main-menu]" not in dp
    assert "Congestion(5)" in dp.split("exten => 5735550100,1,")[1].split("\nexten =>")[0]


def test_audio_library_kinds_licence_and_filter(admin):
    org = admin.get("/api/v1/organizations").json()["items"][0]
    bell = _upload(admin, org["id"], "First period", kind="bell", license="CC0", credit="Freesound")
    assert bell["kind"] == "bell" and bell["license"] == "CC0" and bell["credit"] == "Freesound"
    prompt = _upload(admin, org["id"], "Welcome")
    assert prompt["kind"] == "prompt" and prompt["license"] is None
    assert admin.get(PROMPTS, params={"kind": "bell"}).json()["total"] == 1
    assert admin.get(PROMPTS, params={"kind": "music"}).json()["total"] == 0
    assert admin.get(PROMPTS, params={"kind": "song"}).status_code == 422
    r = admin.patch(
        f"{PROMPTS}/{prompt['id']}", json={"kind": "greeting", "license": " own recording "}
    )
    assert r.status_code == 200 and r.json()["kind"] == "greeting"
    assert r.json()["license"] == "own recording"
    r = admin.post(
        PROMPTS,
        data={"organization_id": org["id"], "name": "x", "kind": "jingle"},
        files={"file": ("x.wav", make_wav(1.0, 8000, 1), "audio/wav")},
    )
    assert r.status_code == 422
