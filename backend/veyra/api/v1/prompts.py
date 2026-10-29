# SPDX-License-Identifier: AGPL-3.0-or-later
"""Audio prompts for IVR menus (docs/VOICEMAIL_IVR.md §4): uploads converted
to the engine's native format, recordings made from a phone (``*95``) that
are named and adopted here, playback in the browser. Files live under the
prompts directory, one folder per organization slug; the database row is
the catalogue entry menus point at."""

from __future__ import annotations

import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from veyra.core import audit
from veyra.core.db import get_db
from veyra.core.deps import RequestContext, request_context, require
from veyra.core.errors import ProblemError, conflict, forbidden, not_found
from veyra.core.events import Event, bus
from veyra.core.models import (
    Announcement,
    CallQueue,
    IvrMenu,
    MohClass,
    MohClassTrack,
    Organization,
    Prompt,
    RecordingPolicy,
)
from veyra.core.models import Page as RecordedPage
from veyra.core.pagination import Page, PageParams, page_params, paginate
from veyra.core.security.principal import Principal
from veyra.telephony import audio, routing, sounds

router = APIRouter(prefix="/prompts", tags=["prompts"])

INCOMING = audio.INCOMING
_RECORDING_RE = re.compile(r"^rec-(?P<ext>[0-9*#+]{1,32})-(?P<epoch>[0-9]{1,12})\.wav$")
_PROMPT_MEDIA_TYPE = "audio/wav"


def _validation(field: str, message: str) -> ProblemError:
    return ProblemError(
        422,
        "Validation failed",
        message,
        code="validation_failed",
        errors=[{"field": field, "message": message}],
    )


def _unsupported(message: str) -> ProblemError:
    return ProblemError(
        422,
        "Unsupported audio",
        f"{message}. Upload {audio.ACCEPTED}.",
        code="unsupported_audio",
        errors=[{"field": "file", "message": message}],
    )


# ----------------------------------------------------------------- schemas


Kind = Literal["prompt", "bell", "announcement", "greeting", "music"]
KINDS: tuple[str, ...] = ("prompt", "bell", "announcement", "greeting", "music")


class PromptPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    kind: Kind | None = None
    license: str | None = Field(None, max_length=100)
    credit: str | None = Field(None, max_length=200)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        return v


class PromptOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    name: str
    slug: str
    description: str | None
    source: str
    kind: str
    license: str | None
    credit: str | None
    duration_seconds: float
    size_bytes: int
    file_present: bool
    in_use_by: int
    created_at: datetime
    updated_at: datetime


class RecordingOut(BaseModel):
    file: str
    organization_id: uuid.UUID
    organization_name: str
    extension_number: str
    recorded_at: datetime
    duration_seconds: float
    size_bytes: int


