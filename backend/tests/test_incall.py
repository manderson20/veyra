# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-call codes (docs/CALL_FEATURES.md §4.11): features.conf, the Dial
options that allow DTMF transfers, and the on-demand recording toggle."""

import pytest
from test_generator_callflow import _context, _files, _snapshot

from veyra.telephony.asterisk import generator

CODES = {"record_toggle": "*1", "attended_transfer": "*2", "blind_transfer": "##"}


def test_features_conf_globals_and_recording_toggle():
    files = _files(_snapshot(feature_codes=CODES))
    fc = files["features.conf"]
    assert "blindxfer=##" in fc and "atxfer=*2" in fc
    assert 'veyra-record => *1,self/both,Gosub,"veyra-ondemand,s,1"' in fc
    dp = files["extensions.conf"]
    globals_ = _context(dp, "globals")
    assert "VEYRA_XFER=tT" in globals_ and "VEYRA_XFER_OUT=T" in globals_
    assert "DYNAMIC_FEATURES=veyra-record" in globals_
    assert "Dial(PJSIP/example-1001,30,${VEYRA_XFER})" in _context(dp, "veyra-internal")
    ondemand = _context(dp, "veyra-ondemand")
    assert "MixMonitor(/var/lib/veyra/recordings/incoming/${VEYRA_CALLREC}--" in ondemand
    assert "00000000-0000-0000-0000-000000000000.wav,b)" in ondemand
    assert "StopMixMonitor()" in ondemand and "Set(CDR(veyra_rec)=${VEYRA_CALLREC})" in ondemand
    assert generator.reload_scopes(["features.conf"]) == ["features"]
    assert generator.validate(generator.generate(_snapshot(feature_codes=CODES))) == []


def test_without_the_codes_nothing_is_enabled():
    files = _files(_snapshot(feature_codes={}))
    fc = files["features.conf"]
    assert "blindxfer=" not in fc and "atxfer=" not in fc and "veyra-record" not in fc
    dp = files["extensions.conf"]
    globals_ = _context(dp, "globals")
    assert "VEYRA_XFER=\n" in globals_ and "DYNAMIC_FEATURES=\n" in globals_
    assert "[veyra-ondemand]" not in dp


def test_transfer_only_keeps_recording_off():
    files = _files(_snapshot(feature_codes={"blind_transfer": "##"}))
    assert "VEYRA_XFER=tT" in files["extensions.conf"]
    assert "DYNAMIC_FEATURES=\n" in files["extensions.conf"]
    assert "atxfer=" not in files["features.conf"] and "blindxfer=##" in files["features.conf"]


def test_features_reload_uses_module_reload_and_sees_console_errors(monkeypatch, tmp_path):
    """Asterisk 22 has no "features reload" console command; the adapter runs
    "module reload features", and a rejected command (exit 0, "No such
    command") counts as a failure instead of a silent no-op (found live on
    0.25.0: the in-call codes never reached the engine)."""
    import subprocess

    from veyra.telephony.adapter import EngineUnavailable
    from veyra.telephony.asterisk import cli
    from veyra.telephony.asterisk.adapter import AsteriskAdapter

    class Proc:
        def __init__(self, out):
            self.returncode, self.stdout, self.stderr = 0, out, ""

    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/sbin/asterisk")
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: Proc("No such command 'features reload' (type ...)")
    )
    ok, out = cli.run("features reload")
    assert not ok and "No such command" in out

    ran = []
    monkeypatch.setattr(
        cli,
        "run",
        lambda command, timeout=10.0: (
            ran.append(command) or (True, "Module 'features' reloaded successfully.")
        ),
    )
    adapter = AsteriskAdapter("http://127.0.0.1:8088/ari", "veyra", tmp_path / "ari.pw")
    adapter.reload("features")
    assert ran == ["module reload features"]
    monkeypatch.setattr(cli, "run", lambda command, timeout=10.0: (False, "No such command"))
    with pytest.raises(EngineUnavailable):
        adapter.reload("features")
