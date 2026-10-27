# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ``veyra-firewall`` service (docs/FIREWALL_TRUST.md §3.3): applies the
``inet veyra`` table, follows the event sources, decides bans and keeps the
automatic allow-list entries current. Runs with CAP_NET_ADMIN only."""

from __future__ import annotations

import contextlib
import ipaddress
import json
import logging
import os
import socket
import subprocess
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from veyra.core.models import (
    AuditEvent,
    FirewallBan,
    FirewallEvent,
    FirewallFeed,
    FirewallRule,
    ProvisioningRequest,
    SipTrunk,
)
from veyra.core.models.base import utcnow
from veyra.core.security.crypto import DecryptionError, InstallationKey
from veyra.firewall import detect, feeds
from veyra.firewall.ports import service_ports
from veyra.firewall.render import BanSpec, Ruleset, RuleSpec, ban_set, render, structure
from veyra.firewall.settings import FirewallSettings, load_settings, save_settings, save_status
from veyra.system import certificate
from veyra.telephony.settings import load_sip_settings

log = logging.getLogger("veyra.firewall")

ASTERISK_SECURITY_LOG = Path("/var/log/asterisk/security.log")
NGINX_ERROR_LOG = Path("/var/log/nginx/error.log")
EVENT_RETENTION_DAYS = 30
AUTOMATIC_ORIGINS = ("server", "sip_local_net", "trunk")


# ------------------------------------------------------------------ nft


class Nft(Protocol):
    def apply(self, script: str) -> None: ...
    def add_element(self, set_name: str, element: str) -> None: ...
    def delete_element(self, set_name: str, address: str) -> None: ...
    def delete_table(self) -> None: ...


class NftError(Exception):
    pass


class NftCommand:
    """Runs ``nft``; only ever names the ``inet veyra`` table."""

    def __init__(self, binary: str = "nft") -> None:
        self.binary = binary

    def _run(self, args: list[str], stdin: str | None = None) -> None:
        res = subprocess.run(  # noqa: S603
            [self.binary, *args], input=stdin, capture_output=True, text=True, timeout=30
        )
        if res.returncode != 0:
            raise NftError((res.stderr or res.stdout).strip()[:500])

    def apply(self, script: str) -> None:
        self._run(["-f", "-"], script)

    def add_element(self, set_name: str, element: str) -> None:
        self._run(["add", "element", "inet", "veyra", set_name, f"{{ {element} }}"])

    def delete_element(self, set_name: str, address: str) -> None:
        # Already expired in the kernel: nothing to do.
        with contextlib.suppress(NftError):
            self._run(["delete", "element", "inet", "veyra", set_name, f"{{ {address} }}"])

    def delete_table(self) -> None:
        with contextlib.suppress(NftError):  # not present
            self._run(["delete", "table", "inet", "veyra"])


# ------------------------------------------------------------- log files


class LogFollower:
    """Reads lines appended to a file; starts at the end, follows rotation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._inode: int | None = None
        self._pos = 0
        self.error: str | None = None

    def lines(self) -> list[str]:
        try:
            st = self.path.stat()
        except OSError as e:
            self.error = e.strerror
            return []
        if self._inode is None:
            self._inode, self._pos = st.st_ino, st.st_size
        elif st.st_ino != self._inode or st.st_size < self._pos:
            self._inode, self._pos = st.st_ino, 0
        if st.st_size == self._pos:
            self.error = None
            return []
        try:
            with self.path.open("rb") as f:
                f.seek(self._pos)
                data = f.read(4 * 1024 * 1024)
        except OSError as e:
            self.error = e.strerror
            return []
        self.error = None
        # Keep a partial last line for the next read.
        end = data.rfind(b"\n") + 1
        self._pos += end
        return data[:end].decode("utf-8", "replace").splitlines()


# ------------------------------------------------------------ allow list


