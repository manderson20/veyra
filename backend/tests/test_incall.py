# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-call codes (docs/CALL_FEATURES.md §4.11): features.conf, the Dial
options that allow DTMF transfers, and the on-demand recording toggle."""

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
