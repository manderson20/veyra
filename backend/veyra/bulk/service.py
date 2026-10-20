# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bulk CSV import and export (issue #41; docs/BULK_IMPORT.md).

Each kind (extensions, users, inbound routes, shared inboxes) exports every
column it imports, so an export edited in a spreadsheet is a valid import.
Rows are matched on their key (number, email or DID): a match is updated in
place, otherwise the row is created. An empty cell leaves the value as it
is; ``-`` clears it.

Every row runs through the same API handlers as the web interface (their
checks, audit entries and events), inside one database transaction with a
savepoint per row: a failed row is rolled back alone and reported. A dry run
rolls the whole transaction back and drops the events, so it validates
exactly what a real import would do.
"""

from __future__ import annotations

import csv
import io
import secrets
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from veyra.core.db import get_engine
from veyra.core.deps import RequestContext
from veyra.core.errors import ProblemError
from veyra.core.events import bus
from veyra.core.models import (
    Announcement,
    Building,
    CallFlow,
    CallQueue,
    ClassOfService,
    ConferenceRoom,
    Department,
    Extension,
    FaxInbox,
    InboundRoute,
    IvrMenu,
    Organization,
    PickupGroup,
    PickupGroupMember,
    RingGroup,
    Role,
    RoleAssignment,
    Site,
    TimeCondition,
    User,
    VoicemailBox,
    VoicemailBoxMember,
)
from veyra.core.models.routing import SipTrunk
from veyra.core.security.principal import Principal

MAX_ROWS = 5000
MAX_BYTES = 5 * 1024 * 1024
CLEAR = "-"
_TRUE = {"yes", "y", "true", "1", "on"}
_FALSE = {"no", "n", "false", "0", "off"}


class RowError(Exception):
    """A row cannot be applied: reported, and the row's changes rolled back."""


@dataclass
class RowResult:
    row: int
    key: str
    action: str  # create | update | unchanged | error
    message: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class Ctx:
    db: Session
    principal: Principal
    request: Request
    rctx: RequestContext
    org: Organization


class _BulkSession(Session):
    """The handlers commit and roll back as if alone: here a commit only
    flushes and a rollback undoes the current row's savepoint."""

    def commit(self) -> None:
        self.flush()

    def rollback(self) -> None:
        nested = self.get_nested_transaction()
        if nested is not None and nested.is_active:
            nested.rollback()
        else:
            super().rollback()

    def finish(self, keep: bool) -> None:
        if keep:
            super().commit()
        else:
            super().rollback()


# ---------------------------------------------------------------- cells


def _text(row: dict[str, str], col: str) -> str | object | None:
    """``None``: leave unchanged; ``""`` never; ``_CLEARED``: clear."""
    v = (row.get(col) or "").strip()
    if not v:
        return None
    return _CLEARED if v == CLEAR else v


_CLEARED = object()


def _bool(row: dict[str, str], col: str) -> bool | None:
    v = (row.get(col) or "").strip().lower()
    if not v:
        return None
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise RowError(f"{col}: {row.get(col)!r} is not yes or no")


def _int(row: dict[str, str], col: str) -> int | object | None:
    v = _text(row, col)
    if v is None or v is _CLEARED:
        return v
    try:
        return int(str(v))
    except ValueError as e:
        raise RowError(f"{col}: {v!r} is not a number") from e


def _list(row: dict[str, str], col: str) -> list[str] | None:
    """``a; b`` → [a, b]; ``-`` → []; empty → None (unchanged)."""
    v = _text(row, col)
    if v is None:
        return None
    if v is _CLEARED:
        return []
    return [p.strip() for p in str(v).replace(",", ";").split(";") if p.strip()]


def _yn(v: bool | None) -> str:
    return "" if v is None else ("yes" if v else "no")


def _find(db: Session, model: Any, org_id: uuid.UUID, value: str, label: str) -> Any:
    """A row of ``model`` in the organization by number, name or slug."""
    cols = [c for c in ("number", "name", "slug") if hasattr(model, c)]
    for col in cols:
        attr = getattr(model, col)
        cond = attr == value if col != "name" else func.lower(attr) == value.lower()
        row = db.scalar(select(model).where(model.organization_id == org_id, cond).limit(1))
        if row is not None:
            return row
    raise RowError(f"no {label} {value!r} in {db.get(Organization, org_id).name}")  # type: ignore[union-attr]


