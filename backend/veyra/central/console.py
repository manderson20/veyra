# SPDX-License-Identifier: AGPL-3.0-or-later
"""The central console (docs/CENTRAL_MANAGEMENT.md §2-6): enrollment,
check-ins, policies and commands, as seen from the console installation."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.central import protocol
from veyra.central.policy import validate_document
from veyra.core.models import (
    CentralCommand,
    CentralEnrollmentToken,
    CentralInstance,
    CentralNonce,
    CentralPolicy,
    CentralSample,
    Installation,
    SystemSetting,
)
from veyra.core.models.base import utcnow
from veyra.core.security import tokens
from veyra.core.security.crypto import InstallationKey

STATE_KEY = "central.console"
TOKEN_TTL = timedelta(hours=24)
COMMAND_TTL = timedelta(hours=24)
SAMPLE_EVERY = timedelta(minutes=5)
KEEP_SAMPLES = timedelta(days=30)
CHECK_IN_SECONDS = 60
DEFAULT_OFFLINE_MINUTES = 10
COMMANDS = ("check_updates", "download_update", "approve_update", "refresh_catalogs")


class CentralError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# --------------------------------------------------------------------- state


def state(db: Session) -> dict[str, Any]:
    row = db.get(SystemSetting, STATE_KEY)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


def _save(db: Session, value: dict[str, Any]) -> None:
    row = db.get(SystemSetting, STATE_KEY)
    if row is None:
        db.add(SystemSetting(key=STATE_KEY, value=value))
    else:
        row.value = value
    db.flush()


def enabled(db: Session) -> bool:
    return bool(state(db).get("enabled"))


def set_enabled(db: Session, on: bool, key: InstallationKey) -> dict[str, Any]:
    """Turning the console on creates its signing key once; it is kept when
    the console is turned off, so enrolled instances recognise it later."""
    value = state(db)
    if on and not value.get("public_key"):
        private, public = protocol.new_keypair()
        value["public_key"] = public
        value["private_key"] = key.encrypt(private, protocol.KEY_PURPOSE)
    value["enabled"] = on
    value.setdefault("offline_minutes", DEFAULT_OFFLINE_MINUTES)
    _save(db, value)
    return value


def set_offline_minutes(db: Session, minutes: int) -> None:
    value = state(db)
    value["offline_minutes"] = max(2, min(int(minutes), 1440))
    _save(db, value)


def _private_key(db: Session, key: InstallationKey) -> str:
    value = state(db)
    if not value.get("private_key"):
        raise CentralError(409, "console_off", "This installation is not a central console.")
    return key.decrypt(str(value["private_key"]), protocol.KEY_PURPOSE)


def public_key(db: Session) -> str | None:
    return state(db).get("public_key")


# --------------------------------------------------------------------- tokens


def create_token(
    db: Session, *, label: str | None, policy_id: uuid.UUID | None, created_by: str
) -> tuple[str, CentralEnrollmentToken]:
    raw = "vye_" + tokens.new_token(24)
    now = utcnow()
    row = CentralEnrollmentToken(
        id=uuid.uuid4(),
        token_hash=tokens.digest(raw),
        label=label,
        policy_id=policy_id,
        created_by=created_by,
        created_at=now,
        expires_at=now + TOKEN_TTL,
    )
    db.add(row)
    db.flush()
    return raw, row


# --------------------------------------------------------------------- requests


def _parse(body: bytes) -> dict[str, Any]:
    try:
        data = json.loads(body)
    except ValueError as e:
        raise CentralError(400, "bad_request", "The request is not JSON.") from e
    if not isinstance(data, dict):
        raise CentralError(400, "bad_request", "The request is not a JSON object.")
    return data


def _check_signature(
    db: Session, public: str, path: str, body: bytes, headers: dict[str, str]
) -> str:
    ts = headers.get(protocol.H_TIMESTAMP.lower(), "")
    nonce = headers.get(protocol.H_NONCE.lower(), "")
    sig = headers.get(protocol.H_SIGNATURE.lower(), "")
    if not (ts and nonce and sig) or len(nonce) > 64:
        raise CentralError(401, "unsigned", "The request is not signed.")
    if not protocol.fresh(ts):
        raise CentralError(401, "stale", "The request's time is off by more than five minutes.")
    if not protocol.verify(public, protocol.request_string("POST", path, ts, nonce, body), sig):
        raise CentralError(401, "bad_signature", "The request's signature is not valid.")
    try:
        with db.begin_nested():
            db.add(CentralNonce(nonce=nonce, seen_at=utcnow()))
    except IntegrityError as e:
        raise CentralError(401, "replayed", "This request was already received.") from e
    return nonce


def _answer(
    db: Session, key: InstallationKey, nonce: str, payload: dict[str, Any]
) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return body, protocol.sign_answer(_private_key(db, key), nonce, body)


def enroll(
    db: Session,
    key: InstallationKey,
    body: bytes,
    headers: dict[str, str],
    address: str | None,
) -> tuple[bytes, dict[str, str], CentralInstance]:
    if not enabled(db):
        raise CentralError(404, "console_off", "This installation is not a central console.")
    data = _parse(body)
    public = str(data.get("public_key") or "")
    try:
        instance_id = uuid.UUID(str(data.get("instance_id")))
        protocol.fingerprint(public)
    except (ValueError, TypeError) as e:
        raise CentralError(400, "bad_request", "The instance identity is not valid.") from e
    nonce = _check_signature(db, public, protocol.ENROLL_PATH, body, headers)
    token = db.scalar(
        select(CentralEnrollmentToken).where(
            CentralEnrollmentToken.token_hash == tokens.digest(str(data.get("token") or ""))
        )
    )
    now = utcnow()
    if token is None or token.used_at is not None or token.expires_at < now:
        raise CentralError(403, "bad_token", "The enrollment token is not valid or was used.")
    token.used_at, token.used_by = now, instance_id
    inst = db.get(CentralInstance, instance_id)
    if inst is None:
        inst = CentralInstance(instance_id=instance_id, enrolled_at=now)
        db.add(inst)
    inst.name = str(data.get("name") or "Veyra")[:200]
    inst.version = str(data.get("version") or "")[:64] or None
    inst.public_key = public
    inst.label = token.label or inst.label
    inst.policy_id = token.policy_id or inst.policy_id or default_policy_id(db)
    inst.revoked_at = None
    inst.enrolled_at = now
    inst.last_seen_at, inst.last_address = now, address
    db.flush()
    console = db.scalar(select(Installation))
    out, sig = _answer(
        db,
        key,
        nonce,
        {
            "console_public_key": public_key(db),
            "console_name": console.name if console else "Veyra",
            "next_check_in": CHECK_IN_SECONDS,
        },
    )
    return out, sig, inst


def default_policy_id(db: Session) -> uuid.UUID | None:
    return db.scalar(select(CentralPolicy.id).where(CentralPolicy.is_default.is_(True)))


def policy_of(db: Session, inst: CentralInstance) -> CentralPolicy | None:
    pid = inst.policy_id or default_policy_id(db)
    return db.get(CentralPolicy, pid) if pid else None


def check_in(
    db: Session,
    key: InstallationKey,
    body: bytes,
    headers: dict[str, str],
    address: str | None,
) -> tuple[bytes, dict[str, str]]:
    if not enabled(db):
        raise CentralError(404, "console_off", "This installation is not a central console.")
    try:
        instance_id = uuid.UUID(headers.get(protocol.H_INSTANCE.lower(), ""))
    except ValueError as e:
        raise CentralError(401, "unknown_instance", "Unknown instance.") from e
    inst = db.get(CentralInstance, instance_id)
    if inst is None:
        raise CentralError(401, "unknown_instance", "Unknown instance.")
    nonce = _check_signature(db, inst.public_key, protocol.CHECK_IN_PATH, body, headers)
    if inst.revoked_at is not None:
        raise CentralError(403, "revoked", "This instance was revoked by the central console.")
    report = _parse(body)
    now = utcnow()
    _store_report(db, inst, report, now, address)
    _store_results(db, inst, report.get("command_results"))
    payload: dict[str, Any] = {"next_check_in": CHECK_IN_SECONDS, "commands": []}
    policy = policy_of(db, inst)
    raw_policy = report.get("policy")
    applied: dict[str, Any] = raw_policy if isinstance(raw_policy, dict) else {}
    wanted = (str(policy.id), policy.version) if policy else (None, 0)
    if (applied.get("id"), applied.get("version")) != wanted:
        payload["policy"] = {
            "id": wanted[0],
            "version": wanted[1],
            "name": policy.name if policy else None,
            "document": policy.document if policy else {},
        }
    for cmd in db.scalars(
        select(CentralCommand)
        .where(
            CentralCommand.instance_id == inst.instance_id,
            CentralCommand.delivered_at.is_(None),
            CentralCommand.expires_at > now,
        )
        .order_by(CentralCommand.created_at)
    ):
        cmd.delivered_at = now
        payload["commands"].append(
            {"id": str(cmd.id), "kind": cmd.kind, "arguments": cmd.arguments}
        )
    db.flush()
    return _answer(db, key, nonce, payload)


def _store_report(
    db: Session, inst: CentralInstance, report: dict[str, Any], now: datetime, address: str | None
) -> None:
    clean = {k: v for k, v in report.items() if k != "command_results"}
    inst.last_report = clean
    inst.last_seen_at = now
    inst.last_address = address
    identity = report.get("identity") or {}
    if isinstance(identity, dict):
        inst.name = str(identity.get("name") or inst.name)[:200]
        inst.version = str(identity.get("version") or inst.version or "")[:64] or None
    last = db.scalar(
        select(CentralSample.at)
        .where(CentralSample.instance_id == inst.instance_id)
        .order_by(CentralSample.at.desc())
        .limit(1)
    )
    if last is None or now - last >= SAMPLE_EVERY:
        tel = report.get("telephony") or {}

        def num(v: Any) -> int | None:
            return int(v) if isinstance(v, int) and not isinstance(v, bool) else None

        db.add(
            CentralSample(
                id=uuid.uuid4(),
                instance_id=inst.instance_id,
                at=now,
                registered=num(tel.get("registered")),
                active_calls=num(tel.get("active_calls")),
                extensions=num(tel.get("extensions")),
                alerts=len(report.get("alerts") or []),
                status=str((report.get("health") or {}).get("status") or "unknown")[:16],
            )
        )


def _store_results(db: Session, inst: CentralInstance, results: Any) -> None:
    if not isinstance(results, list):
        return
    for r in results[:50]:
        if not isinstance(r, dict):
            continue
        try:
            cmd = db.get(CentralCommand, uuid.UUID(str(r.get("id"))))
        except ValueError:
            continue
        if cmd is None or cmd.instance_id != inst.instance_id or cmd.completed_at is not None:
            continue
        outcome = str(r.get("outcome") or "failed")
        cmd.outcome = outcome if outcome in ("ok", "failed", "refused") else "failed"
        cmd.message = str(r.get("message") or "")[:2000] or None
        cmd.completed_at = utcnow()


# --------------------------------------------------------------------- management


def status_of(inst: CentralInstance, offline_minutes: int, now: datetime | None = None) -> str:
    now = now or utcnow()
    if inst.revoked_at is not None:
        return "revoked"
    if inst.last_seen_at is None or now - inst.last_seen_at > timedelta(minutes=offline_minutes):
        return "offline"
    health = ((inst.last_report or {}).get("health") or {}).get("status")
    return str(health) if health in ("ok", "degraded", "failed") else "online"


def queue_command(
    db: Session,
    inst: CentralInstance,
    kind: str,
    arguments: dict[str, Any],
    created_by: str,
) -> CentralCommand:
    if kind not in COMMANDS:
        raise CentralError(422, "unknown_command", f"Unknown command {kind!r}.")
    if kind in ("download_update", "approve_update") and not str(arguments.get("version") or ""):
        raise CentralError(422, "version_required", "Name the version.")
    if kind == "approve_update" and arguments.get("when") not in ("now", "window"):
        raise CentralError(422, "when_required", "Approve 'now' or in the 'window'.")
    if inst.revoked_at is not None:
        raise CentralError(409, "revoked", "The instance is revoked.")
    now = utcnow()
    cmd = CentralCommand(
        id=uuid.uuid4(),
        instance_id=inst.instance_id,
        kind=kind,
        arguments={k: arguments[k] for k in ("version", "when") if k in arguments},
        created_by=created_by,
        created_at=now,
        expires_at=now + COMMAND_TTL,
    )
    db.add(cmd)
    db.flush()
    return cmd


def save_policy(
    db: Session,
    policy: CentralPolicy | None,
    *,
    name: str,
    description: str | None,
    document: dict[str, Any],
    is_default: bool,
) -> CentralPolicy:
    try:
        parsed = validate_document(document)
    except ValueError as e:
        raise CentralError(422, "bad_policy", str(e)) from e
    clean = parsed.model_dump(mode="json", exclude_none=True)
    if policy is None:
        policy = CentralPolicy(id=uuid.uuid4(), name=name, document=clean, version=1)
        db.add(policy)
    else:
        if policy.document != clean:
            policy.version += 1
        policy.document = clean
        policy.name = name
    policy.description = description
    if is_default:
        for other in db.scalars(select(CentralPolicy).where(CentralPolicy.is_default.is_(True))):
            other.is_default = False
    policy.is_default = is_default
    db.flush()
    return policy


def expire_and_prune(db: Session, now: datetime | None = None) -> None:
    now = now or utcnow()
    for cmd in db.scalars(
        select(CentralCommand).where(
            CentralCommand.completed_at.is_(None), CentralCommand.expires_at < now
        )
    ):
        cmd.outcome, cmd.completed_at = "expired", now
        cmd.message = "Not delivered or not answered within 24 hours."
    db.execute(delete(CentralNonce).where(CentralNonce.seen_at < now - timedelta(minutes=10)))
    db.execute(delete(CentralSample).where(CentralSample.at < now - KEEP_SAMPLES))
