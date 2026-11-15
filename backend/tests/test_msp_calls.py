# SPDX-License-Identifier: AGPL-3.0-or-later
"""Active calls between organizations with the same numbers
(docs/MULTI_TENANCY_MSP.md §2): a channel belongs to an organization by its
phone, by the phone it is bridged with, or by VEYRA_ORG; never by caller
number."""

from conftest import org_user, two_organizations
from fake_adapter import FakeAdapter

from veyra.telephony.adapter import ActiveCall
from veyra.telephony.asterisk.adapter import AsteriskAdapter

CALLS = "/api/v1/calls"


def _setup(admin, app):
    adapter = FakeAdapter()
    app.state.telephony = adapter
    a, b = two_organizations(admin)
    ea, eb = a.extensions, b.extensions
    adapter.calls = [
        # A's 1001 calls A's 1002; B's 1001 calls B's 1002: the same numbers.
        ActiveCall("a1", "1001", "1002", "Up", 30, endpoint=ea["1001"]["endpoint_name"]),
        ActiveCall("a2", "1001", "1002", "Up", 30, endpoint=ea["1002"]["endpoint_name"]),
        ActiveCall("b1", "1001", "1002", "Up", 20, endpoint=eb["1001"]["endpoint_name"]),
        ActiveCall("b2", "1001", "1002", "Up", 20, endpoint=eb["1002"]["endpoint_name"]),
        # B's outside call: the trunk leg shows B's 1001 as the caller and is
        # bridged with B's phone.
        ActiveCall(
            "b3",
            "1001",
            "5551234567",
            "Up",
            9,
            endpoint=eb["1002"]["endpoint_name"],
            bridge_id="br-b",
        ),
        ActiveCall("b4", "1001", "5551234567", "Up", 9, endpoint="trunk-main", bridge_id="br-b"),
        # Ringing inbound on the trunk for A: no bridge yet, VEYRA_ORG says whose.
        ActiveCall(
            "a3", "5559876543", "1001", "Ring", 2, endpoint="trunk-main", organization=a.slug
        ),
        # Nobody's: only platform administrators see it.
        ActiveCall("x1", "1001", None, "Down", 0, endpoint=None),
    ]
    return adapter, a, b


def test_list_by_organization_not_by_number(admin, app):
    _, a, b = _setup(admin, app)
    every = {c["channel_id"] for c in admin.get(CALLS).json()["calls"]}
    assert every == {"a1", "a2", "a3", "b1", "b2", "b3", "b4", "x1"}
    alice = org_user(admin, app, "admin@a.local", "org_admin", a.id)
    mine = {c["channel_id"]: c for c in alice.get(CALLS).json()["calls"]}
    assert set(mine) == {"a1", "a2", "a3"}
    assert mine["a1"]["extension_name"] == f"{a.slug} 1001"
    bob = org_user(admin, app, "admin@b.local", "org_admin", b.id)
    theirs = {c["channel_id"]: c for c in bob.get(CALLS).json()["calls"]}
    assert set(theirs) == {"b1", "b2", "b3", "b4"}
    # The trunk leg is shown with B's own phone, never with A's 1001.
    assert theirs["b4"]["extension_name"] == f"{b.slug} 1002"
    assert all(c["extension_name"].startswith(b.slug) for c in theirs.values())


def test_hangup_record_monitor_stay_in_the_organization(admin, app):
    adapter, a, _ = _setup(admin, app)
    alice = org_user(admin, app, "admin@a.local", "org_admin", a.id)
    for channel in ("b1", "b4", "x1"):
        assert alice.delete(f"{CALLS}/{channel}").status_code == 404
        r = alice.post(f"{CALLS}/{channel}/record", json={"action": "start"})
        assert r.status_code == 404
        r = alice.post(
            f"{CALLS}/{channel}/monitor",
            json={"mode": "listen", "extension_id": a.extensions["1002"]["id"]},
        )
        assert r.status_code == 404
    assert adapter.hung_up == [] and not getattr(adapter, "recording", set())
    assert alice.post(f"{CALLS}/a3/record", json={"action": "start"}).status_code == 200
    assert alice.delete(f"{CALLS}/a1").status_code == 200
    assert adapter.hung_up == ["a1"]
    events = admin.get("/api/v1/audit", params={"q": "call.hangup"}).json()["items"]
    assert events[0]["organization_id"] == a.id
    # A platform administrator may end any channel, including an unknown one.
    assert admin.delete(f"{CALLS}/x1").status_code == 200