def _name_of(db: Session, model: Any, row_id: uuid.UUID | None) -> str:
    if row_id is None:
        return ""
    obj = db.get(model, row_id)
    if obj is None:
        return ""
    return str(getattr(obj, "number", None) or getattr(obj, "name", "") or "")


def _problem_message(e: Exception) -> str:
    if isinstance(e, ProblemError):
        parts = [e.detail or e.title]
        for err in e.errors or []:
            parts.append(f"{err.get('field')}: {err.get('message')}")
        return "; ".join(p for p in parts if p)
    if isinstance(e, ValidationError):
        return "; ".join(
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()
        )
    return str(e)


def _changes(current: Any, wanted: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in wanted.items() if getattr(current, k) != v}


def _resolve_refs(
    db: Session, org_id: uuid.UUID, row: dict[str, str], refs: dict[str, tuple[str, Any, str]]
) -> dict[str, Any]:
    """Columns naming another object → their id fields (``-`` → None)."""
    out: dict[str, Any] = {}
    for col, (fld, model, label) in refs.items():
        v = _text(row, col)
        if v is None:
            continue
        out[fld] = None if v is _CLEARED else _find(db, model, org_id, str(v), label).id
    return out


# ------------------------------------------------------------- extensions


class ExtensionsKind:
    name = "extensions"
    label = "Extensions"
    permission = "extensions.write"
    key = "number"
    columns = [
        "number",
        "display_name",
        "user_email",
        "caller_id_name",
        "caller_id_number",
        "outbound_caller_id_number",
        "outbound_caller_id_name",
        "emergency_caller_id_number",
        "intercom",
        "class_of_service",
        "site",
        "building",
        "location",
        "department",
        "max_registrations",
        "enabled",
        "voicemail",
        "voicemail_email",
        "voicemail_attach_audio",
        "voicemail_delete_after_email",
        "voicemail_ring_seconds",
        "pickup_groups",
    ]
    _TEXT = (
        "display_name",
        "caller_id_name",
        "caller_id_number",
        "outbound_caller_id_number",
        "outbound_caller_id_name",
        "emergency_caller_id_number",
        "intercom",
        "location",
    )
    _REFS: dict[str, tuple[str, Any, str]] = {
        "class_of_service": ("class_of_service_id", ClassOfService, "class of service"),
        "site": ("site_id", Site, "site"),
        "building": ("building_id", Building, "building"),
        "department": ("department_id", Department, "department"),
    }

    def export(self, db: Session, org: Organization) -> list[dict[str, str]]:
        exts = list(
            db.scalars(
                select(Extension)
                .where(Extension.organization_id == org.id)
                .order_by(func.length(Extension.number), Extension.number)
            )
        )
        boxes = {
            b.extension_id: b
            for b in db.scalars(
                select(VoicemailBox).where(VoicemailBox.extension_id.in_([e.id for e in exts]))
            )
        }
        groups: dict[uuid.UUID, list[str]] = {}
        for gname, ext_id in db.execute(
            select(PickupGroup.name, PickupGroupMember.extension_id)
            .join(PickupGroupMember, PickupGroupMember.group_id == PickupGroup.id)
            .where(PickupGroup.organization_id == org.id)
            .order_by(PickupGroup.name)
        ):
            groups.setdefault(ext_id, []).append(gname)
        out = []
        for e in exts:
            user = db.get(User, e.user_id) if e.user_id else None
            box = boxes.get(e.id)
            out.append(
                {
                    "number": e.number,
                    "display_name": e.display_name,
                    "user_email": user.email if user else "",
                    **{c: str(getattr(e, c) or "") for c in self._TEXT if c != "display_name"},
                    "class_of_service": _name_of(db, ClassOfService, e.class_of_service_id),
                    "site": _name_of(db, Site, e.site_id),
                    "building": _name_of(db, Building, e.building_id),
                    "department": _name_of(db, Department, e.department_id),
                    "max_registrations": str(e.max_registrations or ""),
                    "enabled": _yn(e.is_enabled),
                    "voicemail": _yn(box is not None),
                    "voicemail_email": (box.email or "") if box else "",
                    "voicemail_attach_audio": _yn(box.attach_audio) if box else "",
                    "voicemail_delete_after_email": _yn(box.delete_after_email) if box else "",
                    "voicemail_ring_seconds": str(box.ring_seconds) if box else "",
                    "pickup_groups": "; ".join(groups.get(e.id, [])),
                }
            )
        return out

    def apply(self, ctx: Ctx, row: dict[str, str]) -> tuple[str, list[str]]:
        from veyra.api.v1 import extensions as api

        db, org = ctx.db, ctx.org
        number = (row.get("number") or "").strip()
        wanted: dict[str, Any] = {}
        for col in self._TEXT:
            v = _text(row, col)
            if v is not None:
                wanted[col] = None if v is _CLEARED else v
        email = _text(row, "user_email")
        if email is not None:
            if email is _CLEARED:
                wanted["user_id"] = None
            else:
                user = db.scalar(select(User).where(func.lower(User.email) == str(email).lower()))
                if user is None:
                    raise RowError(f"user_email: no user {email!r} (import the users first)")
                wanted["user_id"] = user.id
        wanted.update(_resolve_refs(db, org.id, row, self._REFS))
        maxreg = _int(row, "max_registrations")
        if maxreg is not None:
            wanted["max_registrations"] = None if maxreg is _CLEARED else maxreg
        enabled = _bool(row, "enabled")
        if enabled is not None:
            wanted["is_enabled"] = enabled
        if wanted.get("display_name") is None:
            wanted.pop("display_name", None)
        if wanted.get("intercom") is None:
            wanted.pop("intercom", None)
        ext = db.scalar(
            select(Extension).where(Extension.organization_id == org.id, Extension.number == number)
        )
        notes: list[str] = []
        if ext is None:
            if "display_name" not in wanted:
                raise RowError("display_name: required for a new extension")
            api.create_extension(
                api.ExtensionIn(organization_id=org.id, number=number, **wanted),
                ctx.request,
                ctx.principal,
                db,
                ctx.rctx,
            )
            ext = db.scalar(
                select(Extension).where(
                    Extension.organization_id == org.id, Extension.number == number
                )
            )
            assert ext is not None
            action = "create"
        else:
            changes = _changes(ext, wanted)
            if changes:
                api.update_extension(
                    ext.id, api.ExtensionPatch(**changes), ctx.principal, db, ctx.rctx
                )
            action = "update" if changes else "unchanged"
        vm_action = self._voicemail(ctx, ext, row, notes)
        pg_action = self._pickup(ctx, ext, row)
        if action == "unchanged" and (vm_action or pg_action):
            action = "update"
        return action, notes

    def _voicemail(self, ctx: Ctx, ext: Extension, row: dict[str, str], notes: list[str]) -> bool:
        from veyra.api.v1 import voicemail as vapi

        db = ctx.db
        want = _bool(row, "voicemail")
        fields: dict[str, Any] = {}
        email = _text(row, "voicemail_email")
        if email is not None:
            fields["email"] = None if email is _CLEARED else email
        for col, fld in (
            ("voicemail_attach_audio", "attach_audio"),
            ("voicemail_delete_after_email", "delete_after_email"),
        ):
            b = _bool(row, col)
            if b is not None:
                fields[fld] = b
        ring = _int(row, "voicemail_ring_seconds")
        if ring is not None and ring is not _CLEARED:
            fields["ring_seconds"] = ring
        box = db.scalar(select(VoicemailBox).where(VoicemailBox.extension_id == ext.id))
        if box is None:
            if not want:
                if fields:
                    notes.append("voicemail settings ignored: the extension has no box")
                return False
            vapi.create_box(
                vapi.VoicemailBoxIn(extension_id=ext.id, **fields),
                ctx.request,
                ctx.principal,
                db,
                ctx.rctx,
            )
            notes.append("voicemail box created with a random PIN")
            return True
        if want is False:
            notes.append("voicemail=no: the existing box is kept (delete it on the Voicemail page)")
        changes = _changes(box, fields)
        if not changes:
            return False
        vapi.update_box(
            box.id, vapi.VoicemailBoxPatch(**changes), ctx.request, ctx.principal, db, ctx.rctx
        )
        return True

    def _pickup(self, ctx: Ctx, ext: Extension, row: dict[str, str]) -> bool:
        from veyra.api.v1 import pickup_groups as papi

        names = _list(row, "pickup_groups")
        if names is None:
            return False
        db = ctx.db
        wanted = {_find(db, PickupGroup, ext.organization_id, n, "pickup group").id for n in names}
        changed = False
        for group in db.scalars(
            select(PickupGroup).where(PickupGroup.organization_id == ext.organization_id)
        ):
            members = list(
                db.scalars(
                    select(PickupGroupMember.extension_id).where(
                        PickupGroupMember.group_id == group.id
                    )
                )
            )
            inside = ext.id in members
            if (group.id in wanted) == inside:
                continue
            members = [m for m in members if m != ext.id] if inside else [*members, ext.id]
            papi.update_group(
                group.id, papi.PickupGroupPatch(members=members), ctx.principal, db, ctx.rctx
            )
            changed = True
        return changed