class AdoptIn(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("enter a name")
        return v


# ----------------------------------------------------------------- helpers


def prompts_dir(request: Request) -> Path:
    return Path(request.app.state.settings.prompts_dir)


def prompt_path(base: Path, org_slug: str, slug: str) -> Path:
    return base / org_slug / f"{slug}.wav"


def _org_filter(stmt: Select[Any], column: Any, principal: Principal, perm: str) -> Select[Any]:
    orgs = principal.organization_ids_with(perm)
    if orgs is not None:
        stmt = stmt.where(column.in_(orgs or {uuid.UUID(int=0)}))
    return stmt


def _org_for(
    db: Session, principal: Principal, organization_id: uuid.UUID, perm: str
) -> Organization:
    if not principal.has(perm, organization_id):
        raise forbidden()
    org = db.get(Organization, organization_id)
    if org is None:
        raise not_found("Organization")
    return org


# Everything that plays a recording from the library: (what, the row's name,
# the recording columns). A recording in use cannot be deleted; before, the
# columns set to NULL silently dropped it from queues, policies and pages.
_USERS: tuple[tuple[str, Any, tuple[Any, ...]], ...] = (
    ("IVR menus", IvrMenu.name, (IvrMenu.prompt_id, IvrMenu.invalid_prompt_id)),
    ("announcements", Announcement.name, (Announcement.prompt_id,)),
    (
        "call queues",
        CallQueue.name,
        (CallQueue.announcement_prompt_id, CallQueue.periodic_prompt_id),
    ),
    ("recording policies", RecordingPolicy.name, (RecordingPolicy.announcement_prompt_id,)),
    ("pages and bells", RecordedPage.name, (RecordedPage.audio_id,)),
)


def _uses(db: Session, ids: set[uuid.UUID]) -> dict[Any, int]:
    counts: dict[Any, int] = {}
    if not ids:
        return counts
    cols = [c for _, _, columns in _USERS for c in columns] + [MohClassTrack.prompt_id]
    for col in cols:
        for pid, n in db.execute(select(col, func.count()).where(col.in_(ids)).group_by(col)):
            counts[pid] = counts.get(pid, 0) + n
    return counts


def _users_of(db: Session, prompt_id: uuid.UUID) -> list[tuple[str, list[str]]]:
    """What plays the recording: (kind, names), hold music sets included."""
    out = []
    for kind, name, columns in _USERS:
        names = db.scalars(
            select(name).where(or_(*(c == prompt_id for c in columns))).order_by(name)
        ).all()
        if names:
            out.append((kind, list(names)))
    sets = db.scalars(
        select(MohClass.name)
        .join(MohClassTrack, MohClassTrack.class_id == MohClass.id)
        .where(MohClassTrack.prompt_id == prompt_id)
        .order_by(MohClass.name)
    ).all()
    if sets:
        out.append(("hold music sets", list(sets)))
    return out


def _outs(request: Request, db: Session, rows: list[Prompt]) -> list[PromptOut]:
    if not rows:
        return []
    org_ids = {r.organization_id for r in rows}
    orgs = {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids)))}
    uses = _uses(db, {r.id for r in rows})
    base = prompts_dir(request)
    out = []
    for r in rows:
        org = orgs.get(r.organization_id)
        out.append(
            PromptOut(
                id=r.id,
                organization_id=r.organization_id,
                organization_name=org.name if org else "",
                name=r.name,
                slug=r.slug,
                description=r.description,
                source=r.source,
                kind=r.kind,
                license=r.license,
                credit=r.credit,
                duration_seconds=round(r.duration_seconds, 1),
                size_bytes=r.size_bytes,
                file_present=prompt_path(base, org.slug, r.slug).is_file() if org else False,
                in_use_by=uses.get(r.id, 0),
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


def _get(db: Session, principal: Principal, prompt_id: uuid.UUID, perm: str) -> Prompt:
    stmt = _org_filter(select(Prompt), Prompt.organization_id, principal, perm)
    row = db.scalar(stmt.where(Prompt.id == prompt_id))
    if row is None:
        raise not_found("Prompt")
    return row


def _unique_slug(db: Session, org_id: uuid.UUID, name: str) -> str:
    try:
        base = routing.slugify(name)
    except ValueError as e:
        raise _validation("name", str(e)) from e
    slug = base
    n = 2
    while (
        db.scalar(select(Prompt.id).where(Prompt.organization_id == org_id, Prompt.slug == slug))
        is not None
    ):
        slug = f"{base[: 40 - len(str(n)) - 1]}-{n}"
        n += 1
    return slug


async def _read_upload(file: UploadFile) -> tuple[bytes, float, bytes | None]:
    """(8 kHz WAV, seconds, 16 kHz WAV or None) of an upload."""
    data = await file.read(audio.MAX_COMPRESSED_BYTES + 1)
    if not data:
        raise _unsupported("the file is empty")
    try:
        narrow, duration = audio.convert_any(data, file.filename)
    except audio.AudioError as e:
        raise _unsupported(str(e)) from e
    return narrow, duration, audio.wideband_copy(data, file.filename)


def _store(path: Path, data: bytes, wide: bytes | None = None) -> None:
    """The recording, and its 16 kHz copy when there is one (a stale copy of
    an earlier upload is removed, so G.722 channels never play old audio)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        audio.write_atomic(path, data)
        wide_path = path.with_suffix(audio.WIDE_SUFFIX)
        if wide:
            audio.write_atomic(wide_path, wide)
        else:
            wide_path.unlink(missing_ok=True)
    except OSError as e:
        raise ProblemError(
            503,
            "Prompt storage unavailable",
            f"The prompt could not be written to {path.parent}: {e}",
            code="prompt_storage",
        ) from e


def _audit(
    db: Session,
    ctx: RequestContext,
    principal: Principal,
    action: str,
    *,
    organization_id: uuid.UUID,
    target_id: Any,
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        action=action,
        actor_user_id=principal.user_id,
        actor_label=principal.label,
        organization_id=organization_id,
        target_type="prompt",
        target_id=target_id,
        ip_address=ctx.ip,
        request_id=ctx.request_id,
        details=details,
    )


def _recording_path(base: Path, org: Organization, file: str) -> Path:
    if not _RECORDING_RE.match(file):
        raise not_found("Recording")
    # The pattern leaves no path characters; the normalized-prefix check makes
    # containment evident (and holds if the pattern ever loosens).
    folder = os.path.normpath(str(base / org.slug / INCOMING))
    candidate = os.path.normpath(os.path.join(folder, file))
    if not candidate.startswith(folder + os.sep):
        raise not_found("Recording")
    path = Path(candidate)
    if not path.is_file():
        raise not_found("Recording")
    return path


# ----------------------------------------------------------------- recordings (before /{id})


@router.get(
    "/recordings", response_model=list[RecordingOut], summary="Recordings made from phones (*95)"
)
def list_recordings(
    request: Request,
    organization_id: uuid.UUID | None = None,
    principal: Principal = Depends(require("ivr.read")),
    db: Session = Depends(get_db),
) -> list[RecordingOut]:
    stmt = _org_filter(select(Organization), Organization.id, principal, "ivr.read")
    if organization_id:
        stmt = stmt.where(Organization.id == organization_id)
    base = prompts_dir(request)
    orgs = db.scalars(stmt.order_by(Organization.slug)).all()
    # Phones can only record into folders that exist (the worker also makes them).
    audio.ensure_org_dirs(base, [o.slug for o in orgs if o.is_active])
    out = []
    for org in orgs:
        folder = base / org.slug / INCOMING
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            m = _RECORDING_RE.match(path.name)
            if not m or not path.is_file():
                continue
            out.append(
                RecordingOut(
                    file=path.name,
                    organization_id=org.id,
                    organization_name=org.name,
                    extension_number=m.group("ext"),
                    recorded_at=datetime.fromtimestamp(int(m.group("epoch")), tz=UTC),
                    duration_seconds=round(audio.wav_duration(path), 1),
                    size_bytes=path.stat().st_size,
                )
            )
    out.sort(key=lambda r: r.recorded_at, reverse=True)
    return out


@router.get(
    "/recordings/{file}/audio", summary="Listen to a recording", response_class=FileResponse
)
def recording_audio(
    file: str,
    request: Request,
    organization_id: uuid.UUID = Query(...),
    principal: Principal = Depends(require("ivr.read")),
    db: Session = Depends(get_db),
) -> FileResponse:
    org = _org_for(db, principal, organization_id, "ivr.read")
    path = _recording_path(prompts_dir(request), org, file)
    return FileResponse(path, media_type=_PROMPT_MEDIA_TYPE, filename=file)


@router.post(
    "/recordings/{file}/adopt",
    response_model=PromptOut,
    status_code=201,
    summary="Turn a phone recording into a prompt",
)
def adopt_recording(
    file: str,
    body: AdoptIn,
    request: Request,
    principal: Principal = Depends(require("ivr.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PromptOut:
    org = _org_for(db, principal, body.organization_id, "ivr.write")
    base = prompts_dir(request)
    src = _recording_path(base, org, file)
    try:
        data, duration = audio.convert_wav(src.read_bytes())
    except (OSError, audio.AudioError) as e:
        raise _unsupported(f"the recording cannot be used ({e})") from e
    prompt = Prompt(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=body.name,
        slug=_unique_slug(db, org.id, body.name),
        description=(body.description or "").strip() or None,
        source="recording",
        duration_seconds=duration,
        size_bytes=len(data),
    )
    db.add(prompt)
    db.flush()
    _store(prompt_path(base, org.slug, prompt.slug), data)
    src.unlink(missing_ok=True)
    _audit(
        db,
        ctx,
        principal,
        "prompt.create",
        organization_id=org.id,
        target_id=prompt.id,
        details={"name": prompt.name, "slug": prompt.slug, "source": "recording", "file": file},
    )
    db.commit()
    bus.publish(Event("prompt.created", {"id": str(prompt.id)}))
    return _outs(request, db, [prompt])[0]


@router.delete("/recordings/{file}", status_code=204, summary="Discard a phone recording")
def delete_recording(
    file: str,
    request: Request,
    organization_id: uuid.UUID = Query(...),
    principal: Principal = Depends(require("ivr.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    org = _org_for(db, principal, organization_id, "ivr.write")
    path = _recording_path(prompts_dir(request), org, file)
    path.unlink(missing_ok=True)
    _audit(
        db,
        ctx,
        principal,
        "prompt.recording_delete",
        organization_id=org.id,
        target_id=file,
        details={"file": file},
    )
    db.commit()
    return Response(status_code=204)


# ----------------------------------------------------------------- prompts


# ----------------------------------------------------------------- built-in sounds


class BuiltinOut(BaseModel):
    key: str
    name: str
    kind: str
    description: str
    duration_seconds: float
    license: str


class BuiltinCopyIn(BaseModel):
    organization_id: uuid.UUID
    name: str | None = Field(None, min_length=1, max_length=100)


def _builtin(key: str) -> sounds.Sound:
    sound = sounds.BY_KEY.get(key)
    if sound is None:
        raise not_found("Sound")
    return sound


@router.get("/builtin", response_model=list[BuiltinOut], summary="Sounds shipped with Veyra")
def list_builtin(principal: Principal = Depends(require("ivr.read"))) -> list[BuiltinOut]:
    return [
        BuiltinOut(
            key=s.key,
            name=s.name,
            kind=s.kind,
            description=s.description,
            duration_seconds=round(sounds.duration(s.key), 1),
            license=sounds.LICENSE,
        )
        for s in sounds.SOUNDS
    ]


@router.get("/builtin/{key}/audio", summary="Listen to a built-in sound")
def builtin_audio(key: str, principal: Principal = Depends(require("ivr.read"))) -> Response:
    sound = _builtin(key)
    return Response(
        sounds.wav(sound.key),
        media_type=_PROMPT_MEDIA_TYPE,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.post(
    "/builtin/{key}/copy",
    response_model=PromptOut,
    status_code=201,
    summary="Add a built-in sound to an organization's audio library",
)
def copy_builtin(
    key: str,
    body: BuiltinCopyIn,
    request: Request,
    principal: Principal = Depends(require("ivr.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PromptOut:
    sound = _builtin(key)
    org = _org_for(db, principal, body.organization_id, "ivr.write")
    name = (body.name or sound.name).strip() or sound.name
    data = sounds.wav(sound.key)
    prompt = Prompt(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=name,
        slug=_unique_slug(db, org.id, name),
        description=sound.description,
        source="builtin",
        kind=sound.kind,
        license=sounds.LICENSE,
        credit=sounds.CREDIT,
        duration_seconds=sounds.duration(sound.key),
        size_bytes=len(data),
    )
    db.add(prompt)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict(
            "A recording with that name exists in this organization; choose another name.",
            "name_in_use",
        ) from e
    _store(prompt_path(prompts_dir(request), org.slug, prompt.slug), data)
    _audit(
        db,
        ctx,
        principal,
        "prompt.create",
        organization_id=org.id,
        target_id=prompt.id,
        details={"name": prompt.name, "slug": prompt.slug, "source": "builtin", "sound": key},
    )
    db.commit()
    bus.publish(Event("prompt.created", {"id": str(prompt.id)}))
    return _outs(request, db, [prompt])[0]


@router.get("", response_model=Page[PromptOut], summary="List prompts")
def list_prompts(
    request: Request,
    organization_id: uuid.UUID | None = None,
    kind: Kind | None = None,
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(require("ivr.read")),
    db: Session = Depends(get_db),
) -> Page[PromptOut]:
    stmt = _org_filter(select(Prompt), Prompt.organization_id, principal, "ivr.read").order_by(
        Prompt.name
    )
    if organization_id:
        stmt = stmt.where(Prompt.organization_id == organization_id)
    if kind:
        stmt = stmt.where(Prompt.kind == kind)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Prompt.name.ilike(like), Prompt.description.ilike(like)))
    rows, total = paginate(db, stmt, params)
    return Page(
        items=_outs(request, db, rows), total=total, limit=params.limit, offset=params.offset
    )


@router.post(
    "",
    response_model=PromptOut,
    status_code=201,
    summary="Upload audio (WAV, or MP3 and others with ffmpeg)",
)
async def create_prompt(
    request: Request,
    organization_id: uuid.UUID = Form(...),
    name: str = Form(..., min_length=1, max_length=100),
    description: str | None = Form(None, max_length=2000),
    kind: Kind = Form("prompt"),
    license: str | None = Form(None, max_length=100),
    credit: str | None = Form(None, max_length=200),
    file: UploadFile = File(...),
    principal: Principal = Depends(require("ivr.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PromptOut:
    org = _org_for(db, principal, organization_id, "ivr.write")
    name = name.strip()
    if not name:
        raise _validation("name", "enter a name")
    data, duration, wide = await _read_upload(file)
    prompt = Prompt(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=name,
        slug=_unique_slug(db, org.id, name),
        description=(description or "").strip() or None,
        source="upload",
        kind=kind,
        license=(license or "").strip() or None,
        credit=(credit or "").strip() or None,
        duration_seconds=duration,
        size_bytes=len(data),
    )
    db.add(prompt)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise conflict("A prompt with that name exists in this organization.", "name_in_use") from e
    _store(prompt_path(prompts_dir(request), org.slug, prompt.slug), data, wide)
    _audit(
        db,
        ctx,
        principal,
        "prompt.create",
        organization_id=org.id,
        target_id=prompt.id,
        details={
            "name": prompt.name,
            "slug": prompt.slug,
            "source": "upload",
            "duration_seconds": round(duration, 1),
            "original_name": file.filename,
        },
    )
    db.commit()
    bus.publish(Event("prompt.created", {"id": str(prompt.id)}))
    return _outs(request, db, [prompt])[0]


@router.get("/{prompt_id}", response_model=PromptOut)
def get_prompt(
    prompt_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("ivr.read")),
    db: Session = Depends(get_db),
) -> PromptOut:
    return _outs(request, db, [_get(db, principal, prompt_id, "ivr.read")])[0]


@router.get("/{prompt_id}/audio", summary="Listen to a prompt", response_class=FileResponse)
def prompt_audio(
    prompt_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("ivr.read")),
    db: Session = Depends(get_db),
) -> FileResponse:
    prompt = _get(db, principal, prompt_id, "ivr.read")
    org = db.get(Organization, prompt.organization_id)
    path = prompt_path(prompts_dir(request), org.slug if org else "", prompt.slug)
    if not path.is_file():
        raise ProblemError(
            404,
            "Audio missing",
            "The prompt's file is not on the server.",
            code="prompt_file_missing",
        )
    return FileResponse(path, media_type=_PROMPT_MEDIA_TYPE, filename=f"{prompt.slug}.wav")


@router.put("/{prompt_id}/audio", response_model=PromptOut, summary="Replace the audio")
async def replace_audio(
    prompt_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(require("ivr.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PromptOut:
    prompt = _get(db, principal, prompt_id, "ivr.write")
    org = db.get(Organization, prompt.organization_id)
    data, duration, wide = await _read_upload(file)
    _store(prompt_path(prompts_dir(request), org.slug if org else "", prompt.slug), data, wide)
    prompt.duration_seconds = duration
    prompt.size_bytes = len(data)
    prompt.source = "upload"
    db.flush()
    # Hold music sets play copies; refresh them (docs/PAGING_RECORDINGS.md §3.2).
    from veyra.api.v1 import hold_music

    hold_music.sync_sets_using(request, db, prompt.id)
    _audit(
        db,
        ctx,
        principal,
        "prompt.replace_audio",
        organization_id=prompt.organization_id,
        target_id=prompt.id,
        details={"name": prompt.name, "duration_seconds": round(duration, 1)},
    )
    db.commit()
    bus.publish(Event("prompt.updated", {"id": str(prompt.id)}))
    return _outs(request, db, [prompt])[0]


@router.patch("/{prompt_id}", response_model=PromptOut)
def update_prompt(
    prompt_id: uuid.UUID,
    body: PromptPatch,
    request: Request,
    principal: Principal = Depends(require("ivr.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> PromptOut:
    prompt = _get(db, principal, prompt_id, "ivr.write")
    changes = body.model_dump(exclude_unset=True)
    details: dict[str, Any] = {}
    if "name" in changes and body.name and body.name != prompt.name:
        details["name"] = {"from": prompt.name, "to": body.name}
        prompt.name = body.name
    if "description" in changes:
        desc = (changes["description"] or "").strip() or None
        if desc != prompt.description:
            prompt.description = desc
            details["description"] = True
    if "kind" in changes and changes["kind"] and changes["kind"] != prompt.kind:
        details["kind"] = {"from": prompt.kind, "to": changes["kind"]}
        prompt.kind = changes["kind"]
    for field in ("license", "credit"):
        if field in changes:
            value = (changes[field] or "").strip() or None
            if value != getattr(prompt, field):
                setattr(prompt, field, value)
                details[field] = value
    if not details:
        return _outs(request, db, [prompt])[0]
    db.flush()
    _audit(
        db,
        ctx,
        principal,
        "prompt.update",
        organization_id=prompt.organization_id,
        target_id=prompt.id,
        details={"name": prompt.name, **details},
    )
    db.commit()
    bus.publish(Event("prompt.updated", {"id": str(prompt.id)}))
    return _outs(request, db, [prompt])[0]


@router.delete("/{prompt_id}", status_code=204)
def delete_prompt(
    prompt_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require("ivr.write")),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    prompt = _get(db, principal, prompt_id, "ivr.write")
    users = _users_of(db, prompt.id)
    if users:
        listing = "; ".join(f"{kind}: {', '.join(names)}" for kind, names in users)
        raise ProblemError(
            409,
            "Recording in use",
            f"It is still played by {listing}. Choose another recording there first.",
            code="prompt_in_use",
            errors=[{"field": kind, "message": n} for kind, names in users for n in names],
        )
    org = db.get(Organization, prompt.organization_id)
    path = prompt_path(prompts_dir(request), org.slug if org else "", prompt.slug)
    _audit(
        db,
        ctx,
        principal,
        "prompt.delete",
        organization_id=prompt.organization_id,
        target_id=prompt.id,
        details={"name": prompt.name, "slug": prompt.slug},
    )
    db.delete(prompt)
    db.commit()
    path.unlink(missing_ok=True)
    path.with_suffix(audio.WIDE_SUFFIX).unlink(missing_ok=True)
    bus.publish(Event("prompt.deleted", {"id": str(prompt_id)}))
    return Response(status_code=204)
