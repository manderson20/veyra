# SPDX-License-Identifier: AGPL-3.0-or-later
"""Download, approval and installation of Veyra releases on this server
(docs/SOFTWARE_UPDATES.md §2-5).

The service account downloads and verifies a release into
``<data>/updates/<version>/`` and, once approved, starts the root unit
``veyra-upgrade@<version>.service`` (polkit allows exactly that). The root
runner (``veyra.updates.runner``) verifies everything again before it runs
the release's own ``installer/upgrade.sh``.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import shutil
import socket
import subprocess
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.core.config import Settings
from veyra.core.models import AvailableUpdate, InstalledModule, SystemSetting, UpdatePolicy
from veyra.core.models.base import utcnow
from veyra.core.models.platform import ClusterNode
from veyra.core.semver import Version, VersionRange
from veyra.core.signing import Keyring
from veyra.updates.metadata import MetadataError, Release, UpdateMetadata, verify_metadata
from veyra.version import __version__

log = logging.getLogger("veyra.updates")

SOURCE_KEY = "updates.source"
SYSTEM_PACKAGES_KEY = "updates.system_packages"
TOKEN_PURPOSE = "updates:source-token"  # noqa: S105 (an encryption purpose)
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
TIMEOUT = 30
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
ARTIFACT_NAME = "release.tar.gz"
METADATA_NAME = "metadata.json"
# Nothing starts in the last minutes of a maintenance window (§4).
WINDOW_TAIL = timedelta(minutes=15)
# An installation that never reported progress is given up after this.
START_TIMEOUT = timedelta(minutes=15)


class UpdateError(RuntimeError):
    pass


# ------------------------------------------------------------------ source


def load_source(db: Session) -> dict[str, Any]:
    row = db.get(SystemSetting, SOURCE_KEY)
    return dict(row.value) if row else {}


def save_source(db: Session, value: dict[str, Any]) -> None:
    row = db.get(SystemSetting, SOURCE_KEY)
    if row is None:
        db.add(SystemSetting(key=SOURCE_KEY, value=value))
    else:
        row.value = value


# One fixed source (issue #84): this repository's signed feed.
OFFICIAL_FEED_URL = "https://raw.githubusercontent.com/manderson20/veyra/updates/stable.json"


def source_url(db: Session, settings: Settings) -> str:
    """Where releases come from: in production always this repository's
    feed (issue #84). Outside production only ``VEYRA_UPDATE_METADATA_URL``
    (tests, a local release under development); empty: no source, so tests
    never reach the network."""
    if settings.is_production:
        return OFFICIAL_FEED_URL
    return settings.update_metadata_url


def check_url(url: str, settings: Settings) -> None:
    """HTTPS; plain HTTP only to this machine (a local test source); file://
    only outside production."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https":
        return
    if parts.scheme == "file" and not settings.is_production:
        return
    if parts.scheme == "http":
        host = parts.hostname or ""
        try:
            if host == "localhost" or ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
    raise UpdateError(f"Update sources must use HTTPS ({url}).")


def _open(url: str, settings: Settings, token: str | None) -> Any:
    check_url(url, settings)
    req = urllib.request.Request(url, headers={"User-Agent": f"Veyra/{__version__}"})  # noqa: S310
    if token:
        # Not repeated on redirects (GitHub sends assets from a signed address).
        req.add_unredirected_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/octet-stream")
    resp = urllib.request.urlopen(req, timeout=TIMEOUT)  # noqa: S310 (scheme checked)
    check_url(resp.geturl(), settings)  # redirects must stay on HTTPS
    return resp


def fetch(
    url: str, settings: Settings, token: str | None = None, limit: int = MAX_METADATA_BYTES
) -> bytes:
    try:
        with _open(url, settings, token) as resp:
            data: bytes = resp.read(limit + 1)
    except OSError as e:
        raise UpdateError(f"Could not download {url}: {e}") from e
    if len(data) > limit:
        raise UpdateError(f"{url} is too large.")
    return data


def fetch_metadata(
    db: Session, settings: Settings, keyring: Keyring, *, last_sequence: int = 0
) -> tuple[UpdateMetadata, bytes, str]:
    """The verified metadata with its raw body and signature document."""
    url = source_url(db, settings)
    if not url:
        raise UpdateError("No update source is configured.")
    body = fetch(url, settings)
    sig = fetch(url + ".sig", settings, None, 64 * 1024).decode("utf-8", "replace")
    meta = verify_metadata(body, sig, keyring, last_sequence=last_sequence)
    return meta, body, sig


# ---------------------------------------------------------------- download


def version_dir(settings: Settings, version: str) -> Path:
    if not VERSION_RE.match(version):
        raise UpdateError(f"Invalid version {version!r}")
    return settings.updates_dir / version


def core_release(meta: UpdateMetadata, version: str) -> Release:
    for rel in meta.releases:
        if rel.component.value == "veyra_core" and rel.target == "veyra" and rel.version == version:
            if rel.artifact is None:
                raise UpdateError(f"Release {version} has no downloadable artifact.")
            return rel
    raise UpdateError(f"Release {version} is no longer offered by the update source.")


def download(db: Session, settings: Settings, keyring: Keyring, update: AvailableUpdate) -> None:
    """Fetch the signed metadata again, download the artifact it names and
    keep it only when size and SHA-256 match (§2)."""
    if update.component != "veyra_core":
        raise UpdateError("Only Veyra releases are downloaded here; modules use the catalog.")
    meta, body, sig = fetch_metadata(db, settings, keyring)
    rel = core_release(meta, update.version)
    assert rel.artifact is not None
    dest = version_dir(settings, update.version)
    part = dest.with_name(dest.name + ".part")
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True, mode=0o750)
    h = hashlib.sha256()
    size = 0
    try:
        with (
            _open(rel.artifact.url, settings, None) as resp,
            (part / ARTIFACT_NAME).open("wb") as out,
        ):
            while chunk := resp.read(1 << 20):
                size += len(chunk)
                if size > min(rel.artifact.size, MAX_ARTIFACT_BYTES):
                    raise UpdateError("The download is larger than the signed size.")
                h.update(chunk)
                out.write(chunk)
        if size != rel.artifact.size or h.hexdigest() != rel.artifact.sha256:
            raise UpdateError("The download does not match the signed size and checksum.")
        (part / METADATA_NAME).write_bytes(body)
        (part / (METADATA_NAME + ".sig")).write_text(sig)
    except OSError as e:
        shutil.rmtree(part, ignore_errors=True)
        raise UpdateError(f"Could not download the release: {e}") from e
    except UpdateError:
        shutil.rmtree(part, ignore_errors=True)
        raise
    shutil.rmtree(dest, ignore_errors=True)
    part.rename(dest)
    # One core version is kept downloaded: the newest (§2).
    for other in db.scalars(
        select(AvailableUpdate).where(
            AvailableUpdate.component == "veyra_core",
            AvailableUpdate.id != update.id,
            AvailableUpdate.state.in_(("downloaded", "approved")),
        )
    ):
        shutil.rmtree(version_dir(settings, other.version), ignore_errors=True)
        other.state, other.install_when, other.approved_at = "available", None, None
    update.metadata_ = rel.model_dump(mode="json")
    update.state = "downloaded"
    update.downloaded_at = utcnow()
    update.error = None


