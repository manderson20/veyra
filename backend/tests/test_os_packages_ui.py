# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operating system packages from the Updates page (docs/SOFTWARE_UPDATES.md
§6): the root unit is started per mode, its status is read back, and the
upgradable list is read again once a run has finished."""

from __future__ import annotations

from types import SimpleNamespace


def _done(stdout: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def test_package_runs_start_the_unit_and_refresh_the_list(admin, app, tmp_path):
    calls: list[list[str]] = []
    app.state.systemctl_run = lambda cmd: calls.append(cmd) or _done()
    app.state.os_packages_dir = str(tmp_path)
    listing = (
        "Listing...\n"
        "openssl/noble-security 3.0.13-0ubuntu3.6 amd64 [upgradable from: 3.0.13-0ubuntu3.5]\n"
    )
    app.state.apt_run = lambda cmd: _done(listing)

    assert admin.post("/api/v1/updates/system-packages/dist-upgrade", json={}).status_code == 404
    r = admin.post("/api/v1/updates/system-packages/security", json={})
    assert r.status_code == 202, r.text
    assert calls[-1] == ["systemctl", "start", "--no-block", "veyra-os-packages@security.service"]

    # Running: a second start is refused.
    (tmp_path / "started").write_text("2099-01-01T00:00:00Z\n")
    (tmp_path / "mode").write_text("security\n")
    (tmp_path / "last.log").write_text("Upgrading: openssl\n")
    assert admin.post("/api/v1/updates/system-packages/all", json={}).status_code == 409
    run = admin.get("/api/v1/updates/system-packages").json()["run"]
    assert run["running"] and run["mode"] == "security"

    # Finished, with a reboot wanted: the list is read again at once.
    (tmp_path / "exit").write_text("0\n")
    (tmp_path / "finished").write_text("2099-01-01T00:05:00Z\n")
    (tmp_path / "reboot").write_text("linux-image-6.8.0-50-generic\n")
    out = admin.get("/api/v1/updates/system-packages").json()
    assert out["run"]["ok"] and out["run"]["reboot_required"]
    assert out["run"]["reboot_packages"] == ["linux-image-6.8.0-50-generic"]
    assert out["counts"] == {"total": 1, "security": 1, "telephony": 0}

    events = admin.get("/api/v1/audit", params={"action": "updates.system_packages"}).json()
    assert events["items"][0]["target_id"] == "security"


def test_a_missing_unit_is_reported(admin, app, tmp_path):
    app.state.systemctl_run = lambda cmd: SimpleNamespace(
        returncode=5, stdout="", stderr="Unit veyra-os-packages@refresh.service not found."
    )
    app.state.os_packages_dir = str(tmp_path)
    r = admin.post("/api/v1/updates/system-packages/refresh", json={})
    assert r.status_code == 503 and "not found" in r.json()["detail"]