# ------------------------------------------------------------------ users


class UsersKind:
    name = "users"
    label = "Users"
    permission = "users.write"
    key = "email"
    columns = ["email", "display_name", "enabled", "roles", "password"]

    def export(self, db: Session, org: Organization) -> list[dict[str, str]]:
        users = list(
            db.scalars(select(User).where(User.home_organization_id == org.id).order_by(User.email))
        )
        roles: dict[uuid.UUID, list[str]] = {}
        for uid, key in db.execute(
            select(RoleAssignment.user_id, Role.key)
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(
                RoleAssignment.organization_id == org.id,
                RoleAssignment.scope_type == "organization",
            )
            .order_by(Role.key)
        ):
            roles.setdefault(uid, []).append(key)
        return [
            {
                "email": u.email,
                "display_name": u.display_name,
                "enabled": _yn(u.is_active),
                "roles": "; ".join(roles.get(u.id, [])),
                "password": "",
            }
            for u in users
        ]

    def apply(self, ctx: Ctx, row: dict[str, str]) -> tuple[str, list[str]]:
        from veyra.api.v1 import schemas
        from veyra.api.v1 import users as api

        db, org = ctx.db, ctx.org
        email = (row.get("email") or "").strip().lower()
        name = _text(row, "display_name")
        enabled = _bool(row, "enabled")
        password = (row.get("password") or "").strip() or None
        notes: list[str] = []
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if user is None:
            if not isinstance(name, str):
                raise RowError("display_name: required for a new user")
            if password is None:
                # Nobody learns it: the user sets their own with "Forgot password".
                password = secrets.token_urlsafe(24) + "aA1!"
                notes.append("no password given: the user sets one with “Forgot password”")
            api.create_user(
                schemas.UserCreate(
                    email=email,
                    display_name=name,
                    password=password,
                    home_organization_id=org.id,
                ),
                ctx.principal,
                db,
                ctx.rctx,
            )
            user = db.scalar(select(User).where(func.lower(User.email) == email))
            assert user is not None
            if enabled is False:
                api.update_user(
                    user.id, schemas.UserPatch(is_active=False), ctx.principal, db, ctx.rctx
                )
            action = "create"
        else:
            patch: dict[str, Any] = {}
            if isinstance(name, str) and name != user.display_name:
                patch["display_name"] = name
            if enabled is not None and enabled != user.is_active:
                patch["is_active"] = enabled
            if password:
                patch["password"] = password
                notes.append("password set (the user changes it at the next sign-in)")
            if patch:
                api.update_user(user.id, schemas.UserPatch(**patch), ctx.principal, db, ctx.rctx)
            action = "update" if patch else "unchanged"
        for key in _list(row, "roles") or []:
            role = db.scalar(select(Role).where(Role.key == key, Role.organization_id.is_(None)))
            if role is None:
                raise RowError(f"roles: no role {key!r}")
            has = db.scalar(
                select(RoleAssignment.id).where(
                    RoleAssignment.user_id == user.id,
                    RoleAssignment.role_id == role.id,
                    RoleAssignment.scope_type == "organization",
                    RoleAssignment.organization_id == org.id,
                )
            )
            if has is None:
                api.add_assignment(
                    user.id,
                    schemas.RoleAssignmentIn(
                        role_key=key, scope_type="organization", organization_id=org.id
                    ),
                    ctx.principal,
                    db,
                    ctx.rctx,
                )
                action = "update" if action == "unchanged" else action
        return action, notes


