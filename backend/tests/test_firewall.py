# SPDX-License-Identifier: AGPL-3.0-or-later
"""Firewall (docs/FIREWALL_TRUST.md): ruleset rendering, event parsing
(samples captured from Asterisk 22 on dev1), scoring and bans, the service
pass against a fake nft, and the API's guards against self-lockout."""

from datetime import UTC, datetime, timedelta

import pytest

from veyra.core.db import session_scope
from veyra.core.models import FirewallBan, FirewallEvent, FirewallRule
from veyra.firewall import detect, feeds
from veyra.firewall.ports import service_ports
from veyra.firewall.render import BanSpec, Ruleset, RuleSpec, render
from veyra.firewall.service import (
    FirewallService,
    LogFollower,
    Sources,
    automatic_entries,
    sync_automatic_rules,
)
from veyra.firewall.settings import FirewallSettings, load_settings, save_settings
from veyra.telephony.settings import SipSettings, save_sip_settings

FW = "/api/v1/firewall"
T0 = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)

# Real lines from dev1 (2026-10-15): an unknown account produces both events
# per attempt; a wrong password on a real account only ChallengeResponseFailed.
UNKNOWN = (
    '[Oct 15 01:19:11] SECURITY[781046] res_security_log.c: SecurityEvent="InvalidAccountID",'
    'EventTV="2026-10-15T01:19:11.567+0000",Severity="Error",Service="PJSIP",EventVersion="1",'
    'AccountID="nosuchuser999",SessionID="5f12",LocalAddress="IPV4/UDP/172.16.2.250/5060",'
    'RemoteAddress="IPV4/UDP/198.51.100.9/5099"'
)
UNKNOWN_CHALLENGE = (
    "[Oct 15 01:19:11] SECURITY[781046] res_security_log.c: "
    'SecurityEvent="ChallengeResponseFailed",'
    'EventTV="2026-10-15T01:19:11.567+0000",Severity="Error",Service="PJSIP",EventVersion="1",'
    'AccountID="<unknown>",SessionID="5f12",LocalAddress="IPV4/UDP/172.16.2.250/5060",'
    'RemoteAddress="IPV4/UDP/198.51.100.9/5099",Challenge="1/5c",Response="69",ExpectedResponse=""'
)
BAD_PASSWORD = (
    "[Oct 15 01:19:17] SECURITY[781046] res_security_log.c: "
    'SecurityEvent="ChallengeResponseFailed",'
    'EventTV="2026-10-15T01:19:17.579+0000",Severity="Error",Service="PJSIP",EventVersion="1",'
    'AccountID="example-22214",SessionID="6a62",LocalAddress="IPV4/UDP/172.16.2.250/5060",'
    'RemoteAddress="IPV6/TCP/2001:db8::7/5098",Challenge="1/5c",Response="69",ExpectedResponse=""'
)
CHALLENGE_SENT = (
    '[Oct 15 01:19:11] SECURITY[781046] res_security_log.c: SecurityEvent="ChallengeSent",'
    'AccountID="<unknown>",RemoteAddress="IPV4/UDP/198.51.100.9/5099",Challenge=""'
)
NGINX = (
    "2026/10/15 01:20:00 [error] 123#123: *45 limiting requests, excess: 10.500 by zone "
    '"veyra_auth", client: 203.0.113.4, server: veyra-dev1, request: "POST /api/v1/auth/login"'
)


# ------------------------------------------------------------------ render


def test_render_sets_order_and_service_rules():
    fw = FirewallSettings(policy={"ssh": "allow_list_only"})
    script = render(
        Ruleset(
            rules=[
                RuleSpec("allow", "172.16.0.0/21"),
                RuleSpec("allow", "172.16.2.250/32"),  # inside the /21: merged
                RuleSpec("allow", "fd42::/16"),
                RuleSpec("block", "203.0.113.0/24"),
                RuleSpec("block", "203.0.113.5", timeout_seconds=300),  # covered: dropped
                RuleSpec("block", "198.51.100.7", timeout_seconds=600),
                RuleSpec("block", "192.0.2.0/24", ("sip",)),
            ],
            bans=[BanSpec("198.51.100.9", 3600), BanSpec("2001:db8::1", 60)],
            feed=["100.64.0.0/10"],
            ports=service_ports(SipSettings(), fw),
            restricted=fw.restricted(),
        )
    )
    assert script.startswith("table inet veyra\ndelete table inet veyra\ntable inet veyra {")
    assert "elements = { 172.16.0.0/21 }" in script
    assert "203.0.113.5" not in script
    assert "198.51.100.7/32 timeout 600s" in script
    assert "198.51.100.9 timeout 3600s" in script and "2001:db8::1 timeout 60s" in script
    lines = script.splitlines()
    # The allow list comes before every drop.
    assert lines.index("    ip saddr @allow4 return") < lines.index("    ip saddr @block4 drop")
    assert "    ip saddr 192.0.2.0/24 udp dport { 5060 } drop" in lines
    assert "    tcp dport { 22 } drop" in lines
    assert "lxd" not in script and "flush" not in script