def refresh_stored_metadata(
    db: Session, settings: Settings, keyring: Keyring, version: str
) -> None:
    """Replace the stored metadata with the current one before installing,
    so an approval older than the metadata's expiry still installs. Kept as
    is when the source cannot be reached (the runner then decides)."""
    try:
        meta, body, sig = fetch_metadata(db, settings, keyring)
        core_release(meta, version)
    except (UpdateError, MetadataError, ValueError) as e:
        log.info("Keeping the stored update metadata: %s", e)
        return
    d = version_dir(settings, version)
    (d / METADATA_NAME).write_bytes(body)
    (d / (METADATA_NAME + ".sig")).write_text(sig)


# ------------------------------------------------------------------ checks


def preflight(db: Session, settings: Settings, update: AvailableUpdate) -> list[dict[str, Any]]:
    """Checks shown before approval (§3.3); the runner and upgrade.sh check
    again. Each: {key, ok, message}."""
    rel = update.metadata_ or {}
    out: list[dict[str, Any]] = []
    try:
        newer = Version.parse(update.version) > Version.parse(__version__)
    except ValueError:
        newer = False
    out.append(
        {
            "key": "newer",
            "ok": newer,
            "message": f"{update.version} is newer than the installed {__version__}"
            if newer
            else f"{update.version} is not newer than the installed {__version__}",
        }
    )
    min_from = rel.get("min_from_version")
    if min_from:
        ok = Version.parse(__version__) >= Version.parse(min_from)
        out.append(
            {
                "key": "min_from_version",
                "ok": ok,
                "message": f"Requires {min_from} or later to be installed"
                + ("" if ok else f"; upgrade to {min_from} first"),
            }
        )
    api = rel.get("module_api")
    if api:
        broken = []
        for m in db.scalars(select(InstalledModule).where(InstalledModule.state != "removed")):
            spec = (m.manifest or {}).get("compatibility", {}).get("core_api")
            if spec:
                try:
                    if not VersionRange.parse(spec).contains(api):
                        broken.append(m.module_id)
                except ValueError:
                    continue
        out.append(
            {
                "key": "modules",
                "ok": not broken,
                "message": "Installed modules support the new module API"
                if not broken
                else f"Not compatible with module API {api}: {', '.join(broken)}",
            }
        )
    size = int((rel.get("artifact") or {}).get("size") or 0)
    try:
        free = shutil.disk_usage(settings.data_dir).free
        ok = free > size * 4 + 2 * 1024**3
        out.append(
            {
                "key": "disk",
                "ok": ok,
                "message": f"{free // 1024**2} MB free"
                + ("" if ok else "; at least 2 GB plus the release is needed"),
            }
        )
    except OSError:
        pass
    busy = db.scalar(
        select(AvailableUpdate).where(
            AvailableUpdate.state == "installing", AvailableUpdate.id != update.id
        )
    )
    out.append(
        {
            "key": "idle_installer",
            "ok": busy is None,
            "message": "No other installation is running"
            if busy is None
            else f"Version {busy.version} is being installed",
        }
    )
    return out


