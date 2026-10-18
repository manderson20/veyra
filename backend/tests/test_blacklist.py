# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caller block list (docs/CALL_FEATURES.md §4.8): numbers and policy through
the API, phone events, the worker's sync and the generated dialplan."""

import pytest
from fake_adapter import FakeAdapter
from test_api_ivr import _ext, _org
from test_generator_callflow import _context, _files, _snapshot

from veyra.core.db import session_scope
from veyra.telephony import blacklist
from veyra.telephony.asterisk import generator

BLOCKS = "/api/v1/caller-blocks"
INBOUND = "/api/v1/routing/inbound"


def _fake(app):
    adapter = FakeAdapter(prompts_dir=app.state.settings.prompts_dir)
    app.state.telephony = adapter
    return adapter


def test_normalize():
    assert blacklist.normalize("(573) 555-1234") == "5735551234"
    assert blacklist.normalize("+1 573 555 1234") == "+15735551234"
    for bad in ("", "abc", "1", "+", "573-555-12x4"):
        with pytest.raises(blacklist.BlockError):
            blacklist.normalize(bad)


def test_block_list_api_import_export_and_policy(admin, app):
    adapter = _fake(app)
    org = _org(admin)
    ext = _ext(admin, org["id"], "5001")
    r = admin.post(
        BLOCKS,
        json={"organization_id": org["id"], "number": "573-555-0001", "description": "Robocaller"},
    )
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["number"] == "5735550001" and b["source"] == "api" and b["hits"] == 0
    # The engine's store was written at once.
    assert adapter.store[f"veyra/blacklist/{org['slug']}"] == {"5735550001": "1"}
    assert (
        admin.post(BLOCKS, json={"organization_id": org["id"], "number": "5735550001"}).status_code
        == 409
    )
    assert (
        admin.post(BLOCKS, json={"organization_id": org["id"], "number": "nope"}).status_code == 422
    )
    # Import: header skipped, bad lines reported, existing numbers updated.
    r = admin.post(
        f"{BLOCKS}/import",
        json={
            "organization_id": org["id"],
            "text": (
                "number,description\n5735550002,Spam\n5735550001,Known robocaller\n"
                "bogus\n8005550003\n"
            ),
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"added": 2, "updated": 1, "skipped": ["bogus"]}
    assert admin.get(BLOCKS, params={"organization_id": org["id"]}).json()["total"] == 3
    assert (
        admin.get(BLOCKS, params={"q": "Known"}).json()["items"][0]["description"]
        == "Known robocaller"
    )
    r = admin.get(f"{BLOCKS}/export", params={"organization_id": org["id"]})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "5735550002,Spam,0,,csv" in r.text and r.text.startswith("number,description,hits")
    # Policy: default, then anonymous blocking with a destination (marks a deployment).
    p = admin.get(f"{BLOCKS}/policy", params={"organization_id": org["id"]}).json()
    assert (
        not p["block_anonymous"]
        and p["destination"]["type"] == "hangup"
        and p["blocked_numbers"] == 3
    )
    r = admin.put(
        f"{BLOCKS}/policy",
        json={
            "organization_id": org["id"],
            "block_anonymous": True,
            "destination": {"type": "extension", "extension_id": ext["id"]},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["block_anonymous"] and r.json()["destination"]["label"].startswith("5001")
    # Unblock: the store entry goes too.
    assert admin.delete(f"{BLOCKS}/{b['id']}").status_code == 204
    assert "5735550001" not in adapter.store[f"veyra/blacklist/{org['slug']}"]
    assert admin.get(BLOCKS, params={"organization_id": org["id"]}).json()["total"] == 2


def test_phone_events_and_sync(admin, app):
    adapter = _fake(app)
    org = _org(admin)
    slug = org["slug"]
    with session_scope() as db:
        # A phone added a number: the row appears (the dialplan wrote the store).
        assert blacklist.handle_blacklist_event(
            db, {"Action": "add", "Org": slug, "Number": "5735550009", "By": "5001"}
        )
        # Adding again is not a change.
        assert not blacklist.handle_blacklist_event(
            db, {"Action": "add", "Org": slug, "Number": "5735550009"}
        )
    rows = admin.get(BLOCKS, params={"q": "5735550009"}).json()["items"]
    assert rows[0]["source"] == "phone" and "5001" in rows[0]["description"]
    with session_scope() as db:
        # Blocked calls are counted on the number, anonymous ones on the policy.
        assert blacklist.handle_blocked_event(
            db, {"Org": slug, "Number": "5735550009", "Did": "5735550100"}
        )
        assert blacklist.handle_blocked_event(
            db, {"Org": slug, "Number": "anonymous", "Did": "5735550100"}
        )
    rows = admin.get(BLOCKS, params={"q": "5735550009"}).json()["items"]
    assert rows[0]["hits"] == 1 and rows[0]["last_hit_at"]
    policy = admin.get(f"{BLOCKS}/policy", params={"organization_id": org["id"]}).json()
    assert policy["anonymous_hits"] == 1
    with session_scope() as db:
        # Sync: a missing store entry is added, a stray one removed.
        adapter.store[f"veyra/blacklist/{slug}"] = {"1112223333": "1"}
        assert blacklist.sync(db, adapter) == 2
        assert adapter.store[f"veyra/blacklist/{slug}"] == {"5735550009": "1"}
        assert blacklist.handle_blacklist_event(
            db, {"Action": "remove", "Org": slug, "Number": "5735550009"}
        )
        assert blacklist.sync(db, adapter) == 1
        assert adapter.store[f"veyra/blacklist/{slug}"] == {}
        assert not blacklist.handle_blacklist_event(
            db, {"Action": "add", "Org": "nope", "Number": "5735550009"}
        )


def test_generated_dialplan_checks_the_store_and_offers_the_codes():
    route = {
        "did": "5735550100",
        "trunk": None,
        "destination": {"type": "extension", "number": "1001"},
        "after_hours": None,
        "time_condition": None,
        "caller_id_prefix": None,
        "organization": "x",
        "organization_slug": "example",
    }
    codes = {"blacklist_add": "*30", "blacklist_remove": "*31", "blacklist_last": "*32"}
    dp = _files(
        _snapshot(
            inbound_routes=[route],
            caller_block_policies=[
                {
                    "organization": "example",
                    "block_anonymous": True,
                    "destination": {"type": "directory"},
                }
            ],
            feature_codes=codes,
        )
    )["extensions.conf"]
    body = dp.split("exten => 5735550100,1,")[1].split("\nexten =>")[0]
    assert "GotoIf(${DB_EXISTS(veyra/blacklist/example/${VEYRA_CID})}?blocked)" in body
    assert '"${TOLOWER(${VEYRA_CID})}"="anonymous"' in body and "prohib" in body
    assert "UserEvent(VeyraBlocked,Org: example,Number: ${VEYRA_CID},Did: ${VEYRA_DID})" in body
    assert "Goto(veyra-directory,s,1)" in body.split("(blocked)")[1]
    assert body.index("DB_EXISTS") < body.index("Goto(veyra-internal,1001,1)")
    features = _context(dp, "veyra-features")
    assert "Read(VEYRA_NUM,enter-num-blacklist,32,,1,10)" in features
    assert "Set(DB(veyra/blacklist/${VEYRA_ORG}/${VEYRA_NUM})=1)" in features
    assert "DB_DELETE(veyra/blacklist/${VEYRA_ORG}/${VEYRA_NUM})" in features
    assert "DB(veyra/lastcid/${VEYRA_ORG}/${VEYRA_EXT})" in features
    internal = _context(dp, "veyra-internal")
    assert "Set(DB(veyra/lastcid/example/1001)=${CALLERID(num)})" in internal
    # Without a policy: no anonymous rule, the "no service" tail; without
    # codes: no feature code blocks.
    dp2 = _files(_snapshot(inbound_routes=[route]))["extensions.conf"]
    body2 = dp2.split("exten => 5735550100,1,")[1].split("\nexten =>")[0]
    assert "anonymous" not in body2 and "Playback(ss-noservice)" in body2
    assert "enter-num-blacklist" not in dp2
    assert generator.validate(generator.generate(_snapshot(inbound_routes=[route]))) == []