def test_ports_follow_sip_settings():
    sip = SipSettings(
        udp_port=5080, tcp_port=5080, tls_enabled=True, rtp_start=12000, rtp_end=13000
    )
    ports = service_ports(sip, FirewallSettings(ssh_ports=[2222]))
    assert ports["sip"].udp == ("5080",) and ports["sip"].tcp == ("5061", "5080")
    assert ports["rtp"].udp == ("12000-13000",)
    assert ports["ssh"].tcp == ("2222",)


# ----------------------------------------------------------------- detect


def test_parse_asterisk_samples():
    ev = detect.parse_asterisk(UNKNOWN, T0)
    assert ev and ev.kind == "sip_unknown_account" and ev.address == "198.51.100.9"
    assert ev.detail == "PJSIP account nosuchuser999"
    assert detect.parse_asterisk(UNKNOWN_CHALLENGE, T0) is None  # same attempt
    ev6 = detect.parse_asterisk(BAD_PASSWORD, T0)
    assert ev6 and ev6.kind == "sip_bad_password" and ev6.address == "2001:db8::7"
    assert detect.parse_asterisk(CHALLENGE_SENT, T0) is None
    assert detect.parse_asterisk("[Oct 15] NOTICE something else", T0) is None


def test_parse_nginx_and_normalise():
    ev = detect.parse_nginx(NGINX, T0)
    assert ev and ev.address == "203.0.113.4" and ev.detail == "zone veyra_auth"
    assert detect.normalise_address("::ffff:192.0.2.1") == "192.0.2.1"
    assert detect.normalise_address("testclient") is None


def test_aggregate_and_score_with_counts():
    fw = FirewallSettings()
    evs = [detect.Event(T0, "198.51.100.9", "asterisk", "sip_unknown_account", "x")] * 500
    agg = detect.aggregate(evs)
    assert len(agg) == 1 and agg[0].count == 500
    scorer = detect.Scorer()
    assert scorer.add(agg[0], fw) == 1000
    assert scorer.score("198.51.100.9", T0 + timedelta(minutes=11), fw) == 0


def test_ban_minutes_double_and_cap():
    fw = FirewallSettings(ban_minutes=60, max_ban_days=1)
    assert [detect.ban_minutes(n, fw) for n in (1, 2, 3, 6)] == [60, 120, 240, 1440]


def test_feed_parsing():
    assert feeds.parse_list("# DROP\n192.0.2.0/24 ; SBL1\n\n127.0.0.1\n2001:db8::/32\nbad") == [
        "192.0.2.0/24",
        "2001:db8::/32",
    ]
    doc = (
        b'{"new":[{"value":"198.51.100.1","scope":"Ip","type":"ban"},'
        b'{"value":"203.0.113.0/24","scope":"Range","type":"ban"},'
        b'{"value":"x","scope":"Country","type":"ban"},'
        b'{"value":"192.0.2.9","scope":"Ip","type":"captcha"}]}'
    )
    assert feeds.parse_crowdsec(doc) == ["198.51.100.1/32", "203.0.113.0/24"]
    with pytest.raises(feeds.FeedError):
        feeds.fetch("list", "http://example.test/list.txt", None)


def test_log_follower_starts_at_end_and_follows_rotation(tmp_path):
    p = tmp_path / "security.log"
    p.write_text("old line\n")
    f = LogFollower(p)
    assert f.lines() == []
    with p.open("a") as fh:
        fh.write("one\ntwo\npart")
    assert f.lines() == ["one", "two"]
    with p.open("a") as fh:
        fh.write("ial\n")
    assert f.lines() == ["partial"]
    p.unlink()
    p.write_text("rotated\n")
    assert f.lines() == ["rotated"]


# ---------------------------------------------------------------- service