def blocking_problems(db: Session, settings: Settings, update: AvailableUpdate) -> list[str]:
    return [c["message"] for c in preflight(db, settings, update) if not c["ok"]]


# ---------------------------------------------------------------- windows


def window_open(window: dict[str, Any] | None, now: datetime) -> bool:
    """Whether ``now`` is inside the maintenance window, leaving out its last
    15 minutes (§4). Windows may run past midnight."""
    if not window:
        return False
    tz = ZoneInfo(window.get("timezone") or "UTC")
    local = now.astimezone(tz)
    hh, mm = (int(x) for x in window["start"].split(":"))
    duration = timedelta(minutes=int(window["duration_minutes"]))
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    for back in (0, 1):
        day = local.date() - timedelta(days=back)
        if days[day.weekday()] not in window["days"]:
            continue
        start = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
        if start <= local < start + duration - WINDOW_TAIL:
            return True
    return False


def next_window_start(window: dict[str, Any] | None, now: datetime) -> datetime | None:
    if not window:
        return None
    tz = ZoneInfo(window.get("timezone") or "UTC")
    local = now.astimezone(tz)
    hh, mm = (int(x) for x in window["start"].split(":"))
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    for ahead in range(8):
        day = local.date() + timedelta(days=ahead)
        start = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
        if days[day.weekday()] in window["days"] and start > local:
            return start
    return None


# ---------------------------------------------------------- installation


def unit_name(version: str) -> str:
    if not VERSION_RE.match(version):
        raise UpdateError(f"Invalid version {version!r}")
    return f"veyra-upgrade@{version}.service"


def read_status(settings: Settings) -> dict[str, Any] | None:
    """The root runner's progress file (§3.4)."""
    try:
        return dict(json.loads((settings.upgrade_dir / "status.json").read_text()))
    except (OSError, ValueError):
        return None


# installer/templates/systemd/veyra-worker.service.in starts the worker with
# `--interval 60`: approved installations wait for its next housekeeping pass.
WORKER_INTERVAL_SECONDS = 60


