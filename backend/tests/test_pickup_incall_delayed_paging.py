# SPDX-License-Identifier: AGPL-3.0-or-later
"""Grandstream features of issue #392: Pickup In-call (take over another
phone's answered call, only for the extensions it lists) and delayed paging
(record, then page after the zone's delay)."""

from pathlib import Path

from test_api_ivr import _ext, _org
from test_features import _section, _snapshot

from veyra.cli.main import clean_delayed_pages
from veyra.telephony.asterisk import generator

CODES = {"pickup_incall": "*51", "delayed_page": "*59"}


def _dp(**over):
    snap = _snapshot(feature_codes=CODES, **over)
    return {f.path: f.content for f in generator.generate(snap)}["extensions.conf"]


def _two_phones(by):
    first = _snapshot()["extensions"][0]
    return [
        {**first, "pickup_incall_by": by},
        {**first, "endpoint_name": "example-1002", "number": "1002", "display_name": "Nurse"},
    ]


def test_pickup_incall_only_for_listed_extensions():
    assert "*511001" not in _dp(extensions=_two_phones([]))
    calls = _section(_dp(extensions=_two_phones(["1002"])), "veyra-call-codes")
    entry = calls.split("exten => *511001,1,")[1].split("exten => ")[0]
    assert '${REGEX("^(1002)$" ${VEYRA_EXT})}?ok:denied)' in entry
    assert "CHANNELS(^PJSIP/example\\-1001\\-[0-9a-f]{8}$)" in entry
    # "PJSIP/example-1001-" is 19 characters, plus 8 hex digits.
    assert "Set(VEYRA_C=${VEYRA_CHANS:0:27})" in entry
    assert "Set(VEYRA_C=${VEYRA_CHANS:28:27})" in entry
    assert "?Set(VEYRA_PEER=${IMPORT(${VEYRA_C},BRIDGEPEER)}))" in entry
    assert '"${VEYRA_PEER:0:19}"="PJSIP/example-1001-"]?none)' in entry
    assert " same => n,Bridge(${VEYRA_PEER})" in entry
    # No code, nothing written.
    snap = _snapshot(feature_codes={}, extensions=_two_phones(["1002"]))
    d = {f.path: f.content for f in generator.generate(snap)}["extensions.conf"]
    assert "pickup in-call" not in d


def _zone(**over):
    return {
        "slug": "all",
        "name": "All",
        "organization": "example",
        "number": "9001",
        "multicast_address": "239.0.0.1",
        "multicast_port": 5004,
        "port": 5004,
        "poly_address": "224.0.1.116",
        "poly_port": 5001,
        "poly_group": 1,
        "kind": "normal",
        "max_seconds": 60,
        **over,
    }


def test_delayed_paging_records_then_pages_after_the_delay():
    assert "*599001" not in _dp(paging={"zones": [_zone()]})
    d = _dp(paging={"zones": [_zone(delayed_seconds=10)]})
    paging = _section(d, "veyra-paging")
    entry = paging.split("exten => *599001,1,")[1].split("exten => ")[0]
    assert "Set(VEYRA_DFILE=/var/lib/veyra/paging-delayed/${UNIQUEID})" in entry
    assert "Set(VEYRA_DSEND=zone-all)" in entry
    assert "Record(${VEYRA_DFILE}.wav,0,60,k)" in entry
    assert "Gosub(veyra-delayed-send,1)" in entry
    # Hanging up while recording also sends it.
    assert 'exten => h,1,ExecIf($["${VEYRA_DSEND}"!=""]?Gosub(veyra-delayed-send,1))' in paging
    assert (
        "Originate(Local/dplay-${VEYRA_DSEND}@veyra-page-play/n,exten,veyra-page-play,"
        "dpage-${VEYRA_DSEND},1,${VEYRA_DTIMEOUT},av(__VEYRA_DFILE=${VEYRA_DFILE}))"
    ) in paging
    play = _section(d, "veyra-page-play")
    assert "exten => dpage-zone-all,1," in play
    dplay = play.split("exten => dplay-zone-all,1,")[1]
    assert "Wait(10)" in dplay
    assert "GROUP_COUNT(zone-all@veyra_dpage)" in dplay
    assert "Playback(${VEYRA_DFILE})" in dplay


def test_old_delayed_recordings_are_removed(tmp_path: Path):
    import os

    old, new = tmp_path / "old.wav", tmp_path / "new.wav"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    os.utime(old, (1000, 1000))
    os.utime(new, (9000, 9000))
    assert clean_delayed_pages(tmp_path, now=9000) == 1
    assert not old.exists() and new.exists()
    assert clean_delayed_pages(tmp_path / "missing") == 0


# ----------------------------------------------------------------- API


def test_api_pickup_incall_list(admin, app):
    org = _org(admin)
    a = _ext(admin, org["id"], "3101")
    b = _ext(admin, org["id"], "3102")
    url = f"/api/v1/extensions/{a['id']}"
    r = admin.patch(url, json={"pickup_incall_ids": [b["id"]]})
    assert r.status_code == 200, r.text
    assert r.json()["pickup_incall_ids"] == [b["id"]]
    r = admin.patch(url, json={"pickup_incall_ids": [a["id"]]})
    assert r.status_code == 422, r.text
    r = admin.patch(url, json={"pickup_incall_ids": ["00000000-0000-0000-0000-000000000001"]})
    assert r.status_code == 422, r.text
    r = admin.patch(url, json={"pickup_incall_ids": []})
    assert r.status_code == 200 and r.json()["pickup_incall_ids"] == []


def test_api_delayed_seconds_on_zones_and_pages(admin, app):
    from test_api_paging import PAGES, ZONES
    from test_api_paging import _zone as make_zone

    org = _org(admin)
    zone = make_zone(admin, org["id"], "Hall", 7, number="7101", delayed_seconds=5)
    assert zone["delayed_seconds"] == 5
    r = admin.patch(f"{ZONES}/{zone['id']}", json={"delayed_seconds": None})
    assert r.status_code == 200 and r.json()["delayed_seconds"] is None
    r = admin.patch(f"{ZONES}/{zone['id']}", json={"delayed_seconds": 900})
    assert r.status_code == 422
    r = admin.post(
        PAGES,
        json={
            "organization_id": org["id"],
            "name": "Office",
            "number": "7102",
            "zones": [zone["id"]],
            "delayed_seconds": 15,
        },
    )
    assert r.status_code == 201, r.text
    page = r.json()
    assert page["delayed_seconds"] == 15
    r = admin.patch(f"{PAGES}/{page['id']}", json={"delayed_seconds": None})
    assert r.status_code == 200 and r.json()["delayed_seconds"] is None
