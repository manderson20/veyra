# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hold music sets (docs/PAGING_RECORDINGS.md §3.2): an ordered list of
library recordings played to held and queued callers; the default set of an
organization, or the set of a queue or ring group."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.api.v1 import group_helpers as helpers
from veyra.api.v1.prompts import prompt_path, prompts_dir
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, not_found
from veyra.core.events import Event, bus
from veyra.core.models import CallQueue, MohClass, MohClassTrack, Organization, Prompt, RingGroup
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import moh

router = APIRouter(prefix="/hold-music", tags=["hold-music"])

READ = "ivr.read"
WRITE = "ivr.write"
MAX_TRACKS = 50


class MohIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    # Library recordings in playing order (docs/PAGING_RECORDINGS.md §3).
    tracks: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_TRACKS)
    random: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        return v


class MohPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    tracks: list[uuid.UUID] | None = Field(None, max_length=MAX_TRACKS)
    random: bool | None = None


class TrackOut(BaseModel):
    prompt_id: uuid.UUID
    name: str
    kind: str
    license: str | None
    duration_seconds: float
    file_present: bool


class MohOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    slug: str
    # The engine's music class.
    class_name: str
    description: str | None
    random: bool
    tracks: list[TrackOut]
    # Organizations (as default), queues and ring groups playing this set.
    in_use_by: int
    problems: list[str]
    created_at: datetime
    updated_at: datetime


def moh_dir(request: Request) -> Path:
    return Path(request.app.state.settings.moh_dir)


def _tracks(db: Session, class_ids: set[uuid.UUID]) -> dict[uuid.UUID, list[MohClassTrack]]:
    out: dict[uuid.UUID, list[MohClassTrack]] = {c: [] for c in class_ids}
    if class_ids:
        for t in db.scalars(
            select(MohClassTrack)
            .where(MohClassTrack.class_id.in_(class_ids))
            .order_by(MohClassTrack.position)
        ):
            out[t.class_id].append(t)
    return out


def uses_of(db: Session, class_ids: set[uuid.UUID]) -> dict[Any, int]:
    """Organizations, queues and ring groups that play these sets."""
    counts: dict[Any, int] = {}
    if not class_ids:
        return counts
    for col in (Organization.moh_class_id, CallQueue.moh_class_id, RingGroup.moh_class_id):
        for cid, n in db.execute(select(col, func.count()).where(col.in_(class_ids)).group_by(col)):
            counts[cid] = counts.get(cid, 0) + n
    return counts