def _parse_ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def install_progress(
    db: Session, settings: Settings, now: datetime | None = None
) -> dict[str, Any]:
    """What `GET /updates/status` returns (§3.4): the runner's status file and,
    while an installation is approved or starting, the stage it is in before
    the installer prints anything — so the interface can show a live
    timeline from the approval on instead of a page that does not change:

    * ``queued``: approved for "now", waiting for the worker's next pass
      (``worker_last_pass_at`` + ``worker_interval_seconds`` say when);
    * ``window``: approved for the maintenance window (``next_window``);
    * ``starting``: the worker ran the pre-checks and started the root unit,
      which is verifying and unpacking the release (no status file yet);
    * ``running``: the installer is running (``run`` has the step and output);
    * ``finishing``: the installer is done, the new worker is recording it.

    A status file from an earlier run (another version, or older than this
    approval) is not reported as this installation's ``run``."""
    now = now or utcnow()
    run = read_status(settings)
    row = db.scalar(
        select(AvailableUpdate)
        .where(
            AvailableUpdate.component == "veyra_core",
            AvailableUpdate.state.in_(["approved", "installing"]),
        )
        .order_by(AvailableUpdate.approved_at)
    )
    pending: dict[str, Any] | None = None
    if row is not None:
        started = _parse_ts(run.get("started_at")) if run else None
        this_run = (
            run is not None
            and run.get("version") == row.version
            and started is not None
            and row.approved_at is not None
            and started >= row.approved_at - timedelta(seconds=5)
        )
        if row.state == "approved":
            phase = "queued" if row.install_when == "now" else "window"
        elif this_run and run is not None and run.get("state") == "running":
            phase = "running"
        elif this_run:
            phase = "finishing"
        else:
            phase = "starting"
        if not this_run:
            run = None
        node = db.scalar(select(ClusterNode).where(ClusterNode.node_name == socket.gethostname()))
        policy = db.get(UpdatePolicy, "veyra_core")
        pending = {
            "id": str(row.id),
            "version": row.version,
            "state": row.state,
            "install_when": row.install_when,
            "approved_at": row.approved_at,
            "approved_by": row.approved_by,
            "install_started_at": row.install_started_at,
            "error": row.error,
            "phase": phase,
            "worker_last_pass_at": node.last_heartbeat_at if node else None,
            "worker_interval_seconds": WORKER_INTERVAL_SECONDS,
            "next_window": next_window_start(policy.maintenance_window, now)
            if policy is not None and row.install_when == "window"
            else None,
        }
    return {"installed_version": __version__, "run": run, "pending": pending}


def start_install(
    db: Session,
    settings: Settings,
    keyring: Keyring,
    update: AvailableUpdate,
    run: Callable[[list[str]], Any] | None = None,
) -> bool:
    """Start the root unit. The state is committed before systemctl runs: the
    upgrade stops this worker."""
    problems = blocking_problems(db, settings, update)
    if problems:
        update.state, update.error = "failed", "; ".join(problems)
        update.install_finished_at = utcnow()
        db.commit()
        return False
    refresh_stored_metadata(db, settings, keyring, update.version)
    update.state = "installing"
    update.install_started_at = utcnow()
    update.error = None
    db.commit()
    cmd = ["systemctl", "start", "--no-block", unit_name(update.version)]
    res = (
        run(cmd)
        if run
        else subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)  # noqa: S603
    )
    if getattr(res, "returncode", 1) != 0:
        update.state = "failed"
        update.install_finished_at = utcnow()
        update.error = (
            "The upgrade could not be started: "
            + ((getattr(res, "stderr", "") or "systemctl failed").strip()[:500])
        )
        db.commit()
        return False
    return True


def due_for_start(
    db: Session, now: datetime, calls_in_progress: Callable[[], int | None]
) -> AvailableUpdate | None:
    """The approved update to start now: "now" approvals at once, "window"
    approvals inside the open window when no call is in progress (§4)."""
    if db.scalar(select(AvailableUpdate).where(AvailableUpdate.state == "installing")):
        return None
    rows = list(
        db.scalars(
            select(AvailableUpdate)
            .where(AvailableUpdate.component == "veyra_core", AvailableUpdate.state == "approved")
            .order_by(AvailableUpdate.approved_at)
        )
    )
    for row in rows:
        if row.install_when == "now":
            return row
    if not rows:
        return None
    policy = db.get(UpdatePolicy, "veyra_core")
    if policy is None or not window_open(policy.maintenance_window, now):
        return None
    if calls_in_progress():
        return None
    return rows[0]


def auto_approve(db: Session, now: datetime) -> None:
    """Mode D: downloaded releases in an allowed category are approved for
    the window without an administrator (§4)."""
    policy = db.get(UpdatePolicy, "veyra_core")
    if policy is None or policy.mode != "auto_install_window":
        return
    for row in db.scalars(
        select(AvailableUpdate).where(
            AvailableUpdate.component == "veyra_core", AvailableUpdate.state == "downloaded"
        )
    ):
        if row.category in (policy.auto_install_categories or []):
            row.state, row.install_when = "approved", "window"
            row.approved_at, row.approved_by = now, "maintenance policy"