# --------------------------------------------------------- inbound routes

# destination type → (model, label); "voicemail" is an extension's box.
_DEST_MODELS: dict[str, tuple[Any, str]] = {
    "extension": (Extension, "extension"),
    "voicemail": (Extension, "extension"),
    "voicemail_box": (VoicemailBox, "voicemail box"),
    "ivr": (IvrMenu, "IVR menu"),
    "ring_group": (RingGroup, "ring group"),
    "queue": (CallQueue, "queue"),
    "announcement": (Announcement, "announcement"),
    "conference": (ConferenceRoom, "conference room"),
    "call_flow": (CallFlow, "call flow"),
    "fax": (FaxInbox, "fax inbox"),
}
_DEST_FIELDS = {
    "extension": "extension_id",
    "voicemail": "extension_id",
    "voicemail_box": "voicemail_box_id",
    "ivr": "ivr_id",
    "ring_group": "ring_group_id",
    "queue": "queue_id",
    "announcement": "announcement_id",
    "conference": "conference_id",
    "call_flow": "call_flow_id",
    "fax": "fax_inbox_id",
}


def _destination(db: Session, org_id: uuid.UUID, value: str, prefix: str) -> dict[str, Any]:
    """``type:target`` (``extension:1001``, ``ivr:Main menu``, ``directory``)
    → the route's ``<prefix>_type`` and target id fields, others cleared."""
    kind, _, target = value.partition(":")
    kind, target = kind.strip().lower(), target.strip()
    out: dict[str, Any] = {f"{prefix}_{f}": None for f in set(_DEST_FIELDS.values())}
    out[f"{prefix}_type" if prefix == "destination" else "after_hours_type"] = kind
    if kind == "directory":
        return out
    if kind not in _DEST_MODELS:
        raise RowError(f"{prefix}: unknown destination type {kind!r}")
    if not target:
        raise RowError(f"{prefix}: write it as {kind}:<number or name>")
    model, label = _DEST_MODELS[kind]
    out[f"{prefix}_{_DEST_FIELDS[kind]}"] = _find(db, model, org_id, target, label).id
    return out


