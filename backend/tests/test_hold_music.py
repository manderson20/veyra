# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hold music sets (docs/PAGING_RECORDINGS.md §3.2): the generator's
musiconhold.conf and class references, the file copies, and the API."""

import pytest
from fake_adapter import FakeAdapter
from test_audio import make_wav

from veyra.configmgmt import service
from veyra.core.db import session_scope
from veyra.core.security.crypto import load_installation_key
from veyra.telephony import moh
from veyra.telephony.asterisk import generator
from veyra.telephony.settings import SipSettings

HM = "/api/v1/hold-music"


# ----------------------------------------------------------------- generator


def _ext(number, org="example"):
    return {
        "endpoint_name": f"{org}-{number}",
        "number": number,
        "display_name": f"Phone {number}",
        "organization": org,
        "secret": "s3cret-value-123",
    }


def _snapshot(**over):
    snap = {
        "sip": SipSettings().model_dump(mode="json"),
        "installation": {"name": "Test"},
        "organizations": [{"slug": "example", "name": "Example", "timezone": "UTC"}],
        "extensions": [_ext("1001"), _ext("1002")],
        "hold_music": [
            {
                "slug": "classical",
                "name": "Classical",
                "organization": "example",
                "random": False,
                "files": ["01-bach.wav", "02-handel.wav"],
            },
            {
                "slug": "jazz",
                "name": "Jazz",
                "organization": "example",
                "random": True,
                "files": [],
            },
        ],
    }
    snap.update(over)
    return snap


def _file(files, name):
    return next(f for f in files if f.path == name).content


def test_moh_conf_classes_and_endpoint_default():
    files = generator.generate(
        _snapshot(
            organizations=[
                {"slug": "example", "name": "Example", "timezone": "UTC", "hold_music": "jazz"}
            ]
        ),
        moh_dir="/srv/moh",
    )
    conf = _file(files, "musiconhold.conf")
    assert "[veyra-classical]\n" in conf and "[veyra-jazz]\n" in conf
    assert "directory=/srv/moh/classical\n" in conf and "sort=alpha" in conf
    assert "sort=random" in conf
    assert "tracks: 01-bach.wav, 02-handel.wav" in conf
    ep = _file(files, "pjsip.endpoints.conf")
    assert ep.count("moh_suggest=veyra-jazz") == 2
    assert generator.reload_scopes(["musiconhold.conf"]) == ["res_musiconhold.so"]


def test_no_set_keeps_the_builtin_class():
    files = generator.generate(_snapshot(hold_music=[]))
    assert "[veyra-" not in _file(files, "musiconhold.conf")
    assert "moh_suggest" not in _file(files, "pjsip.endpoints.conf")


def test_queue_and_ring_group_use_their_set():
    member = {"endpoint_name": "example-1001", "number": "1001", "name": "Phone 1001"}
    snap = _snapshot(
        queues=[
            {
                "slug": "support",
                "name": "Support",
                "number": "2400",
                "organization": "example",
                "music": "default",
                "hold_music": "classical",
                "members": [member],
            },
            {
                "slug": "billing",
                "name": "Billing",
                "number": "2401",
                "organization": "example",
                "music": "default",
                "members": [member],
            },
        ],
        ring_groups=[
            {
                "slug": "front",
                "name": "Front",
                "number": "2300",
                "organization": "example",
                "music": "default",
                "hold_music": "jazz",
                "members": [member],
            },
            {
                "slug": "back",
                "name": "Back",
                "number": "2301",
                "organization": "example",
                "members": [member],
            },
        ],
    )
    files = generator.generate(snap)
    queues = _file(files, "queues.conf")
    assert "[veyra-support]" in queues.split("musicclass=veyra-classical")[0]
    assert "musicclass=default" in queues.split("[veyra-billing]")[1]
    dp = _file(files, "extensions.conf")
    front = dp.split("[veyra-rg-front]")[1].split("[veyra-rg-back]")[0]
    assert "Dial(${VEYRA_DIAL:1},20,${VEYRA_XFER}m(veyra-jazz))" in front
    back = dp.split("[veyra-rg-back]")[1]
    assert "Dial(${VEYRA_DIAL:1},20,${VEYRA_XFER})" in back


def test_unknown_or_bad_sets_are_rejected():
    with pytest.raises(generator.GenerationError, match="not in the snapshot"):
        generator.generate(
            _snapshot(
                organizations=[
                    {"slug": "example", "name": "E", "timezone": "UTC", "hold_music": "gone"}
                ]
            )
        )
    bad = _snapshot()
    bad["hold_music"][0]["files"] = ["../etc/passwd"]
    with pytest.raises(generator.GenerationError, match="file name"):
        generator.generate(bad)
    bad = _snapshot()
    bad["hold_music"][0]["slug"] = "Bad Slug"
    with pytest.raises(generator.GenerationError):
        generator.generate(bad)


def test_sync_class_copies_in_order_and_removes_stale(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.wav").write_bytes(b"AAAA")
    (src / "b.wav").write_bytes(b"BB")
    base = tmp_path / "moh"
    names = moh.sync_class(base, "set", [("bach", src / "a.wav"), ("handel", src / "b.wav")])
    assert names == ["01-bach.wav", "02-handel.wav"]
    assert (base / "set" / "01-bach.wav").read_bytes() == b"AAAA"
    # reorder, change one, drop the other, a missing source is skipped
    (src / "b.wav").write_bytes(b"CC")
    names = moh.sync_class(base, "set", [("handel", src / "b.wav"), ("gone", src / "x.wav")])
    assert names == ["01-handel.wav"]
    assert sorted(p.name for p in (base / "set").iterdir()) == ["01-handel.wav"]
    assert (base / "set" / "01-handel.wav").read_bytes() == b"CC"
    moh.remove_class(base, "set")
    assert not (base / "set").exists()
    with pytest.raises(moh.MohError):
        moh.sync_class(base, "../x", [])


# ----------------------------------------------------------------- API


def _org(admin):
    return admin.get("/api/v1/organizations").json()["items"][0]


def _upload(admin, org_id, name):
    r = admin.post(
        "/api/v1/prompts",
        data={"organization_id": org_id, "name": name, "kind": "music"},
        files={"file": (f"{name}.wav", make_wav(1.0, 8000, 1), "audio/wav")},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_hold_music_api_files_assignments_and_deployment(admin, app, tmp_path):
    settings = app.state.settings
    adapter = FakeAdapter(prompts_dir=settings.prompts_dir, moh_dir=settings.moh_dir)
    app.state.telephony = adapter
    cfg = tmp_path / "asterisk-veyra"
    cfg.mkdir()
    settings.asterisk_config_dir = cfg
    deployer = service.Deployer(adapter, cfg, load_installation_key(settings))
    org = _org(admin)
    bach = _upload(admin, org["id"], "Bach")
    handel = _upload(admin, org["id"], "Handel")
    r = admin.post(HM, json={"organization_id": org["id"], "name": "Classical", "tracks": []})
    assert r.status_code == 201, r.text
    assert r.json()["problems"]  # empty set warns
    admin.delete(f"{HM}/{r.json()['id']}")
    r = admin.post(
        HM,
        json={
            "organization_id": org["id"],
            "name": "Classical",
            "tracks": [bach["id"], handel["id"]],
        },
    )
    assert r.status_code == 201, r.text
    hm = r.json()
    assert hm["class_name"] == "veyra-classical" and hm["problems"] == []
    assert [t["name"] for t in hm["tracks"]] == ["Bach", "Handel"]
    folder = settings.moh_dir / "classical"
    assert sorted(p.name for p in folder.iterdir()) == ["01-bach.wav", "02-handel.wav"]
    # duplicate name, foreign recording
    r = admin.post(HM, json={"organization_id": org["id"], "name": "Classical"})
    assert r.status_code == 409
    r = admin.post(
        HM,
        json={"organization_id": org["id"], "name": "Other", "tracks": [str(org["id"])]},
    )
    assert r.status_code == 422
    # reorder
    r = admin.patch(f"{HM}/{hm['id']}", json={"tracks": [handel["id"], bach["id"]]})
    assert r.status_code == 200, r.text
    assert sorted(p.name for p in folder.iterdir()) == ["01-handel.wav", "02-bach.wav"]
    # the recording counts as used and cannot be deleted
    p = admin.get(f"/api/v1/prompts/{bach['id']}").json()
    assert p["in_use_by"] == 1
    r = admin.delete(f"/api/v1/prompts/{bach['id']}")
    assert r.status_code == 409 and "Classical" in r.text
    # replacing the audio refreshes the copy
    r = admin.put(
        f"/api/v1/prompts/{bach['id']}/audio",
        files={"file": ("b.wav", make_wav(2.0, 8000, 1), "audio/wav")},
    )
    assert r.status_code == 200, r.text
    library = settings.prompts_dir / org["slug"] / f"{bach['slug']}.wav"
    assert (folder / "02-bach.wav").read_bytes() == library.read_bytes()
    # assign: organization default, a queue, a ring group
    r = admin.patch(f"/api/v1/organizations/{org['id']}", json={"moh_class_id": hm["id"]})
    assert r.status_code == 200 and r.json()["moh_class_id"] == hm["id"]
    ext = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1001", "display_name": "Front"},
    ).json()
    q = admin.post(
        "/api/v1/queues",
        json={
            "organization_id": org["id"],
            "name": "Support",
            "number": "2400",
            "moh_class_id": hm["id"],
            "members": [{"extension_id": ext["id"], "penalty": 0}],
        },
    )
    assert q.status_code == 201, q.text
    assert q.json()["moh_class_name"] == "Classical"
    g = admin.post(
        "/api/v1/ring-groups",
        json={
            "organization_id": org["id"],
            "name": "Front",
            "number": "2300",
            "music": "default",
            "moh_class_id": hm["id"],
            "members": [ext["id"]],
        },
    )
    assert g.status_code == 201, g.text
    assert g.json()["music"] == "default" and g.json()["moh_class_id"] == hm["id"]
    assert admin.get(f"{HM}/{hm['id']}").json()["in_use_by"] == 3
    assert admin.delete(f"{HM}/{hm['id']}").status_code == 409
    # deployment
    r = admin.post("/api/v1/telephony/apply", json={})
    assert r.status_code in (200, 202), r.text
    with session_scope() as db:
        deployer.run_once(db)
    conf = (cfg / "musiconhold.conf").read_text()
    assert f"directory={settings.moh_dir}/classical" in conf
    assert "tracks: 01-handel.wav, 02-bach.wav" in conf
    assert "moh_suggest=veyra-classical" in (cfg / "pjsip.endpoints.conf").read_text()
    assert "musicclass=veyra-classical" in (cfg / "queues.conf").read_text()
    assert "m(veyra-classical)" in (cfg / "extensions.conf").read_text()
    assert "res_musiconhold.so" in adapter.reloads
    # release the assignments, then the set can go and its folder with it
    admin.patch(f"/api/v1/organizations/{org['id']}", json={"moh_class_id": None})
    admin.patch(f"/api/v1/queues/{q.json()['id']}", json={"moh_class_id": None})
    admin.patch(f"/api/v1/ring-groups/{g.json()['id']}", json={"moh_class_id": None})
    assert admin.delete(f"{HM}/{hm['id']}").status_code == 204
    assert not folder.exists()


def test_streamed_hold_music(admin):
    """An internet station as hold music (#138): a custom class fed by ffmpeg."""
    snap = _snapshot()
    snap["hold_music"].append(
        {
            "slug": "radio",
            "name": "Radio",
            "organization": "example",
            "random": False,
            "files": [],
            "stream_url": "https://stream.example.org:8443/live.mp3?quality=low",
        }
    )
    conf = _file(generator.generate(snap), "musiconhold.conf")
    radio = conf.split("[veyra-radio]")[1].split("[")[0]
    assert "mode=custom" in radio and "format=slin" in radio
    assert (
        f"application={generator.MOH_STREAM_COMMAND} "
        "https://stream.example.org:8443/live.mp3?quality=low /var/lib/veyra/moh/radio"
    ) in radio
    snap["hold_music"][-1]["stream_url"] = "https://x.example/a b"
    with pytest.raises(generator.GenerationError, match="stream"):
        generator.generate(snap)

    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    r = admin.post(
        HM,
        json={"organization_id": org, "name": "Radio", "stream_url": "http://radio.example/live"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["stream_url"] == "http://radio.example/live"
    assert not any("no recordings" in p for p in r.json()["problems"])
    for bad in ("ftp://x.example/a", "http://x.example/a,b", 'http://x.example/"a'):
        r2 = admin.patch(f"{HM}/{r.json()['id']}", json={"stream_url": bad})
        assert r2.status_code == 422, bad
    r3 = admin.patch(f"{HM}/{r.json()['id']}", json={"stream_url": ""})
    assert r3.status_code == 200 and r3.json()["stream_url"] is None
