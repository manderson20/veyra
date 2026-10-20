# SPDX-License-Identifier: AGPL-3.0-or-later
"""Installation key rotation from the interface (issue #125): the root unit
is started through systemctl, its status files are read back, a second
start is refused while one runs, and it is audited."""


def test_rotate_from_the_interface(admin, app, tmp_path):
    calls = []

    class Done:
        returncode = 0
        stderr = ""

    app.state.systemctl_run = lambda cmd: calls.append(cmd) or Done()
    app.state.key_rotate_dir = str(tmp_path)
    info = admin.get("/api/v1/system/installation-key").json()
    assert info["fingerprint"] and info["rotation"] is None
    r = admin.post("/api/v1/system/installation-key/rotate")
    assert r.status_code == 202, r.text
    assert calls == [["systemctl", "start", "--no-block", "veyra-key-rotate.service"]]
    # The unit is running: started, no exit yet.
    (tmp_path / "started").write_text("2026-10-20T10:00:00Z\n")
    assert admin.get("/api/v1/system/installation-key").json()["rotation"]["running"] is True
    assert admin.post("/api/v1/system/installation-key/rotate").status_code == 409
    (tmp_path / "exit").write_text("0\n")
    (tmp_path / "finished").write_text("2026-10-20T10:00:09Z\n")
    (tmp_path / "last.log").write_text('{"rotated": 12}\nInstallation key rotated\n')
    rot = admin.get("/api/v1/system/installation-key").json()["rotation"]
    assert rot["ok"] and not rot["running"] and "rotated" in rot["output"]
    events = admin.get("/api/v1/audit", params={"q": "installation_key_rotate"}).json()
    assert events["total"] == 1
