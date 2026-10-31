# SPDX-License-Identifier: AGPL-3.0-or-later
"""Base File Edit (issue #372): single settings changed after rendering."""

from test_api_devices import DEVICES, _ext, _org, _profile

from veyra.provisioning import base_edits as be

URL = "/api/v1/device-profiles"


def edit(parameter, value="", remove=False, file="f", models=("M",)):
    return {
        "file": file,
        "parameter": parameter,
        "value": value,
        "remove": remove,
        "models": list(models),
    }


def run(fmt, content, *edits, model="M"):
    return be.apply(fmt, content, "f", model, edits)


def test_settings_found_in_each_format():
    xml = '<?xml version="1.0"?>\n<!-- a="b" --><c>\n <r reg.1.label="A &amp; B" x="1" /></c>'
    assert [(s.parameter, s.value) for s in be.settings("xml", xml)] == [
        ("reg.1.label", "A & B"),
        ("x", "1"),
    ]
    gs = "<config><P47>host</P47><P48></P48></config>"
    assert [(s.parameter, s.value) for s in be.settings("xml", gs)] == [
        ("P47", "host"),
        ("P48", ""),
    ]
    cfg = "#!version:1.0\n## note = no\naccount.1.label = Front desk\nblank =\n"
    found = be.settings("cfg", cfg)
    assert [(s.parameter, s.value) for s in found] == [
        ("account.1.label", "Front desk"),
        ("blank", ""),
    ]
    assert cfg[found[0].start : found[0].end] == "Front desk"


def test_change_remove_add_and_nothing_else_moves():
    cfg = "# top\na.b = 1\nc = 2\n"
    assert run("cfg", cfg, edit("c", "9")) == "# top\na.b = 1\nc = 9\n"
    assert run("cfg", cfg, edit("a.b", remove=True)) == "# top\nc = 2\n"
    assert run("cfg", cfg, edit("new.one", "x")) == "# top\na.b = 1\nc = 2\nnew.one = x\n"
    # Not its model, not its file.
    assert run("cfg", cfg, edit("c", "9"), model="Other") == cfg
    assert run("cfg", cfg, edit("c", "9", file="g")) == cfg

    xml = '<polycomConfig>\n  <r a.b="1" c="2" />\n</polycomConfig>\n'
    assert 'c="3 &lt;&quot;" />' in run("xml", xml, edit("c", '3 <"'))
    assert run("xml", xml, edit("c", remove=True)) == xml.replace(' c="2"', "")
    added = run("xml", xml, edit("d.e", "1"))
    assert '<veyra d.e="1" />' in added and added.endswith("</polycomConfig>\n")

    gs = "<config>\n<P1>a</P1>\n<P2>b</P2>\n</config>\n"
    assert "<P1>x&amp;y</P1>" in run("xml", gs, edit("P1", "x&y"))
    assert "<P1>" not in run("xml", gs, edit("P1", remove=True))
    assert "<P9>n</P9>\n</config>" in run("xml", gs, edit("P9", "n"))


def test_api_each_brand_preview_checksum_and_rules(admin, app):
    org = _org(admin)
    ext = _ext(admin, org["id"], "1401")
    poly = _profile(admin, org["id"])
    pid = poly["id"]
    r = admin.get(f"{URL}/{pid}/base-files", params={"model": "VVX 411"})
    assert r.status_code == 200, r.text
    names = {f["file"] for f in r.json()}
    assert "veyra-{mac}.cfg" in names
    phone_file = next(f for f in r.json() if f["file"] == "veyra-{mac}.cfg")
    secret = next(s for s in phone_file["settings"] if "password" in s["parameter"])
    assert secret["secret"] is True and "example" not in secret["value"]
    assert admin.get(f"{URL}/{pid}/base-files", params={"model": "T46U"}).status_code == 422

    for template, name, model in (
        ("yealink.base", "Y", "T46U"),
        ("grandstream.base", "G", "GRP2614"),
        ("algo.sip", "A", "8301"),
    ):
        p = _profile(admin, org["id"], name, template)
        r = admin.get(f"{URL}/{p['id']}/base-files", params={"model": model})
        assert r.status_code == 200, r.text
        assert r.json()[0]["settings"], template

    body = {
        "edits": [
            edit("tcpIpApp.sntp.address", "ntp.example", file="veyra-{mac}.cfg", models=["VVX 411"])
        ]
    }
    r = admin.put(f"{URL}/{pid}/base-edits", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["base_edits"][0]["value"] == "ntp.example"
    device = admin.post(
        DEVICES,
        json={
            "organization_id": org["id"],
            "mac_address": "00:04:F2:00:03:01",
            "manufacturer": "Poly",
            "model": "VVX 411",
            "profile_id": pid,
            "primary_extension_id": ext["id"],
        },
    ).json()
    files = admin.get(f"{DEVICES}/{device['id']}/preview").json()["files"]
    assert "ntp.example" in "\n".join(f["content"] for f in files)

    # Refused: passwords by name, by masked value, a model not served, doubles.
    bad = [
        edit("reg.1.auth.password", "x", file="veyra-{mac}.cfg", models=["VVX 411"]),
        edit("a", "x", file="veyra-{mac}.cfg", models=["T46U"]),
    ]
    for one in bad:
        assert admin.put(f"{URL}/{pid}/base-edits", json={"edits": [one]}).status_code == 422
    twice = [edit("a", "1", models=["VVX 411"]), edit("a", "2", models=["VVX 411"])]
    assert admin.put(f"{URL}/{pid}/base-edits", json={"edits": twice}).status_code == 422
    assert (
        admin.put(f"{URL}/{pid}/base-edits", json={"edits": [edit("a", "x\ny")]}).status_code == 422
    )

    # The checksum of an Algo file follows the edited text.
    algo = admin.get(f"{URL}", params={"manufacturer": "algo"}).json()["items"][0]
    device = admin.post(
        DEVICES,
        json={
            "organization_id": org["id"],
            "mac_address": "00:22:EE:00:03:02",
            "manufacturer": "Algo",
            "model": "8301",
            "profile_id": algo["id"],
        },
    ).json()
    conf = "algom{mac_upper}.conf"
    r = admin.put(
        f"{URL}/{algo['id']}/base-edits",
        json={"edits": [edit("sip.regexp", "77", file=conf, models=["8301"])]},
    )
    assert r.status_code == 200, r.text
    files = admin.get(f"{DEVICES}/{device['id']}/preview").json()["files"]
    text = next(f["content"] for f in files if f["filename"].endswith(".conf"))
    assert "sip.regexp = 77" in text
    import hashlib

    digest = hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()
    assert any(f["filename"].endswith(".md5") and digest in f["content"] for f in files)
