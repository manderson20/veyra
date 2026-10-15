# SPDX-License-Identifier: AGPL-3.0-or-later
"""Module catalog (docs/MODULE_CATALOG.md): a signed index served over
loopback, install, update, rollback, upload, settings, restart requests,
and the publishing commands."""

import hashlib
import http.server
import json
import shutil
import threading
from pathlib import Path

import pytest
from conftest import REPO

from veyra.cli.main import main as cli
from veyra.core.db import session_scope
from veyra.core.models import ModuleConfig, SystemSetting
from veyra.core.signing import generate_keypair
from veyra.modules import catalog
from veyra.modules.packages import build_package, sign_directory

MOD = "veyra.example-notes"


@pytest.fixture
def served(tmp_path):
    root = tmp_path / "www"
    root.mkdir()

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield root, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _package(tmp_path, version, key, key_id, extra_migration=False):
    src = tmp_path / f"src-{version}"
    shutil.copytree(
        REPO / "modules" / "veyra-example-notes", src, ignore=shutil.ignore_patterns("__pycache__")
    )
    toml = src / "module.toml"
    toml.write_text(toml.read_text().replace('version = "0.1.0"', f'version = "{version}"'))
    if extra_migration:
        (src / "migrations" / "versions" / "0002_more.py").write_text(
            'revision = "notes_0002"\ndown_revision = "notes_0001"\nbranch_labels = None\n'
            "depends_on = None\n\n\ndef upgrade():\n    pass\n\n\ndef downgrade():\n    pass\n"
        )
    sign_directory(src, key, key_id)
    return build_package(src, tmp_path / "dist")


def _catalog(app, tmp_path, served, versions=("0.2.0", "0.3.0")):
    """Trust a catalog key and an official publisher key; publish packages."""
    root, base = served
    trust = app.state.settings.trust_dir
    cat_priv, cat_pub = generate_keypair()
    pub_priv, pub_pub = generate_keypair()
    (trust / "catalog").mkdir(parents=True, exist_ok=True)
    (trust / "official").mkdir(parents=True, exist_ok=True)
    (trust / "catalog" / "test-catalog.pub").write_text(cat_pub)
    (trust / "official" / "test-publisher.pub").write_text(pub_pub)
    app.state.modules.keyring = __import__("veyra.core.signing", fromlist=["Keyring"]).Keyring.load(
        trust
    )
    key_file = tmp_path / "catalog.key"
    key_file.write_text(cat_priv)
    index = root / "index.json"
    for v in versions:
        pkg = _package(tmp_path, v, pub_priv, "test-publisher")
        shutil.copy(pkg, root / pkg.name)
        assert (
            cli(["catalog", "add", str(pkg), "--url", f"{base}/{pkg.name}", "--index", str(index)])
            == 0
        )
    assert (
        cli(
            ["catalog", "sign", str(index), "--key-file", str(key_file), "--key-id", "test-catalog"]
        )
        == 0
    )
    return root, base, pub_priv, cat_priv


def test_index_signature_and_tampering(app, tmp_path, served):
    root, base, _, _ = _catalog(app, tmp_path, served)
    keyring = catalog.catalog_keyring(app.state.settings.trust_dir)
    index, key_id = catalog.fetch_index(f"{base}/index.json", keyring)
    assert key_id == "test-catalog" and [v.version for v in index.modules[0].versions] == [
        "0.3.0",
        "0.2.0",
    ]
    doc = json.loads((root / "index.json").read_text())
    doc["modules"][0]["versions"][0]["url"] = "https://evil.example/x.vmod"
    (root / "index.json").write_text(json.dumps(doc))
    with pytest.raises(catalog.CatalogError, match="signature"):
        catalog.fetch_index(f"{base}/index.json", keyring)
    with pytest.raises(catalog.CatalogError, match="HTTPS"):
        catalog.fetch("http://example.org/index.json", 10)
    assert (
        cli(
            [
                "catalog",
                "verify",
                str(root / "index.json"),
                "--trust-dir",
                str(app.state.settings.trust_dir),
            ]
        )
        == 1
    )