def server_addresses() -> list[str]:
    """Addresses on this server's interfaces (``ip -j addr``)."""
    try:
        res = subprocess.run(
            ["ip", "-j", "addr", "show"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
        )
        doc = json.loads(res.stdout or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    out = []
    for iface in doc:
        for a in iface.get("addr_info") or []:
            addr = detect.normalise_address(a.get("local"))
            if addr and not ipaddress.ip_address(addr).is_link_local:
                out.append(addr)
    return sorted(set(out))


def _resolve(host: str) -> list[str]:
    try:
        ipaddress.ip_network(host, strict=False)
        return [str(ipaddress.ip_network(host, strict=False))]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    return sorted({str(i[4][0]) for i in infos})


def automatic_entries(
    db: Session, addresses: Iterable[str], resolve: Callable[[str], list[str]] = _resolve
) -> dict[tuple[str, str], str]:
    """(cidr, origin) → comment for every allow entry Veyra maintains."""
    out: dict[tuple[str, str], str] = {}
    for a in addresses:
        out[(str(ipaddress.ip_network(a)), "server")] = "This server"
    for net in load_sip_settings(db).local_nets:
        out[(net, "sip_local_net")] = "SIP local network"
    for trunk in db.scalars(select(SipTrunk)):
        hosts = [trunk.host, *(trunk.match_addresses or [])]
        for h in hosts:
            for cidr in resolve(h):
                out[(str(ipaddress.ip_network(cidr, strict=False)), "trunk")] = (
                    f"Trunk {trunk.name}"[:200]
                )
    return out


def sync_automatic_rules(db: Session, entries: dict[tuple[str, str], str]) -> bool:
    """Make the automatic allow rows match ``entries``; True when changed."""
    changed = False
    existing = {
        (r.cidr, r.origin): r
        for r in db.scalars(
            select(FirewallRule).where(
                FirewallRule.action == "allow", FirewallRule.origin.in_(AUTOMATIC_ORIGINS)
            )
        )
    }
    for key, row in existing.items():
        if key not in entries:
            db.delete(row)
            changed = True
        elif row.comment != entries[key]:
            row.comment = entries[key]
    for (cidr, origin), comment in entries.items():
        if (cidr, origin) not in existing:
            db.add(
                FirewallRule(
                    id=uuid.uuid4(),
                    action="allow",
                    cidr=cidr,
                    services=[],
                    comment=comment,
                    origin=origin,
                    created_by="Veyra",
                )
            )
            changed = True
    db.flush()
    return changed


def active_rules(db: Session, now: datetime) -> list[FirewallRule]:
    return list(
        db.scalars(
            select(FirewallRule)
            .where((FirewallRule.expires_at.is_(None)) | (FirewallRule.expires_at > now))
            .order_by(FirewallRule.created_at)
        )
    )


def active_bans(db: Session, now: datetime) -> list[FirewallBan]:
    return list(
        db.scalars(
            select(FirewallBan).where(FirewallBan.lifted_at.is_(None), FirewallBan.expires_at > now)
        )
    )


def allowed(address: str, rules: Iterable[FirewallRule]) -> FirewallRule | None:
    ip = ipaddress.ip_address(address)
    for r in rules:
        if r.action != "allow" or r.services:
            continue
        net = ipaddress.ip_network(r.cidr, strict=False)
        if net.version == ip.version and ip in net:
            return r
    return None


def blocked_by(address: str, rules: Iterable[FirewallRule]) -> FirewallRule | None:
    ip = ipaddress.ip_address(address)
    for r in rules:
        if r.action != "block":
            continue
        net = ipaddress.ip_network(r.cidr, strict=False)
        if net.version == ip.version and ip in net:
            return r
    return None


# --------------------------------------------------------------- service


@dataclass
class Sources:
    asterisk: LogFollower
    nginx: LogFollower


class FirewallService:
    def __init__(
        self,
        data_dir: Path,
        nft: Nft,
        key: InstallationKey | None = None,
        sources: Sources | None = None,
        addresses: Callable[[], list[str]] = server_addresses,
        resolve: Callable[[str], list[str]] = _resolve,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.dir = data_dir / "firewall"
        self.nft = nft
        self.key = key
        self.sources = sources or Sources(
            LogFollower(ASTERISK_SECURITY_LOG), LogFollower(NGINX_ERROR_LOG)
        )
        self.addresses = addresses
        self.resolve = resolve
        self.clock = clock
        self.scorer = detect.Scorer()
        self.applied_structure: str | None = None
        self.applied_bans: dict[str, datetime] = {}
        self.enabled_applied: bool | None = None
        self.audit_cursor: int | None = None
        self.prov_cursor: datetime | None = None
        self.last_sync = self.last_feeds = self.last_prune = datetime.min.replace(
            tzinfo=clock().tzinfo
        )
        self.error: str | None = None

    # -- boot

    @property
    def ruleset_file(self) -> Path:
        return self.dir / "veyra.nft"

    def restore_last(self) -> bool:
        """Apply the last ruleset written, before the database is reachable."""
        try:
            script = self.ruleset_file.read_text()
        except OSError:
            return False
        self.nft.apply(script)
        log.info("Applied the last saved ruleset (%s)", self.ruleset_file)
        return True

    # -- one pass

    def tick(self, db: Session) -> None:
        now = self.clock()
        fw = load_settings(db)
        if fw.pending_confirm and fw.pending_confirm.deadline <= now:
            log.warning("Policy change not confirmed by %s; reverting", fw.pending_confirm.by)
            fw.policy = fw.pending_confirm.previous_policy
            fw.pending_confirm = None
            save_settings(db, fw)
        if now - self.last_sync >= timedelta(seconds=60):
            sync_automatic_rules(db, automatic_entries(db, self.addresses(), self.resolve))
            self.last_sync = now
        rules = active_rules(db, now)
        self._collect_events(db, fw, rules, now)
        if now - self.last_feeds >= timedelta(seconds=feeds.REFRESH_SECONDS):
            self._refresh_feeds(db)
            self.last_feeds = now
        else:
            # Added, changed or "Fetch now" in the interface.
            for feed in db.scalars(
                select(FirewallFeed).where(
                    FirewallFeed.is_enabled.is_(True), FirewallFeed.last_status == "pending"
                )
            ):
                self.refresh_feed(db, feed)
        self._enforce(db, fw, rules, now)
        if now - self.last_prune >= timedelta(hours=1):
            db.execute(
                delete(FirewallEvent).where(
                    FirewallEvent.at < now - timedelta(days=EVENT_RETENTION_DAYS)
                )
            )
            self.scorer.prune(now, fw)
            self.last_prune = now
        self._status(db, fw, now)

    # -- events

    def _collect_events(
        self, db: Session, fw: FirewallSettings, rules: list[FirewallRule], now: datetime
    ) -> None:
        events: list[detect.Event] = []
        for line in self.sources.asterisk.lines():
            ev = detect.parse_asterisk(line, now)
            if ev:
                events.append(ev)
        for line in self.sources.nginx.lines():
            ev = detect.parse_nginx(line, now)
            if ev:
                events.append(ev)
        events.extend(self._database_events(db))
        for ev in detect.aggregate(events):
            self.handle(db, fw, rules, ev)

    def _database_events(self, db: Session) -> list[detect.Event]:
        out: list[detect.Event] = []
        if self.audit_cursor is None:
            self.audit_cursor = db.scalar(select(func.max(AuditEvent.id))) or 0
        rows = db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.id > self.audit_cursor,
                AuditEvent.action.in_(detect.AUDIT_KINDS),
                AuditEvent.outcome.in_(("failure", "denied")),
            )
            .order_by(AuditEvent.id)
            .limit(5000)
        ).all()
        for a in rows:
            address = detect.normalise_address(a.ip_address)
            if address:
                out.append(
                    detect.Event(
                        a.occurred_at,
                        address,
                        "auth",
                        detect.AUDIT_KINDS[a.action],
                        (a.actor_label or "")[:300] or None,
                    )
                )
        if rows:
            self.audit_cursor = rows[-1].id
        else:
            self.audit_cursor = max(
                self.audit_cursor, db.scalar(select(func.max(AuditEvent.id))) or 0
            )
        if self.prov_cursor is None:
            self.prov_cursor = self.clock()
        reqs = db.scalars(
            select(ProvisioningRequest)
            .where(ProvisioningRequest.at > self.prov_cursor, ProvisioningRequest.status == 401)
            .order_by(ProvisioningRequest.at)
            .limit(5000)
        ).all()
        for r in reqs:
            address = detect.normalise_address(r.ip_address)
            if address:
                out.append(
                    detect.Event(
                        r.at, address, "provisioning", "prov_unauthorized", r.filename[:300]
                    )
                )
        if reqs:
            self.prov_cursor = reqs[-1].at
        return out

    def handle(
        self, db: Session, fw: FirewallSettings, rules: list[FirewallRule], ev: detect.Event
    ) -> FirewallBan | None:
        """Record one event; ban its address when the score reaches the
        threshold and it is not on the allow list."""
        score = self.scorer.add(ev, fw)
        over = score >= fw.ban_score
        is_allowed = allowed(ev.address, rules) is not None
        db.add(
            FirewallEvent(
                id=uuid.uuid4(),
                at=ev.at,
                address=ev.address,
                source=ev.source,
                kind=ev.kind,
                detail=ev.detail,
                count=ev.count,
                would_ban=over and is_allowed,
            )
        )
        if not over or is_allowed or not fw.enabled:
            return None
        now = self.clock()
        if ev.address in self.applied_bans and self.applied_bans[ev.address] > now:
            return None  # already banned; late events from before the drop
        recent = db.scalar(
            select(func.count())
            .select_from(FirewallBan)
            .where(
                FirewallBan.address == ev.address,
                FirewallBan.banned_at > now - timedelta(days=7),
            )
        )
        offence = int(recent or 0) + 1
        minutes = detect.ban_minutes(offence, fw)
        ban = FirewallBan(
            id=uuid.uuid4(),
            address=ev.address,
            reason=f"{ev.kind.replace('_', ' ')} (score {score} in {fw.window_minutes} min)",
            source=ev.source,
            event_count=self.scorer.count(ev.address),
            offence=offence,
            banned_at=now,
            expires_at=now + timedelta(minutes=minutes),
        )
        db.add(ban)
        db.flush()
        self.scorer.reset(ev.address)
        log.warning("Banned %s for %d min: %s", ev.address, minutes, ban.reason)
        return ban

    # -- feeds

    def _feed_path(self, feed_id: uuid.UUID) -> Path:
        return self.dir / f"feed-{feed_id}.txt"

    def _refresh_feeds(self, db: Session) -> None:
        for feed in db.scalars(select(FirewallFeed).where(FirewallFeed.is_enabled.is_(True))):
            self.refresh_feed(db, feed)

    def refresh_feed(self, db: Session, feed: FirewallFeed) -> None:
        key = None
        if feed.key_ciphertext and self.key is not None:
            try:
                key = self.key.decrypt(feed.key_ciphertext, f"firewall.feed:{feed.id}")
            except DecryptionError:
                key = None
        try:
            entries = feeds.fetch(feed.kind, feed.url, key)
        except feeds.FeedError as e:
            feed.last_status, feed.last_error = "failed", str(e)[:500]
        else:
            self.dir.mkdir(parents=True, exist_ok=True)
            feeds.store(self._feed_path(feed.id), entries)
            feed.last_status, feed.last_error = "ok", None
            feed.entry_count = len(entries)
        feed.last_fetched_at = self.clock()

    def _feed_entries(self, db: Session) -> list[str]:
        out: list[str] = []
        for feed in db.scalars(select(FirewallFeed).where(FirewallFeed.is_enabled.is_(True))):
            out.extend(feeds.load(self._feed_path(feed.id)))
        return out

    # -- enforcement

    def ruleset(
        self, db: Session, fw: FirewallSettings, rules: list[FirewallRule], now: datetime
    ) -> Ruleset:
        specs = [
            RuleSpec(
                r.action,
                r.cidr,
                tuple(r.services or ()),
                int((r.expires_at - now).total_seconds()) if r.expires_at else None,
            )
            for r in rules
        ]
        bans = [
            BanSpec(b.address, int((b.expires_at - now).total_seconds()))
            for b in active_bans(db, now)
        ]
        return Ruleset(
            rules=specs,
            bans=bans,
            feed=self._feed_entries(db),
            ports=service_ports(load_sip_settings(db), fw),
            restricted=fw.restricted(),
            open_tcp=("80",) if certificate.challenge_window_open(db, now) else (),
        )

    def _enforce(
        self, db: Session, fw: FirewallSettings, rules: list[FirewallRule], now: datetime
    ) -> None:
        if not fw.enabled:
            if self.enabled_applied is not False:
                self.nft.delete_table()
                self.ruleset_file.unlink(missing_ok=True)
                self.applied_structure, self.applied_bans = None, {}
                self.enabled_applied = False
                log.info("Firewall off: table inet veyra removed")
            return
        rs = self.ruleset(db, fw, rules, now)
        # Timed blocks change their remaining seconds every pass; compare
        # without them so only real changes re-apply.
        shape = structure(
            Ruleset(
                [RuleSpec(r.action, r.cidr, r.services) for r in rs.rules],
                (),
                rs.feed,
                rs.ports,
                rs.restricted,
            )
        )
        try:
            if shape != self.applied_structure or not self.enabled_applied:
                script = render(rs)
                self.nft.apply(script)
                self.dir.mkdir(parents=True, exist_ok=True)
                tmp = self.ruleset_file.with_suffix(".tmp")
                tmp.write_text(script)
                os.replace(tmp, self.ruleset_file)
                self.applied_structure = shape
                self.applied_bans = {
                    b.address: now + timedelta(seconds=b.timeout_seconds) for b in rs.bans
                }
                self.enabled_applied = True
                log.info(
                    "Applied table inet veyra (%d rules, %d bans)", len(rs.rules), len(rs.bans)
                )
            else:
                self._sync_bans(rs.bans, now)
            self.error = None
        except NftError as e:
            self.error = str(e)
            log.error("nft failed: %s", e)

    def _sync_bans(self, bans: Iterable[BanSpec], now: datetime) -> None:
        wanted = {b.address: b for b in bans}
        for address in list(self.applied_bans):
            if address not in wanted:
                self.nft.delete_element(ban_set(address), address)
                del self.applied_bans[address]
        for address, b in wanted.items():
            if address not in self.applied_bans:
                self.nft.add_element(
                    ban_set(address), f"{address} timeout {max(b.timeout_seconds, 1)}s"
                )
                self.applied_bans[address] = now + timedelta(seconds=b.timeout_seconds)

    def _status(self, db: Session, fw: FirewallSettings, now: datetime) -> None:
        status: dict[str, Any] = {
            "heartbeat": now.isoformat(),
            "enabled": fw.enabled,
            "applied": bool(self.enabled_applied),
            "bans": len(self.applied_bans),
            "error": self.error,
            "sources": {
                "asterisk": self.sources.asterisk.error,
                "nginx": self.sources.nginx.error,
            },
        }
        save_status(db, status)
