# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caller name lookup over HTTP (issue #392): off by default, platform
setting, lookup with cache and timeout, the internal endpoint for the
dialplan, and the dialplan lines of a route that asks for it."""

import json

import pytest
from test_api_routing import INBOUND, _ext, _org
from test_generator_routing import _files, _section, _snapshot

from veyra.core.db import session_scope
from veyra.telephony import caller_name as cn
from veyra.telephony.asterisk import generator

URL = "/api/v1/telephony/caller-name"
CFG = {
    "url": "http://127.0.0.1:8100/api/v1/internal/caller-name",
    "token": "abcdefghijklmnop1234",
    "timeout_seconds": 2,
}


def _route(**over):
    return {
        "did": "5735550100",
        "trunk": None,
        "destination": "1001",
        "after_hours": None,
        "time_condition": None,
        "caller_id_prefix": None,
        "organization": "o",
        **over,
    }


def test_dialplan_lookup_only_for_routes_that_ask():
    d = _files(_snapshot(inbound_routes=[_route()], caller_name=CFG))["extensions.conf"].content
    assert "CURL(" not in d
    d = _files(_snapshot(inbound_routes=[_route(name_lookup=True)], caller_name=CFG))[
        "extensions.conf"
    ].content
    entry = _section(d, "veyra-from-trunk")
    assert "Set(CURLOPT(httptimeout)=2)" in entry
    assert (
        "Set(VEYRA_CNAM=${CURL(http://127.0.0.1:8100/api/v1/internal/caller-name"
        "?token=abcdefghijklmnop1234&number=${URIENCODE(${CALLERID(num)})})})"
    ) in entry
    assert '"${CALLERID(name)}"!="${CALLERID(num)}"]?cnamdone)' in entry
    # Off at the installation: nothing, even for a route that asks.
    d = _files(_snapshot(inbound_routes=[_route(name_lookup=True)]))["extensions.conf"].content
    assert "CURL(" not in d
    with pytest.raises(generator.GenerationError, match="token"):
        generator.generate(
            _snapshot(inbound_routes=[_route(name_lookup=True)], caller_name={**CFG, "token": "x"})
        )


def test_lookup_parses_cleans_and_caches():
    cn.clear_cache()
    s = cn.CallerNameSettings(
        enabled=True, url="https://cnam.example/{number}", json_field="data.name"
    )
    calls = []

    def fetcher(url, headers, timeout):
        calls.append(url)
        return json.dumps({"data": {"name": 'ACME, "Schools":'}}).encode()

    assert cn.lookup(s, "+15735550100", now=0, fetcher=fetcher) == "ACME Schools"
    assert calls == ["https://cnam.example/%2B15735550100"]
    assert cn.lookup(s, "+15735550100", now=10, fetcher=fetcher) == "ACME Schools"
    assert len(calls) == 1  # cached
    assert cn.lookup(s, "anonymous", fetcher=fetcher) == ""

    def failing(url, headers, timeout):
        raise TimeoutError

    assert cn.lookup(s, "5735550111", fetcher=failing) == ""
    plain = s.model_copy(update={"json_field": None})
    cn.clear_cache()
    assert cn.lookup(plain, "5735550122", fetcher=lambda *a: b"Jane Doe\nmore") == "Jane Doe"


def test_settings_api_and_internal_endpoint(admin, app):
    assert admin.get(URL).json()["enabled"] is False
    r = admin.put(URL, json={"enabled": True, "url": "http://insecure.example/{number}"})
    assert r.status_code == 422
    r = admin.put(URL, json={"enabled": True, "url": "https://cnam.example/lookup"})
    assert r.status_code == 422  # no {number}
    r = admin.put(
        URL,
        json={
            "enabled": True,
            "url": "https://cnam.example/{number}",
            "header_name": "X-Api-Key",
            "header_value": "s3cret",
            "json_field": "name",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["has_header_value"] and "header_value" not in out
    with session_scope() as db:
        s = cn.load(db)
        assert s.token and s.header_value_ciphertext and "s3cret" not in s.header_value_ciphertext
    # The internal endpoint wants the token (the test client is not 127.0.0.1 either).
    r = admin.get("/api/v1/internal/caller-name", params={"number": "5735550100", "token": "x"})
    assert r.status_code == 403
    # A route can ask for it.
    org = _org(admin)
    ext = _ext(admin, org["id"], "1001")
    r = admin.post(
        INBOUND,
        json={
            "organization_id": org["id"],
            "did": "5735550188",
            "destination_extension_id": ext["id"],
            "name_lookup": True,
        },
    )
    assert r.status_code == 201 and r.json()["name_lookup"] is True
    from veyra.core.security.crypto import load_installation_key
    from veyra.telephony.snapshot import build_snapshot

    with session_scope() as db:
        snap = build_snapshot(db, load_installation_key(app.state.settings))
    assert snap["caller_name"]["token"] == s.token
    assert any(x.get("name_lookup") for x in snap["inbound_routes"])
