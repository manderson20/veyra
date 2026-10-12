"""Users, roles and role assignments."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1.auth import session_summary
from veyra.api.v1.schemas import (
    MessageOut,
    PasswordResetLinkOut,
    RoleAssignmentIn,
    RoleAssignmentOut,
    RoleOut,
    UserCreate,
    UserOut,
    UserPatch,
    UserSessionOut,
)
from veyra.core import audit
from veyra.core.config import Settings, get_settings
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.models import Organization, Role, RoleAssignment, Site, User
from veyra.core.models.base import utcnow
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security import password_reset, passwords
from veyra.core.security.principal import Principal
from veyra.core.security.sessions import active_sessions, revoke_user_sessions

router = APIRouter(tags=["users"])


def _user_scope(principal: Principal, permission: str) -> Select[User]:
    """Platform grants see everyone; organization grants see users whose home
    organization (or any role assignment) is in one of their organizations."""
    stmt = select(User)
    orgs = principal.organization_ids_with(permission)
    if orgs is None:
        return stmt
    ids = orgs or {uuid.UUID(int=0)}
    assigned = select(RoleAssignment.user_id).where(RoleAssignment.organization_id.in_(ids))
    return stmt.where(or_(User.home_organization_id.in_(ids), User.id.in_(assigned)))


def _get_visible_user(
    db: Session, principal: Principal, user_id: uuid.UUID, permission: str
) -> User:
    user = db.scalar(_user_scope(principal, permission).where(User.id == user_id))
    if user is None:
        raise not_found("User")
    return user


def _guard_platform_admin_target(db: Session, principal: Principal, user: User) -> None:
    """Only platform administrators may modify platform-scoped accounts."""
    if principal.is_platform_admin:
        return
    has_platform = db.scalar(
        select(RoleAssignment.id)
        .where(RoleAssignment.user_id == user.id, RoleAssignment.scope_type == "platform")
        .limit(1)
    )
    if has_platform or user.is_recovery_admin:
        raise forbidden("Only a platform administrator can change this account.")


@router.get("/users", response_model=Page[UserOut], summary="List users")
def list_users(
    q: str | None = Query(None, max_length=100),
    page: PageParams = Depends(page_params),
    principal: Principal = Depends(require("users.read")),
    db: Session = Depends(get_db),
) -> Page[UserOut]:
    stmt = _user_scope(principal, "users.read").order_by(User.display_name)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.display_name.ilike(like)))
    rows, total = paginate(db, stmt, page)
    return Page(
        items=[UserOut.model_validate(u) for u in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/users", response_model=UserOut, status_code=201, summary="Create a local user")
def create_user(
    body: UserCreate,
    principal: Principal = Depends(require("users.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> UserOut:
    if body.home_organization_id is None:
        if not principal.is_platform_admin:
            raise ProblemError(
                422,
                "Validation failed",
                "Choose the user's organization.",
                code="validation_failed",
                errors=[{"field": "home_organization_id", "message": "required"}],
            )
    elif not principal.has("users.write", body.home_organization_id):
        raise forbidden()
    elif db.get(Organization, body.home_organization_id) is None:
        raise not_found("Organization")
    try:
        passwords.validate_password(body.password, email=body.email, display_name=body.display_name)
    except passwords.PasswordPolicyError as e:
        raise ProblemError(
            422,
            "Validation failed",
            str(e),
            code="password_policy",
            errors=[{"field": "password", "message": str(e)}],
        ) from e
    # A password chosen by an administrator is temporary: the user picks their
    # own at first sign-in.
    user = User(
        id=uuid.uuid4(),
        email=body.email,
        display_name=body.display_name,
        password_hash=passwords.hash_password(body.password),
        password_changed_at=utcnow(),
        must_change_password=body.require_password_change,
        home_organization_id=body.home_organization_id,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("A user with this email address already exists.") from e
    audit.record(
        db,
        action="user.create",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=body.home_organization_id,
        target_type="user",
        target_id=user.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"email": body.email, "require_password_change": body.require_password_change},
    )
    db.commit()
    return UserOut.model_validate(user)


@router.get("/users/{user_id}", response_model=UserOut, summary="Get a user")
def get_user(
    user_id: uuid.UUID,
    principal: Principal = Depends(require("users.read")),
    db: Session = Depends(get_db),
) -> UserOut:
    return UserOut.model_validate(_get_visible_user(db, principal, user_id, "users.read"))


@router.patch("/users/{user_id}", response_model=UserOut, summary="Update a user")
def update_user(
    user_id: uuid.UUID,
    body: UserPatch,
    principal: Principal = Depends(require("users.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> UserOut:
    user = _get_visible_user(db, principal, user_id, "users.write")
    _guard_platform_admin_target(db, principal, user)
    details: dict[str, object] = {}
    if body.display_name is not None:
        user.display_name = details["display_name"] = body.display_name
    if body.is_active is not None:
        if user.id == principal.user_id and not body.is_active:
            raise ProblemError(
                409, "Conflict", "You cannot deactivate your own account.", code="self_deactivation"
            )
        user.is_active = details["is_active"] = body.is_active
        if not body.is_active:
            revoke_user_sessions(db, user.id)
    if body.password is not None:
        if user.id == principal.user_id:
            raise ProblemError(
                409,
                "Conflict",
                "Change your own password from your account page.",
                code="self_password_reset",
            )
        try:
            passwords.validate_password(
                body.password, email=user.email, display_name=user.display_name
            )
        except passwords.PasswordPolicyError as e:
            raise ProblemError(
                422,
                "Validation failed",
                str(e),
                code="password_policy",
                errors=[{"field": "password", "message": str(e)}],
            ) from e
        user.password_hash = passwords.hash_password(body.password)
        user.password_changed_at = utcnow()
        user.must_change_password = body.require_password_change
        user.failed_login_count, user.locked_until = 0, None
        details["sessions_revoked"] = revoke_user_sessions(db, user.id)
        details["password_reset"] = True
        details["require_password_change"] = body.require_password_change
    audit.record(
        db,
        action="user.update",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=user.home_organization_id,
        target_type="user",
        target_id=user.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=details,
    )
    db.commit()
    return UserOut.model_validate(user)


@router.post(
    "/users/{user_id}/unlock", response_model=MessageOut, summary="Clear an account lockout"
)
def unlock_user(
    user_id: uuid.UUID,
    principal: Principal = Depends(require("users.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    user = _get_visible_user(db, principal, user_id, "users.write")
    _guard_platform_admin_target(db, principal, user)
    was_locked = bool(user.locked_until and user.locked_until > utcnow())
    user.locked_until = None
    user.failed_login_count = 0
    audit.record(
        db,
        action="user.unlock",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=user.home_organization_id,
        target_type="user",
        target_id=user.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"was_locked": was_locked},
    )
    db.commit()
    return MessageOut(message="Account unlocked." if was_locked else "The account was not locked.")


@router.post(
    "/users/{user_id}/password-reset-link",
    response_model=PasswordResetLinkOut,
    status_code=201,
    summary="Issue a one-time password reset link for a user",
)
def create_password_reset_link(
    user_id: uuid.UUID,
    principal: Principal = Depends(require("users.write")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ctx: RequestContext = Depends(request_context),
) -> PasswordResetLinkOut:
    """The link is returned once and never stored in clear. Give it to the
    user over a channel you trust; it is valid for a limited time and for a
    single use, and it replaces any earlier unused link."""
    user = _get_visible_user(db, principal, user_id, "users.write")
    _guard_platform_admin_target(db, principal, user)
    if user.id == principal.user_id:
        raise ProblemError(
            409,
            "Conflict",
            "Change your own password from your account page.",
            code="self_password_reset",
        )
    if not user.is_active:
        raise conflict("The account is disabled. Enable it before resetting the password.")
    if user.auth_source != "local" and not user.is_recovery_admin:
        raise conflict("This account signs in through an external identity provider.")
    token, row = password_reset.issue_reset_token(
        db, user, settings, issued_by=principal.label, issued_from_ip=ctx.ip
    )
    audit.record(
        db,
        action="user.password_reset_link",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=user.home_organization_id,
        target_type="user",
        target_id=user.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"expires_at": row.expires_at.isoformat()},
    )
    db.commit()
    return PasswordResetLinkOut(
        token=token, path=password_reset.reset_link_path(token), expires_at=row.expires_at
    )


@router.get(
    "/users/{user_id}/sessions",
    response_model=list[UserSessionOut],
    summary="A user's active sessions",
)
def list_user_sessions(
    user_id: uuid.UUID,
    principal: Principal = Depends(require("users.write")),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[UserSessionOut]:
    user = _get_visible_user(db, principal, user_id, "users.write")
    _guard_platform_admin_target(db, principal, user)
    current = principal.session_id if user.id == principal.user_id else None
    return [session_summary(s, current) for s in active_sessions(db, user.id, settings)]


@router.delete(
    "/users/{user_id}/sessions",
    response_model=MessageOut,
    summary="Sign a user out of every session",
)
def revoke_user_sessions_endpoint(
    user_id: uuid.UUID,
    principal: Principal = Depends(require("users.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    user = _get_visible_user(db, principal, user_id, "users.write")
    _guard_platform_admin_target(db, principal, user)
    # An administrator acting on their own account keeps the session in use.
    keep = principal.session_id if user.id == principal.user_id else None
    revoked = revoke_user_sessions(db, user.id, except_id=keep)
    audit.record(
        db,
        action="user.sessions_revoke",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=user.home_organization_id,
        target_type="user",
        target_id=user.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"sessions_revoked": revoked},
    )
    db.commit()
    return MessageOut(message=f"Signed out of {revoked} session{'s' if revoked != 1 else ''}.")


@router.get("/roles", response_model=list[RoleOut], summary="List roles")
def list_roles(
    principal: Principal = Depends(require("roles.read")),
    db: Session = Depends(get_db),
) -> list[RoleOut]:
    roles = db.scalars(select(Role).where(Role.organization_id.is_(None)).order_by(Role.name))
    return [RoleOut.model_validate(r) for r in roles]


@router.get(
    "/users/{user_id}/roles",
    response_model=list[RoleAssignmentOut],
    summary="List a user's role assignments",
)
def list_assignments(
    user_id: uuid.UUID,
    principal: Principal = Depends(require("roles.read")),
    db: Session = Depends(get_db),
) -> list[RoleAssignmentOut]:
    _get_visible_user(db, principal, user_id, "roles.read")
    rows = db.execute(
        select(RoleAssignment, Role, Organization.name)
        .join(Role, Role.id == RoleAssignment.role_id)
        .outerjoin(Organization, Organization.id == RoleAssignment.organization_id)
        .where(RoleAssignment.user_id == user_id)
        .order_by(Role.name)
    ).all()
    return [
        RoleAssignmentOut(
            id=a.id,
            role_key=r.key,
            role_name=r.name,
            scope_type=a.scope_type,
            organization_id=a.organization_id,
            organization_name=org_name,
            site_id=a.site_id,
        )
        for a, r, org_name in rows
    ]


@router.post(
    "/users/{user_id}/roles",
    response_model=RoleAssignmentOut,
    status_code=201,
    summary="Assign a role to a user",
)
def add_assignment(
    user_id: uuid.UUID,
    body: RoleAssignmentIn,
    principal: Principal = Depends(require("roles.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RoleAssignmentOut:
    user = _get_visible_user(db, principal, user_id, "roles.write")
    role = db.scalar(select(Role).where(Role.key == body.role_key, Role.organization_id.is_(None)))
    if role is None:
        raise not_found("Role")
    if body.scope_type == "platform" or role.key == "platform_admin":
        if body.scope_type != "platform" or not principal.is_platform_admin:
            raise forbidden(
                "Only a platform administrator can grant platform-wide roles, "
                "and the Platform Administrator role is always platform-wide."
            )
        org_id = site_id = None
    else:
        if body.organization_id is None or not principal.has("roles.write", body.organization_id):
            raise forbidden()
        org_id = body.organization_id
        site_id = body.site_id if body.scope_type == "site" else None
        if body.scope_type == "site":
            site = db.get(Site, site_id) if site_id else None
            if site is None or site.organization_id != org_id:
                raise not_found("Site")
        if db.get(Organization, org_id) is None:
            raise not_found("Organization")
    assignment = RoleAssignment(
        id=uuid.uuid4(),
        user_id=user.id,
        role_id=role.id,
        scope_type=body.scope_type,
        organization_id=org_id,
        site_id=site_id,
    )
    db.add(assignment)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("The user already has this role in this scope.") from e
    audit.record(
        db,
        action="role.assign",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=org_id,
        target_type="user",
        target_id=user.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"role": role.key, "scope_type": body.scope_type, "site_id": site_id},
    )
    db.commit()
    org = db.get(Organization, org_id) if org_id else None
    return RoleAssignmentOut(
        id=assignment.id,
        role_key=role.key,
        role_name=role.name,
        scope_type=assignment.scope_type,
        organization_id=org_id,
        organization_name=org.name if org else None,
        site_id=site_id,
    )


@router.delete(
    "/users/{user_id}/roles/{assignment_id}",
    response_model=MessageOut,
    summary="Remove a role assignment",
)
def remove_assignment(
    user_id: uuid.UUID,
    assignment_id: uuid.UUID,
    principal: Principal = Depends(require("roles.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MessageOut:
    user = _get_visible_user(db, principal, user_id, "roles.write")
    a = db.get(RoleAssignment, assignment_id)
    if a is None or a.user_id != user.id:
        raise not_found("Role assignment")
    if a.scope_type == "platform":
        if not principal.is_platform_admin:
            raise forbidden()
        remaining = db.scalars(
            select(RoleAssignment)
            .join(Role)
            .where(Role.key == "platform_admin", RoleAssignment.id != a.id)
        ).first()
        role = db.get(Role, a.role_id)
        if role and role.key == "platform_admin" and remaining is None:
            raise ProblemError(
                409,
                "Conflict",
                "At least one platform administrator must remain.",
                code="last_platform_admin",
            )
    elif not principal.has("roles.write", a.organization_id):
        raise forbidden()
    db.delete(a)
    audit.record(
        db,
        action="role.unassign",
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=a.organization_id,
        target_type="user",
        target_id=user.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"assignment_id": str(a.id)},
    )
    db.commit()
    return MessageOut(message="Role removed.")