def test_install_update_rollback_and_settings(admin, app, tmp_path, served):
    root, base, pub_priv, _ = _catalog(app, tmp_path, served)
    r = admin.post(
        "/api/v1/modules/catalog-sources", json={"name": "Test", "url": f"{base}/index.json"}
    )
    assert r.status_code == 201, r.text
    assert (
        r.json()["last_status"] == "ok"
        and r.json()["modules"] == 1
        and r.json()["signed_by"] == "test-catalog"
    )
    listing = admin.get("/api/v1/modules/catalog").json()
    assert listing[0]["id"] == MOD and listing[0]["latest_compatible"] == "0.3.0"

    r = admin.post("/api/v1/modules/catalog/install", json={"module_id": MOD, "version": "0.2.0"})
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "installed and enabled"
    detail = admin.get(f"/api/v1/modules/{MOD}").json()
    assert detail["installed_version"] == "0.2.0" and detail["trust_level"] == "official"
    assert admin.get("/api/v1/modules/catalog").json()[0]["update_available"] is True

    r = admin.post("/api/v1/modules/catalog/install", json={"module_id": MOD})
    assert (
        r.status_code == 200
        and r.json()["result"] == "updated from 0.2.0"
        and r.json()["restart_required"]
    )
    store = catalog.Store(app.state.settings.module_store_dir)
    assert store.previous(MOD)[1].module.version == "0.2.0"

    r = admin.post(f"/api/v1/modules/{MOD}/rollback")
    assert r.status_code == 200 and r.json()["version"] == "0.2.0"
    assert admin.get(f"/api/v1/modules/{MOD}").json()["installed_version"] == "0.2.0"

    # A version that changed the database cannot be rolled back automatically.
    pkg = _package(tmp_path, "0.4.0", pub_priv, "test-publisher", extra_migration=True)
    with pkg.open("rb") as f:
        r = admin.post("/api/v1/modules/upload", files={"file": (pkg.name, f, "application/gzip")})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "0.4.0"
    assert admin.post(f"/api/v1/modules/{MOD}/rollback").json()["code"] == "rollback_blocked"
    # An older version than installed is refused.
    old = root / f"{MOD}-0.3.0.vmod"
    with old.open("rb") as f:
        r = admin.post("/api/v1/modules/upload", files={"file": (old.name, f, "application/gzip")})
    assert r.status_code == 409 and "not newer" in r.json()["detail"]

    # Settings from the manifest's [[config]].
    cfg = admin.get(f"/api/v1/modules/{MOD}/config").json()
    assert (
        cfg["fields"][0]["key"] == "max_notes_per_organization"
        and cfg["values"]["max_notes_per_organization"] == 500
    )
    r = admin.put(
        f"/api/v1/modules/{MOD}/config", json={"values": {"max_notes_per_organization": 20000}}
    )
    assert r.status_code == 422
    r = admin.put(
        f"/api/v1/modules/{MOD}/config", json={"values": {"max_notes_per_organization": 42}}
    )
    assert r.status_code == 200 and r.json()["values"]["max_notes_per_organization"] == 42
    with session_scope() as db:
        assert db.query(ModuleConfig).one().config == {"max_notes_per_organization": 42}


def test_checksum_mismatch_and_bad_sources(admin, app, tmp_path, served):
    root, base, _, _ = _catalog(app, tmp_path, served, versions=("0.2.0",))
    admin.post(
        "/api/v1/modules/catalog-sources", json={"name": "Test", "url": f"{base}/index.json"}
    )
    pkg = root / f"{MOD}-0.2.0.vmod"
    pkg.write_bytes(pkg.read_bytes() + b"x")  # replaced on the server after signing
    r = admin.post("/api/v1/modules/catalog/install", json={"module_id": MOD})
    assert r.status_code == 502 and "checksum" in r.json()["detail"]
    r = admin.post(
        "/api/v1/modules/catalog-sources",
        json={"name": "Plain", "url": "http://example.org/index.json"},
    )
    assert r.status_code == 422
    (app.state.settings.trust_dir / "catalog" / "test-catalog.pub").unlink()
    r = admin.post(
        "/api/v1/modules/catalog-sources", json={"name": "Again", "url": f"{base}/index.json?x=1"}
    )
    assert r.json()["last_status"] == "failed" and "No catalog key" in r.json()["last_error"]


def test_restart_request(admin):
    assert admin.post("/api/v1/modules/restart-services").status_code == 202
    calls = []

    class Done:
        returncode = 0
        stderr = ""

    with session_scope() as db:
        assert catalog.run_restart_request(db, run=lambda cmd: calls.append(cmd) or Done())
    assert calls == [["systemctl", "restart", "--no-block", *catalog.VEYRA_UNITS]]
    with session_scope() as db:
        assert db.get(SystemSetting, catalog.RESTART_KEY) is None
        assert db.get(SystemSetting, catalog.RESTART_RESULT_KEY).value["ok"] is True
        assert catalog.run_restart_request(db, run=lambda cmd: Done()) is False  # nothing asked


def test_catalog_add_keeps_checksums_honest(tmp_path):
    priv, _ = generate_keypair()
    pkg = _package(tmp_path, "0.5.0", priv, "test-publisher")
    index = tmp_path / "index.json"
    assert (
        cli(
            [
                "catalog",
                "add",
                str(pkg),
                "--url",
                "https://example.org/p.vmod",
                "--index",
                str(index),
            ]
        )
        == 0
    )
    v = json.loads(index.read_text())["modules"][0]["versions"][0]
    assert (
        v["sha256"] == hashlib.sha256(Path(pkg).read_bytes()).hexdigest()
        and v["size"] == Path(pkg).stat().st_size
    )
