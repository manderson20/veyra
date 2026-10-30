# SPDX-License-Identifier: AGPL-3.0-or-later
"""The template editor's catalog (veyra/provisioning/catalog.py): every fact
it offers exists in the facts the renderer builds, and every snippet is
valid Jinja for the sandbox."""

from sqlalchemy import select
from test_provisioning_grandstream import _device, _setup

from veyra.core.db import session_scope
from veyra.core.models import AuditEvent, Device, ProvisioningTemplate
from veyra.provisioning import catalog
from veyra.provisioning.facts import build_facts, resolve_device, sample_facts
from veyra.provisioning.renderer import _environment


def _check(facts, group):
    if group.source is None:
        for f in group.facts:
            catalog.lookup(facts, f.expr)
        return
    items = catalog.lookup(facts, group.source)
    assert items, f"no {group.source} to check {group.key} against"
    for f in group.facts:
        name, _, rest = f.expr.partition(".")
        assert name == group.item, f.expr
        catalog.lookup(items[0], rest)


def test_every_fact_exists(admin, app):
    o, ext, profile = _setup(admin)
    d, _ = _device(admin, o, ext, profile, "00:0B:82:11:22:33", "GRP2614")
    with session_scope() as db:
        device = db.get(Device, d["id"])
        ctx = resolve_device(app.state.templates, db, device)
        facts = build_facts(db, app.state.settings, ctx, key=None, mask_secrets=True)
    for group in catalog.GROUPS:
        _check(facts, group)
    # The preview's sample facts have the same names (no keys or zones there).
    sample = sample_facts({"timezone": "America/Chicago"}, "000b82000001", "GRP2614")
    for group in catalog.GROUPS:
        if group.source in (None, "lines"):
            _check(sample, group)


def test_catalog_endpoint_and_snippets(admin, app):
    r = admin.get("/api/v1/provisioning/template-catalog")
    assert r.status_code == 200, r.text
    body = r.json()
    groups = {g["key"]: g for g in body["groups"]}
    assert groups["lines"]["loop"].startswith("{% for line in lines %}")
    assert any(f["sensitive"] for f in groups["lines"]["facts"])
    assert "sip_username" in body["core_variables"]
    env = _environment([], autoescape=False)
    for s in body["snippets"]:
        env.parse(s["text"])
    for g in body["groups"]:
        if g["loop"]:
            env.parse(g["loop"].replace("{}", "{{ x }}"))


def test_editor_saves_variables_and_inherited_defaults(admin):
    """What the editor's Variables card sends: a new variable of its own, a
    default for an inherited one, and a file that uses both."""
    org = admin.get("/api/v1/organizations").json()["items"][0]
    base = "/api/v1/provisioning/templates"
    r = admin.post(
        f"{base}/grandstream.grp261x/customize",
        json={"key": "local.gs.grp", "name": "Our GRP", "organization_id": org["id"]},
    )
    assert r.status_code == 201, r.text
    export = admin.get(f"{base}/local.gs.grp/export").json()
    manifest = export["manifest"]
    manifest["variables"] = [
        {
            "name": "backlight_level",
            "type": "integer",
            "description": "Screen brightness",
            "required": False,
            "sensitive": False,
            "default": 7,
        },
    ]
    manifest["defaults"] = {**manifest.get("defaults", {}), "polling_hour": 4}
    sources = dict(export["sources"])
    (name,) = [n for n in sources if n.endswith(".j2")]
    sources[name] = (
        '{% extends "grandstream.grp261x/cfg.xml.j2" %}{% block model_settings %}'
        "<P1000>{{ backlight_level }}</P1000><P1001>{{ polling_hour }}</P1001>{% endblock %}"
    )
    r = admin.put(f"{base}/local.gs.grp", json={"manifest": manifest, "sources": sources})
    assert r.status_code == 200, r.text
    t = admin.get(f"{base}/local.gs.grp").json()
    assert t["validation"] == []
    assert {v["name"]: v["default"] for v in t["variables"]}["backlight_level"] == 7
    assert t["defaults"]["polling_hour"] == 4
    out = admin.post(
        f"{base}/local.gs.grp/preview",
        json={
            "model": "GRP2614",
            "mac": "000b82000001",
            "values": {
                "sip_server": "pbx.example.org",
                "extension_number": "1001",
                "sip_username": "example-1001",
                "sip_password": "secret",
            },
        },
    )
    assert out.status_code == 200, out.text
    content = out.json()["files"][0]["content"]
    assert "<P1000>7</P1000>" in content and "<P1001>4</P1001>" in content


