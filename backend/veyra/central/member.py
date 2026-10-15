# SPDX-License-Identifier: AGPL-3.0-or-later
"""This installation as an instance of a central console
(docs/CENTRAL_MANAGEMENT.md §2-5, §9).

The membership lives in ``system_settings`` (``central.membership``). The
worker checks in when due; nothing here listens for the console.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.central import policy as central_policy
from veyra.central import protocol, report
from veyra.core.config import Settings
from veyra.core.models import AvailableUpdate, Installation, SystemSetting, UpdatePolicy
from veyra.core.models.base import utcnow
from veyra.core.security.crypto import InstallationKey
from veyra.core.signing import Keyring
from veyra.version import __version__

KEY = "central.membership"
DEFAULT_ACCEPTED: dict[str, bool] = {
    **dict.fromkeys(central_policy.SECTIONS, True),
    "commands": True,
}
LOG_SIZE = 20


class MemberError(Exception):
    pass


def membership(db: Session) -> dict[str, Any]:
    row = db.get(SystemSetting, KEY)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


def _save(db: Session, value: dict[str, Any]) -> None:
    row = db.get(SystemSetting, KEY)
    if row is None:
        db.add(SystemSetting(key=KEY, value=value))
    else:
        row.value = value
    db.flush()


def enrolled(db: Session) -> bool:
    return bool(membership(db).get("console_url"))


def _instance(db: Session) -> Installation:
    inst = db.scalar(select(Installation))
    if inst is None:
        raise MemberError("Complete the setup first.")
    return inst


def enroll(
    db: Session,
    key: InstallationKey,
    *,
    url: str,
    token: str,
    fingerprint: str,
    ca_pem: str | None,
) -> dict[str, Any]:
    if enrolled(db):
        raise MemberError("This installation is already enrolled. Leave the console first.")
    try:
        url = protocol.check_console_url(url)
    except protocol.ProtocolError as e:
        raise MemberError(str(e)) from e
    inst = _instance(db)
    private, public = protocol.new_keypair()
    body = json.dumps(
        {
            "token": token.strip(),
            "instance_id": str(inst.instance_id),
            "name": inst.name,
            "version": __version__,
            "public_key": public,
        }
    ).encode()
    try:
        r, nonce = protocol.signed_post(
            url,
            protocol.ENROLL_PATH,
            body,
            instance_id=str(inst.instance_id),
            private_key=private,
            ca_pem=ca_pem or None,
        )
    except (protocol.ProtocolError, ValueError) as e:  # ValueError: a bad CA certificate
        raise MemberError(str(e)) from e
    if r.status_code != 200:
        raise MemberError(_problem(r, "The console refused the enrollment"))
    try:
        claimed = r.json().get("console_public_key", "")
        if protocol.normalize_fingerprint(
            protocol.fingerprint(claimed)
        ) != protocol.normalize_fingerprint(fingerprint):
            raise MemberError(
                "The console's key does not match the fingerprint you entered; nothing was saved."
            )
        answer = protocol.check_answer(r, claimed, nonce)
    except (protocol.ProtocolError, ValueError, AttributeError) as e:
        raise MemberError(str(e)) from e
    now = utcnow()
    value = {
        "console_url": url,
        "console_name": str(answer.get("console_name") or "")[:200],
        "console_public_key": claimed,
        "public_key": public,
        "private_key": key.encrypt(private, protocol.KEY_PURPOSE),
        "ca_pem": ca_pem or None,
        "accepted": dict(DEFAULT_ACCEPTED),
        "enrolled_at": now.isoformat(),
        "last_contact": now.isoformat(),
        "last_error": None,
        "next_check_in": int(answer.get("next_check_in") or 60),
        "policy": None,
        "pending_results": [],
        "log": [],
        "revoked": False,
    }
    _save(db, value)
    inst.central_management_enabled = True
    return value


def _problem(r: Any, fallback: str) -> str:
    try:
        data = r.json()
        return f"{fallback}: {data.get('detail') or data.get('title') or r.status_code}"
    except ValueError:
        return f"{fallback} (HTTP {r.status_code})."


def leave(db: Session) -> None:
    central_policy.clear(db)
    _save(db, {})
    _instance(db).central_management_enabled = False


def set_accepted(db: Session, accepted: dict[str, bool]) -> dict[str, Any]:
    value = membership(db)
    if not value:
        raise MemberError("This installation is not enrolled.")
    current = {**DEFAULT_ACCEPTED, **(value.get("accepted") or {})}
    for k, v in accepted.items():
        if k in DEFAULT_ACCEPTED:
            current[k] = bool(v)
    value["accepted"] = current
    # Re-apply the last policy so refused sections are withdrawn at once.
    pol = value.get("policy") or {}
    if pol.get("document") is not None:
        pol["results"] = central_policy.apply(db, _settings(), pol["document"], current)
        value["policy"] = pol
    _save(db, value)
    return value


def _settings() -> Settings:
    from veyra.core.config import get_settings

    return get_settings()


def due(db: Session) -> bool:
    value = membership(db)
    if not value.get("console_url") or value.get("revoked"):
        return False
    last = value.get("last_attempt") or value.get("last_contact")
    if not last:
        return True
    from datetime import datetime

    try:
        when = datetime.fromisoformat(str(last))
    except ValueError:
        return True
    return utcnow() - when >= timedelta(seconds=max(30, int(value.get("next_check_in") or 60)))


def check_in(
    db: Session,
    settings: Settings,
    key: InstallationKey,
    adapter: Any | None,
    keyring: Keyring | None = None,
) -> dict[str, Any]:
    """One check-in; returns the updated membership. Errors are recorded,
    never raised: an unreachable console is normal."""
    value = membership(db)
    if not value.get("console_url"):
        raise MemberError("This installation is not enrolled.")
    now = utcnow()
    value["last_attempt"] = now.isoformat()
    inst = _instance(db)
    pol = value.get("policy") or {}
    body = report.build(db, adapter)
    body["policy"] = {
        "id": pol.get("id"),
        "version": pol.get("version", 0),
        "results": pol.get("results") or {},
    }
    body["accepted"] = value.get("accepted") or DEFAULT_ACCEPTED
    body["command_results"] = list(value.get("pending_results") or [])
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True, default=str).encode()
    try:
        private = key.decrypt(str(value["private_key"]), protocol.KEY_PURPOSE)
        r, nonce = protocol.signed_post(
            str(value["console_url"]),
            protocol.CHECK_IN_PATH,
            raw,
            instance_id=str(inst.instance_id),
            private_key=private,
            ca_pem=value.get("ca_pem"),
        )
        if r.status_code == 403 and _code(r) == "revoked":
            value["revoked"] = True
            value["last_error"] = "Revoked by the central console."
            central_policy.clear(db)
            _save(db, value)
            return value
        if r.status_code != 200:
            raise protocol.ProtocolError(_problem(r, "The console refused the check-in"))
        answer = protocol.check_answer(r, str(value["console_public_key"]), nonce)
    except (protocol.ProtocolError, ValueError) as e:
        value["last_error"] = str(e)[:500]
        _save(db, value)
        return value
    value["pending_results"] = []
    value["last_contact"] = now.isoformat()
    value["last_error"] = None
    value["next_check_in"] = max(30, min(int(answer.get("next_check_in") or 60), 3600))
    accepted = {**DEFAULT_ACCEPTED, **(value.get("accepted") or {})}
    new_policy = answer.get("policy")
    if isinstance(new_policy, dict):
        document = new_policy.get("document") or {}
        results = central_policy.apply(db, settings, document, accepted)
        value["policy"] = {
            "id": new_policy.get("id"),
            "version": int(new_policy.get("version") or 0),
            "name": new_policy.get("name"),
            "document": document,
            "results": results,
            "applied_at": now.isoformat(),
        }
        _log(value, f"Policy {new_policy.get('name') or '(none)'} applied", results)
    for cmd in answer.get("commands") or []:
        if not isinstance(cmd, dict):
            continue
        outcome, message = run_command(
            db, settings, keyring, str(cmd.get("kind")), cmd.get("arguments") or {}, accepted
        )
        value["pending_results"].append(
            {"id": cmd.get("id"), "outcome": outcome, "message": message}
        )
        _log(value, f"Command {cmd.get('kind')}: {outcome}", message)
    _save(db, value)
    return value


def _code(r: Any) -> str | None:
    try:
        return str(r.json().get("code"))
    except (ValueError, AttributeError):
        return None


def _log(value: dict[str, Any], what: str, detail: Any) -> None:
    entry = {"at": utcnow().isoformat(), "what": what, "detail": detail}
    value["log"] = [entry, *list(value.get("log") or [])][:LOG_SIZE]


def run_command(
    db: Session,
    settings: Settings,
    keyring: Keyring | None,
    kind: str,
    arguments: dict[str, Any],
    accepted: dict[str, bool],
) -> tuple[str, str]:
    """(outcome, message) for one command (docs/CENTRAL_MANAGEMENT.md §5)."""
    if not accepted.get("commands", True):
        return "refused", "This installation does not accept commands from the console."
    keyring = keyring or Keyring.load(settings.trust_dir)
    try:
        if kind == "check_updates":
            from veyra.updates.checker import check_for_updates

            check = check_for_updates(db, settings, keyring)
            db.flush()
            return ("ok" if check.outcome == "ok" else "failed"), (check.message or check.outcome)
        if kind == "refresh_catalogs":
            from veyra.modules import catalog

            n = catalog.refresh_due(db, settings.trust_dir)
            return "ok", f"{n} catalog(s) refreshed."
        version = str(arguments.get("version") or "")
        row = db.scalar(
            select(AvailableUpdate)
            .where(AvailableUpdate.component == "veyra_core", AvailableUpdate.version == version)
            .order_by(AvailableUpdate.created_at.desc())
            .limit(1)
        )
        if row is None:
            return "failed", f"Version {version} is not among the available updates; check first."
        if kind == "download_update":
            from veyra.updates import manager

            if row.state not in ("available", "failed"):
                return "failed", f"The update is {row.state}."
            manager.download(db, settings, keyring, row)
            return "ok", f"{version} downloaded and verified."
        if kind == "approve_update":
            return _approve(db, settings, row, str(arguments.get("when") or ""))
    except Exception as e:  # a failed command is reported, never fatal
        return "failed", f"{type(e).__name__}: {e}"[:500]
    return "refused", f"Unknown command {kind!r}."


def _approve(db: Session, settings: Settings, row: AvailableUpdate, when: str) -> tuple[str, str]:
    from veyra.updates import manager

    if when not in ("now", "window"):
        return "failed", "Approve 'now' or in the 'window'."
    if row.state != "downloaded":
        return "failed", "Download the update first."
    problems = manager.blocking_problems(db, settings, row)
    if problems:
        return "failed", "; ".join(problems)
    if when == "window":
        pol = db.get(UpdatePolicy, "veyra_core")
        if pol is None or not pol.maintenance_window:
            return "failed", "This installation has no maintenance window."
    row.state, row.install_when = "approved", when
    row.approved_at, row.approved_by = utcnow(), "Central console"
    row.error = None
    return "ok", f"{row.version} approved ({when})."
