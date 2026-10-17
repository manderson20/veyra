# SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: E501 — engine output fixtures are long lines by nature
"""Where phones register from (docs/CALL_FEATURES.md §2.1): contact parsing
and the registrations API."""

from conftest import ADMIN_PASSWORD, login
from fake_adapter import FakeAdapter
from test_api_rbac import make_org, make_user

from veyra.telephony.adapter import Registration
from veyra.telephony.asterisk import contacts

DB_OUTPUT = """
/registrar/contact/example-1001;@2f3a9c0d1e5b7a8c : {"uri":"sip:example-1001@192.168.10.20:5060;transport=tls","expiration_time":"1792188000","qualify_frequency":"60","outbound_proxy":"","path":"","qualify_timeout":"3.000000","call_id":"abc@192.168.10.20","endpoint":"example-1001","prune_on_boot":"no","via_addr":"203.0.113.7","via_port":"41234","user_agent":"PolycomVVX-VVX_411-UA/6.4.3","reg_server":"veyra-dev1","authenticate_qualify":"no"}
/registrar/contact/example-1002;@0a0b0c0d0e0f1011 : {"uri":"sip:example-1002@[fd00::20]:5061;ob","expiration_time":"1792188060.123456","endpoint":"example-1002","via_addr":"fd00::20","via_port":"5061","user_agent":"Yealink SIP-T46U 108.86.0.45"}
/registrar/contact/broken;@ffff : not json
/registrar/contact/example-1004;@fec70f3d2636c1cc760df46db8ee9c25: {"via_addr":"192.168.77.10","qualify_timeout":"3.000000","qualify_2xx_only":"false","call_id":"288567362@192.168.77.10","reg_server":"","prune_on_boot":"no","path":"","endpoint":"example-1004","via_port":"5060","authenticate_qualify":"no","uri":"sip:example-1004@203.0.113.9:36821;x-ast-orig-host=192.168.77.10:5060","qualify_frequency":"60","user_agent":"VeyraTestPhone/0.1","expiration_time":"1792278523","outbound_proxy":""}
4 results found.
"""

LISTING = """
  Contact:  <Aor/ContactUri................................................> <Hash....> <Status> <RTT(ms)..>
==========================================================================================================

  Contact:  example-1001/sip:example-1001@192.168.10.20:5060;transport=tls 2f3a9c0d1e Avail        12.345
  Contact:  example-1002/sip:example-1002@[fd00::20]:5061;ob             0a0b0c0d0e NonQual         nan
  Contact:  example-1003/sip:example-1003@10.0.0.3:5060                    1111111111 Unavail         nan
  Contact:  example-1004/sip:exa fec70f3d26 Avail        -nan

Objects found: 4
"""

# A listing whose column is exactly as wide as the longest row (the live shape).
LISTING_TRUNCATED = """
  Contact:  <Aor/ContactUri....> <Hash....> <Status> <RTT(ms)..>
=================================================================

  Contact:  example-1004/sip:exa fec70f3d26 Unavail        -nan
  Contact:  example-1005/sip:exa 1111111111 Avail         3.1

Objects found: 2
"""


def test_parse_uri_variants():
    assert contacts.parse_uri("sip:u@192.168.1.5:5060;transport=tls") == (
        "192.168.1.5",
        5060,
        "tls",
    )
    assert contacts.parse_uri("<sips:u@phone.example:5061>") == ("phone.example", 5061, "tls")
    assert contacts.parse_uri("sip:u@[fd00::20]:5061;ob") == ("fd00::20", 5061, None)
    assert contacts.parse_uri("sip:u@10.0.0.3") == ("10.0.0.3", None, None)
    assert contacts.parse_uri("garbage") == ("garbage", None, None)


def test_addresses_with_and_without_rewrite_contact():
    # rewrite_contact=yes: URI host = source, x-ast-orig-host = the phone's own address.
    assert contacts.addresses(
        "sip:u@203.0.113.9:36821;x-ast-orig-host=192.168.77.10:5060", "192.168.77.10", "5060"
    ) == ("192.168.77.10", 5060, "203.0.113.9", 36821, None)
    assert contacts.addresses(
        "sip:u@[2001:db8::9]:5061;x-ast-orig-host=[fd00::20]:5060;transport=tls"
    ) == ("fd00::20", 5060, "2001:db8::9", 5061, "tls")
    # Without it, the URI is the phone's own address and Via is the best source we have.
    assert contacts.addresses("sip:u@192.168.1.5:5060", "203.0.113.7", "41234") == (
        "192.168.1.5",
        5060,
        "203.0.113.7",
        41234,
        None,
    )
    assert contacts.addresses("sip:u@192.168.1.5:5060") == ("192.168.1.5", 5060, None, None, None)