def test_bridge_of_two_organizations_is_nobodys(admin, app):
    adapter, a, b = _setup(admin, app)
    adapter.calls = [
        ActiveCall(
            "p",
            "1001",
            None,
            "Up",
            1,
            endpoint=a.extensions["1001"]["endpoint_name"],
            bridge_id="br",
        ),
        ActiveCall(
            "q",
            "1001",
            None,
            "Up",
            1,
            endpoint=b.extensions["1001"]["endpoint_name"],
            bridge_id="br",
        ),
        ActiveCall("t", "1001", None, "Up", 1, endpoint="trunk-main", bridge_id="br"),
    ]
    alice = org_user(admin, app, "admin@a.local", "org_admin", a.id)
    assert {c["channel_id"] for c in alice.get(CALLS).json()["calls"]} == {"p"}


class _Ari:
    def __init__(self, channels, bridges, variables=None):
        self._channels, self._bridges = channels, bridges
        self.variables = variables or {}
        self.asked: list[str] = []

    def channels(self):
        return self._channels

    def bridges(self):
        return self._bridges

    def get_variable(self, channel_id, name):
        self.asked.append(channel_id)
        return self.variables.get(channel_id, "")


def _adapter(ari):
    adapter = object.__new__(AsteriskAdapter)
    adapter.ari = ari
    return adapter


def test_asterisk_adapter_reports_bridge_and_organization():
    ari = _Ari(
        [
            {"id": "1", "name": "PJSIP/beta-1001-0001", "channelvars": {"VEYRA_ORG": "beta"}},
            {"id": "2", "name": "PJSIP/trunk-main-0002", "channelvars": {"VEYRA_ORG": ""}},
            {"id": "3", "name": "PJSIP/trunk-main-0003", "channelvars": {"VEYRA_ORG": "acme"}},
        ],
        [{"id": "br", "channels": ["1", "2"]}],
    )
    calls = {c.channel_id: c for c in _adapter(ari).active_calls()}
    assert calls["1"].bridge_id == "br" and calls["1"].organization == "beta"
    assert calls["2"].bridge_id == "br" and calls["2"].organization is None
    assert calls["3"].bridge_id is None and calls["3"].organization == "acme"
    assert ari.asked == []  # channelvars present: nothing asked one by one


def test_asterisk_adapter_without_channelvars_asks_unbridged_channels():
    ari = _Ari(
        [
            {"id": "1", "name": "PJSIP/beta-1001-0001"},
            {"id": "2", "name": "PJSIP/trunk-main-0002"},
            {"id": "3", "name": "PJSIP/trunk-main-0003"},
        ],
        [{"id": "br", "channels": ["1", "2"]}],
        {"3": "acme"},
    )
    calls = {c.channel_id: c for c in _adapter(ari).active_calls()}
    assert ari.asked == ["3"] and calls["3"].organization == "acme"


def test_generated_veyra_org_reaches_trunk_legs_only_with_several_namespaces():
    from test_multi_tenancy import _base, _files, _org_b

    route = {
        "did": "5735550100",
        "trunk": None,
        "destination": {"type": "queue", "queue": "support"},
        "after_hours": None,
        "time_condition": None,
        "caller_id_prefix": None,
        "organization": "x",
        "organization_slug": "beta",
    }
    snap = _org_b(_base())
    snap["installation"]["multi_tenancy_enabled"] = True
    snap["inbound_routes"] = [route]
    files = _files(snap)
    ep, dp = files["pjsip.endpoints.conf"].content, files["extensions.conf"].content
    assert "set_var=__VEYRA_ORG=beta" in ep and "set_var=VEYRA_ORG=" not in ep
    assert (
        "exten => 5735550100,1,NoOp(Veyra inbound 5735550100 via ${VEYRA_TRUNK})\n"
        " same => n,Set(__VEYRA_ORG=beta)\n"
    ) in dp
    from veyra.telephony.asterisk import isolation

    assert isolation.verify(files.values()) == []
    # One organization: today's lines (the golden tests hold the rest).
    one = _base()
    one["inbound_routes"] = [{**route, "organization_slug": "example"}]
    single = _files(one)
    assert "set_var=VEYRA_ORG=example" in single["pjsip.endpoints.conf"].content
    assert "__VEYRA_ORG" not in single["extensions.conf"].content
