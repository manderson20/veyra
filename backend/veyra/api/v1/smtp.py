# SPDX-License-Identifier: AGPL-3.0-or-later
"""Email delivery settings (docs/VOICEMAIL_IVR.md §2): the SMTP server Veyra
sends through. Platform administrators only; the password is write-only."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from veyra.api.v1.extensions import installation_key
from veyra.configmgmt import service as configmgmt
from veyra.core import audit, mail
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError
from veyra.core.models import Installation, SystemSetting, User
from veyra.core.security.crypto import try_load_installation_key
from veyra.core.security.principal import Principal
from veyra.telephony import routing

router = APIRouter(prefix="/system/smtp", tags=["system"])


class SmtpSettingsIn(BaseModel):
    enabled: bool = False
    host: str = Field("", max_length=253)
    port: int = Field(587, ge=1, le=65535)
    security: Literal["starttls", "tls", "none"] = "starttls"
    username: str | None = Field(None, max_length=200)
    # Omitted: unchanged. Null or empty: removed.
    password: str | None = Field(None, max_length=500)
    from_address: str | None = Field(None, max_length=254)
    from_name: str | None = Field(None, max_length=100)

    @field_validator("from_address")
    @classmethod
    def _from(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return routing.check_email(v)


class SmtpSettingsOut(BaseModel):
    enabled: bool
    host: str
    port: int
    security: str
    username: str | None
    has_password: bool
    from_address: str | None
    from_name: str | None
    # What messages actually carry (defaults filled in).
    effective_from_address: str
    effective_from_name: str
    problems: list[str]
    queue: dict[str, int]
    updated_at: datetime | None


class TestOut(BaseModel):
    ok: bool
    message: str
    recipient: str


def _installation_name(db: Session) -> str:
    inst = db.scalar(select(Installation))
    return inst.name if inst else "Veyra"


def _out(request: Request, db: Session, s: mail.SmtpSettings) -> SmtpSettingsOut:
    address, name = mail.sender(s, _installation_name(db))
    row = db.get(SystemSetting, mail.SMTP_SETTINGS_KEY)
    return SmtpSettingsOut(
        enabled=s.enabled,
        host=s.host,
        port=s.port,
        security=s.security,
        username=s.username,
        has_password=s.has_password,
        from_address=s.from_address,
        from_name=s.from_name,
        effective_from_address=address,
        effective_from_name=name,
        problems=s.problems(),
        queue=mail.queue_summary(request.app.state.settings.mailqueue_dir),
        updated_at=getattr(row, "updated_at", None),
    )


@router.get("", response_model=SmtpSettingsOut, summary="Email delivery settings")
def get_smtp(
    request: Request,
    principal: Principal = Depends(require("system.settings.read")),
    db: Session = Depends(get_db),
) -> SmtpSettingsOut:
    return _out(request, db, mail.load_smtp_settings(db))


@router.put("", response_model=SmtpSettingsOut, summary="Change email delivery settings")
def put_smtp(
    body: SmtpSettingsIn,
    request: Request,
    principal: Principal = Depends(require("system.settings.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> SmtpSettingsOut:
    current = mail.load_smtp_settings(db)
    data: dict[str, Any] = body.model_dump(exclude={"password"})
    data["password_ciphertext"] = current.password_ciphertext
    if "password" in body.model_fields_set:
        if body.password:
            key = installation_key(request)
            data["password_ciphertext"] = key.encrypt(body.password, mail.SMTP_PASSWORD_PURPOSE)
        else:
            data["password_ciphertext"] = None
    try:
        new = mail.SmtpSettings.model_validate(data)
    except ValueError as e:
        raise ProblemError(
            422, "Validation failed", str(e).splitlines()[0], code="validation_failed"
        ) from e
    problems = new.problems()
    if problems:
        raise ProblemError(
            422,
            "Settings not saved",
            " ".join(problems),
            code="validation_failed",
            errors=[{"field": "settings", "message": p} for p in problems],
        )
    before = current.model_dump(mode="json")
    after = new.model_dump(mode="json")
    changed = {
        k: (after[k] if k != "password_ciphertext" else "[changed]")
        for k in after
        if before.get(k) != after[k]
    }
    mail.save_smtp_settings(db, new, updated_by=principal.user_id)
    # The sender address and the delivery switch are rendered into voicemail.conf.
    if any(k in changed for k in ("enabled", "from_address", "from_name")):
        configmgmt.mark_changed(db, by=principal.label, what="smtp.update")
    audit.record(
        db,
        action="smtp.update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="settings",
        target_id=mail.SMTP_SETTINGS_KEY,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"changed": changed},
    )
    db.commit()
    return _out(request, db, new)


@router.post("/test", response_model=TestOut, summary="Send a test message to yourself")
def test_smtp(
    request: Request,
    principal: Principal = Depends(require("system.settings.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> TestOut:
    user = db.get(User, principal.user_id)
    if user is None or not user.email:
        raise ProblemError(409, "No address", "Your account has no email address.", code="no_email")
    s = mail.load_smtp_settings(db)
    address, name = mail.sender(s, _installation_name(db))
    msg = mail.compose(
        from_address=address,
        from_name=name,
        to=user.email,
        subject=f"{name}: test message",
        text=(
            f"This test message was sent by {name} (Veyra) at the request of "
            f"{principal.label}.\n\nIf you can read it, email delivery works."
        ),
    )
    key = try_load_installation_key(request.app.state.settings)
    try:
        mail.send(s, key, msg)
    except mail.MailError as e:
        outcome, message = "failure", str(e)
    else:
        outcome, message = "success", f"Sent to {user.email}."
    audit.record(
        db,
        action="smtp.test",
        outcome=outcome,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        target_type="settings",
        target_id=mail.SMTP_SETTINGS_KEY,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"recipient": user.email, "message": message, "host": s.host},
    )
    db.commit()
    return TestOut(ok=outcome == "success", message=message, recipient=user.email)