def _destination_text(db: Session, route: InboundRoute, prefix: str) -> str:
    kind = getattr(route, f"{prefix}_type" if prefix == "destination" else "after_hours_type")
    if not kind:
        return ""
    if kind == "directory":
        return kind
    fld = _DEST_FIELDS.get(kind)
    target = getattr(route, f"{prefix}_{fld}", None) if fld else None
    model = _DEST_MODELS[kind][0] if kind in _DEST_MODELS else None
    return f"{kind}:{_name_of(db, model, target)}" if model else kind


class InboundRoutesKind:
    name = "inbound_routes"
    label = "Inbound routes"
    permission = "routing.write"
    key = "did"
    columns = [
        "did",
        "trunk",
        "description",
        "destination",
        "time_condition",
        "after_hours",
        "caller_id_prefix",
        "enabled",
    ]

    def export(self, db: Session, org: Organization) -> list[dict[str, str]]:
        out = []
        for r in db.scalars(
            select(InboundRoute)
            .where(InboundRoute.organization_id == org.id)
            .order_by(InboundRoute.did)
        ):
            trunk = db.get(SipTrunk, r.trunk_id) if r.trunk_id else None
            tc = db.get(TimeCondition, r.time_condition_id) if r.time_condition_id else None
            out.append(
                {
                    "did": r.did,
                    "trunk": trunk.name if trunk else "",
                    "description": r.description or "",
                    "destination": _destination_text(db, r, "destination"),
                    "time_condition": tc.name if tc else "",
                    "after_hours": _destination_text(db, r, "after_hours") if tc else "",
                    "caller_id_prefix": r.caller_id_prefix or "",
                    "enabled": _yn(r.is_enabled),
                }
            )
        return out

    def apply(self, ctx: Ctx, row: dict[str, str]) -> tuple[str, list[str]]:
        from veyra.api.v1 import routing as api
        from veyra.telephony import routing

        db, org = ctx.db, ctx.org
        did = (row.get("did") or "").strip()
        wanted: dict[str, Any] = {}
        trunk_name = _text(row, "trunk")
        trunk_id = None
        if isinstance(trunk_name, str):
            trunk = db.scalar(
                select(SipTrunk).where(func.lower(SipTrunk.name) == trunk_name.lower())
            )
            if trunk is None:
                raise RowError(f"trunk: no trunk {trunk_name!r}")
            trunk_id = trunk.id
        if trunk_name is not None:
            wanted["trunk_id"] = trunk_id
        for col in ("description", "caller_id_prefix"):
            v = _text(row, col)
            if v is not None:
                wanted[col] = None if v is _CLEARED else v
        dest = _text(row, "destination")
        if isinstance(dest, str):
            wanted.update(_destination(db, org.id, dest, "destination"))
        tc = _text(row, "time_condition")
        if tc is not None:
            wanted["time_condition_id"] = (
                None
                if tc is _CLEARED
                else _find(db, TimeCondition, org.id, str(tc), "time condition").id
            )
        after = _text(row, "after_hours")
        if isinstance(after, str):
            wanted.update(_destination(db, org.id, after, "after_hours"))
        enabled = _bool(row, "enabled")
        if enabled is not None:
            wanted["is_enabled"] = enabled
        canonical = routing.canonical_did(did)
        stmt = select(InboundRoute).where(
            InboundRoute.organization_id == org.id, InboundRoute.did_canonical == canonical
        )
        if trunk_name is not None:
            stmt = stmt.where(InboundRoute.trunk_id == trunk_id)
        route = db.scalars(stmt).first()
        if route is None:
            if "destination_type" not in wanted:
                raise RowError("destination: required for a new route")
            api.create_inbound(
                api.InboundRouteIn(organization_id=org.id, did=did, **wanted),
                ctx.principal,
                db,
                ctx.rctx,
            )
            return "create", []
        changes = _changes(route, wanted)
        if not changes:
            return "unchanged", []
        api.update_inbound(route.id, api.InboundRoutePatch(**changes), ctx.principal, db, ctx.rctx)
        return "update", []