def reconcile(
    db: Session, settings: Settings, notify: Callable[[str, AvailableUpdate], None]
) -> None:
    """Finish an installation from the runner's status file (the new worker
    after a successful upgrade, or this one after a failure)."""
    row = db.scalar(select(AvailableUpdate).where(AvailableUpdate.state == "installing"))
    if row is None:
        return
    status = read_status(settings)
    started = row.install_started_at or utcnow()
    if (
        status
        and status.get("version") == row.version
        and status.get("state")
        in (
            "succeeded",
            "failed",
        )
    ):
        try:
            finished = datetime.fromisoformat(status.get("finished_at") or "")
        except ValueError:
            finished = utcnow()
        if finished < started:
            return  # an older attempt's file
        row.install_finished_at = finished
        if status["state"] == "succeeded" and __version__ == row.version:
            row.state, row.error = "installed", None
            shutil.rmtree(version_dir(settings, row.version), ignore_errors=True)
            supersede_older(db, settings)
            notify("installed", row)
        elif status["state"] == "failed":
            row.state = "failed"
            error = str(status.get("error") or "The upgrade failed.")
            if __version__ == row.version:
                # Failed after the switch (issue #88): the server already
                # runs the new release; a step after it did not finish.
                error = (
                    f"Veyra {row.version} is installed and running, but a later step "
                    f"failed: {error} Fix the cause and run the upgrade again "
                    "(sudo veyra updates install, or installer/upgrade.sh)."
                )
            row.error = error[:2000]
            notify("failed", row)
        return
    if (
        status is None or status.get("version") != row.version
    ) and utcnow() - started > START_TIMEOUT:
        row.state, row.install_finished_at = "failed", utcnow()
        row.error = "The upgrade did not start (no progress from veyra-upgrade@.service)."
        notify("failed", row)


def supersede_older(db: Session, settings: Settings) -> int:
    """Releases the installed version has overtaken leave the offer: a row
    that is still available, downloaded or failed, whose version is not newer
    than what runs now, becomes ``superseded`` (its download is removed).
    Called after every check and after a successful installation."""
    from veyra.updates.checker import installed_versions

    current = installed_versions(db)
    changed = 0
    for row in db.scalars(
        select(AvailableUpdate).where(
            AvailableUpdate.state.in_(("available", "downloaded", "failed"))
        )
    ):
        installed = current.get((row.component, row.target))
        if installed is None:
            continue
        try:
            older = Version.parse(row.version) <= Version.parse(installed)
        except ValueError:
            continue
        if not older:
            continue
        if row.component == "veyra_core":
            shutil.rmtree(version_dir(settings, row.version), ignore_errors=True)
        row.state, row.install_when, row.approved_at = "superseded", None, None
        changed += 1
    return changed


def version_order(rows: list[AvailableUpdate]) -> list[AvailableUpdate]:
    """Veyra's own releases before the modules, newest version first."""

    def version(r: AvailableUpdate) -> Version:
        try:
            return Version.parse(r.version)
        except ValueError:
            return Version.parse("0.0.0")

    newest_first = sorted(rows, key=version, reverse=True)
    return sorted(newest_first, key=lambda r: (r.component != "veyra_core", r.target))


# ------------------------------------------------------------ notifications


def mail_notifier(db: Session, settings: Settings) -> Callable[[str, AvailableUpdate], None]:
    """Email to the update recipients (§5); silent when there are none or
    email is off."""
    from veyra.core import mail
    from veyra.core.models import Installation

    recipients = [r for r in load_source(db).get("recipients", []) if r]
    smtp = mail.load_smtp_settings(db)
    inst = db.scalar(select(Installation))
    name = inst.name if inst else "Veyra"

    def notify(what: str, row: AvailableUpdate) -> None:
        if not recipients or not smtp.enabled:
            return
        subjects = {
            "available": f"Veyra {row.version} is available",
            "downloaded": f"Veyra {row.version} is downloaded and waiting for approval",
            "installed": f"Veyra {row.version} was installed",
            "failed": f"Installing Veyra {row.version} failed",
        }
        text = f"{subjects[what]} on {name}.\n\n"
        if what in ("available", "downloaded") and row.release_notes:
            text += f"Release notes:\n{row.release_notes}\n\n"
        if what == "failed" and row.error:
            text += (
                f"{row.error}\n\n"
                "The previous version keeps running unless the log says otherwise.\n\n"
            )
        text += "See System → Updates in Veyra.\n"
        address, from_name = mail.sender(smtp, name)
        try:
            for to in recipients:
                msg = mail.compose(
                    from_address=address,
                    from_name=from_name,
                    to=to,
                    subject=f"[{name}] {subjects[what]}",
                    text=text,
                )
                mail.enqueue(settings.mailqueue_dir, msg.as_bytes())
        except Exception as e:
            log.warning("Update email not queued: %s", e)

    return notify