def _customize(admin, parent, key):
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    r = admin.post(
        f"/api/v1/provisioning/templates/{parent}/customize",
        json={"key": key, "name": key, "organization_id": org},
    )
    assert r.status_code == 201, r.text
    return f"/api/v1/provisioning/templates/{key}"


def test_customize_a_template_without_blocks_can_be_changed(admin):
    """Issue #350: the Algo files have no blocks, so a change must not be dropped."""
    url = _customize(admin, "algo.sip", "local.algo")
    doc = admin.get(f"{url}/export").json()
    source = doc["sources"]["algom.conf.j2"]
    assert "model_settings" not in source and "extends" not in source
    assert "sip" in source.lower()
    doc["sources"]["algom.conf.j2"] = source + "\nmy.setting = 1\n"
    r = admin.put(url, json={"manifest": doc["manifest"], "sources": doc["sources"]})
    assert r.status_code == 200, r.text


def test_block_the_parent_lacks_is_refused(admin):
    url = _customize(admin, "grandstream.grp261x", "local.gs")
    doc = admin.get(f"{url}/export").json()
    name = next(iter(doc["sources"]))
    doc["sources"][name] = doc["sources"][name] + "{% block not_there %}x{% endblock %}\n"
    r = admin.put(url, json={"manifest": doc["manifest"], "sources": doc["sources"]})
    assert r.status_code == 422, r.text
    assert "not_there" in r.text


def test_accept_parent(admin):
    url = _customize(admin, "grandstream.grp261x", "local.gs2")
    with session_scope() as db:
        row = db.scalars(
            select(ProvisioningTemplate).where(ProvisioningTemplate.template_key == "local.gs2")
        ).one()
        real = row.manifest["template"]["parent_version"]
        row.manifest = {
            **row.manifest,
            "template": {**row.manifest["template"], "parent_version": "0.0.1"},
        }
    t = admin.get(url).json()
    assert t["parent_updated"] and t["parent_current_version"] == real
    listed = admin.get("/api/v1/provisioning/templates").json()["items"]
    assert next(i for i in listed if i["key"] == "local.gs2")["parent_updated"]
    r = admin.post(f"{url}/accept-parent", json={})
    assert r.status_code == 200, r.text
    assert not r.json()["parent_updated"] and r.json()["parent_version"] == real
    with session_scope() as db:
        ev = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "provisioning.template.accept_parent")
        ).one()
        assert ev.details["from"] == "0.0.1"
    # An official template has no stored row.
    official = "/api/v1/provisioning/templates/grandstream.grp261x"
    assert admin.post(f"{official}/accept-parent", json={}).status_code == 404


def test_broken_template_can_be_opened_and_fixed(admin):
    url = _customize(admin, "grandstream.grp261x", "local.broken")
    with session_scope() as db:
        row = db.scalars(
            select(ProvisioningTemplate).where(ProvisioningTemplate.template_key == "local.broken")
        ).one()
        good = row.manifest
        bad = {**good, "template": {k: v for k, v in good["template"].items() if k != "models"}}
        row.manifest = bad
    listed = admin.get("/api/v1/provisioning/templates").json()
    assert "db:local.broken" in listed["load_errors"]
    assert admin.get(url).status_code == 404
    stored = admin.get(f"{url}/stored").json()
    assert stored["problems"] and stored["manifest"] == bad
    r = admin.put(url, json={"manifest": good, "sources": stored["sources"]})
    assert r.status_code == 200, r.text
    assert (
        "db:local.broken" not in admin.get("/api/v1/provisioning/templates").json()["load_errors"]
    )
