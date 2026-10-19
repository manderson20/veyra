# SPDX-License-Identifier: AGPL-3.0-or-later
"""Monitoring alerts (docs/REPORTING.md §6.1).

Every worker pass the checks report what is wrong right now; an alert is
*pending* when first seen, *raised* (and emailed) once it has lasted the
rule's delay, reminded every 24 hours, and *cleared* (emailed once) when it
is gone. Built-in rules only; administrators switch and tune them."""

from __future__ import annotations

import logging
import shutil
import socket
import ssl
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.core import mail
from veyra.core.models import (
    Alert,
    AlertRule,
    Device,
    Extension,
    FirewallBan,
    Installation,
    SipTrunk,
)
from veyra.core.models.base import utcnow

log = logging.getLogger("veyra.alerts")

REMIND_AFTER = timedelta(hours=24)


@dataclass(frozen=True)
class RuleDef:
    key: str
    title: str
    delay_minutes: int
    threshold: int | None = None
    unit: str = ""


RULES: dict[str, RuleDef] = {
    r.key: r
    for r in (
        RuleDef("engine_down", "Telephony engine down", 2),
        RuleDef("trunk_down", "Trunk down", 5),
        RuleDef("service_down", "Veyra service not running", 2),
        RuleDef("disk_space", "Disk space low", 5, 10, "% free"),
        RuleDef("certificate", "HTTPS certificate expiring", 0, 21, "days"),
        RuleDef("firewall_bans", "Many firewall bans", 0, 20, "bans per hour"),
        RuleDef("phones_unregistered", "Phones unregistered", 15, 20, "% of phones"),
        # Central console only (docs/CENTRAL_MANAGEMENT.md §6).
        RuleDef("instance_offline", "Instance not checking in", 0),
        RuleDef("instance_failed", "Instance unhealthy", 5),
        RuleDef("instance_update_failed", "Instance update failed", 0),
        # Backups (docs/PRODUCTION_HARDENING.md §2.6).
        RuleDef("backup_failed", "Backup failed", 0),
        RuleDef("backup_stale", "No recent good backup", 0),
        # High availability (docs/HIGH_AVAILABILITY.md §10).
        RuleDef("node_offline", "HA node offline", 2),
        RuleDef("replication_broken", "Replication broken", 2),
        RuleDef("replication_lag", "Replication lagging", 1, 64, "MB behind"),
        RuleDef("ha_sync_failed", "File sync failing", 5),
        RuleDef("node_isolated", "Primary isolated", 0),
        RuleDef("ha_operation_failed", "HA operation failed", 0),
    )
}
SERVICES = ("veyra-api", "veyra-deployer", "veyra-pager", "veyra-firewall")


@dataclass(frozen=True)
class Finding:
    rule: str
    subject: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def ensure_rules(db: Session) -> dict[str, AlertRule]:
    rows = {r.key: r for r in db.scalars(select(AlertRule))}
    for key, d in RULES.items():
        if key not in rows:
            rows[key] = AlertRule(
                key=key,
                is_enabled=True,
                delay_minutes=d.delay_minutes,
                threshold=d.threshold,
                recipients=[],
            )
            db.add(rows[key])
    db.flush()
    return rows


# ------------------------------------------------------------------ checks


def check_engine(adapter: Any) -> list[Finding]:
    state = adapter.health().state
    if state == "running":
        return []
    return [Finding("engine_down", "", f"The telephony engine is {state.replace('_', ' ')}.")]


def check_trunks(db: Session, adapter: Any) -> list[Finding]:
    live = {s.endpoint: s.registered for s in adapter.endpoint_statuses()}
    # The outbound registration state, when the engine reports it (issue #45):
    # a rejected registration is a down trunk even when the host answers pings.
    registrations: dict[str, str] = {}
    try:
        registrations = {r.section: r.status for r in adapter.trunk_registrations()}
    except Exception:
        registrations = {}
    out = []
    for t in db.scalars(select(SipTrunk).where(SipTrunk.is_enabled.is_(True))):
        name = f"trunk-{t.slug}"
        word = registrations.get(name) if t.auth_mode == "registration" else None
        if word and not word.lower().startswith("registered"):
            out.append(
                Finding("trunk_down", t.slug, f"Trunk {t.name}: registration {word.lower()}.")
            )
        elif t.qualify_frequency and name in live and not live[name]:
            out.append(
                Finding("trunk_down", t.slug, f"Trunk {t.name} is not reachable or not registered.")
            )
    return out