# ------------------------------------------------------------- the worker


def process(
    db: Session,
    settings: Settings,
    keyring: Keyring,
    calls_in_progress: Callable[[], int | None],
    run: Callable[[list[str]], Any] | None = None,
    now: datetime | None = None,
) -> None:
    """One worker pass: finish, auto-download, auto-approve, start."""
    now = now or utcnow()
    notify = mail_notifier(db, settings)
    reconcile(db, settings, notify)
    policy = db.get(UpdatePolicy, "veyra_core")
    if policy is not None and (
        policy.mode in ("download_approve", "auto_install_window") or policy.auto_download
    ):
        newest = _newest_available(db)
        if newest is not None:
            try:
                download(db, settings, keyring, newest)
                notify("downloaded", newest)
            except (UpdateError, MetadataError, ValueError) as e:
                newest.error = f"Automatic download failed: {e}"[:2000]
                log.warning("Automatic download of %s failed: %s", newest.version, e)
    auto_approve(db, now)
    db.commit()
    row = due_for_start(db, now, calls_in_progress)
    if row is not None:
        log.info("Starting the upgrade to %s", row.version)
        start_install(db, settings, keyring, row, run=run)


def _newest_available(db: Session) -> AvailableUpdate | None:
    rows = [
        r
        for r in db.scalars(
            select(AvailableUpdate).where(
                AvailableUpdate.component == "veyra_core", AvailableUpdate.state == "available"
            )
        )
        if not r.error  # one failed automatic attempt per check; "Download" retries
    ]
    if not rows:
        return None
    best = max(rows, key=lambda r: Version.parse(r.version))
    if db.scalar(
        select(AvailableUpdate).where(
            AvailableUpdate.component == "veyra_core",
            AvailableUpdate.state.in_(("downloaded", "approved", "installing")),
        )
    ):
        return None
    try:
        if Version.parse(best.version) <= Version.parse(__version__):
            return None
    except ValueError:
        return None
    return best


# ------------------------------------------------------ system packages (§6)


_APT_LINE = re.compile(
    r"^(?P<name>[^/\s]+)/(?P<suites>\S+)\s+(?P<version>\S+)\s+(?P<arch>\S+)"
    r"(?:\s+\[upgradable from: (?P<from>[^\]]+)\])?"
)


def parse_apt_upgradable(text: str) -> list[dict[str, Any]]:
    out = []
    for line in text.splitlines():
        m = _APT_LINE.match(line.strip())
        if not m:
            continue
        name = m["name"]
        out.append(
            {
                "name": name,
                "version": m["version"],
                "from": m["from"],
                "security": "-security" in m["suites"],
                "telephony": name.startswith(("asterisk", "libpj")),
            }
        )
    out.sort(key=lambda p: (not p["security"], not p["telephony"], p["name"]))
    return out


def refresh_system_packages(db: Session, run: Callable[[list[str]], Any] | None = None) -> None:
    """Daily: what the package manager could upgrade (shown, never applied)."""
    row = db.get(SystemSetting, SYSTEM_PACKAGES_KEY)
    if row is not None:
        try:
            last = datetime.fromisoformat(row.value.get("checked_at", ""))
            if utcnow() - last < timedelta(hours=24):
                return
        except ValueError:
            pass
    cmd = ["apt", "list", "--upgradable"]
    try:
        res = (
            run(cmd)
            if run
            else subprocess.run(  # noqa: S603
                cmd, capture_output=True, text=True, timeout=120, check=False, env={"LC_ALL": "C"}
            )
        )
        packages, error = parse_apt_upgradable(getattr(res, "stdout", "")), None
        if getattr(res, "returncode", 1) != 0:
            error = (getattr(res, "stderr", "") or "apt failed").strip()[:500]
    except (OSError, subprocess.SubprocessError) as e:
        packages, error = [], str(e)[:500]
    value = {"checked_at": utcnow().isoformat(), "packages": packages, "error": error}
    if row is None:
        db.add(SystemSetting(key=SYSTEM_PACKAGES_KEY, value=value))
    else:
        row.value = value