def _outs(request: Request, db: Session, rows: list[MohClass]) -> list[MohOut]:
    if not rows:
        return []
    orgs = {
        o.id: o
        for o in db.scalars(
            select(Organization).where(Organization.id.in_({r.organization_id for r in rows}))
        )
    }
    tracks = _tracks(db, {r.id for r in rows})
    prompt_ids = {t.prompt_id for ts in tracks.values() for t in ts}
    prompts = (
        {p.id: p for p in db.scalars(select(Prompt).where(Prompt.id.in_(prompt_ids)))}
        if prompt_ids
        else {}
    )
    uses = uses_of(db, {r.id for r in rows})
    base = prompts_dir(request)
    out = []
    for r in rows:
        org = orgs.get(r.organization_id)
        track_outs = []
        for t in tracks[r.id]:
            p = prompts.get(t.prompt_id)
            if p is None:
                continue
            track_outs.append(
                TrackOut(
                    prompt_id=p.id,
                    name=p.name,
                    kind=p.kind,
                    license=p.license,
                    duration_seconds=round(p.duration_seconds, 1),
                    file_present=prompt_path(base, org.slug, p.slug).is_file() if org else False,
                )
            )
        problems = []
        if not track_outs:
            problems.append("The set has no recordings: callers would hear silence.")
        elif not all(t.file_present for t in track_outs):
            problems.append("A recording's audio file is missing.")
        out.append(
            MohOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=org.name if org else "",
                name=r.name,
                slug=r.slug,
                class_name=f"veyra-{r.slug}",
                description=r.description,
                random=r.random,
                tracks=track_outs,
                in_use_by=uses.get(r.id, 0),
                problems=problems,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def check_set(db: Session, org_id: uuid.UUID, class_id: uuid.UUID | None, field: str) -> None:
    """422 unless the set exists in this organization (none = the built-in set)."""
    if class_id is None:
        return
    cls = db.get(MohClass, class_id)
    if cls is None or cls.organization_id != org_id:
        raise helpers.validation(field, "hold music set not found in this organization")


def set_names(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    return {c.id: c.name for c in db.scalars(select(MohClass).where(MohClass.id.in_(wanted)))}


def _get(db: Session, principal: Principal, class_id: uuid.UUID, perm: str) -> MohClass:
    stmt = helpers.org_filter(select(MohClass), MohClass.organization_id, principal, perm)
    row = db.scalar(stmt.where(MohClass.id == class_id))
    if row is None:
        raise not_found("Hold music set")
    return row


def _load_tracks(db: Session, org_id: uuid.UUID, ids: list[uuid.UUID]) -> list[Prompt]:
    """The recordings in order; 422 when one is missing or in another organization."""
    found = (
        {p.id: p for p in db.scalars(select(Prompt).where(Prompt.id.in_(set(ids))))} if ids else {}
    )
    out = []
    for pid in ids:
        p = found.get(pid)
        if p is None or p.organization_id != org_id:
            raise helpers.validation("tracks", "recording not found in this organization")
        out.append(p)
    return out


def _set_tracks(db: Session, cls: MohClass, prompts: list[Prompt]) -> None:
    for old in db.scalars(select(MohClassTrack).where(MohClassTrack.class_id == cls.id)):
        db.delete(old)
    db.flush()
    seen: set[uuid.UUID] = set()
    for i, p in enumerate(prompts):
        if p.id in seen:
            # The same recording twice in a set is allowed by the engine but
            # the table keys on (class, prompt); keep the first occurrence.
            continue
        seen.add(p.id)
        db.add(MohClassTrack(class_id=cls.id, prompt_id=p.id, position=i))
    db.flush()


def sync_files(request: Request, db: Session, cls: MohClass) -> None:
    """Copy the set's recordings into its engine directory (``telephony.moh``)."""
    org = db.get(Organization, cls.organization_id)
    base = prompts_dir(request)
    tracks = _tracks(db, {cls.id})[cls.id]
    prompts = {
        p.id: p
        for p in db.scalars(select(Prompt).where(Prompt.id.in_({t.prompt_id for t in tracks})))
    }
    sources = [
        (
            prompts[t.prompt_id].slug,
            prompt_path(base, org.slug if org else "", prompts[t.prompt_id].slug),
        )
        for t in tracks
        if t.prompt_id in prompts
    ]
    try:
        moh.sync_class(moh_dir(request), cls.slug, sources)
    except moh.MohError as e:
        raise ProblemError(503, "Hold music storage unavailable", str(e), code="moh_storage") from e


def sync_sets_using(request: Request, db: Session, prompt_id: uuid.UUID) -> None:
    """After a recording's audio changed: refresh every set that plays it."""
    class_ids = set(
        db.scalars(select(MohClassTrack.class_id).where(MohClassTrack.prompt_id == prompt_id))
    )
    for cls in db.scalars(select(MohClass).where(MohClass.id.in_(class_ids))) if class_ids else []:
        sync_files(request, db, cls)


def _record(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    cls: MohClass,
    details: dict[str, Any],
) -> None:
    helpers.record(
        db, ctx, principal, action, target_type="hold_music", target=cls, details=details
    )


@router.get("", response_model=Page[MohOut], summary="List hold music sets")
def list_sets(
    request: Request,
    organization_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> Page[MohOut]:
    stmt = helpers.org_filter(select(MohClass), MohClass.organization_id, principal, READ).order_by(
        MohClass.name
    )
    if organization_id:
        stmt = stmt.where(MohClass.organization_id == organization_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(MohClass.name.ilike(like), MohClass.description.ilike(like)))
    rows, total = paginate(db, stmt, params)
    return Page(
        items=_outs(request, db, rows), total=total, limit=params.limit, offset=params.offset
    )


@router.post("", response_model=MohOut, status_code=201, summary="Create a hold music set")
def create_set(
    body: MohIn,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MohOut:
    org = helpers.org_for_write(db, principal, body.organization_id)
    prompts = _load_tracks(db, org.id, body.tracks)
    cls = MohClass(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=body.name,
        slug=helpers.unique_slug(db, MohClass, body.name),
        description=(body.description or "").strip() or None,
        random=body.random,
    )
    db.add(cls)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(
            "A hold music set with that name exists in this organization.", "name_in_use"
        ) from e
    _set_tracks(db, cls, prompts)
    sync_files(request, db, cls)
    _record(
        db, ctx, principal, "hold_music.create", cls, {"slug": cls.slug, "tracks": len(prompts)}
    )
    db.commit()
    bus.publish(Event("hold_music.created", {"id": str(cls.id), "slug": cls.slug}))
    return _outs(request, db, [cls])[0]


@router.get("/{class_id}", response_model=MohOut)
def get_set(
    class_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(READ)),
    db: Session = Depends(get_db),
) -> MohOut:
    return _outs(request, db, [_get(db, principal, class_id, READ)])[0]


@router.patch("/{class_id}", response_model=MohOut)
def update_set(
    class_id: uuid.UUID,
    body: MohPatch,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> MohOut:
    cls = _get(db, principal, class_id, WRITE)
    changes = body.model_dump(exclude_unset=True)
    details: dict[str, Any] = {}
    if changes.get("name") and changes["name"].strip() != cls.name:
        details["name"] = {"from": cls.name, "to": changes["name"].strip()}
        cls.name = changes["name"].strip()
    if "description" in changes:
        desc = (changes["description"] or "").strip() or None
        if desc != cls.description:
            cls.description = desc
            details["description"] = True
    if "random" in changes and changes["random"] is not None and changes["random"] != cls.random:
        cls.random = changes["random"]
        details["random"] = cls.random
    if changes.get("tracks") is not None:
        prompts = _load_tracks(db, cls.organization_id, list(changes["tracks"]))
        current = [t.prompt_id for t in _tracks(db, {cls.id})[cls.id]]
        if [p.id for p in prompts] != current:
            _set_tracks(db, cls, prompts)
            details["tracks"] = len(prompts)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(
            "A hold music set with that name exists in this organization.", "name_in_use"
        ) from e
    sync_files(request, db, cls)
    if details:
        _record(db, ctx, principal, "hold_music.update", cls, details)
    db.commit()
    bus.publish(Event("hold_music.updated", {"id": str(cls.id)}))
    return _outs(request, db, [cls])[0]


@router.delete("/{class_id}", status_code=204)
def delete_set(
    class_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(WRITE)),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    cls = _get(db, principal, class_id, WRITE)
    uses = uses_of(db, {cls.id}).get(cls.id, 0)
    if uses:
        raise ProblemError(
            409,
            "Hold music set in use",
            f"{uses} organization(s), queue(s) or ring group(s) play it; change them first.",
            code="hold_music_in_use",
        )
    _record(db, ctx, principal, "hold_music.delete", cls, {"name": cls.name, "slug": cls.slug})
    slug = cls.slug
    db.delete(cls)
    db.commit()
    moh.remove_class(moh_dir(request), slug)
    bus.publish(Event("hold_music.deleted", {"id": str(class_id)}))
    return Response(status_code=204)
