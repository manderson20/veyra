# SPDX-License-Identifier: AGPL-3.0-or-later
"""IVR menus (docs/VOICEMAIL_IVR.md §5): a prompt, a key map, timeout and
invalid handling, optional direct extension dialling. One organization per
menu; the slug names the dialplan context and is stable."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import destinations
from veyra.api.v1.destinations import DestinationIn, DestinationOut, Resolver, check_destination
from veyra.configmgmt import service as configmgmt
from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.events import Event, bus
from veyra.core.models import IvrEntry, IvrMenu, Organization, Prompt
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import routing

router = APIRouter(prefix="/ivr", tags=["ivr"])


def _validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


# ----------------------------------------------------------------- schemas


class EntryIn(BaseModel):
    digit: str = Field(min_length=1, max_length=1)
    destination: DestinationIn

    @field_validator("digit")
    @classmethod
    def _digit(cls, v: str) -> str:
        if v not in routing.IVR_DIGITS:
            raise ValueError("a key 0-9, * or #")
        return v


class IvrMenuIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    prompt_id: uuid.UUID | None = None
    invalid_prompt_id: uuid.UUID | None = None
    timeout_seconds: int = Field(5, ge=1, le=30)
    max_retries: int = Field(3, ge=1, le=9)
    allow_direct_dial: bool = True
    timeout_destination: DestinationIn = Field(default_factory=lambda: DestinationIn(type="hangup"))
    invalid_destination: DestinationIn = Field(default_factory=lambda: DestinationIn(type="hangup"))
    entries: list[EntryIn] = Field(default_factory=list, max_length=12)
    is_enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        routing.slugify(v)
        return v

    @field_validator("entries")
    @classmethod
    def _entries(cls, v: list[EntryIn]) -> list[EntryIn]:
        seen = set()
        for e in v:
            if e.digit in seen:
                raise ValueError(f"key {e.digit} is mapped twice")
            seen.add(e.digit)
        return sorted(v, key=lambda e: routing.IVR_DIGITS.index(e.digit))


class IvrMenuPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    prompt_id: uuid.UUID | None = None
    invalid_prompt_id: uuid.UUID | None = None
    timeout_seconds: int | None = Field(None, ge=1, le=30)
    max_retries: int | None = Field(None, ge=1, le=9)
    allow_direct_dial: bool | None = None
    timeout_destination: DestinationIn | None = None
    invalid_destination: DestinationIn | None = None
    entries: list[EntryIn] | None = Field(None, max_length=12)
    is_enabled: bool | None = None


class EntryOut(BaseModel):
    digit: str
    destination: DestinationOut


class IvrMenuOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    slug: str
    context: str
    description: str | None
    prompt_id: uuid.UUID | None
    prompt_name: str | None
    invalid_prompt_id: uuid.UUID | None
    invalid_prompt_name: str | None
    timeout_seconds: int
    max_retries: int
    allow_direct_dial: bool
    timeout_destination: DestinationOut
    invalid_destination: DestinationOut
    entries: list[EntryOut]
    is_enabled: bool
    # Why the menu will not work as configured (no prompt, missing targets).
    problems: list[str]
    # Inbound routes and other menus that point at this menu.
    in_use_by: int
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------- helpers


def _org_filter(stmt: Select[Any], column: Any, principal: Principal, perm: str) -> Select[Any]:
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(column.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _org_for_write(db: Session, principal: Principal, organization_id: uuid.UUID) -> Organization:
    if not principal.has("ivr.write", organization_id):
        raise forbidden()
    org = db.get(Organization, organization_id)
    if org is None:
        raise not_found("Organization")
    if not org.is_active:
        raise conflict("This organization is inactive.", "organization_inactive")
    return org


def _entries(db: Session, menu_ids: set[uuid.UUID]) -> dict[uuid.UUID, list[IvrEntry]]:
    out: dict[uuid.UUID, list[IvrEntry]] = {m: [] for m in menu_ids}
    if menu_ids:
        for e in db.scalars(select(IvrEntry).where(IvrEntry.menu_id.in_(menu_ids))):
            out[e.menu_id].append(e)
    for rows in out.values():
        rows.sort(key=lambda e: routing.IVR_DIGITS.index(e.digit))
    return out


def _uses(db: Session, menu_ids: set[uuid.UUID]) -> dict[Any, int]:
    return destinations.count_uses(db, "ivr", menu_ids)


def _outs(db: Session, rows: list[IvrMenu]) -> list[IvrMenuOut]:
    if not rows:
        return []
    org_ids = {r.organization_id for r in rows}
    orgs = {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids)))}
    prompt_ids = {r.prompt_id for r in rows} | {r.invalid_prompt_id for r in rows}
    prompt_ids.discard(None)
    prompts = (
        {p.id: p for p in db.scalars(select(Prompt).where(Prompt.id.in_(prompt_ids)))}
        if prompt_ids
        else {}
    )
    entries = _entries(db, {r.id for r in rows})
    uses = _uses(db, {r.id for r in rows})
    resolver = Resolver(db)
    refs: list[destinations.Ref] = []
    for r in rows:
        refs.append(destinations.ref_of(r, "timeout"))
        refs.append(destinations.ref_of(r, "invalid"))
        refs += [destinations.ref_of(e, "destination") for e in entries[r.id]]
    resolver.load(refs)
    out = []
    for r in rows:
        org = orgs.get(r.organization_id)
        prompt = prompts.get(r.prompt_id) if r.prompt_id else None
        invalid_prompt = prompts.get(r.invalid_prompt_id) if r.invalid_prompt_id else None
        timeout = resolver.out_ref(destinations.ref_of(r, "timeout"))
        invalid = resolver.out_ref(destinations.ref_of(r, "invalid"))
        outs = [
            EntryOut(
                digit=e.digit, destination=resolver.out_ref(destinations.ref_of(e, "destination"))
            )
            for e in entries[r.id]
        ]
        problems = []
        if prompt is None:
            problems.append("No prompt: the menu answers with congestion until one is chosen.")
        if timeout.missing:
            problems.append("The timeout destination no longer exists.")
        if invalid.missing:
            problems.append("The invalid-key destination no longer exists.")
        for e in outs:
            if e.destination.missing:
                problems.append(f"Key {e.digit} points at a destination that no longer exists.")
        if not outs and not r.allow_direct_dial:
            problems.append("The menu has no keys and direct dialling is off.")
        out.append(
            IvrMenuOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=org.name if org else "",
                name=r.name,
                slug=r.slug,
                context=f"veyra-ivr-{r.slug}",
                description=r.description,
                prompt_id=r.prompt_id,
                prompt_name=prompt.name if prompt else None,
                invalid_prompt_id=r.invalid_prompt_id,
                invalid_prompt_name=invalid_prompt.name if invalid_prompt else None,
                timeout_seconds=r.timeout_seconds,
                max_retries=r.max_retries,
                allow_direct_dial=r.allow_direct_dial,
                timeout_destination=timeout,
                invalid_destination=invalid,
                entries=outs,
                is_enabled=r.is_enabled,
                problems=problems,
                in_use_by=uses.get(r.id, 0),
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _get(db: Session, principal: Principal, menu_id: uuid.UUID, perm: str) -> IvrMenu:
    stmt = _org_filter(select(IvrMenu), IvrMenu.organization_id, principal, perm)
    menu = db.scalar(stmt.where(IvrMenu.id == menu_id))
    if menu is None:
        raise not_found("IVR menu")
    return menu


def _check_prompt(db: Session, org_id: uuid.UUID, prompt_id: uuid.UUID | None, field: str) -> None:
    if prompt_id is None:
        return
    p = db.get(Prompt, prompt_id)
    if p is None or p.organization_id != org_id:
        raise _validation(field, "prompt not found in this organization")


def _unique_slug(db: Session, name: str) -> str:
    base = routing.slugify(name)
    slug = base
    n = 2
    while db.scalar(select(IvrMenu.id).where(IvrMenu.slug == slug)) is not None:
        slug = f"{base[: 40 - len(str(n)) - 1]}-{n}"
        n += 1
    return slug


def _set_entries(db: Session, menu: IvrMenu, entries: list[EntryIn]) -> None:
    for old in db.scalars(select(IvrEntry).where(IvrEntry.menu_id == menu.id)).all():
        db.delete(old)
    db.flush()
    for e in entries:
        row = IvrEntry(menu_id=menu.id, digit=e.digit)
        destinations.apply(row, "destination", e.destination)
        db.add(row)
    db.flush()


def _check_all(
    db: Session, org_id: uuid.UUID, body: IvrMenuIn, self_id: uuid.UUID | None = None
) -> None:
    _check_prompt(db, org_id, body.prompt_id, "prompt_id")
    _check_prompt(db, org_id, body.invalid_prompt_id, "invalid_prompt_id")
    # A menu may replay itself from a key or a fallback (that is how "press 9
    # to hear this again" works), so self references are not excluded here.
    check_destination(
        db, org_id, body.timeout_destination, field="timeout_destination", allow_hangup=True
    )
    check_destination(
        db, org_id, body.invalid_destination, field="invalid_destination", allow_hangup=True
    )
    for e in body.entries:
        check_destination(db, org_id, e.destination, field=f"entries.{e.digit}", allow_hangup=True)


def _audit(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    menu: IvrMenu,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=menu.organization_id,
        target_type="ivr_menu",
        target_id=menu.id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details={"name": menu.name, **details},
    )
    configmgmt.mark_changed(db, by=principal.label, what=f"{action} {menu.name}")


# ----------------------------------------------------------------- routes


@router.get("", response_model=Page[IvrMenuOut], summary="List IVR menus")
def list_menus(
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require("ivr.read")),
    db: Session = Depends(get_db),
) -> Page[IvrMenuOut]:
    stmt = _org_filter(select(IvrMenu), IvrMenu.organization_id, principal, "ivr.read").order_by(
        IvrMenu.name
    )
    if organization_id:
        stmt = stmt.where(IvrMenu.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(IvrMenu.name.ilike(like), IvrMenu.description.ilike(like)))
    rows, total = paginate(db, stmt, params)
    return Page(items=_outs(db, rows), total=total, limit=params.limit, offset=params.offset)


@router.post("", response_model=IvrMenuOut, status_code=201, summary="Create an IVR menu")
def create_menu(
    body: IvrMenuIn,
    principal: Principal = Depends(require("ivr.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> IvrMenuOut:
    org = _org_for_write(db, principal, body.organization_id)
    _check_all(db, org.id, body)
    menu = IvrMenu(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=body.name,
        slug=_unique_slug(db, body.name),
        description=(body.description or "").strip() or None,
        prompt_id=body.prompt_id,
        invalid_prompt_id=body.invalid_prompt_id,
        timeout_seconds=body.timeout_seconds,
        max_retries=body.max_retries,
        allow_direct_dial=body.allow_direct_dial,
        is_enabled=body.is_enabled,
    )
    destinations.apply(menu, "timeout", body.timeout_destination)
    destinations.apply(menu, "invalid", body.invalid_destination)
    db.add(menu)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(
            "An IVR menu with that name exists in this organization.", "name_in_use"
        ) from e
    _set_entries(db, menu, body.entries)
    _audit(
        db,
        ctx,
        principal,
        "ivr.create",
        menu,
        {"slug": menu.slug, "keys": [e.digit for e in body.entries]},
    )
    db.commit()
    bus.publish(Event("ivr.created", {"id": str(menu.id), "name": menu.name}))
    return _outs(db, [menu])[0]


@router.get("/{menu_id}", response_model=IvrMenuOut)
def get_menu(
    menu_id: uuid.UUID,
    principal: Principal = Depends(require("ivr.read")),
    db: Session = Depends(get_db),
) -> IvrMenuOut:
    return _outs(db, [_get(db, principal, menu_id, "ivr.read")])[0]


@router.patch("/{menu_id}", response_model=IvrMenuOut)
def update_menu(
    menu_id: uuid.UUID,
    body: IvrMenuPatch,
    principal: Principal = Depends(require("ivr.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> IvrMenuOut:
    menu = _get(db, principal, menu_id, "ivr.write")
    changes = body.model_dump(exclude_unset=True)
    current_entries = _entries(db, {menu.id})[menu.id]
    current = {
        "organization_id": menu.organization_id,
        "name": menu.name,
        "description": menu.description,
        "prompt_id": menu.prompt_id,
        "invalid_prompt_id": menu.invalid_prompt_id,
        "timeout_seconds": menu.timeout_seconds,
        "max_retries": menu.max_retries,
        "allow_direct_dial": menu.allow_direct_dial,
        "timeout_destination": destinations.as_input(destinations.ref_of(menu, "timeout")),
        "invalid_destination": destinations.as_input(destinations.ref_of(menu, "invalid")),
        "entries": [
            {
                "digit": e.digit,
                "destination": destinations.as_input(destinations.ref_of(e, "destination")),
            }
            for e in current_entries
        ],
        "is_enabled": menu.is_enabled,
    }
    merged = {**current, **changes}
    try:
        validated = IvrMenuIn.model_validate(merged)
    except ValueError as e:
        raise _validation("menu", str(e).splitlines()[0]) from e
    _check_all(db, menu.organization_id, validated)
    details: dict[str, Any] = {}
    if validated.name != menu.name:
        details["name"] = {"from": menu.name, "to": validated.name}
        menu.name = validated.name
    desc = (validated.description or "").strip() or None
    if desc != menu.description:
        menu.description = desc
        details["description"] = True
    for field in (
        "prompt_id",
        "invalid_prompt_id",
        "timeout_seconds",
        "max_retries",
        "allow_direct_dial",
        "is_enabled",
    ):
        value = getattr(validated, field)
        if value != getattr(menu, field):
            setattr(menu, field, value)
            details[field] = str(value) if value is not None else None
    for prefix in ("timeout", "invalid"):
        d = getattr(validated, f"{prefix}_destination")
        if destinations.ref_of(menu, prefix) != d.as_ref():
            destinations.apply(menu, prefix, d)
            details[f"{prefix}_destination"] = d.model_dump(mode="json")
    if "entries" in changes:
        wanted = [(e.digit, *e.destination.as_ref()) for e in validated.entries]
        have = [(e.digit, *destinations.ref_of(e, "destination")) for e in current_entries]
        if wanted != have:
            _set_entries(db, menu, validated.entries)
            details["keys"] = [e.digit for e in validated.entries]
    if not details:
        return _outs(db, [menu])[0]
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(
            "An IVR menu with that name exists in this organization.", "name_in_use"
        ) from e
    _audit(db, ctx, principal, "ivr.update", menu, details)
    db.commit()
    bus.publish(Event("ivr.updated", {"id": str(menu.id)}))
    return _outs(db, [menu])[0]


@router.delete("/{menu_id}", status_code=204)
def delete_menu(
    menu_id: uuid.UUID,
    principal: Principal = Depends(require("ivr.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    menu = _get(db, principal, menu_id, "ivr.write")
    # References from the menu to itself do not keep it alive.
    what = destinations.describe_uses(db, "ivr", menu.id, exclude_self=menu.id)
    if what:
        raise destinations.in_use_error("IVR menu in use", "ivr_in_use", what)
    _audit(db, ctx, principal, "ivr.delete", menu, {"slug": menu.slug})
    for e in db.scalars(select(IvrEntry).where(IvrEntry.menu_id == menu.id)).all():
        db.delete(e)
    if menu.timeout_ivr_id == menu.id:
        menu.timeout_type, menu.timeout_ivr_id = "hangup", None
    if menu.invalid_ivr_id == menu.id:
        menu.invalid_type, menu.invalid_ivr_id = "hangup", None
    db.flush()
    db.delete(menu)
    db.commit()
    bus.publish(Event("ivr.deleted", {"id": str(menu_id)}))
    return Response(status_code=204)