# ---------------------------------------------------------- shared inboxes


class SharedInboxesKind:
    name = "shared_inboxes"
    label = "Shared voicemail inboxes"
    permission = "voicemail.write"
    key = "number"
    columns = [
        "number",
        "name",
        "members",
        "email",
        "attach_audio",
        "delete_after_email",
        "ring_seconds",
        "enabled",
    ]

    def export(self, db: Session, org: Organization) -> list[dict[str, str]]:
        out = []
        for b in db.scalars(
            select(VoicemailBox)
            .where(VoicemailBox.organization_id == org.id, VoicemailBox.extension_id.is_(None))
            .order_by(VoicemailBox.number)
        ):
            members = db.scalars(
                select(Extension.number)
                .join(VoicemailBoxMember, VoicemailBoxMember.extension_id == Extension.id)
                .where(VoicemailBoxMember.box_id == b.id)
                .order_by(Extension.number)
            )
            out.append(
                {
                    "number": b.number or "",
                    "name": b.name or "",
                    "members": "; ".join(members),
                    "email": b.email or "",
                    "attach_audio": _yn(b.attach_audio),
                    "delete_after_email": _yn(b.delete_after_email),
                    "ring_seconds": str(b.ring_seconds),
                    "enabled": _yn(b.is_enabled),
                }
            )
        return out

    def apply(self, ctx: Ctx, row: dict[str, str]) -> tuple[str, list[str]]:
        from veyra.api.v1 import voicemail as api

        db, org = ctx.db, ctx.org
        number = (row.get("number") or "").strip()
        wanted: dict[str, Any] = {}
        name = _text(row, "name")
        if isinstance(name, str):
            wanted["name"] = name
        email = _text(row, "email")
        if email is not None:
            wanted["email"] = None if email is _CLEARED else email
        for col in ("attach_audio", "delete_after_email"):
            b = _bool(row, col)
            if b is not None:
                wanted[col] = b
        enabled = _bool(row, "enabled")
        if enabled is not None:
            wanted["is_enabled"] = enabled
        ring = _int(row, "ring_seconds")
        if ring is not None and ring is not _CLEARED:
            wanted["ring_seconds"] = ring
        members = _list(row, "members")
        member_ids = None
        if members is not None:
            member_ids = [_find(db, Extension, org.id, m, "extension").id for m in members]
        box = db.scalar(
            select(VoicemailBox).where(
                VoicemailBox.organization_id == org.id,
                VoicemailBox.extension_id.is_(None),
                VoicemailBox.number == number,
            )
        )
        if box is None:
            if "name" not in wanted:
                raise RowError("name: required for a new shared inbox")
            api.create_box(
                api.VoicemailBoxIn(
                    organization_id=org.id, number=number, members=member_ids or [], **wanted
                ),
                ctx.request,
                ctx.principal,
                db,
                ctx.rctx,
            )
            return "create", ["created with a random PIN"]
        changes = _changes(box, wanted)
        if member_ids is not None:
            current = set(
                db.scalars(
                    select(VoicemailBoxMember.extension_id).where(
                        VoicemailBoxMember.box_id == box.id
                    )
                )
            )
            if current != set(member_ids):
                changes["members"] = member_ids
        if not changes:
            return "unchanged", []
        api.update_box(
            box.id, api.VoicemailBoxPatch(**changes), ctx.request, ctx.principal, db, ctx.rctx
        )
        return "update", []