def check_phones(db: Session, adapter: Any, threshold: int) -> list[Finding]:
    """Extensions that have provisioned phones and are not registered."""
    with_devices = select(Device.primary_extension_id).where(
        Device.is_enabled.is_(True), Device.primary_extension_id.is_not(None)
    )
    exts = db.scalars(
        select(Extension).where(Extension.is_enabled.is_(True), Extension.id.in_(with_devices))
    ).all()
    if not exts:
        return []
    live = {s.endpoint: s.registered for s in adapter.endpoint_statuses()}
    down = [e for e in exts if not live.get(e.endpoint_name, False)]
    share = 100 * len(down) / len(exts)
    if share <= threshold:
        return []
    return [
        Finding(
            "phones_unregistered",
            "",
            f"{len(down)} of {len(exts)} provisioned phones are not registered.",
            {"numbers": sorted(e.number for e in down)[:50]},
        )
    ]


def unit_active(unit: str) -> bool:
    try:
        res = subprocess.run(  # noqa: S603
            ["systemctl", "is-active", "--quiet", unit],  # noqa: S607
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True  # cannot tell: do not cry wolf
    return res.returncode == 0


def check_services(units: tuple[str, ...], active: Callable[[str], bool]) -> list[Finding]:
    return [
        Finding("service_down", u, f"The {u} service is not running (journalctl -u {u}).")
        for u in units
        if not active(u)
    ]


def check_disk(paths: list[Path], threshold: int) -> list[Finding]:
    out = []
    for p in paths:
        try:
            usage = shutil.disk_usage(p)
        except OSError:
            continue
        free = 100 * usage.free / usage.total if usage.total else 100
        if free < threshold:
            out.append(
                Finding(
                    "disk_space",
                    str(p),
                    f"Only {free:.0f}% free on the volume of {p}.",
                    {"free_percent": round(free, 1)},
                )
            )
    return out


def certificate_days_left(host: str = "127.0.0.1", port: int = 443) -> float | None:
    from cryptography import x509

    ctx = ssl.create_default_context()
    # Only the certificate is read (expiry check); verification is off on
    # purpose, old protocol versions are not.
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with (
            socket.create_connection((host, port), timeout=5) as sock,
            ctx.wrap_socket(sock) as tls,
        ):
            der = tls.getpeercert(binary_form=True)
    except OSError:
        return None
    if not der:
        return None
    cert = x509.load_der_x509_certificate(der)
    return (cert.not_valid_after_utc - utcnow()).total_seconds() / 86400


def check_certificate(days_left: float | None, threshold: int) -> list[Finding]:
    if days_left is None or days_left >= threshold:
        return []
    return [
        Finding(
            "certificate", "", f"The HTTPS certificate expires in {max(days_left, 0):.0f} days."
        )
    ]


def check_central(db: Session, now: datetime) -> list[Finding]:
    """Instances of this central console that stopped checking in or report
    a failed health (docs/CENTRAL_MANAGEMENT.md §6)."""
    from veyra.central import console
    from veyra.core.models import CentralInstance

    if not console.enabled(db):
        return []
    offline = int(console.state(db).get("offline_minutes") or console.DEFAULT_OFFLINE_MINUTES)
    out: list[Finding] = []
    for inst in db.scalars(select(CentralInstance).where(CentralInstance.revoked_at.is_(None))):
        label = inst.label or inst.name
        status = console.status_of(inst, offline, now)
        if status == "offline":
            out.append(
                Finding(
                    "instance_offline",
                    label,
                    f"{label} has not checked in for more than {offline} minutes.",
                    {"instance_id": str(inst.instance_id)},
                )
            )
        elif status == "failed":
            out.append(
                Finding(
                    "instance_failed",
                    label,
                    f"{label} reports a failed health check.",
                    {"instance_id": str(inst.instance_id)},
                )
            )
        # An update the instance could not install (CENTRAL_MANAGEMENT.md §6; #120).
        report = inst.last_report or {}
        updates = report.get("updates") if isinstance(report, dict) else None
        for u in (updates or {}).get("available") or [] if isinstance(updates, dict) else []:
            if isinstance(u, dict) and u.get("state") == "failed":
                error = str(u.get("error") or "").strip()
                out.append(
                    Finding(
                        "instance_update_failed",
                        f"{label} {u.get('version')}",
                        f"{label} could not install Veyra {u.get('version')}"
                        + (f": {error[:200]}" if error else "."),
                        {"instance_id": str(inst.instance_id), "version": u.get("version")},
                    )
                )
    return out


def check_backups(db: Session, now: datetime) -> list[Finding]:
    """The last backup failed, or no verified backup within two days while
    backups are enabled (docs/PRODUCTION_HARDENING.md §2.6)."""
    from veyra.backups import service as backups

    s = backups.summary(db)
    out: list[Finding] = []
    if s["last_state"] == "failed":
        out.append(Finding("backup_failed", "backup", f"The last backup failed: {s['last_error']}"))
    if s["stale"]:
        out.append(
            Finding(
                "backup_stale",
                "backup",
                "No verified backup in the last two days"
                + (f" (last good {s['last_good_at']})." if s["last_good_at"] else "."),
            )
        )
    return out


def check_ha(db: Session, settings: Any, now: datetime, lag_mb: int) -> list[Finding]:
    """The HA pair (docs/HIGH_AVAILABILITY.md §10), evaluated on the primary:
    the peer's heartbeat, replication, the file sync, isolation, failed
    operations."""
    from veyra.core.models import ClusterNode, Installation
    from veyra.ha import service as ha
    from veyra.ha.state import StateDir

    inst = db.scalar(select(Installation))
    if inst is None or inst.deployment_mode != "ha":
        return []
    out: list[Finding] = []
    state_dir = StateDir(settings.data_dir / "ha")
    local = state_dir.node()
    me = ha.local_name()
    for n in db.scalars(select(ClusterNode).where(ClusterNode.node_name != me)):
        if n.role not in ("primary", "secondary"):
            continue
        if n.last_heartbeat_at is None or now - n.last_heartbeat_at > ha.HEARTBEAT_STALE_AFTER:
            out.append(
                Finding("node_offline", n.node_name, f"{n.node_name} has not sent a heartbeat.")
            )
            continue
        rep = n.replication or {}
        if n.role == "secondary" and rep.get("receiver") not in ("streaming", None):
            out.append(
                Finding(
                    "replication_broken",
                    n.node_name,
                    f"{n.node_name} is not receiving WAL ({rep.get('receiver')}).",
                )
            )
        if n.sync_at is None or now - n.sync_at > timedelta(minutes=5):
            out.append(
                Finding("ha_sync_failed", n.node_name, f"The file sync to {n.node_name} is stale.")
            )
    mine = db.scalar(select(ClusterNode).where(ClusterNode.node_name == me))
    if mine is not None and mine.role == "primary":
        rep = mine.replication or {}
        if rep.get("db_role") == "primary" and rep.get("state") is None:
            out.append(Finding("replication_broken", me, "No standby is connected."))
        lag = rep.get("lag_bytes")
        secs = rep.get("lag_seconds")
        if (lag is not None and lag > lag_mb * 1024 * 1024) or (secs is not None and secs > 60):
            out.append(
                Finding(
                    "replication_lag",
                    me,
                    f"The standby is {(lag or 0) // (1024 * 1024)} MB and "
                    f"{int(secs or 0)} s behind.",
                )
            )
    if local is not None and local.state == "isolated":
        out.append(
            Finding(
                "node_isolated",
                local.node_name,
                "This primary cannot reach its peer and is not serving calls; "
                "confirm the peer is down and resume, or fix the link.",
            )
        )
    op = state_dir.operation()
    if op is not None and op.status == "failed":
        out.append(
            Finding(
                "ha_operation_failed",
                op.kind,
                f"The {op.kind} started {op.started_at} failed: {op.error}",
            )
        )
    return out


def check_firewall(db: Session, now: datetime, threshold: int) -> list[Finding]:
    n = db.scalar(
        select(func.count())
        .select_from(FirewallBan)
        .where(FirewallBan.banned_at > now - timedelta(hours=1))
    )
    if not n or n <= threshold:
        return []
    return [
        Finding(
            "firewall_bans",
            "",
            f"{n} addresses were banned in the last hour: an attack may be under way.",
        )
    ]


# --------------------------------------------------------------- evaluate


def _webhook(db: Session, event: str, a: Alert) -> None:
    from veyra.integrations import webhooks

    webhooks.emit_all(
        db,
        event,
        {
            "rule": a.rule,
            "title": RULES[a.rule].title if a.rule in RULES else a.rule,
            "subject": a.subject,
            "message": a.message,
            "details": a.details,
        },
    )


def evaluate(
    db: Session,
    findings: list[Finding],
    notify: Callable[[AlertRule, Alert, str], None],
    now: datetime | None = None,
) -> None:
    now = now or utcnow()
    rules = ensure_rules(db)
    current = {
        (f.rule, f.subject): f for f in findings if rules.get(f.rule) and rules[f.rule].is_enabled
    }
    open_alerts = {
        (a.rule, a.subject): a
        for a in db.scalars(select(Alert).where(Alert.state.in_(("pending", "raised"))))
    }
    for key, f in current.items():
        rule = rules[f.rule]
        a = open_alerts.get(key)
        if a is None:
            a = Alert(
                id=uuid.uuid4(),
                rule=f.rule,
                subject=f.subject,
                state="pending",
                message=f.message,
                details=f.details,
                first_seen_at=now,
            )
            db.add(a)
        a.message, a.details = f.message, f.details
        if a.state == "pending" and now - a.first_seen_at >= timedelta(minutes=rule.delay_minutes):
            a.state, a.raised_at = "raised", now
            notify(rule, a, "raised")
            _webhook(db, "alert.raised", a)
            a.last_notified_at = now
        elif (
            a.state == "raised" and a.last_notified_at and now - a.last_notified_at >= REMIND_AFTER
        ):
            notify(rule, a, "reminder")
            a.last_notified_at = now
    for key, a in open_alerts.items():
        if key in current:
            continue
        if a.state == "pending":
            db.delete(a)  # it went away before anyone needed to know
            continue
        a.state, a.cleared_at = "cleared", now
        _webhook(db, "alert.resolved", a)
        cleared_rule = rules.get(a.rule)
        if cleared_rule is not None and cleared_rule.is_enabled:
            notify(cleared_rule, a, "cleared")
    db.flush()


def mail_notifier(db: Session, queue_dir: Path) -> Callable[[AlertRule, Alert, str], None]:
    """Email through the outgoing mail queue (docs/VOICEMAIL_IVR.md §2)."""
    smtp = mail.load_smtp_settings(db)
    inst = db.scalar(select(Installation))
    name = inst.name if inst else "Veyra"
    address, from_name = mail.sender(smtp, name)

    def notify(rule: AlertRule, alert: Alert, what: str) -> None:
        if not rule.recipients:
            return
        if not smtp.enabled:
            alert.notify_error = "Email delivery is off (System → Settings → Email)."
            return
        title = RULES[rule.key].title if rule.key in RULES else rule.key
        prefix = {"raised": "ALERT", "reminder": "STILL", "cleared": "CLEARED"}[what]
        subject = f"[{name}] {prefix}: {title}" + (f" ({alert.subject})" if alert.subject else "")
        text = (
            f"{alert.message}\n\n"
            + (
                f"First seen {alert.first_seen_at:%Y-%m-%d %H:%M} UTC.\n"
                if what != "cleared"
                else f"Cleared {alert.cleared_at:%Y-%m-%d %H:%M} UTC.\n"
            )
            + "\nSee System → Alerts in Veyra.\n"
        )
        try:
            for to in rule.recipients:
                msg = mail.compose(
                    from_address=address, from_name=from_name, to=to, subject=subject, text=text
                )
                mail.enqueue(queue_dir, msg.as_bytes())
            alert.notify_error = None
        except Exception as e:
            alert.notify_error = str(e)[:500]
            log.warning("Alert email not queued: %s", e)

    return notify


def run(db: Session, settings: Any, adapter: Any | None, now: datetime | None = None) -> None:
    """One evaluation pass for the worker."""
    now = now or utcnow()
    rules = ensure_rules(db)

    def threshold(key: str) -> int:
        r = rules[key]
        return r.threshold if r.threshold is not None else (RULES[key].threshold or 0)

    findings: list[Finding] = []
    checks: list[Callable[[], list[Finding]]] = [
        lambda: check_services(
            SERVICES if adapter is not None else ("veyra-api", "veyra-firewall"), unit_active
        ),
        lambda: check_disk([settings.data_dir, settings.log_dir], threshold("disk_space")),
        lambda: check_certificate(certificate_days_left(), threshold("certificate")),
        lambda: check_firewall(db, now, threshold("firewall_bans")),
        lambda: check_central(db, now),
        lambda: check_ha(db, settings, now, threshold("replication_lag")),
        lambda: check_backups(db, now),
    ]
    if adapter is not None:
        checks += [
            lambda: check_engine(adapter),
            lambda: check_trunks(db, adapter),
            lambda: check_phones(db, adapter, threshold("phones_unregistered")),
        ]
    for check in checks:
        try:
            findings += check()
        except Exception:
            log.exception("Alert check failed")
    evaluate(db, findings, mail_notifier(db, settings.mailqueue_dir), now)
