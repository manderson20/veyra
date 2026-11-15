# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where capability packs come from (docs/CONFIG_VERIFICATION.md §2.0):
built in, from modules, imported; the Coverage listing; the pack author's
tools."""

import io
import zipfile
from pathlib import Path

import pytest
from test_capabilities import BUILT_IN, _pack

from veyra.core.models import CapabilityPack
from veyra.modules.manifest import Provisioning
from veyra.provisioning import packs
from veyra.provisioning.capabilities import load_pack
from veyra.provisioning.renderer import TemplateCatalog

REPO = Path(__file__).resolve().parents[2]
PACKS = "/api/v1/provisioning/capability-packs"


def _zip(root: Path, prefix: str = "") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in sorted(root.rglob("*.toml")):
            zf.writestr(prefix + str(p.relative_to(root)), p.read_text())
    return buf.getvalue()


def _row(root: Path) -> CapabilityPack:
    files = {str(p.relative_to(root)): p.read_text() for p in root.rglob("*.toml")}
    return CapabilityPack(pack_id="test.acme", files=files)


def test_sources_in_order(tmp_path):
    acme = _pack(tmp_path / "m")
    catalog = packs.build([BUILT_IN], [("acme.module", acme.parent)], [_row(acme)])
    assert catalog.packs["test.acme"].origin == "module:acme.module"
    assert catalog.packs["veyra.yealink"].origin == "built-in"
    # The imported copy of an id a module already provides is refused, not merged.
    assert any("already loaded" in e for e in catalog.load_errors["imported:test.acme"])
    alone = packs.build([BUILT_IN], [], [_row(acme)])
    assert alone.packs["test.acme"].origin == "local"


def test_read_archive(tmp_path):
    acme = _pack(tmp_path)
    files = packs.read_archive(_zip(acme))
    assert "pack.toml" in files and "desk/1.1.toml" in files
    nested = packs.read_archive(_zip(acme, "acme-pack/"))
    assert nested == files
    assert packs.validate_files(files).info.id == "test.acme"
    with pytest.raises(packs.PackImportError):
        packs.read_archive(b"not a zip")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.toml", "x")
    with pytest.raises(packs.PackImportError, match="inside the pack"):
        packs.read_archive(buf.getvalue())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("pack.toml", "x")
        zf.writestr("run.sh", "rm -rf /")
    with pytest.raises(packs.PackImportError, match=r"only \.toml"):
        packs.read_archive(buf.getvalue())


def test_module_manifest_section():
    assert Provisioning(capabilities="capabilities").capabilities == "capabilities"
    for bad in ("/etc", "../x", "a/../../b"):
        with pytest.raises(ValueError):
            Provisioning(capabilities=bad)


def test_author_tools(tmp_path):
    written = packs.new_pack(tmp_path / "acme", "acme", "desk")
    assert {p.name for p in written} == {"pack.toml", "family.toml", "1.0.toml"}
    with pytest.raises(packs.PackImportError):
        packs.new_pack(tmp_path / "acme", "acme", "desk")  # never over existing work
    templates = TemplateCatalog.from_paths([REPO / "provisioning" / "templates"])
    checks = packs.check_pack(load_pack(BUILT_IN / "yealink"), templates)
    assert {c.model for c in checks} == {"T42U", "T43U", "T44U", "T44W", "T46U", "T48U"}
    assert all(c.error is None and not c.findings for c in checks)


def test_api(admin, app, tmp_path):
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    for mac, model in (
        ("805ec0aa0001", "T58W"),
        ("805ec0aa0002", "T58W"),
        ("805ec0aa0003", "T46U"),
    ):
        r = admin.post(
            "/api/v1/devices",
            json={
                "organization_id": org,
                "mac_address": mac,
                "manufacturer": "Yealink",
                "model": model,
            },
        )
        assert r.status_code == 201, r.text
    listed = admin.get(PACKS).json()
    ids = {p["id"]: p for p in listed["packs"]}
    assert {"veyra.poly", "veyra.yealink"} <= set(ids)
    yealink = ids["veyra.yealink"]
    assert yealink["supports"][0]["provenance"] == "seeded-from-template"
    assert yealink["families"][0]["releases"][0]["cited"] == 0
    assert listed["uncovered"] == [{"manufacturer": "Yealink", "model": "T58W", "phones": 2}]

    acme = _pack(tmp_path)
    r = admin.post(PACKS, files={"file": ("acme.zip", _zip(acme), "application/zip")})
    assert r.status_code == 201, r.text
    assert r.json()["origin"] == "local" and r.json()["id"] == "test.acme"
    assert "test.acme" in {p["id"] for p in admin.get(PACKS).json()["packs"]}
    # Importing again replaces it (a newer version of the same pack).
    assert (
        admin.post(PACKS, files={"file": ("acme.zip", _zip(acme), "application/zip")}).status_code
        == 201
    )

    poly = BUILT_IN / "poly"
    r = admin.post(PACKS, files={"file": ("poly.zip", _zip(poly), "application/zip")})
    assert r.status_code == 409 and r.json()["code"] == "pack_id_in_use"
    broken = tmp_path / "broken" / "acme"
    broken.mkdir(parents=True)
    (broken / "pack.toml").write_text('schema = 1\n[pack]\nid = "x"\n')
    r = admin.post(PACKS, files={"file": ("b.zip", _zip(broken), "application/zip")})
    assert r.status_code == 422 and r.json()["code"] == "invalid_pack"

    check = admin.get(f"{PACKS}/veyra.yealink/check").json()
    assert check and all(c["error"] is None for c in check)

    assert admin.delete(f"{PACKS}/test.acme").status_code == 204
    assert "test.acme" not in {p["id"] for p in admin.get(PACKS).json()["packs"]}
    assert admin.delete(f"{PACKS}/veyra.poly").status_code == 404  # built-in packs stay


EXAMPLE = REPO / "docs" / "examples" / "capability-pack-yealink-strict"


def test_imported_pack_wins_for_its_models():
    files = {str(p.relative_to(EXAMPLE)): p.read_text() for p in EXAMPLE.rglob("*.toml")}
    row = CapabilityPack(pack_id="example.yealink-strict", files=files)
    catalog = packs.build([BUILT_IN], [], [row])
    hit = catalog.family_for("Yealink", "T46U")
    assert hit is not None and hit[0].info.id == "example.yealink-strict"
    assert catalog.family_for("Poly", "VVX 450")[0].info.id == "veyra.poly"


def test_packs_imported_elsewhere_are_picked_up(admin, app):
    """The console command and the other HA node write the table; the web
    service reloads at its next check."""
    from datetime import UTC, datetime

    from veyra.core.db import session_scope

    files = {str(p.relative_to(EXAMPLE)): p.read_text() for p in EXAMPLE.rglob("*.toml")}
    with session_scope() as db:
        now = datetime.now(UTC)
        db.add(
            CapabilityPack(
                pack_id="example.yealink-strict",
                name="x",
                vendor="yealink",
                version="0.1.0",
                files=files,
                uploaded_by_label="console",
                created_at=now,
                updated_at=now,
            )
        )
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    pid = admin.post(
        "/api/v1/device-profiles",
        json={"organization_id": org, "name": "Test", "template_key": "yealink.t4x"},
    ).json()["id"]
    edit = {
        "file": "{mac}.cfg",
        "parameter": "account.1.sip_server.1.transport_type",
        "value": "4",
        "models": ["T46U"],
    }
    r = admin.put(f"/api/v1/device-profiles/{pid}/base-edits", json={"edits": [edit]})
    assert r.status_code == 422 and r.json()["code"] == "config_findings", r.text
    origins = {p["id"]: p["origin"] for p in admin.get(PACKS).json()["packs"]}
    assert origins["example.yealink-strict"] == "local"