# ------------------------------------------------------------- ring groups


def _destination_in(db: Session, org_id: uuid.UUID, value: str) -> dict[str, Any]:
    """``type:target`` → a DestinationIn body (``hangup`` and ``directory``
    need no target)."""
    kind, _, target = value.partition(":")
    kind, target = kind.strip().lower(), target.strip()
    if kind in ("hangup", "directory"):
        return {"type": kind}
    if kind not in _DEST_MODELS:
        raise RowError(f"unknown destination type {kind!r}")
    if not target:
        raise RowError(f"write it as {kind}:<number or name>")
    model, label = _DEST_MODELS[kind]
    return {"type": kind, _DEST_FIELDS[kind]: _find(db, model, org_id, target, label).id}


def _destination_of(db: Session, obj: Any, prefix: str) -> str:
    kind = getattr(obj, f"{prefix}_type", None)
    if not kind:
        return ""
    if kind in ("hangup", "directory"):
        return kind
    fld = _DEST_FIELDS.get(kind)
    target = getattr(obj, f"{prefix}_{fld}", None) if fld else None
    model = _DEST_MODELS[kind][0] if kind in _DEST_MODELS else None
    return f"{kind}:{_name_of(db, model, target)}" if model else kind


class RingGroupsKind:
    name = "ring_groups"
    label = "Ring groups"
    permission = "groups.write"
    key = "number"
    columns = [
        "number",
        "name",
        "description",
        "strategy",
        "ring_seconds",
        "ring_busy_members",
        "members",
        "external_members",
        "caller_id_prefix",
        "failover",
        "enabled",
    ]

    def export(self, db: Session, org: Organization) -> list[dict[str, str]]:
        from veyra.core.models import RingGroupMember

        out = []
        for g in db.scalars(
            select(RingGroup).where(RingGroup.organization_id == org.id).order_by(RingGroup.number)
        ):
            members = db.scalars(
                select(Extension.number)
                .join(RingGroupMember, RingGroupMember.extension_id == Extension.id)
                .where(RingGroupMember.group_id == g.id)
                .order_by(RingGroupMember.position)
            )
            out.append(
                {
                    "number": g.number,
                    "name": g.name,
                    "description": g.description or "",
                    "strategy": g.strategy,
                    "ring_seconds": str(g.ring_seconds),
                    "ring_busy_members": _yn(g.ring_busy_members),
                    "members": "; ".join(members),
                    "external_members": "; ".join(g.external_members or []),
                    "caller_id_prefix": g.caller_id_prefix or "",
                    "failover": _destination_of(db, g, "failover"),
                    "enabled": _yn(g.is_enabled),
                }
            )
        return out

    def apply(self, ctx: Ctx, row: dict[str, str]) -> tuple[str, list[str]]:
        from veyra.api.v1 import ring_groups as api
        from veyra.api.v1.destinations import DestinationIn
        from veyra.core.models import RingGroupMember

        db, org = ctx.db, ctx.org
        number = (row.get("number") or "").strip()
        wanted: dict[str, Any] = {}
        for col in ("name", "description", "strategy", "caller_id_prefix"):
            v = _text(row, col)
            if v is not None:
                wanted[col] = None if v is _CLEARED else v
        ring = _int(row, "ring_seconds")
        if ring is not None and ring is not _CLEARED:
            wanted["ring_seconds"] = ring
        for col, fld in (("ring_busy_members", "ring_busy_members"), ("enabled", "is_enabled")):
            b = _bool(row, col)
            if b is not None:
                wanted[fld] = b
        ext_numbers = _list(row, "external_members")
        if ext_numbers is not None:
            wanted["external_members"] = ext_numbers
        members = _list(row, "members")
        member_ids = (
            [_find(db, Extension, org.id, m, "extension").id for m in members]
            if members is not None
            else None
        )
        failover = _text(row, "failover")
        failover_in = None
        if isinstance(failover, str):
            failover_in = DestinationIn(**_destination_in(db, org.id, failover))
        group = db.scalar(
            select(RingGroup).where(RingGroup.organization_id == org.id, RingGroup.number == number)
        )
        if group is None:
            if not wanted.get("name"):
                raise RowError("name: required for a new ring group")
            api.create_group(
                api.RingGroupIn(
                    organization_id=org.id,
                    number=number,
                    members=member_ids or [],
                    **({"failover": failover_in} if failover_in else {}),
                    **{k: v for k, v in wanted.items() if v is not None},
                ),
                ctx.principal,
                db,
                ctx.rctx,
            )
            return "create", []
        changes = _changes(group, {k: v for k, v in wanted.items() if k != "external_members"})
        if (
            "external_members" in wanted
            and list(group.external_members or []) != wanted["external_members"]
        ):
            changes["external_members"] = wanted["external_members"]
        if member_ids is not None:
            current = list(
                db.scalars(
                    select(RingGroupMember.extension_id)
                    .where(RingGroupMember.group_id == group.id)
                    .order_by(RingGroupMember.position)
                )
            )
            if current != member_ids:
                changes["members"] = member_ids
        if (
            failover_in is not None
            and _destination_of(db, group, "failover") != str(failover).lower()
        ):
            changes["failover"] = failover_in
        if not changes:
            return "unchanged", []
        api.update_group(group.id, api.RingGroupPatch(**changes), ctx.principal, db, ctx.rctx)
        return "update", []


