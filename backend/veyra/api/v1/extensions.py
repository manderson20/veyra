# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extensions: numbers, SIP credentials and caller ID, scoped by organization.

Changing an extension changes only the database. The engine takes the change
when a configuration revision is generated and deployed (System → Telephony
Engine, or ``veyra config generate --deploy``); ``GET /telephony/engine``
reports ``changes_pending`` until then.
"""

from __future__ import annotations

import re
import secrets
import string
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, func, literal, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1.group_helpers import MembershipOut
from veyra.configmgmt import service as configmgmt
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.events import Event, bus
from veyra.core.models import (
    CallQueue,
    Extension,
    Organization,
    PickupGroup,
    PickupGroupMember,
    QueueMember,
    RingGroup,
    RingGroupMember,
    User,
)
from veyra.core.models.base import utcnow
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.crypto import (
    InstallationKey,
    InstallationKeyError,
    load_installation_key,
)
from veyra.core.security.principal import Principal
from veyra.telephony.adapter import Capability, EngineUnavailable, NotSupported
from veyra.telephony.numbering import (
    NumberingPlan,
    load_numbering_plan,
    number_owner,
    used_numbers,
)
from veyra.telephony.settings import load_sip_settings
from veyra.telephony.snapshot import secret_purpose

router = APIRouter(prefix="/extensions", tags=["extensions"])

# SIP secrets: letters and digits only, because phone web interfaces and
# provisioning formats disagree about which symbols they accept. 24
# characters from 62 symbols is about 143 bits.
SECRET_ALPHABET = string.ascii_letters + string.digits
SECRET_LENGTH = 24
_CALLER_ID_NUMBER_RE = re.compile(r"^[0-9+]{1,32}$")
_CALLER_ID_NAME_RE = re.compile(r"^[\w .'&()-]{1,60}$", re.UNICODE)


def new_sip_secret() -> str:
    return "".join(secrets.choice(SECRET_ALPHABET) for _ in range(SECRET_LENGTH))


def installation_key(request: Request) -> InstallationKey:
    try:
        return load_installation_key(request.app.state.settings)
    except InstallationKeyError as e:
        raise ProblemError(
            503,
            "Installation key unavailable",
            f"SIP secrets cannot be stored or read: {e}",
            code="installation_key_missing",
        ) from e


# ----------------------------------------------------------------- schemas


def _caller_id_name(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if not _CALLER_ID_NAME_RE.match(v):
        raise ValueError("letters, digits, spaces and . ' & ( ) - only, at most 60 characters")
    return v


def _caller_id_number(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if not _CALLER_ID_NUMBER_RE.match(v):
        raise ValueError("digits (and a leading +) only")
    return v


class ExtensionIn(BaseModel):
    organization_id: uuid.UUID
    number: str = Field(min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=200)
    user_id: uuid.UUID | None = None
    caller_id_name: str | None = Field(None, max_length=80)
    caller_id_number: str | None = Field(None, max_length=32)
    emergency_caller_id_number: str | None = Field(None, max_length=32)
    is_enabled: bool = True

    @field_validator("number")
    @classmethod
    def _number(cls, v: str) -> str:
        return v.strip()

    @field_validator("display_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        return v

    @field_validator("caller_id_name")
    @classmethod
    def _cid_name(cls, v: str | None) -> str | None:
        return _caller_id_name(v)

    @field_validator("caller_id_number", "emergency_caller_id_number")
    @classmethod
    def _cid_number(cls, v: str | None) -> str | None:
        return _caller_id_number(v)


class ExtensionPatch(BaseModel):
    number: str | None = Field(None, min_length=1, max_length=32)
    display_name: str | None = Field(None, min_length=1, max_length=200)
    user_id: uuid.UUID | None = None
    caller_id_name: str | None = Field(None, max_length=80)
    caller_id_number: str | None = Field(None, max_length=32)
    emergency_caller_id_number: str | None = Field(None, max_length=32)
    is_enabled: bool | None = None

    @field_validator("number")
    @classmethod
    def _number(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else None

    @field_validator("display_name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        return v

    @field_validator("caller_id_name")
    @classmethod
    def _cid_name(cls, v: str | None) -> str | None:
        return _caller_id_name(v)

    @field_validator("caller_id_number", "emergency_caller_id_number")
    @classmethod
    def _cid_number(cls, v: str | None) -> str | None:
        return _caller_id_number(v)


class RegistrationOut(BaseModel):
    registered: bool
    # Channels currently up on this endpoint (0 when idle).
    channels: int = 0


class ExtensionOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    number: str
    display_name: str
    endpoint_name: str
    user_id: uuid.UUID | None
    user_display_name: str | None
    user_email: str | None
    caller_id_name: str | None
    caller_id_number: str | None
    # Presented on emergency routes instead of the regular caller ID
    # (docs/TRUNKS_ROUTING.md §7).
    emergency_caller_id_number: str | None
    is_enabled: bool
    sip_secret_set: bool
    sip_secret_changed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Live state from the engine; None when the engine cannot report it.
    registration: RegistrationOut | None = None
    # Groups the extension belongs to (docs/RING_GROUPS_QUEUES.md).
    ring_groups: list[MembershipOut] = []
    queues: list[MembershipOut] = []
    pickup_groups: list[MembershipOut] = []


class SipCredentialsOut(BaseModel):
    """Shown on request to administrators with ``extensions.write``; every
    request is audited."""

    extension_id: uuid.UUID
    number: str
    username: str
    secret: str
    udp_port: int
    tcp_port: int | None
    tls_port: int | None
    rotated_at: datetime | None


class NextNumberOut(BaseModel):
    number: str | None
    plan: str
    message: str | None = None


# ----------------------------------------------------------------- helpers


def _visible(principal: Principal, permission: str) -> Select[Extension]:
    stmt = select(Extension)
    orgs = principal.organization_ids_with(permission)
    if orgs is not None:
        stmt = stmt.where(Extension.organization_id.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _get_visible(
    db: Session, principal: Principal, extension_id: uuid.UUID, permission: str
) -> Extension:
    ext = db.scalar(_visible(principal, permission).where(Extension.id == extension_id))
    if ext is None:
        raise not_found("Extension")
    return ext


def _registrations(request: Request | None) -> dict[str, RegistrationOut] | None:
    """Endpoint name -> live registration, one engine call per request."""
    if request is None:
        return None
    adapter = request.app.state.telephony
    if Capability.ENDPOINT_STATUS not in adapter.capabilities():
        return None
    try:
        return {
            s.endpoint: RegistrationOut(registered=s.registered, channels=len(s.contacts))
            for s in adapter.endpoint_statuses()
        }
    except (EngineUnavailable, NotSupported):
        return None


def _memberships(
    db: Session, extension_ids: set[uuid.UUID]
) -> dict[str, dict[uuid.UUID, list[MembershipOut]]]:
    """Ring groups, queues and pickup groups per extension."""
    out: dict[str, dict[uuid.UUID, list[MembershipOut]]] = {
        "ring_groups": {},
        "queues": {},
        "pickup_groups": {},
    }
    if not extension_ids:
        return out
    for key, link, group, key_col in (
        ("ring_groups", RingGroupMember, RingGroup, RingGroupMember.group_id),
        ("queues", QueueMember, CallQueue, QueueMember.queue_id),
        ("pickup_groups", PickupGroupMember, PickupGroup, PickupGroupMember.group_id),
    ):
        number: Any = getattr(group, "number", literal(None))
        stmt = (
            select(link.extension_id, group.id, group.name, number)
            .join(group, group.id == key_col)
            .where(link.extension_id.in_(extension_ids))
            .order_by(group.name)
        )
        for ext_id, gid, name, num in db.execute(stmt):
            out[key].setdefault(ext_id, []).append(MembershipOut(id=gid, name=name, number=num))
    return out


def _outs(db: Session, rows: list[Extension], request: Request | None = None) -> list[ExtensionOut]:
    live = _registrations(request)
    groups = _memberships(db, {r.id for r in rows})
    org_ids = {r.organization_id for r in rows}
    user_ids = {r.user_id for r in rows if r.user_id}
    orgs = (
        {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids)))}
        if org_ids
        else {}
    )
    users = (
        {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}
    )
    out = []
    for r in rows:
        org = orgs.get(r.organization_id)
        user = users.get(r.user_id) if r.user_id else None
        out.append(
            ExtensionOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=org.name if org else "",
                organization_slug=org.slug if org else "",
                number=r.number,
                display_name=r.display_name,
                endpoint_name=r.endpoint_name,
                user_id=r.user_id,
                user_display_name=user.display_name if user else None,
                user_email=user.email if user else None,
                caller_id_name=r.caller_id_name,
                caller_id_number=r.caller_id_number,
                emergency_caller_id_number=r.emergency_caller_id_number,
                is_enabled=r.is_enabled,
                sip_secret_set=bool(r.sip_secret_ciphertext),
                sip_secret_changed_at=r.sip_secret_changed_at,
                created_at=r.created_at,
                updated_at=r.updated_at,
                registration=(
                    live.get(r.endpoint_name, RegistrationOut(registered=False))
                    if live is not None
                    else None
                ),
                ring_groups=groups["ring_groups"].get(r.id, []),
                queues=groups["queues"].get(r.id, []),
                pickup_groups=groups["pickup_groups"].get(r.id, []),
            )
        )
    return out


def _out(db: Session, ext: Extension, request: Request | None = None) -> ExtensionOut:
    return _outs(db, [ext], request)[0]


def _validation(field: str, message: str, code: str = "validation_failed") -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code=code,
        errors=[{"field": field, "message": message}],
    )


def _check_number(
    db: Session,
    plan: NumberingPlan,
    number: str,
    exclude: uuid.UUID | None,
    organization_id: uuid.UUID,
) -> None:
    problems = plan.check_number(number)
    if problems:
        raise _validation("number", " ".join(problems), code="number_not_in_plan")
    # Numbers are unique across the organization's extensions, groups and
    # queues (docs/MULTI_TENANCY.md §3); number_owner takes the advisory lock
    # that serialises concurrent creations of the same number.
    owner = number_owner(
        db,
        number,
        organization_id=organization_id,
        exclude=("extension", exclude) if exclude else None,
    )
    if owner is not None:
        raise ProblemError(
            409,
            "Number in use",
            f"{owner.capitalize()} {number} already exists.",
            code="number_in_use",
            errors=[{"field": "number", "message": f"already used by a {owner}"}],
        )


def _check_user(db: Session, user_id: uuid.UUID | None, organization_id: uuid.UUID) -> None:
    if user_id is None:
        return
    user = db.get(User, user_id)
    if user is None:
        raise _validation("user_id", "That user does not exist.")
    if user.home_organization_id != organization_id:
        raise _validation("user_id", "The user belongs to a different organization.")


def _endpoint_name(org: Organization, number: str) -> str:
    return f"{org.slug}-{number}"


def _set_secret(ext: Extension, key: InstallationKey) -> str:
    secret = new_sip_secret()
    ext.sip_secret_ciphertext = key.encrypt(secret, secret_purpose(ext.id))
    ext.sip_secret_changed_at = utcnow()
    return secret


def _credentials(db: Session, ext: Extension, key: InstallationKey) -> SipCredentialsOut:
    if not ext.sip_secret_ciphertext:
        raise conflict("This extension has no SIP secret yet; rotate it to create one.")
    try:
        secret = key.decrypt(ext.sip_secret_ciphertext, secret_purpose(ext.id))
    except ValueError as e:
        raise ProblemError(
            503,
            "Secret unreadable",
            f"The stored SIP secret cannot be decrypted with this installation key: {e}",
            code="secret_unreadable",
        ) from e
    sip = load_sip_settings(db)
    return SipCredentialsOut(
        extension_id=ext.id,
        number=ext.number,
        username=ext.endpoint_name,
        secret=secret,
        udp_port=sip.udp_port,
        tcp_port=sip.tcp_port if sip.tcp_enabled else None,
        tls_port=sip.tls_port if sip.tls_enabled else None,
        rotated_at=ext.sip_secret_changed_at,
    )


def _record(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    ext: Extension,
    details: dict[str, object],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=ext.organization_id,
        target_type="extension",
        target_id=ext.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"number": ext.number, **details},
    )
    # Like "Apply Config" elsewhere: the Deploy changes button appears after
    # every save that may affect the engine, until a deployment runs.
    configmgmt.mark_changed(db, by=principal.label, what=f"{action} {ext.number}")


# ----------------------------------------------------------------- routes


@router.get("", response_model=Page[ExtensionOut], summary="List extensions")
def list_extensions(
    request: Request,
    q: str | None = Query(None, max_length=100, description="Search number or name"),
    organization_id: uuid.UUID | None = Query(None),
    page: PageParams = Depends(page_params),
    principal: Principal = Depends(require("extensions.read")),
    db: Session = Depends(get_db),
) -> Page[ExtensionOut]:
    stmt = _visible(principal, "extensions.read").order_by(Extension.number)
    if organization_id is not None:
        stmt = stmt.where(Extension.organization_id == organization_id)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                Extension.number.ilike(like),
                Extension.display_name.ilike(like),
                Extension.endpoint_name.ilike(like),
            )
        )
    rows, total = paginate(db, stmt, page)
    return Page(items=_outs(db, rows, request), total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/next-number",
    response_model=NextNumberOut,
    summary="Suggest the lowest free number under the numbering plan",
)
def next_number(
    after: str | None = Query(None, max_length=32, pattern=r"^[0-9]*$"),
    organization_id: uuid.UUID | None = Query(
        None, description="Numbers are per organization; default: your home organization"
    ),
    principal: Principal = Depends(require("extensions.read")),
    db: Session = Depends(get_db),
) -> NextNumberOut:
    plan = load_numbering_plan(db)
    problems = plan.problems()
    if problems:
        return NextNumberOut(number=None, plan=plan.describe(), message=" ".join(problems))
    org_id = organization_id
    if org_id is None:
        user = db.get(User, principal.user_id)
        org_id = user.home_organization_id if user is not None else None
    if org_id is not None and not principal.has("extensions.read", org_id):
        raise not_found("Organization")
    number = plan.next_available(used_numbers(db, org_id), after=after or None)
    return NextNumberOut(
        number=number,
        plan=plan.describe(),
        message=None if number else "Every number in the plan's range is in use.",
    )


@router.post("", response_model=ExtensionOut, status_code=201, summary="Create an extension")
def create_extension(
    body: ExtensionIn,
    request: Request,
    principal: Principal = Depends(require("extensions.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ExtensionOut:
    if not principal.has("extensions.write", body.organization_id):
        raise forbidden()
    org = db.get(Organization, body.organization_id)
    if org is None:
        raise not_found("Organization")
    if not org.is_active:
        raise conflict("The organization is inactive.", code="organization_inactive")
    key = installation_key(request)
    _check_number(db, load_numbering_plan(db), body.number, None, org.id)
    _check_user(db, body.user_id, body.organization_id)
    ext = Extension(
        id=uuid.uuid4(),
        organization_id=org.id,
        number=body.number,
        display_name=body.display_name,
        endpoint_name=_endpoint_name(org, body.number),
        user_id=body.user_id,
        caller_id_name=body.caller_id_name,
        caller_id_number=body.caller_id_number,
        emergency_caller_id_number=body.emergency_caller_id_number,
        is_enabled=body.is_enabled,
    )
    _set_secret(ext, key)
    db.add(ext)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(f"Extension {body.number} already exists.", code="number_in_use") from e
    _record(
        db,
        ctx,
        principal,
        "extension.create",
        ext,
        {
            "display_name": ext.display_name,
            "endpoint_name": ext.endpoint_name,
            "user_id": str(ext.user_id) if ext.user_id else None,
            "is_enabled": ext.is_enabled,
        },
    )
    db.commit()
    bus.publish(
        Event(
            "extension.created",
            {"extension_id": str(ext.id), "organization_id": str(org.id), "number": ext.number},
        )
    )
    return _out(db, ext)


@router.get("/{extension_id}", response_model=ExtensionOut, summary="Get an extension")
def get_extension(
    extension_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("extensions.read")),
    db: Session = Depends(get_db),
) -> ExtensionOut:
    return _out(db, _get_visible(db, principal, extension_id, "extensions.read"), request)


@router.patch("/{extension_id}", response_model=ExtensionOut, summary="Update an extension")
def update_extension(
    extension_id: uuid.UUID,
    body: ExtensionPatch,
    principal: Principal = Depends(require("extensions.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> ExtensionOut:
    ext = _get_visible(db, principal, extension_id, "extensions.write")
    changes = body.model_dump(exclude_unset=True)
    details: dict[str, object] = {}
    if "number" in changes and changes["number"] != ext.number:
        org = db.get(Organization, ext.organization_id)
        assert org is not None
        _check_number(db, load_numbering_plan(db), changes["number"], ext.id, org.id)
        details["number_from"] = ext.number
        ext.number = changes["number"]
        # The endpoint name follows the number: phones registered with the
        # old name must be reconfigured (docs/EXTENSIONS.md §3).
        details["endpoint_name_from"] = ext.endpoint_name
        ext.endpoint_name = _endpoint_name(org, ext.number)
    if "user_id" in changes and changes["user_id"] != ext.user_id:
        _check_user(db, changes["user_id"], ext.organization_id)
        ext.user_id = changes["user_id"]
        details["user_id"] = str(ext.user_id) if ext.user_id else None
    for field in (
        "display_name",
        "caller_id_name",
        "caller_id_number",
        "emergency_caller_id_number",
        "is_enabled",
    ):
        if field in changes and changes[field] != getattr(ext, field):
            setattr(ext, field, changes[field])
            details[field] = changes[field]
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(f"Extension {ext.number} already exists.", code="number_in_use") from e
    _record(db, ctx, principal, "extension.update", ext, details)
    db.commit()
    bus.publish(Event("extension.updated", {"extension_id": str(ext.id), "changes": details}))
    return _out(db, ext)


@router.delete("/{extension_id}", status_code=204, summary="Delete an extension")
def delete_extension(
    extension_id: uuid.UUID,
    principal: Principal = Depends(require("extensions.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    ext = _get_visible(db, principal, extension_id, "extensions.write")
    _record(
        db,
        ctx,
        principal,
        "extension.delete",
        ext,
        {"display_name": ext.display_name, "endpoint_name": ext.endpoint_name},
    )
    payload = {
        "extension_id": str(ext.id),
        "organization_id": str(ext.organization_id),
        "number": ext.number,
    }
    db.delete(ext)
    db.commit()
    bus.publish(Event("extension.deleted", payload))
    return Response(status_code=204)


@router.get(
    "/{extension_id}/sip-credentials",
    response_model=SipCredentialsOut,
    summary="Show the SIP user name and secret (audited)",
)
def show_sip_credentials(
    extension_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("extensions.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> SipCredentialsOut:
    ext = _get_visible(db, principal, extension_id, "extensions.write")
    key = installation_key(request)
    creds = _credentials(db, ext, key)
    _record(db, ctx, principal, "extension.secret_reveal", ext, {})
    db.commit()
    return creds


@router.post(
    "/{extension_id}/sip-credentials/rotate",
    response_model=SipCredentialsOut,
    summary="Replace the SIP secret with a new random one",
)
def rotate_sip_credentials(
    extension_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("extensions.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> SipCredentialsOut:
    ext = _get_visible(db, principal, extension_id, "extensions.write")
    key = installation_key(request)
    _set_secret(ext, key)
    db.flush()
    _record(db, ctx, principal, "extension.secret_rotate", ext, {})
    db.commit()
    bus.publish(Event("extension.updated", {"extension_id": str(ext.id), "changes": ["secret"]}))
    return _credentials(db, ext, key)


def count_extensions(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Extension)) or 0
