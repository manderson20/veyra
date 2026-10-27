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


def test_maintenance_windows_run_packages_once_and_asterisk_only_without_calls(
    admin, app, tmp_path
):
    from datetime import UTC, datetime

    from veyra.core.db import session_scope
    from veyra.core.models import SystemSetting
    from veyra.updates import manager

    window = {
        "days": ["sun"],
        "start": "02:00",
        "duration_minutes": 180,
        "timezone": "America/Chicago",
    }
    base = {"channel": "stable", "check_enabled": True, "check_interval_hours": 24}
    # Download-and-approve does not apply to packages; automatic in a window does.
    bad = admin.put(
        "/api/v1/updates/policies/operating_system", json={**base, "mode": "download_approve"}
    )
    assert bad.status_code == 422
    for component, cats in (
        ("operating_system", ["security", "bugfix"]),
        ("telephony_engine", ["security"]),
    ):
        r = admin.put(
            f"/api/v1/updates/policies/{component}",
            json={
                **base,
                "mode": "auto_install_window",
                "auto_install_categories": cats,
                "maintenance_window": window,
            },
        )
        assert r.status_code == 200, r.text

    calls: list[list[str]] = []
    run = lambda cmd: calls.append(cmd) or _done()  # noqa: E731
    sunday = datetime(2026, 11, 1, 8, 30, tzinfo=UTC)  # 02:30 Chicago
    monday = datetime(2026, 11, 2, 8, 30, tzinfo=UTC)
    busy = {"n": 1}
    with session_scope() as db:
        settings = app.state.settings
        go = lambda now: manager.process_os_packages(  # noqa: E731
            db, settings, now, lambda: busy["n"], run=run, directory=str(tmp_path)
        )
        assert go(monday) is None and calls == []
        # The operating system first (everything but Asterisk) ...
        assert go(sunday) == "all"
        assert calls[-1][-1] == "veyra-os-packages@all.service"
        # ... while it runs, nothing else starts.
        (tmp_path / "started").write_text("2026-11-01T08:30:05Z\n")
        (tmp_path / "mode").write_text("all\n")
        assert go(sunday) is None
        (tmp_path / "exit").write_text("0\n")
        (tmp_path / "finished").write_text("2026-11-01T08:40:00Z\n")
        (tmp_path / "reboot").write_text("linux-image-generic\n")
        # Asterisk waits while a call is up, then goes.
        assert go(sunday) is None
        busy["n"] = 0
        assert go(sunday) == "telephony"
        assert calls[-1][-1] == "veyra-os-packages@telephony.service"
        # Once per window.
        (tmp_path / "started").write_text("2026-11-01T08:45:00Z\n")
        assert go(sunday) is None and len(calls) == 2
        state = db.get(SystemSetting, manager.OS_AUTO_KEY).value
        assert state["operating_system"] == state["telephony_engine"] == "2026-11-01T02:00:00-06:00"
    events = admin.get("/api/v1/audit", params={"action": "updates.system_packages"}).json()
    assert {
        e["target_id"] for e in events["items"] if e["action"] == "updates.system_packages"
    } == {"all", "telephony"}


def test_security_only_and_unknown_call_count():
    from veyra.core.models import UpdatePolicy
    from veyra.updates import manager

    p = UpdatePolicy(
        component="operating_system",
        mode="auto_install_window",
        auto_install_categories=["security"],
        maintenance_window={"days": ["sun"], "start": "02:00", "duration_minutes": 60},
    )
    assert manager.os_auto_mode("operating_system", p) == "security"
    p.mode = "notify"
    assert manager.os_auto_mode("operating_system", p) is None