KINDS: dict[str, Any] = {
    k.name: k
    for k in (
        ExtensionsKind(),
        UsersKind(),
        RingGroupsKind(),
        InboundRoutesKind(),
        SharedInboxesKind(),
    )
}


# ------------------------------------------------------------------ CSV


def to_csv(kind: Any, rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=kind.columns, extrasaction="ignore", lineterminator="\r\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def parse_csv(kind: Any, text: str) -> list[dict[str, str]]:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ProblemError(413, "Too large", "The file is larger than 5 MB.", code="too_large")
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = [h.strip() for h in reader.fieldnames or []]
    if kind.key not in headers:
        raise ProblemError(
            422,
            "Invalid file",
            f"The first line must be the column names, with {kind.key!r} among them "
            f"(download the template).",
            code="bad_header",
        )
    unknown = [h for h in headers if h and h not in kind.columns]
    if unknown:
        raise ProblemError(
            422,
            "Invalid file",
            f"Unknown column(s): {', '.join(unknown)}. Known: {', '.join(kind.columns)}.",
            code="bad_header",
        )
    rows = []
    for raw in reader:
        row = {(k or "").strip(): (v or "") for k, v in raw.items() if k}
        if any(v.strip() for v in row.values()):
            rows.append(row)
        if len(rows) > MAX_ROWS:
            raise ProblemError(
                413, "Too many rows", f"At most {MAX_ROWS} rows per file.", code="too_large"
            )
    return rows


def run_import(
    kind: Any,
    rows: list[dict[str, str]],
    *,
    principal: Principal,
    request: Request,
    rctx: RequestContext,
    org: Organization,
    dry_run: bool,
) -> list[RowResult]:
    """Apply the rows (line numbers count the header as line 1)."""
    db = _BulkSession(bind=get_engine(), expire_on_commit=False)
    results: list[RowResult] = []
    try:
        org_here = db.get(Organization, org.id)
        assert org_here is not None
        ctx = Ctx(db, principal, request, rctx, org_here)
        seen: set[str] = set()
        with bus.hold() as held:
            for line, row in enumerate(rows, start=2):
                key = (row.get(kind.key) or "").strip()
                if not key:
                    results.append(RowResult(line, "", "error", f"{kind.key}: required"))
                    continue
                if key.lower() in seen:
                    results.append(
                        RowResult(line, key, "error", f"{key} appears twice in the file")
                    )
                    continue
                seen.add(key.lower())
                nested = db.begin_nested()
                try:
                    action, notes = kind.apply(ctx, row)
                except (ProblemError, ValidationError, RowError, ValueError) as e:
                    if nested.is_active:
                        nested.rollback()
                    results.append(RowResult(line, key, "error", _problem_message(e)))
                    continue
                if nested.is_active:
                    nested.commit()
                results.append(RowResult(line, key, action, None, notes))
            ok = not dry_run
            db.finish(keep=ok)
            events = list(held)
        if ok:
            bus.deliver(events)
    finally:
        db.close()
    return results
