# SPDX-License-Identifier: AGPL-3.0-or-later
"""First-run setup.

Setup can run exactly once, while no user exists, and only with the one-time
setup token printed on the server console by the installer
(``sudo veyra setup-token`` creates a new one).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from veyra.api.v1.auth import SessionOut, _session_out, _set_cookies
from veyra.api.v1.schemas import Email, OrganizationIn
from veyra.core import audit, bootstrap, tenancy
from veyra.core.config import Settings, get_settings
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context
from veyra.core.errors import ProblemError
from veyra.core.models import Installation, Organization, Role, RoleAssignment, SystemSetting, User
from veyra.core.models.base import utcnow
from veyra.core.security import mfa, passwords
from veyra.core.security.sessions import create_session, load_principal
from veyra.telephony.numbering import NumberingPlan, save_numbering_plan

router = APIRouter(prefix="/setup", tags=["setup"])

# Wizard steps. ``available`` is False for what is set up after the wizard,
# in the place ``after`` names (the UI lists them instead of inert controls).
STEPS = [
    {"key": "administrator", "title": "Administrator account", "available": True},
    {"key": "organization", "title": "Organization", "available": True},
    {"key": "installation", "title": "Installation name and time zone", "available": True},
    {
        "key": "network",
        "title": "SIP and media addresses",
        "available": False,
        "after": "System → Telephony Engine",
    },
    {"key": "telephony", "title": "Telephony engine check", "available": True},
    {"key": "numbering", "title": "Extension numbering plan", "available": True},
    {"key": "sip", "title": "Outside lines", "available": False, "after": "Telephony → SIP Trunks"},
    {"key": "email", "title": "Email delivery", "available": False, "after": "System → Settings"},
    {"key": "backup", "title": "Backups", "available": False, "after": "System → Backups"},
    {
        "key": "updates",
        "title": "Update preferences",
        "available": False,
        "after": "System → Updates",
    },
    {
        "key": "ha",
        "title": "High availability (optional)",
        "available": False,
        "after": "System → High Availability",
    },
]


class SetupStatus(BaseModel):
    setup_required: bool
    token_issued: bool
    steps: list[dict[str, object]]
    # Engine check for the wizard: the state only, never the version (public endpoint).
    telephony_engine: str
    telephony_state: str


class AdminIn(BaseModel):
    email: Email
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


class SetupIn(BaseModel):
    setup_token: str = Field(min_length=1, max_length=200)
    installation_name: str = Field(min_length=1, max_length=200)
    administrator: AdminIn
    organization: OrganizationIn
    # Optional: the defaults (4 digits, 1000-7999) apply when omitted.
    numbering: NumberingPlan | None = None


@router.get("/status", response_model=SetupStatus, summary="Whether first-run setup is required")
def status(request: Request, db: Session = Depends(get_db)) -> SetupStatus:
    health = request.app.state.telephony.health()
    return SetupStatus(
        setup_required=bootstrap.setup_required(db),
        token_issued=db.get(SystemSetting, bootstrap.SETUP_TOKEN_KEY) is not None,
        steps=STEPS,
        telephony_engine=health.engine,
        telephony_state=health.state,
    )


@router.post("/initialize", response_model=SessionOut, summary="Complete first-run setup")
def initialize(
    body: SetupIn,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> SessionOut:
    # Serialize concurrent attempts; the advisory lock is released at commit/rollback.
    db.execute(text("SELECT pg_advisory_xact_lock(7461001)"))
    if not bootstrap.setup_required(db):
        raise ProblemError(
            409,
            "Setup already completed",
            "This installation has already been set up.",
            code="setup_completed",
        )
    if not bootstrap.check_setup_token(db, body.setup_token):
        audit.record(
            db,
            action="setup.initialize",
            outcome="denied",
            actor_label="anonymous",
            ip_address=ctx.ip,
            request_id=ctx.request_id,
            details={"reason": "bad_token"},
        )
        db.commit()
        raise ProblemError(
            403,
            "Invalid setup token",
            "The setup token is missing, expired or incorrect. Run "
            "'sudo veyra setup-token' on the server to issue a new one.",
            code="invalid_setup_token",
        )
    if body.numbering is not None:
        problems = body.numbering.problems()
        if problems:
            raise ProblemError(
                422,
                "Validation failed",
                " ".join(problems),
                code="validation_failed",
                errors=[{"field": "numbering", "message": p} for p in problems],
            )
    try:
        passwords.validate_password(body.administrator.password, email=body.administrator.email)
    except passwords.PasswordPolicyError as e:
        raise ProblemError(
            422,
            "Validation failed",
            str(e),
            code="password_policy",
            errors=[{"field": "administrator.password", "message": str(e)}],
        ) from e

    inst = bootstrap.bootstrap(db)
    inst.name = body.installation_name
    inst.setup_completed_at = utcnow()
    if body.numbering is not None:
        save_numbering_plan(db, body.numbering)

    org = Organization(
        id=uuid.uuid4(),
        name=body.organization.name,
        slug=body.organization.slug,
        timezone=body.organization.timezone,
        engine_namespace=tenancy.new_namespace(db, body.organization.slug),
    )
    db.add(org)
    db.flush()  # organization must exist before the user that references it
    user = User(
        id=uuid.uuid4(),
        email=body.administrator.email,
        display_name=body.administrator.display_name,
        password_hash=passwords.hash_password(body.administrator.password),
        is_recovery_admin=True,
        home_organization_id=org.id,
    )
    db.add(user)
    db.flush()
    role = db.scalar(select(Role).where(Role.key == "platform_admin", Role.is_system.is_(True)))
    assert role is not None
    db.add(RoleAssignment(id=uuid.uuid4(), user_id=user.id, role_id=role.id, scope_type="platform"))
    db.flush()
    # The policy requires a second factor for platform administrators by
    # default: the enrolment window starts now (docs/MFA_DESIGN.md §7).
    policy = mfa.load_policy(db)
    mfa.ensure_requirement(user, policy, mfa.is_required(db, policy, user), utcnow())
    bootstrap.consume_setup_token(db)
    bootstrap.ensure_local_node(db)
    audit.record(
        db,
        action="setup.initialize",
        actor_user_id=user.id,
        actor_label=user.email,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={
            "organization": org.slug,
            "installation_name": inst.name,
            "numbering": body.numbering.model_dump(mode="json") if body.numbering else None,
        },
    )
    token, csrf, session = create_session(db, user, settings, ip=ctx.ip, user_agent=ctx.user_agent)
    db.commit()
    _set_cookies(response, settings, token, csrf)
    assert isinstance(inst, Installation)
    return _session_out(db, user, load_principal(db, user, session.id), csrf)