class FakeNft:
    def __init__(self):
        self.applied: list[str] = []
        self.added: list[tuple[str, str]] = []
        self.deleted: list[tuple[str, str]] = []
        self.table_deleted = 0

    def apply(self, script):
        self.applied.append(script)

    def add_element(self, set_name, element):
        self.added.append((set_name, element))

    def delete_element(self, set_name, address):
        self.deleted.append((set_name, address))

    def delete_table(self):
        self.table_deleted += 1


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


@pytest.fixture
def svc(db_ready, tmp_path):
    ast, ngx = tmp_path / "security.log", tmp_path / "error.log"
    ast.write_text("")
    ngx.write_text("")
    nft, clock = FakeNft(), Clock()
    service = FirewallService(
        tmp_path,
        nft,
        sources=Sources(LogFollower(ast), LogFollower(ngx)),
        addresses=lambda: ["172.16.2.250"],
        resolve=lambda h: [],
        clock=clock,
    )
    with session_scope() as db:
        save_sip_settings(db, SipSettings(local_nets=["172.16.0.0/21"]))
        save_settings(db, FirewallSettings(enabled=True, ban_score=10))
        service.tick(db)  # positions the followers and cursors
    return service, nft, clock, ast


def _write(path, *lines):
    with path.open("a") as fh:
        fh.write("".join(line + "\n" for line in lines))


def test_service_bans_scanner_and_lifts(svc):
    service, nft, clock, ast = svc
    assert nft.applied and "172.16.0.0/21" in nft.applied[-1]
    _write(ast, *[UNKNOWN, UNKNOWN_CHALLENGE] * 5)  # score 10
    clock.now += timedelta(seconds=2)
    with session_scope() as db:
        service.tick(db)
    with session_scope() as db:
        ban = db.query(FirewallBan).one()
        assert ban.address == "198.51.100.9" and ban.offence == 1
        assert ban.expires_at - ban.banned_at == timedelta(minutes=60)
        ev = db.query(FirewallEvent).one()
        assert ev.count == 5 and not ev.would_ban
        ban.lifted_at = clock.now
    assert ("ban4", "198.51.100.9 timeout 3600s") in nft.added
    clock.now += timedelta(seconds=2)
    with session_scope() as db:
        service.tick(db)
    assert ("ban4", "198.51.100.9") in nft.deleted
    # A second offence within 7 days doubles the ban.
    _write(ast, *[UNKNOWN] * 5)
    clock.now += timedelta(seconds=2)
    with session_scope() as db:
        service.tick(db)
    with session_scope() as db:
        second = db.query(FirewallBan).filter(FirewallBan.lifted_at.is_(None)).one()
        assert second.offence == 2
        assert second.expires_at - second.banned_at == timedelta(minutes=120)


def test_allowed_address_is_never_banned(svc):
    service, _, clock, ast = svc
    lan = UNKNOWN.replace("198.51.100.9", "172.16.3.40")
    _write(ast, *[lan] * 20)
    clock.now += timedelta(seconds=2)
    with session_scope() as db:
        service.tick(db)
    with session_scope() as db:
        assert db.query(FirewallBan).count() == 0
        assert db.query(FirewallEvent).one().would_ban is True


def test_automatic_rules_follow_configuration(svc):
    with session_scope() as db:
        origins = {(r.cidr, r.origin) for r in db.query(FirewallRule)}
        assert ("172.16.2.250/32", "server") in origins
        assert ("172.16.0.0/21", "sip_local_net") in origins
        save_sip_settings(db, SipSettings(local_nets=["10.20.0.0/16"]))
        assert sync_automatic_rules(db, automatic_entries(db, [], lambda h: []))
        origins = {(r.cidr, r.origin) for r in db.query(FirewallRule)}
        assert origins == {("10.20.0.0/16", "sip_local_net")}


def test_disabled_removes_table_and_unconfirmed_policy_reverts(svc):
    service, nft, clock, _ = svc
    from veyra.firewall.settings import PendingConfirm

    with session_scope() as db:
        fw = load_settings(db)
        fw.policy["web"] = "allow_list_only"
        fw.pending_confirm = PendingConfirm(
            previous_policy={"web": "anywhere"}, deadline=clock.now + timedelta(seconds=60), by="x"
        )
        save_settings(db, fw)
    clock.now += timedelta(seconds=61)
    with session_scope() as db:
        service.tick(db)
    with session_scope() as db:
        fw = load_settings(db)
        assert fw.policy["web"] == "anywhere" and fw.pending_confirm is None
        fw.enabled = False
        save_settings(db, fw)
    with session_scope() as db:
        service.tick(db)
    assert nft.table_deleted == 1
    assert not (service.dir / "veyra.nft").exists()