def test_parse_and_merge_contact_store_with_listing():
    db = contacts.parse_database(DB_OUTPUT)
    assert set(db) == {
        "sip:example-1001@192.168.10.20:5060;transport=tls",
        "sip:example-1002@[fd00::20]:5061;ob",
        "sip:example-1004@203.0.113.9:36821;x-ast-orig-host=192.168.77.10:5060",
    }
    assert db["sip:example-1004@203.0.113.9:36821;x-ast-orig-host=192.168.77.10:5060"]["hash"] == (
        "fec70f3d2636c1cc760df46db8ee9c25"
    )
    listing = contacts.parse_contacts(LISTING)
    assert listing["1111111111"]["status"] == "Unavail" and listing["1111111111"]["rtt_ms"] is None
    assert listing["1111111111"]["uri"] == "sip:example-1003@10.0.0.3:5060"
    assert listing["fec70f3d26"]["rtt_ms"] is None  # "-nan"
    rows = contacts.merge(db, listing)
    by = {r.endpoint: r for r in rows}
    assert set(by) == {"example-1001", "example-1002", "example-1003", "example-1004"}
    # The live shape: rewritten contact, truncated listing row joined by hash prefix.
    d = by["example-1004"]
    assert (d.contact_host, d.contact_port) == ("192.168.77.10", 5060)
    assert (d.source_host, d.source_port) == ("203.0.113.9", 36821)
    assert d.nat is True and d.status == "Avail" and d.rtt_ms is None
    assert d.user_agent == "VeyraTestPhone/0.1" and d.reg_server is None
    assert d.expires_at == "2026-10-17T23:08:43Z"
    a = by["example-1001"]
    assert (a.contact_host, a.contact_port, a.transport) == ("192.168.10.20", 5060, "tls")
    assert (a.source_host, a.source_port) == ("203.0.113.7", 41234)
    assert a.nat is True and a.status == "Avail" and a.rtt_ms == 12.345
    assert a.user_agent.startswith("PolycomVVX") and a.expires_at == "2026-10-16T22:00:00Z"
    b = by["example-1002"]
    assert b.nat is False and b.status == "NonQual" and b.rtt_ms is None
    assert b.expires_at == "2026-10-16T22:01:00Z"
    # Listed but no longer in the store: addresses from the URI, nothing invented.
    c = by["example-1003"]
    assert c.contact_host == "10.0.0.3" and c.source_host is None and c.user_agent is None


def test_truncated_listing_rows_invent_no_addresses():
    listing = contacts.parse_contacts(LISTING_TRUNCATED)
    assert listing["fec70f3d26"]["truncated"] is True
    assert listing["1111111111"]["rtt_ms"] == 3.1
    rows = contacts.merge({}, listing)
    by = {r.endpoint: r for r in rows}
    assert set(by) == {"example-1004", "example-1005"}
    assert by["example-1004"].contact_host is None and by["example-1004"].status == "Unavail"
    assert by["example-1005"].contact_host is None and by["example-1005"].rtt_ms == 3.1
    # The store fills the addresses in once the contact is known there.
    db = contacts.parse_database(DB_OUTPUT)
    rows = contacts.merge(db, listing)
    d = next(r for r in rows if r.endpoint == "example-1004")
    assert (d.source_host, d.contact_host, d.status) == ("203.0.113.9", "192.168.77.10", "Unavail")


def test_registrations_api_scoped_and_searchable(admin, app, client):
    adapter = FakeAdapter()
    app.state.telephony = adapter
    org = admin.get("/api/v1/organizations").json()["items"][0]
    ext = admin.post(
        "/api/v1/extensions",
        json={"organization_id": org["id"], "number": "1001", "display_name": "Front Office"},
    ).json()
    endpoint = ext["endpoint_name"]
    adapter.contacts = [
        Registration(
            endpoint=endpoint,
            uri=f"sip:{endpoint}@192.168.10.20:5060",
            contact_host="192.168.10.20",
            contact_port=5060,
            source_host="203.0.113.7",
            source_port=41234,
            transport="udp",
            user_agent="PolycomVVX-VVX_411-UA/6.4.3",
            status="Avail",
            rtt_ms=9.0,
        ),
        Registration(endpoint="stray", uri="sip:stray@10.9.9.9:5060", contact_host="10.9.9.9"),
    ]
    adapter.endpoints[0] = type(adapter.endpoints[0])(endpoint, True)
    r = admin.get("/api/v1/telephony/registrations").json()
    assert r["available"] is True
    names = [x["endpoint"] for x in r["registrations"]]
    assert names == [endpoint, "stray"]  # platform admin sees the stray contact too
    row = r["registrations"][0]
    assert row["extension_number"] == "1001" and row["organization_name"] == org["name"]
    assert row["source_host"] == "203.0.113.7" and row["nat"] is True
    assert (
        admin.get("/api/v1/telephony/registrations", params={"q": "polycom"}).json()[
            "registrations"
        ][0]["endpoint"]
        == endpoint
    )
    assert (
        admin.get("/api/v1/telephony/registrations", params={"q": "nothing"}).json()[
            "registrations"
        ]
        == []
    )
    # The extension list carries the same contact.
    listed = admin.get("/api/v1/extensions").json()["items"]
    mine = next(x for x in listed if x["id"] == ext["id"])
    assert mine["registration"]["registered"] is True
    assert mine["registration"]["contacts"][0]["source_host"] == "203.0.113.7"
    assert mine["registration"]["contacts"][0]["nat"] is True
    # An organization administrator does not see contacts outside their organizations.
    other = make_org(admin, "other")
    make_user(admin, "orgadmin@other.local", other, "org_admin")
    oa = login(client, "orgadmin@other.local", ADMIN_PASSWORD)
    r = oa.get("/api/v1/telephony/registrations").json()
    assert r["available"] is True and r["registrations"] == []


def test_registrations_api_without_engine(admin):
    r = admin.get("/api/v1/telephony/registrations").json()
    assert r["available"] is False and r["registrations"] == []