# -------------------------------------------------------------------- API


def test_api_rules_and_self_block(admin):
    me = {"X-Forwarded-For": "203.0.113.50"}
    r = admin.post(f"{FW}/rules", json={"action": "block", "cidr": "203.0.113.0/24"}, headers=me)
    assert r.status_code == 409 and r.json()["code"] == "firewall_self_block"
    r = admin.post(f"{FW}/rules", json={"action": "allow", "cidr": "203.0.113.50", "comment": "me"})
    assert r.status_code == 201 and r.json()["cidr"] == "203.0.113.50/32"
    allow_id = r.json()["id"]
    r = admin.post(f"{FW}/rules", json={"action": "block", "cidr": "203.0.113.0/24"}, headers=me)
    assert r.status_code == 201
    r = admin.post(f"{FW}/rules", json={"action": "block", "cidr": "203.0.113.0/24"})
    assert r.status_code == 409 and r.json()["code"] == "duplicate"
    r = admin.post(f"{FW}/rules", json={"action": "block", "cidr": "nonsense"})
    assert r.status_code == 422
    r = admin.post(
        f"{FW}/rules", json={"action": "block", "cidr": "192.0.2.1", "services": ["ftp"]}
    )
    assert r.status_code == 422
    # Restrict the web interface to the allow list: confirm-or-revert.
    body = {"enabled": True, "policy": {"web": "allow_list_only"}}
    r = admin.put(f"{FW}/settings", json=body, headers=me)
    assert r.status_code == 200 and r.json()["pending_confirm"]["by"] == "203.0.113.50"
    r = admin.post(f"{FW}/confirm")
    assert r.status_code == 200 and r.json()["pending_confirm"] is None
    # Removing your own allow entry while the web is restricted would lock you out.
    r = admin.delete(f"{FW}/rules/{allow_id}", headers=me)
    assert r.status_code == 409
    r = admin.put(f"{FW}/settings", json=body, headers={"X-Forwarded-For": "198.51.100.77"})
    assert r.status_code == 409
    status = admin.get(f"{FW}/status", headers=me).json()
    assert status["enabled"] is True and status["your_address_allowed"] is True
    assert status["service_running"] is False


def test_api_automatic_rules_are_read_only(admin):
    with session_scope() as db:
        rule = FirewallRule(action="allow", cidr="10.0.0.0/8", services=[], origin="sip_local_net")
        db.add(rule)
        db.flush()
        rule_id = rule.id
    assert admin.delete(f"{FW}/rules/{rule_id}").json()["code"] == "automatic_rule"


def test_api_bans_events_and_feeds(admin):
    with session_scope() as db:
        ban = FirewallBan(
            address="198.51.100.9",
            reason="sip unknown account (score 10 in 10 min)",
            source="asterisk",
            event_count=5,
            offence=3,
            banned_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=4),
        )
        db.add(ban)
        db.add(
            FirewallEvent(
                address="198.51.100.9", source="asterisk", kind="sip_unknown_account", count=5
            )
        )
        db.flush()
        ban_id = ban.id
    assert admin.get(f"{FW}/bans?active=true").json()["total"] == 1
    events = admin.get(f"{FW}/events?address=198.51.100.9").json()
    assert events["total"] == 1 and events["items"][0]["count"] == 5
    r = admin.post(f"{FW}/bans/{ban_id}/block")
    assert r.status_code == 201 and r.json()["cidr"] == "198.51.100.9/32"
    assert admin.get(f"{FW}/bans?active=true").json()["total"] == 0
    r = admin.post(
        f"{FW}/feeds", json={"name": "Spamhaus", "kind": "list", "url": "http://example.test/drop"}
    )
    assert r.status_code == 422
    r = admin.post(
        f"{FW}/feeds",
        json={"name": "CrowdSec", "kind": "crowdsec", "url": "http://127.0.0.1:8080", "key": "k"},
    )
    assert r.status_code == 201 and r.json()["has_key"] and r.json()["last_status"] == "pending"


def test_api_requires_platform_admin(client):
    assert client.get(f"{FW}/status").status_code == 401
